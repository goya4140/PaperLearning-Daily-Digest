from pathlib import Path

from paper_digest.rendering import render, render_email


def test_preview_contains_arxiv_xhs_and_bilibili_channels():
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
        "bilibili": [{
            "title": "AI 产品完整测试", "author": "研究频道", "description": "测试过程",
            "summary_zh": "包含失败案例的产品测试", "reason": "证据完整", "view_count": 12000,
            "danmaku_count": 88, "duration": "18:20", "score": 8,
            "url": "https://www.bilibili.com/video/BV1test", "matched_keywords": ["产品实测"],
        }],
        "bilibili_status": "fetched",
        "disclaimer": "discovery only",
        "query_window_utc": ["2026-07-18T00:00:00Z", "2026-07-18T23:59:59Z"],
    }
    html = render(report, Path(__file__).parents[1] / "templates")
    assert 'data-channel="focus"' in html
    assert 'data-channel="xhs"' in html
    assert 'data-channel="bilibili"' in html
    assert "AI 产品完整测试" in html
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
        "bilibili": [{
            "title": "会议录播", "author": "研究频道", "summary_zh": "技术会议",
            "reason": "信息密度高", "view_count": 100, "duration": "45:00", "score": 8,
            "url": "https://www.bilibili.com/video/BV1test",
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
    assert "会议录播" in html
