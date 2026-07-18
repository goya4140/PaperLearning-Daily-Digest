import datetime as dt

import json

from paper_digest.archive import seal_report
from paper_digest.main import arxiv_query_date, load_archived_report


def test_query_date_follows_arxiv_announcement_calendar():
    settings = {"submission_lag_days": 1, "reuse_latest_on_non_announcement_days": True}
    assert arxiv_query_date(dt.date(2026, 7, 17), settings) == dt.date(2026, 7, 16)
    assert arxiv_query_date(dt.date(2026, 7, 18), settings) == dt.date(2026, 7, 16)
    assert arxiv_query_date(dt.date(2026, 7, 19), settings) == dt.date(2026, 7, 16)
    assert arxiv_query_date(dt.date(2026, 7, 20), settings) == dt.date(2026, 7, 17)


def test_load_archived_report_verifies_hash(tmp_path):
    report = seal_report({"version": 2, "date": "2026-07-18", "focus": [], "explore": [], "xhs": []})
    target = tmp_path / "docs/data/2026/07/2026-07-18.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(report), encoding="utf-8")
    assert load_archived_report(dt.date(2026, 7, 18), tmp_path)["content_sha256"] == report["content_sha256"]
