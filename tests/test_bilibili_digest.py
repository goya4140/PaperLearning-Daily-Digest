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
    ranked = bilibili.rank_videos(videos, {"max_items": 1}, {"enabled": True})
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
