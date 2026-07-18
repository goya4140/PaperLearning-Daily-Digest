from types import SimpleNamespace

import paper_digest.xhs_digest as xhs


NOTES = [
    {
        "id": "note-1",
        "title": "Agent 工具实测",
        "content": "包含安装步骤、三个工具的对比和失败复盘。",
        "liked_count": "1.2万",
        "url": "https://www.xiaohongshu.com/explore/note-1",
        "matched_keywords": ["AI Agent"],
    },
    {
        "id": "note-2",
        "title": "AI 热点",
        "content": "简短转载。",
        "liked_count": "80",
        "url": "https://www.xiaohongshu.com/explore/note-2",
        "matched_keywords": ["AI研究趋势"],
    },
]


def test_missing_cookie_skips_without_error():
    notes, status = xhs.fetch_notes({"enabled": True}, "")
    assert notes == []
    assert status == "missing-cookie"


def test_fetch_normalizes_counts():
    notes, status = xhs.fetch_notes(
        {"enabled": True, "keywords": ["AI Agent"], "candidate_pool": 3},
        "a1=test",
        fetcher=lambda keywords, count, cookie: NOTES,
    )
    assert status == "fetched"
    assert notes[0]["liked_count"] == 12000


def test_qwen_ranks_xhs_array(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test")
    content = '[{"id":"note-1","score":9,"summary_zh":"比较三种 Agent 工具","reason":"有实测与复盘"}]'
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))
    monkeypatch.setattr(xhs, "OpenAI", lambda **kwargs: client)
    result = xhs.rank_notes(NOTES, {"max_items": 1, "min_score": 6}, {"enabled": True})
    assert result[0]["id"] == "note-1"
    assert result[0]["ranking_source"] == "batched-llm"
