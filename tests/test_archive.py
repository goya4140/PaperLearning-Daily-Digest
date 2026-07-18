import json

from paper_digest.archive import archive_report, canonical_payload, seal_report


def test_seal_and_archive_report(tmp_path):
    report = seal_report(
        {
            "version": 2,
            "date": "2026-07-18",
            "generated_at": "2026-07-18T05:00:00+00:00",
            "focus": [],
            "explore": [],
            "xhs": [{"title": "实践笔记"}],
        }
    )
    assert report["content_sha256"]
    assert b"content_sha256" not in canonical_payload(report)

    data_path, latest_path = archive_report(report, tmp_path)
    assert json.loads(data_path.read_text(encoding="utf-8"))["xhs"][0]["title"] == "实践笔记"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest["data_path"] == "data/2026/07/2026-07-18.json"
    assert latest["preview_path"] == "daily/2026/07/2026-07-18.html"
    assert latest["content_sha256"] == report["content_sha256"]

    older = seal_report({**report, "date": "2026-07-17", "generated_at": "2026-07-18T06:00:00+00:00"})
    archive_report(older, tmp_path)
    assert json.loads(latest_path.read_text(encoding="utf-8"))["digest_date"] == "2026-07-18"
