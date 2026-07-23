from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .delivery import send_email
from .archive import archive_report, canonical_payload, seal_report
from .llm_ranker import rerank
from .arxiv_api import fetch
from .rendering import render, render_email
from .selection import deterministic_candidates
from .vault_export import export_to_vault
from .xhs_digest import fetch_notes, rank_notes
from .bilibili_digest import enrich_video_stats, fetch_videos, prepare_video_candidates, rank_videos
from .zhihu_digest import (
    fetch_contents,
    prepare_content_candidates,
    rank_contents,
)


ROOT = Path(__file__).resolve().parents[2]


def arxiv_query_date(target_date: dt.date, settings: dict[str, Any]) -> dt.date:
    query_date = target_date - dt.timedelta(days=int(settings.get("submission_lag_days", 1)))
    if settings.get("reuse_latest_on_non_announcement_days", True):
        # Friday/Saturday have no arXiv announcement. Weekend digests reuse
        # Thursday submissions; Monday uses the Friday submission window.
        offsets = {0: 3, 5: 2, 6: 3}
        if target_date.weekday() in offsets:
            query_date = target_date - dt.timedelta(days=offsets[target_date.weekday()])
    return query_date


def load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if config.get("version") != 1:
        raise ValueError("unsupported config version")
    return config


def load_archived_report(target_date: dt.date, root: Path = ROOT) -> dict[str, Any]:
    date = target_date.isoformat()
    path = root / "docs" / "data" / date[:4] / date[5:7] / f"{date}.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("schema_version") != 1 or report.get("version") != 2 or report.get("date") != date:
        raise ValueError(f"invalid archived digest: {path}")
    expected = hashlib.sha256(canonical_payload(report)).hexdigest()
    if report.get("content_sha256") != expected:
        raise ValueError(f"archived digest hash mismatch: {path}")
    return report


def run(
    target_date: dt.date,
    config_path: Path,
    dry_run: bool,
    vault_path: Path | None = None,
    reuse_archive: bool = False,
) -> dict[str, Any]:
    config = load_config(config_path)
    if reuse_archive:
        report = load_archived_report(target_date)
        print(f"Reusing sealed archive {report['content_sha256'][:12]} for delivery")
    else:
        query_date = arxiv_query_date(target_date, config["arxiv"])
        snapshot = fetch(config["arxiv"], query_date)
        candidates = deterministic_candidates(snapshot["papers"], config["selection"])
        shortlist = rerank(candidates, config["selection"], config.get("llm", {}))
        local_today = dt.datetime.now(ZoneInfo(config.get("timezone", "Asia/Shanghai"))).date()
        if target_date == local_today:
            xhs_candidates, xhs_status = fetch_notes(config.get("xhs", {}), os.environ.get("XHS_COOKIE", ""))
            xhs_notes = rank_notes(xhs_candidates, config.get("xhs", {}), config.get("llm", {}))
            bilibili_cookie = os.environ.get("BILIBILI_COOKIE", "")
            bilibili_candidates, bilibili_status = fetch_videos(config.get("bilibili", {}), bilibili_cookie)
            bilibili_rank_candidates = prepare_video_candidates(
                bilibili_candidates, config.get("bilibili", {})
            )[: int(config.get("bilibili", {}).get("detail_pool", 12))]
            bilibili_rank_candidates, bilibili_stats_status = enrich_video_stats(
                bilibili_rank_candidates,
                bilibili_cookie,
                float(config.get("bilibili", {}).get("request_interval_seconds", 1.2)),
            )
            bilibili_videos = rank_videos(
                bilibili_rank_candidates, config.get("bilibili", {}), config.get("llm", {})
            )
            zhihu_candidates, zhihu_status = fetch_contents(
                config.get("zhihu", {}), os.environ.get("ZHIHU_COOKIE", "")
            )
            zhihu_rank_candidates = prepare_content_candidates(
                zhihu_candidates, config.get("zhihu", {})
            )[: int(config.get("zhihu", {}).get("detail_pool", 16))]
            zhihu_contents = rank_contents(
                zhihu_rank_candidates, config.get("zhihu", {}), config.get("llm", {})
            )
        else:
            xhs_candidates, xhs_notes, xhs_status = [], [], "historical-date-skipped"
            bilibili_candidates, bilibili_videos, bilibili_status = [], [], "historical-date-skipped"
            bilibili_rank_candidates = []
            bilibili_stats_status = "historical-date-skipped"
            zhihu_candidates, zhihu_contents, zhihu_status = [], [], "historical-date-skipped"
            zhihu_rank_candidates = []
        report = seal_report({
            "version": 2,
            "date": target_date.isoformat(),
            "arxiv_query_date": query_date.isoformat(),
            "arxiv_reused_latest": query_date != target_date - dt.timedelta(
                days=int(config["arxiv"].get("submission_lag_days", 1))
            ),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source": snapshot["source"],
            "source_url": snapshot["source_url"],
            "source_urls": snapshot["source_urls"],
            "query_window_utc": snapshot["query_window_utc"],
            "raw_candidate_count": len(snapshot["papers"]),
            "llm_candidate_count": len(candidates),
            "focus": [item for item in shortlist if item["lane"] == "focus"],
            "explore": [item for item in shortlist if item["lane"] == "explore"],
            "xhs": xhs_notes,
            "xhs_candidate_count": len(xhs_candidates),
            "xhs_status": xhs_status,
            "bilibili": bilibili_videos,
            "bilibili_candidate_count": len(bilibili_candidates),
            "bilibili_qualified_count": len(bilibili_rank_candidates),
            "bilibili_status": bilibili_status,
            "bilibili_stats_status": bilibili_stats_status,
            "zhihu": zhihu_contents,
            "zhihu_candidate_count": len(zhihu_candidates),
            "zhihu_qualified_count": len(zhihu_rank_candidates),
            "zhihu_status": zhihu_status,
            "ranking_source": sorted({item["ranking_source"] for item in shortlist}),
            "disclaimer": "发现阶段摘要：仅基于 arXiv 官方元数据、标题和摘要，不等同于论文精读结论。",
        })
    output_dir = ROOT / "out"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "shortlist.json"
    json_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    json_path.write_text(json_text, encoding="utf-8")
    html = render(report, ROOT / "templates")
    email_html = render_email(report, ROOT / "templates")
    (ROOT / "preview.html").write_text(html, encoding="utf-8")
    (output_dir / "email.html").write_text(email_html, encoding="utf-8")
    archive_dir = ROOT / "docs" / "daily" / report["date"][:4] / report["date"][5:7]
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / f"{report['date']}.html").write_text(html, encoding="utf-8")
    archive_report(report, ROOT / "docs")
    if vault_path is not None:
        export_to_vault(report, html, vault_path)
    state = {
        "date": report["date"],
        "digest_sha256": report["content_sha256"],
        "delivered": False,
        "dry_run": dry_run,
    }
    if not dry_run and (
        report["focus"]
        or report["explore"]
        or report["xhs"]
        or report.get("bilibili", [])
        or report.get("zhihu", [])
        or config["delivery"].get("send_empty_digest", True)
    ):
        subject = f"{config['delivery'].get('subject_prefix', 'PaperLearning 每日发现')} · {report['date']}"
        send_email(email_html, subject, str(config["delivery"].get("smtp_provider", "163")))
        state["delivered"] = True
    (output_dir / "delivery.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def cli() -> None:
    parser = argparse.ArgumentParser(description="PaperLearning two-lane daily discovery")
    parser.add_argument("--date", help="digest date (YYYY-MM-DD); arXiv query lag is configured separately")
    parser.add_argument("--config", type=Path, default=ROOT / "config.yml")
    parser.add_argument("--dry-run", action="store_true", help="render without sending email")
    parser.add_argument("--reuse-archive", action="store_true", help="redeliver a sealed archived digest without refetching")
    parser.add_argument("--vault", type=Path, help="also export JSON and preview HTML into a local PaperLearning Vault")
    args = parser.parse_args()
    target = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    report = run(target, args.config, args.dry_run, args.vault, args.reuse_archive)
    print(
        f"Digest {report['date']}: {report['raw_candidate_count']} raw -> "
        f"{report['llm_candidate_count']} ranked -> {len(report['focus'])} focus + {len(report['explore'])} explore"
        f" + {len(report['xhs'])} XHS ({report['xhs_status']})"
        f" + {len(report.get('bilibili', []))} Bilibili ({report.get('bilibili_status', 'unavailable')})"
        f" + {len(report.get('zhihu', []))} Zhihu ({report.get('zhihu_status', 'unavailable')})"
    )


if __name__ == "__main__":
    cli()
