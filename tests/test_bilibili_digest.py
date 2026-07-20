import paper_digest.bilibili_digest as bilibili


VIDEOS = [{
    "bvid": "BV1test123",
    "title": '<em class="keyword">AI</em> 产品实测',
    "description": "完整测试、失败案例与结论",
    "author": "测试频道",
    "duration": "18:20",
    "pubdate": 1784419200,
    "play": "1.2万",
    "video_review": 88,
    "pic": "//i0.hdslb.com/test.jpg",
    "matched_keywords": ["AI 产品实测"],
}]


def test_disabled_source_skips_without_network():
    videos, status = bilibili.fetch_videos({"enabled": False})
    assert videos == []
    assert status == "disabled"


def test_missing_cookie_skips_without_network():
    called = False

    def fetcher(keywords, count, cookie, interval):
        nonlocal called
        called = True
        return VIDEOS

    videos, status = bilibili.fetch_videos(
        {"enabled": True, "keywords": ["AI"]}, "", fetcher=fetcher
    )
    assert videos == []
    assert status == "missing-cookie"
    assert called is False


def test_fetch_normalizes_public_video_metadata():
    videos, status = bilibili.fetch_videos(
        {"enabled": True, "keywords": ["AI 产品实测"], "candidate_pool": 5},
        "SESSDATA=test; bili_jct=test",
        fetcher=lambda keywords, count, cookie, interval: VIDEOS,
    )
    assert status == "fetched"
    assert videos[0]["id"] == "BV1test123"
    assert videos[0]["title"] == "AI 产品实测"
    assert videos[0]["view_count"] == 12_000
    assert videos[0]["cover_url"].startswith("https://")
    assert videos[0]["url"].endswith("BV1test123")


def test_deterministic_ranking_needs_no_api_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    videos, _ = bilibili.fetch_videos(
        {"enabled": True, "keywords": ["AI"], "candidate_pool": 5},
        "SESSDATA=test; bili_jct=test",
        fetcher=lambda keywords, count, cookie, interval: VIDEOS,
    )
    ranked = bilibili.rank_videos(videos, {"max_items": 1, "min_score": 0}, {"enabled": True})
    assert ranked[0]["ranking_source"] == "deterministic-fallback"
    assert ranked[0]["summary_zh"]


def test_enriches_selected_videos_with_like_and_favorite_counts():
    videos, _ = bilibili.fetch_videos(
        {"enabled": True, "keywords": ["AI"], "candidate_pool": 5},
        "SESSDATA=test; bili_jct=test",
        fetcher=lambda keywords, count, cookie, interval: VIDEOS,
    )
    enriched, status = bilibili.enrich_video_stats(
        videos,
        "SESSDATA=test; bili_jct=test",
        fetcher=lambda bvids, cookie, interval: {
            "BV1test123": {"like_count": 2345, "favorite_count": 678}
        },
    )
    assert status == "fetched"
    assert enriched[0]["like_count"] == 2345
    assert enriched[0]["favorite_count"] == 678


def test_stats_failure_keeps_base_video_metadata():
    videos = [{"bvid": "BV1test123", "title": "测试", "view_count": 100}]
    enriched, status = bilibili.enrich_video_stats(
        videos,
        "SESSDATA=test",
        fetcher=lambda bvids, cookie, interval: {},
    )
    assert status == "fetch-failed"
    assert enriched == videos


def test_prepare_candidates_applies_hard_filters_and_content_types():
    videos = [
        {"id": "good", "title": "AI 产品完整实测", "description": "包含对比、失败案例和结论",
         "author": "研究频道", "duration": "18:20", "published_at": 1_784_419_200,
         "view_count": 1000, "matched_keywords": ["AI 产品实测"]},
        {"id": "ad", "title": "AI 训练营招生", "description": "加微信报名",
         "author": "课程频道", "duration": "20:00", "published_at": 1_784_419_200,
         "view_count": 1000, "matched_keywords": ["AI"]},
        {"id": "short", "title": "AI 泛资讯", "description": "今日新闻",
         "author": "资讯频道", "duration": "00:45", "published_at": 1_784_419_200,
         "view_count": 1000, "matched_keywords": ["AI"]},
    ]
    prepared = bilibili.prepare_video_candidates(videos, {}, now_ts=1_784_505_600)
    assert [item["id"] for item in prepared] == ["good"]
    assert prepared[0]["content_type"] == "产品实测"
    assert 0 <= prepared[0]["pre_score"] <= 100


def test_fallback_enforces_author_and_content_type_diversity(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    base = {"description": "完整实测、对比、失败案例、开源工程复盘", "duration": "10:00",
            "published_at": 1_784_419_200, "view_count": 1000, "like_count": 100,
            "favorite_count": 50, "matched_keywords": ["AI", "实测"]}
    videos = [
        {**base, "id": "a", "bvid": "a", "title": "产品实测 A", "author": "同一作者", "content_type": "产品实测"},
        {**base, "id": "b", "bvid": "b", "title": "产品实测 B", "author": "同一作者", "content_type": "产品实测"},
        {**base, "id": "c", "bvid": "c", "title": "论文解读 C", "author": "另一作者", "content_type": "论文解读"},
    ]
    ranked = bilibili.rank_videos(
        videos, {"max_items": 5, "min_score": 0, "max_per_author": 1, "max_per_content_type": 2},
        {"enabled": False},
    )
    assert {item["id"] for item in ranked} in ({"a", "c"}, {"b", "c"})
