from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .delivery import send_email
from .archive import archive_report, seal_report
from .llm_ranker import rerank
from .arxiv_api import fetch
from .rendering import render
from .selection import deterministic_candidates
from .vault_export import export_to_vault
from .xhs_digest import fetch_notes, rank_notes


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


def run(target_date: dt.date, config_path: Path, dry_run: bool, vault_path: Path | None = None) -> dict[str, Any]:
    config = load_config(config_path)
    query_date = arxiv_query_date(target_date, config["arxiv"])
    snapshot = fetch(config["arxiv"], query_date)
    candidates = deterministic_candidates(snapshot["papers"], config["selection"])
    shortlist = rerank(candidates, config["selection"], config.get("llm", {}))
    local_today = dt.datetime.now(ZoneInfo(config.get("timezone", "Asia/Shanghai"))).date()
    if target_date == local_today:
        xhs_candidates, xhs_status = fetch_notes(config.get("xhs", {}), os.environ.get("XHS_COOKIE", ""))
        xhs_notes = rank_notes(xhs_candidates, config.get("xhs", {}), config.get("llm", {}))
    else:
        xhs_candidates, xhs_notes, xhs_status = [], [], "historical-date-skipped"
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
        "ranking_source": sorted({item["ranking_source"] for item in shortlist}),
        "disclaimer": "发现阶段摘要：仅基于 arXiv 官方元数据、标题和摘要，不等同于论文精读结论。",
    })
    output_dir = ROOT / "out"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "shortlist.json"
    json_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    json_path.write_text(json_text, encoding="utf-8")
    html = render(report, ROOT / "templates")
    (ROOT / "preview.html").write_text(html, encoding="utf-8")
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
    if not dry_run and (shortlist or xhs_notes or config["delivery"].get("send_empty_digest", True)):
        subject = f"{config['delivery'].get('subject_prefix', 'PaperLearning 每日发现')} · {report['date']}"
        send_email(html, subject, str(config["delivery"].get("smtp_provider", "163")))
        state["delivered"] = True
    (output_dir / "delivery.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def cli() -> None:
    parser = argparse.ArgumentParser(description="PaperLearning two-lane daily discovery")
    parser.add_argument("--date", help="digest date (YYYY-MM-DD); arXiv query lag is configured separately")
    parser.add_argument("--config", type=Path, default=ROOT / "config.yml")
    parser.add_argument("--dry-run", action="store_true", help="render without sending email")
    parser.add_argument("--vault", type=Path, help="also export JSON and preview HTML into a local PaperLearning Vault")
    args = parser.parse_args()
    target = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    report = run(target, args.config, args.dry_run, args.vault)
    print(
        f"Digest {report['date']}: {report['raw_candidate_count']} raw -> "
        f"{report['llm_candidate_count']} ranked -> {len(report['focus'])} focus + {len(report['explore'])} explore"
        f" + {len(report['xhs'])} XHS ({report['xhs_status']})"
    )


if __name__ == "__main__":
    cli()
