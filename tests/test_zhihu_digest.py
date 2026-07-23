import paper_digest.zhihu_digest as zhihu


LONG_BODY = (
    "这是一次完整复盘。我会按准备阶段、面试流程、具体问题、失败原因和改进策略展开，"
    "并区分个人经历与可迁移的建议。第一轮重点考察基础知识，第二轮关注项目选择，"
    "最后一轮讨论协作方式。真正有帮助的不是背答案，而是说明取舍、验证过程和边界。"
    "文中还包含时间线、踩坑记录、反例和下一次会如何调整。"
)

RAW_ANSWER = {
    "id": 123,
    "type": "answer",
    "question": {"id": 456, "title": "大厂算法工程师面试有哪些真实经验？"},
    "content": f"<p>{LONG_BODY}</p>",
    "excerpt": "完整面试流程与失败复盘",
    "author": {"name": "研究者 A"},
    "created_time": 1_784_419_200,
    "updated_time": 1_784_505_600,
    "voteup_count": 321,
    "comment_count": 28,
    "matched_keywords": ["大厂 面试 经验"],
}


def test_disabled_source_skips_without_network():
    contents, status = zhihu.fetch_contents({"enabled": False})
    assert contents == []
    assert status == "disabled"


def test_cookie_is_required_and_must_include_d_c0():
    called = False

    def fetcher(*args):
        nonlocal called
        called = True
        return [RAW_ANSWER]

    contents, status = zhihu.fetch_contents(
        {"enabled": True, "keywords": ["面试"]}, "", fetcher=fetcher
    )
    assert contents == []
    assert status == "missing-cookie"
    assert called is False

    contents, status = zhihu.fetch_contents(
        {"enabled": True, "keywords": ["面试"]}, "z_c0=test", fetcher=fetcher
    )
    assert contents == []
    assert status == "invalid-cookie-missing-d_c0"
    assert called is False


def test_fetch_normalizes_answer_metadata():
    contents, status = zhihu.fetch_contents(
        {"enabled": True, "keywords": ["大厂 面试 经验"], "candidate_pool": 5},
        'd_c0="test"; z_c0=test',
        fetcher=lambda keywords, count, cookie, interval, search_time: [RAW_ANSWER],
    )
    assert status == "fetched"
    assert contents[0]["id"] == "answer:123"
    assert contents[0]["title"] == "大厂算法工程师面试有哪些真实经验？"
    assert contents[0]["author"] == "研究者 A"
    assert contents[0]["voteup_count"] == 321
    assert contents[0]["comment_count"] == 28
    assert contents[0]["url"].endswith("/question/456/answer/123")
    assert contents[0]["published_date"] == "2026-07-19"


def test_fetch_normalizes_article_and_ignores_video():
    article = {
        "id": "789",
        "type": "article",
        "title": "<b>如何选择 AI 科研方向</b>",
        "content": LONG_BODY,
        "author": {"name": "作者 B"},
        "created": 1_784_419_200,
        "voteup_count": 50,
        "matched_keywords": ["AI 科研 方向 选择"],
    }
    video = {"id": "999", "type": "zvideo", "title": "视频"}
    contents, status = zhihu.fetch_contents(
        {"enabled": True, "keywords": ["科研"]},
        "d_c0=test",
        fetcher=lambda *args: [article, video],
    )
    assert status == "fetched"
    assert [item["id"] for item in contents] == ["article:789"]
    assert contents[0]["url"] == "https://zhuanlan.zhihu.com/p/789"


def test_auth_and_rate_limit_failures_have_distinct_statuses():
    def auth_failure(*args):
        raise zhihu.ZhihuAuthError("403")

    def rate_failure(*args):
        raise zhihu.ZhihuRateLimitError("429")

    settings = {"enabled": True, "keywords": ["科研"]}
    assert zhihu.fetch_contents(settings, "d_c0=test", auth_failure)[1] == (
        "cookie-expired-or-risk-control"
    )
    assert zhihu.fetch_contents(settings, "d_c0=test", rate_failure)[1] == "rate-limited"


def test_prepare_candidates_filters_ads_short_and_old_content():
    base = {
        "author": "作者",
        "excerpt": "完整复盘",
        "content": LONG_BODY,
        "created_at": 1_784_419_200,
        "updated_at": 1_784_419_200,
        "voteup_count": 100,
        "comment_count": 10,
        "matched_keywords": ["面试"],
        "question_id": "q1",
    }
    contents = [
        {**base, "id": "good", "title": "算法面试完整复盘"},
        {**base, "id": "ad", "title": "训练营招生", "content": LONG_BODY + " 加微信"},
        {
            **base,
            "id": "aggregation",
            "title": "2026 大模型面经汇总（多平台整理）",
            "content": LONG_BODY,
        },
        {**base, "id": "short", "title": "一句话经验", "content": "太短了"},
        {
            **base,
            "id": "old",
            "title": "十年前的面试经验",
            "created_at": 1_500_000_000,
            # A recent edit must not refresh an old experience post.
            "updated_at": 1_784_419_200,
        },
    ]
    prepared = zhihu.prepare_content_candidates(
        contents,
        {"max_age_days": 365, "min_content_chars": 120},
        now_ts=1_784_505_600,
    )
    assert [item["id"] for item in prepared] == ["good"]
    assert prepared[0]["content_type"] == "大厂面经"
    assert 0 <= prepared[0]["pre_score"] <= 100


def test_content_type_weights_title_over_incidental_body_terms():
    content = {
        "id": "theory",
        "title": "机器学习理论部分感觉很难学怎么办？",
        "excerpt": "从直觉、机制和推导三个层次理解理论知识",
        "content": LONG_BODY + "这些知识偶尔也会出现在面试中。",
        "created_at": 1_784_419_200,
        "updated_at": 1_784_419_200,
        "author": "研究者",
        "voteup_count": 10,
        "comment_count": 2,
        "matched_keywords": ["机器学习 原理 解读"],
    }
    prepared = zhihu.prepare_content_candidates(
        [content], {"min_content_chars": 120}, now_ts=1_784_505_600
    )
    assert prepared[0]["content_type"] == "知识解读"


def test_fallback_enforces_question_author_and_type_diversity(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    base = {
        "excerpt": "完整面试流程与失败复盘",
        "content": LONG_BODY * 3,
        "created_at": 1_784_419_200,
        "updated_at": 1_784_419_200,
        "voteup_count": 100,
        "comment_count": 10,
        "matched_keywords": ["大厂 面试 经验"],
        "content_type": "大厂面经",
    }
    contents = [
        {
            **base,
            "id": "answer:a",
            "title": "面试 A",
            "author": "同一作者",
            "question_id": "q1",
        },
        {
            **base,
            "id": "answer:b",
            "title": "面试 B",
            "author": "同一作者",
            "question_id": "q2",
        },
        {
            **base,
            "id": "answer:c",
            "title": "面试 C",
            "author": "另一作者",
            "question_id": "q1",
        },
        {
            **base,
            "id": "article:d",
            "title": "科研方向复盘",
            "author": "第三作者",
            "question_id": "",
            "content_type": "科研方向",
        },
    ]
    ranked = zhihu.rank_contents(
        contents,
        {
            "max_items": 5,
            "min_score": 0,
            "max_per_author": 1,
            "max_per_content_type": 2,
        },
        {"enabled": False},
    )
    assert len(ranked) == 2
    assert "article:d" in {item["id"] for item in ranked}
    assert len({item["author"] for item in ranked}) == len(ranked)
    assert len({item.get("question_id") for item in ranked if item.get("question_id")}) == 1
