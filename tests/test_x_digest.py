import paper_digest.x_digest as x_digest


NOW = 1_784_505_600
LONG_POST = (
    "We are releasing a new open-source AI agent benchmark with code, evaluation data, "
    "and a technical report. The report explains the experimental setup, limitations, "
    "failure cases, and how the results compare with existing reasoning systems."
)
SETTINGS = {
    "enabled": True,
    "official_accounts": ["OpenAI", "AnthropicAI"],
    "expert_accounts": ["karpathy"],
    "keyword_queries": ['"AI agent" (release OR benchmark)'],
    "candidate_pool": 20,
    "max_age_days": 7,
    "min_text_chars": 35,
    "languages": ["en", "zh"],
}


def raw_post(post_id="101", handle="OpenAI", **overrides):
    value = {
        "id": post_id,
        "text": LONG_POST,
        "created_at": NOW - 3600,
        "author_name": handle,
        "author_handle": handle,
        "author_verified": True,
        "author_followers": 1_000_000,
        "like_count": 2500,
        "retweet_count": 500,
        "reply_count": 120,
        "quote_count": 80,
        "view_count": 900_000,
        "lang": "en",
        "urls": [{"expanded_url": "https://example.com/report"}],
        "matched_queries": ["official"],
    }
    value.update(overrides)
    return value


def test_parse_cookie_accepts_header_and_json():
    assert x_digest.parse_cookie("auth_token=abc; ct0=csrf; lang=en")["ct0"] == "csrf"
    assert x_digest.parse_cookie('{"auth_token":"abc","ct0":"csrf"}') == {
        "auth_token": "abc",
        "ct0": "csrf",
    }


def test_cookie_is_required_and_validated_before_network():
    called = False

    def fetcher(*args):
        nonlocal called
        called = True
        return []

    posts, status = x_digest.fetch_posts(SETTINGS, "", fetcher)
    assert posts == []
    assert status == "missing-cookie"
    assert called is False

    posts, status = x_digest.fetch_posts(SETTINGS, "auth_token=abc", fetcher)
    assert posts == []
    assert status == "invalid-cookie-missing-ct0"
    assert called is False


def test_fetch_normalizes_and_deduplicates_posts():
    first = raw_post(matched_queries=["official"])
    duplicate = raw_post(matched_queries=["topic-1"])
    posts, status = x_digest.fetch_posts(
        SETTINGS,
        "auth_token=abc; ct0=csrf",
        fetcher=lambda queries, count, cookie, interval: [first, duplicate],
    )
    assert status == "fetched"
    assert len(posts) == 1
    assert posts[0]["source_tier"] == "官方账号"
    assert posts[0]["url"] == "https://x.com/OpenAI/status/101"
    assert posts[0]["external_urls"] == ["https://example.com/report"]
    assert posts[0]["matched_queries"] == ["official", "topic-1"]


def test_auth_and_rate_limit_failures_have_distinct_statuses():
    def auth_failure(*args):
        raise x_digest.XAuthError("401")

    def rate_failure(*args):
        raise x_digest.XRateLimitError("429")

    cookie = "auth_token=abc; ct0=csrf"
    assert x_digest.fetch_posts(SETTINGS, cookie, auth_failure)[1] == (
        "cookie-expired-or-risk-control"
    )
    assert x_digest.fetch_posts(SETTINGS, cookie, rate_failure)[1] == "rate-limited"


def test_prepare_filters_replies_retweets_spam_old_and_duplicate_text():
    valid, _ = x_digest.fetch_posts(
        SETTINGS,
        "auth_token=abc; ct0=csrf",
        fetcher=lambda *args: [
            raw_post("good"),
            raw_post("reply", in_reply_to="1"),
            raw_post("retweet", is_retweet=True),
            raw_post("spam", text=LONG_POST + " AIRDROP giveaway"),
            raw_post("old", created_at=NOW - 9 * 86400),
            raw_post("duplicate"),
            raw_post(
                "vague",
                text="Big news soon.",
                urls=[],
                like_count=100_000,
                retweet_count=20_000,
            ),
        ],
    )
    prepared = x_digest.prepare_post_candidates(valid, SETTINGS, now_ts=NOW)
    assert [item["id"] for item in prepared] == ["good"]
    assert prepared[0]["content_type"] in {"论文发现", "开源项目"}
    assert 0 <= prepared[0]["pre_score"] <= 100


def test_topic_discovery_requires_ai_signal():
    settings = {**SETTINGS, "official_accounts": [], "expert_accounts": []}
    posts, _ = x_digest.fetch_posts(
        settings,
        "auth_token=abc; ct0=csrf",
        fetcher=lambda *args: [
            raw_post("ai", handle="builder", author_verified=False),
            raw_post(
                "noise",
                handle="writer",
                author_verified=False,
                text="A detailed long post about gardening, soil moisture, and tomato plants.",
            ),
        ],
    )
    prepared = x_digest.prepare_post_candidates(posts, settings, now_ts=NOW)
    assert [item["id"] for item in prepared] == ["ai"]


def test_fallback_enforces_author_and_content_type_diversity(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    posts, _ = x_digest.fetch_posts(
        SETTINGS,
        "auth_token=abc; ct0=csrf",
        fetcher=lambda *args: [
            raw_post("a", handle="OpenAI"),
            raw_post("b", handle="OpenAI", text=LONG_POST + " Additional release details."),
            raw_post("c", handle="AnthropicAI", text=LONG_POST + " Model launch."),
        ],
    )
    prepared = x_digest.prepare_post_candidates(posts, SETTINGS, now_ts=NOW)
    ranked = x_digest.rank_posts(
        prepared,
        {**SETTINGS, "max_items": 3, "min_score": 0, "max_per_author": 1, "max_per_content_type": 2},
        {"enabled": False},
    )
    assert len(ranked) == 2
    assert {item["author_handle"] for item in ranked} == {"OpenAI", "AnthropicAI"}
    assert all(item["ranking_source"] == "deterministic-fallback" for item in ranked)
