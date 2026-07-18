from pathlib import Path

from paper_digest.rendering import render, render_email


def test_preview_contains_arxiv_and_xhs_channels():
    report = {
        "date": "2026-07-18",
        "arxiv_query_date": "2026-07-17",
        "raw_candidate_count": 1,
        "focus": [
            {
                "title": "Agent Skill Test",
                "authors": ["Ada"],
                "categories": ["cs.AI"],
                "one_liner": "A discovery-stage line.",
                "abstract": "Official arXiv abstract.",
                "reason": "topic fit",
                "llm_score": 8,
                "url": "https://arxiv.org/abs/2607.12345",
                "pdf_url": "https://arxiv.org/pdf/2607.12345",
            }
        ],
        "explore": [],
        "xhs": [
            {
                "title": "Agent 工具实测",
                "content": "安装与失败复盘",
                "summary_zh": "一条实践经验",
                "reason": "有实测",
                "liked_count": 10,
                "score": 8,
                "url": "https://www.xiaohongshu.com/explore/test",
                "matched_keywords": ["AI Agent"],
            }
        ],
        "xhs_status": "fetched",
        "disclaimer": "discovery only",
        "query_window_utc": ["2026-07-18T00:00:00Z", "2026-07-18T23:59:59Z"],
    }
    html = render(report, Path(__file__).parents[1] / "templates")
    assert 'data-channel="focus"' in html
    assert 'data-channel="xhs"' in html
    assert "PaperLearning-Daily-Digest" in html
    assert "Papers Cool" not in html


def test_email_uses_gmail_safe_single_column_tables():
    report = {
        "date": "2026-07-18",
        "arxiv_query_date": "2026-07-16",
        "raw_candidate_count": 1,
        "focus": [{
            "title": "Agent Skill Test", "authors": ["Ada"], "categories": ["cs.AI"],
            "one_liner": "发现摘要", "reason": "主题匹配", "llm_score": 8,
            "url": "https://arxiv.org/abs/2607.12345", "pdf_url": "https://arxiv.org/pdf/2607.12345",
        }],
        "explore": [],
        "xhs": [{
            "title": "工具实测", "summary_zh": "实践经验", "reason": "有复盘",
            "liked_count": 10, "score": 8, "url": "https://www.xiaohongshu.com/explore/test",
        }],
        "disclaimer": "discovery only",
    }
    html = render_email(report, Path(__file__).parents[1] / "templates")
    lowered = html.lower()
    assert '<table role="presentation"' in lowered
    assert "display:grid" not in lowered
    assert "display:flex" not in lowered
    assert "<script" not in lowered
    assert "<details" not in lowered
    assert "Agent Skill Test" in html
    assert "工具实测" in html
