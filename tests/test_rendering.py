from pathlib import Path

from paper_digest.rendering import render, render_email


def test_preview_contains_arxiv_xhs_bilibili_and_zhihu_channels():
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
            "danmaku_count": 88, "like_count": 2345, "favorite_count": 678,
            "duration": "18:20", "score": 78, "content_type": "产品实测",
            "url": "https://www.bilibili.com/video/BV1test", "matched_keywords": ["产品实测"],
        }],
        "bilibili_status": "fetched",
        "zhihu": [{
            "title": "算法工程师面试完整复盘", "author": "研究者 A",
            "excerpt": "准备、流程、失败原因与改进策略", "content": "具体面试经历",
            "summary_zh": "按时间线复盘面试流程和失败原因", "reason": "第一手且细节完整",
            "voteup_count": 321, "comment_count": 28, "published_date": "2026-07-19",
            "score": 84, "content_type": "大厂面经",
            "url": "https://www.zhihu.com/question/456/answer/123",
            "matched_keywords": ["大厂 面试 经验"],
        }],
        "zhihu_status": "fetched",
        "disclaimer": "discovery only",
        "query_window_utc": ["2026-07-18T00:00:00Z", "2026-07-18T23:59:59Z"],
    }
    html = render(report, Path(__file__).parents[1] / "templates")
    assert 'data-channel="focus"' in html
    assert 'data-channel="xhs"' in html
    assert 'data-channel="bilibili"' in html
    assert 'data-channel="zhihu"' in html
    assert "AI 产品完整测试" in html
    assert "▶️ 12000" in html
    assert "👍 2345" in html
    assert "⭐ 678" in html
    assert "⏱️ 18:20" in html
    assert "推荐 78/100" in html
    assert "算法工程师面试完整复盘" in html
    assert "👍 321" in html
    assert "💬 28" in html
    assert "🗓️ 2026-07-19" in html
    assert "推荐 84/100" in html
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
            "reason": "信息密度高", "view_count": 100, "like_count": 20,
            "favorite_count": 8, "duration": "45:00", "score": 82,
            "content_type": "会议录播",
            "url": "https://www.bilibili.com/video/BV1test",
        }],
        "zhihu": [{
            "title": "科研方向怎么选", "author": "研究者 B",
            "summary_zh": "结合真实研究经历讨论方向选择", "reason": "边界清晰",
            "voteup_count": 80, "comment_count": 12, "published_date": "2026-07-20",
            "score": 81, "content_type": "科研方向",
            "url": "https://zhuanlan.zhihu.com/p/789",
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
    assert "科研方向怎么选" in html
    assert "▶️ 100" in html
    assert "👍 20" in html
    assert "⭐ 8" in html
    assert "⏱️ 45:00" in html
    assert "推荐 82/100" in html
    assert "👍 80" in html
    assert "💬 12" in html
    assert "🗓️ 2026-07-20" in html
    assert "推荐 81/100" in html
