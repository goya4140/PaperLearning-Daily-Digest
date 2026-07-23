from __future__ import annotations

import asyncio
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from typing import Any, Callable

from openai import OpenAI, OpenAIError


URL_RE = re.compile(r"https?://\S+")
SPACE_RE = re.compile(r"\s+")
DEFAULT_BLOCKED_TERMS = (
    "airdrop",
    "giveaway",
    "whitelist",
    "presale",
    "token sale",
    "free crypto",
    "dm for promo",
    "sponsored post",
)
TOPIC_TERMS = (
    "artificial intelligence",
    "machine learning",
    "deep learning",
    "large language model",
    "language model",
    "llm",
    "multimodal",
    "reasoning",
    "agent",
    "alignment",
    "benchmark",
    "inference",
    "training",
    "research",
    "paper",
    "model",
    "open source",
    "github",
    "arxiv",
    "人工智能",
    "大模型",
    "智能体",
    "论文",
    "开源",
)
INFORMATION_TERMS = (
    "release",
    "launch",
    "announce",
    "introduce",
    "available",
    "technical report",
    "paper",
    "benchmark",
    "dataset",
    "weights",
    "code",
    "github",
    "arxiv",
    "results",
    "evaluation",
    "发布",
    "上线",
    "论文",
    "代码",
    "权重",
    "数据集",
    "评测",
)
CONTENT_TYPES = {
    "论文发现": ("paper", "arxiv", "preprint", "technical report", "论文"),
    "开源项目": ("open source", "open-source", "github", "repository", "weights", "code release", "开源"),
    "产品发布": ("launch", "release", "available now", "api", "preview", "model update", "发布", "上线"),
    "研究观点": ("i think", "my view", "we believe", "prediction", "观点", "思考"),
}


class XAuthError(RuntimeError):
    pass


class XRateLimitError(RuntimeError):
    pass


def parse_cookie(cookie: str) -> dict[str, str]:
    """Accept a copied Cookie request header or a Twikit JSON cookie object."""
    raw = cookie.strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {
            str(key).strip(): str(value)
            for key, value in parsed.items()
            if str(key).strip() and value is not None
        }
    jar = SimpleCookie()
    try:
        jar.load(raw)
    except Exception:
        return {}
    return {key: morsel.value for key, morsel in jar.items()}


def _count(value: Any) -> int:
    try:
        return max(0, int(float(str(value or "0").replace(",", ""))))
    except (TypeError, ValueError):
        return 0


def _plain(value: Any) -> str:
    return SPACE_RE.sub(" ", str(value or "")).strip()


def _get(raw: Any, key: str, default: Any = None) -> Any:
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(raw, key, default)


def _timestamp(value: Any) -> int:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) or str(value or "").isdigit():
        return int(float(value))
    else:
        try:
            parsed = parsedate_to_datetime(str(value))
        except (TypeError, ValueError, OverflowError):
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _expanded_urls(value: Any) -> list[str]:
    output: list[str] = []
    for item in value or []:
        if isinstance(item, dict):
            url = item.get("expanded_url") or item.get("url")
        else:
            url = str(item)
        if url and str(url).startswith(("http://", "https://")):
            output.append(str(url))
    return sorted(set(output))


def _safe_error_detail(exc: Exception, cookies: dict[str, str]) -> str:
    detail = SPACE_RE.sub(" ", str(exc)).strip()
    for value in cookies.values():
        if len(value) >= 6:
            detail = detail.replace(value, "***")
    detail = re.sub(
        r"(?i)(auth_token|ct0|cookie)(\s*[=:]\s*)[^\s,;]+",
        r"\1\2***",
        detail,
    )
    return detail[:240]


def _account_sets(settings: dict[str, Any]) -> tuple[set[str], set[str]]:
    official = {
        str(item).strip().lstrip("@").lower()
        for item in settings.get("official_accounts", [])
        if str(item).strip()
    }
    experts = {
        str(item).strip().lstrip("@").lower()
        for item in settings.get("expert_accounts", [])
        if str(item).strip()
    }
    return official, experts


def build_queries(settings: dict[str, Any], now: datetime | None = None) -> list[dict[str, str]]:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=int(settings.get("max_age_days", 7)))).date().isoformat()
    queries: list[dict[str, str]] = []
    for label, key in (("official", "official_accounts"), ("expert", "expert_accounts")):
        accounts = [
            str(item).strip().lstrip("@")
            for item in settings.get(key, [])
            if str(item).strip()
        ]
        for start in range(0, len(accounts), 6):
            chunk = accounts[start : start + 6]
            query = "(" + " OR ".join(f"from:{handle}" for handle in chunk) + ")"
            queries.append(
                {
                    "label": label,
                    "query": f"{query} since:{since} -filter:replies -filter:retweets",
                }
            )
    for index, query in enumerate(settings.get("keyword_queries", [])):
        value = str(query).strip()
        if value:
            queries.append(
                {
                    "label": f"topic-{index + 1}",
                    "query": f"({value}) since:{since} -filter:replies -filter:retweets",
                }
            )
    return queries


def _tweet_dict(tweet: Any, matched_query: str) -> dict[str, Any]:
    user = _get(tweet, "user", {}) or {}
    return {
        "id": str(_get(tweet, "id", "")),
        "text": _plain(_get(tweet, "full_text") or _get(tweet, "text")),
        "created_at": _get(tweet, "created_at_datetime") or _get(tweet, "created_at"),
        "author_name": _plain(_get(user, "name")),
        "author_handle": _plain(_get(user, "screen_name")),
        "author_verified": bool(_get(user, "verified") or _get(user, "is_blue_verified")),
        "author_followers": _count(_get(user, "followers_count")),
        "like_count": _count(_get(tweet, "favorite_count")),
        "retweet_count": _count(_get(tweet, "retweet_count")),
        "reply_count": _count(_get(tweet, "reply_count")),
        "quote_count": _count(_get(tweet, "quote_count")),
        "bookmark_count": _count(_get(tweet, "bookmark_count")),
        "view_count": _count(_get(tweet, "view_count")),
        "lang": _plain(_get(tweet, "lang")),
        "in_reply_to": _get(tweet, "in_reply_to"),
        "is_retweet": _get(tweet, "retweeted_tweet") is not None,
        "is_quote": bool(_get(tweet, "is_quote_status")),
        "urls": _expanded_urls(_get(tweet, "urls")),
        "matched_queries": [matched_query],
    }


async def _search_async(
    queries: list[dict[str, str]], count: int, cookie: str, interval: float
) -> list[dict[str, Any]]:
    from twikit import Client
    from twikit.errors import Forbidden, TooManyRequests, Unauthorized

    client = Client("en-US")
    client.set_cookies(parse_cookie(cookie), clear_cookies=True)
    per_query = max(1, min(20, math.ceil(count / max(len(queries), 1))))
    output: list[dict[str, Any]] = []
    for index, query in enumerate(queries):
        if index:
            await asyncio.sleep(interval)
        try:
            tweets = await client.search_tweet(query["query"], "Latest", count=per_query)
        except (Unauthorized, Forbidden) as exc:
            raise XAuthError(str(exc)) from exc
        except TooManyRequests as exc:
            raise XRateLimitError(str(exc)) from exc
        for tweet in tweets:
            output.append(_tweet_dict(tweet, query["label"]))
            if len(output) >= count:
                return output
    return output


def _search(
    queries: list[dict[str, str]], count: int, cookie: str, interval: float
) -> list[dict[str, Any]]:
    return asyncio.run(_search_async(queries, count, cookie, interval))


def _normalize(raw: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any] | None:
    post_id = str(raw.get("id") or "").strip()
    text = _plain(raw.get("text") or raw.get("full_text"))
    author = raw.get("user") if isinstance(raw.get("user"), dict) else {}
    handle = _plain(raw.get("author_handle") or author.get("screen_name")).lstrip("@")
    if not post_id or not text or not handle:
        return None
    official, experts = _account_sets(settings)
    handle_key = handle.lower()
    if handle_key in official:
        source_tier = "官方账号"
    elif handle_key in experts:
        source_tier = "领域专家"
    elif raw.get("author_verified") or author.get("verified") or author.get("is_blue_verified"):
        source_tier = "认证来源"
    else:
        source_tier = "主题发现"
    created_at = _timestamp(raw.get("created_at"))
    return {
        "id": post_id,
        "text": text,
        "author_name": _plain(raw.get("author_name") or author.get("name")) or handle,
        "author_handle": handle,
        "author_verified": bool(
            raw.get("author_verified") or author.get("verified") or author.get("is_blue_verified")
        ),
        "author_followers": _count(raw.get("author_followers") or author.get("followers_count")),
        "source_tier": source_tier,
        "created_at": created_at,
        "published_date": (
            datetime.fromtimestamp(created_at, tz=timezone.utc).date().isoformat()
            if created_at
            else ""
        ),
        "like_count": _count(raw.get("like_count") or raw.get("favorite_count")),
        "retweet_count": _count(raw.get("retweet_count")),
        "reply_count": _count(raw.get("reply_count")),
        "quote_count": _count(raw.get("quote_count")),
        "bookmark_count": _count(raw.get("bookmark_count")),
        "view_count": _count(raw.get("view_count")),
        "lang": _plain(raw.get("lang")),
        "in_reply_to": raw.get("in_reply_to"),
        "is_retweet": bool(raw.get("is_retweet")),
        "is_quote": bool(raw.get("is_quote")),
        "external_urls": _expanded_urls(raw.get("urls")),
        "url": f"https://x.com/{handle}/status/{post_id}",
        "matched_queries": sorted(
            {str(item) for item in raw.get("matched_queries", []) if str(item).strip()}
        ),
    }


def fetch_posts(
    settings: dict[str, Any],
    cookie: str = "",
    fetcher: Callable[..., list[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    if not settings.get("enabled", True):
        return [], "disabled"
    if not cookie.strip():
        return [], "missing-cookie"
    cookies = parse_cookie(cookie)
    missing = [name for name in ("auth_token", "ct0") if not cookies.get(name)]
    if missing:
        return [], "invalid-cookie-missing-" + "-".join(missing)
    queries = build_queries(settings)
    if not queries:
        return [], "missing-queries"
    fetcher = fetcher or _search
    try:
        raw_posts = fetcher(
            queries,
            int(settings.get("candidate_pool", 40)),
            cookie,
            float(settings.get("request_interval_seconds", 2.0)),
        )
    except XAuthError:
        print("[warning] X Cookie expired or was rejected; continuing without X.", file=sys.stderr)
        return [], "cookie-expired-or-risk-control"
    except XRateLimitError:
        print("[warning] X rate limit reached; continuing without X.", file=sys.stderr)
        return [], "rate-limited"
    except Exception as exc:
        detail = _safe_error_detail(exc, cookies)
        suffix = f": {detail}" if detail else ""
        print(
            f"[warning] X fetch failed ({type(exc).__name__}{suffix}); "
            "continuing without X.",
            file=sys.stderr,
        )
        return [], "fetch-failed"

    by_id: dict[str, dict[str, Any]] = {}
    for raw in raw_posts:
        item = _normalize(raw, settings)
        if item is None:
            continue
        existing = by_id.get(item["id"])
        matched = set((existing or {}).get("matched_queries", []))
        matched.update(item["matched_queries"])
        item["matched_queries"] = sorted(matched)
        by_id[item["id"]] = item
    posts = list(by_id.values())[: int(settings.get("candidate_pool", 40))]
    return posts, "fetched" if posts else "empty-or-cookie-expired"


def _content_type(post: dict[str, Any]) -> str:
    text = post.get("text", "").lower()
    scores = {
        label: sum(term in text for term in terms) for label, terms in CONTENT_TYPES.items()
    }
    label, score = max(scores.items(), key=lambda pair: pair[1])
    if score:
        return label
    if post.get("source_tier") == "官方账号":
        return "官方动态"
    if post.get("source_tier") == "领域专家":
        return "专家观点"
    return "前沿资讯"


def _score(post: dict[str, Any], settings: dict[str, Any], now_ts: int | None = None) -> int:
    text = post.get("text", "").lower()
    topic_hits = sum(term in text for term in TOPIC_TERMS)
    relevance = min(25.0, 10 + 3 * min(len(post.get("matched_queries", [])), 2) + 3 * min(topic_hits, 3))
    source = {
        "官方账号": 25.0,
        "领域专家": 22.0,
        "认证来源": 14.0,
        "主题发现": 7.0,
    }.get(post.get("source_tier"), 5.0)
    information_hits = sum(term in text for term in INFORMATION_TERMS)
    information = min(
        20.0,
        min(len(post.get("text", "")) / 240, 1) * 10
        + min(information_hits, 3) * 2
        + (4 if post.get("external_urls") else 0),
    )
    now_ts = now_ts or int(time.time())
    max_age = max(1, int(settings.get("max_age_days", 7))) * 86400
    age = max(0, now_ts - int(post.get("created_at") or now_ts))
    freshness = max(0.0, 15 * (1 - age / max_age))
    engagement_total = (
        _count(post.get("like_count"))
        + 2 * _count(post.get("retweet_count"))
        + _count(post.get("quote_count"))
    )
    engagement = min(10.0, math.log10(engagement_total + 1) * 2.5)
    originality = 0 if post.get("is_retweet") else (3 if post.get("is_quote") else 5)
    return round(relevance + source + information + freshness + engagement + originality)


def prepare_post_candidates(
    posts: list[dict[str, Any]], settings: dict[str, Any], now_ts: int | None = None
) -> list[dict[str, Any]]:
    now_ts = now_ts or int(time.time())
    maximum_age = int(settings.get("max_age_days", 7)) * 86400
    minimum_chars = int(settings.get("min_text_chars", 35))
    blocked = tuple(
        str(term).lower() for term in settings.get("blocked_terms", DEFAULT_BLOCKED_TERMS)
    )
    allowed_languages = {
        str(item).lower() for item in settings.get("languages", []) if str(item).strip()
    }
    output: list[dict[str, Any]] = []
    signatures: set[str] = set()
    for post in posts:
        text = post.get("text", "")
        lowered = text.lower()
        published = int(post.get("created_at") or 0)
        if published and (now_ts - published > maximum_age or published > now_ts + 3600):
            continue
        if post.get("is_retweet") or post.get("in_reply_to"):
            continue
        if any(term in lowered for term in blocked):
            continue
        language = post.get("lang", "").lower().split("-")[0]
        if (
            allowed_languages
            and language not in allowed_languages
            and post.get("source_tier") not in {"官方账号", "领域专家"}
        ):
            continue
        visible_chars = len(URL_RE.sub("", text).strip())
        if visible_chars < minimum_chars:
            informative_official = (
                post.get("source_tier") == "官方账号"
                and (
                    post.get("external_urls")
                    or any(term in lowered for term in INFORMATION_TERMS)
                )
            )
            if not informative_official:
                continue
        if post.get("source_tier") == "主题发现" and not any(term in lowered for term in TOPIC_TERMS):
            continue
        signature = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", URL_RE.sub("", lowered))
        if signature and signature in signatures:
            continue
        signatures.add(signature)
        item = dict(post)
        item["content_type"] = _content_type(item)
        item["pre_score"] = _score(item, settings, now_ts)
        output.append(item)
    return sorted(output, key=lambda item: (-item["pre_score"], item["id"]))


def _diverse(posts: list[dict[str, Any]], settings: dict[str, Any], count: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    authors: dict[str, int] = {}
    types: dict[str, int] = {}
    for post in posts:
        author = post.get("author_handle", "").lower()
        content_type = post.get("content_type", "前沿资讯")
        if authors.get(author, 0) >= int(settings.get("max_per_author", 2)):
            continue
        if types.get(content_type, 0) >= int(settings.get("max_per_content_type", 2)):
            continue
        output.append(post)
        authors[author] = authors.get(author, 0) + 1
        types[content_type] = types.get(content_type, 0) + 1
        if len(output) >= count:
            break
    return output


def _fallback(posts: list[dict[str, Any]], settings: dict[str, Any], count: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    minimum = int(settings.get("min_score", 65))
    for post in sorted(posts, key=lambda item: (-_score(item, settings), item["id"])):
        score = _score(post, settings)
        if score < minimum:
            continue
        item = dict(post)
        source = item.get("text", "")
        item.update(
            {
                "title": f"@{item['author_handle']} · {source[:72]}{'…' if len(source) > 72 else ''}",
                "score": score,
                "summary_zh": source[:140] + ("…" if len(source) > 140 else ""),
                "reason": "来源可信度、信息增量、主题相关性、新鲜度与互动质量综合评分",
                "ranking_source": "deterministic-fallback",
            }
        )
        selected.append(item)
    return _diverse(selected, settings, count)


def _prompt(posts: list[dict[str, Any]], settings: dict[str, Any]) -> str:
    candidates = [
        {
            "id": post["id"],
            "author": f"{post['author_name']} (@{post['author_handle']})",
            "source_tier": post["source_tier"],
            "text": post["text"][:1000],
            "external_urls": post["external_urls"],
            "published_date": post["published_date"],
            "likes": post["like_count"],
            "retweets": post["retweet_count"],
            "quotes": post["quote_count"],
            "views": post["view_count"],
            "content_type": post.get("content_type"),
            "pre_score": post.get("pre_score"),
        }
        for post in posts
    ]
    return f"""你是 AI 研究者的 X（Twitter）前沿信息策展助手。请最多选择 {int(settings.get('max_items', 6))} 条。

优先级：
1. AI 公司、研究机构官方账号的模型、产品、研究、安全或组织动态；
2. 可信研究者给出有信息增量、有明确论点的原创观点；
3. 新论文、开源项目、数据集、评测和高质量技术实测。

排除营销、币圈、抽奖、无上下文情绪、纯转发、回复、重复消息和只靠热度的内容。
官方账号不是自动入选；必须有明确新信息。互动指标只是弱信号。
按百分制综合来源可信度、信息增量、主题相关性、新鲜度与可行动性；仅选择 score >= {int(settings.get('min_score', 65))}。
title 用中文概括核心消息，不超过 32 字；summary_zh 不超过 80 字；reason 不超过 45 字。
只能依据候选文本和链接，不得补充未提供的事实，并区分官方声明、个人观点与论文结论。
严格输出 JSON：{{"posts":[{{"id":"...","score":82,"title":"...","summary_zh":"...","reason":"..."}}]}}

候选：
{json.dumps(candidates, ensure_ascii=False)}
"""


def rank_posts(
    posts: list[dict[str, Any]], settings: dict[str, Any], llm: dict[str, Any]
) -> list[dict[str, Any]]:
    if not posts:
        return []
    maximum = int(settings.get("max_items", 6))
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not llm.get("enabled", True) or not api_key:
        return _fallback(posts, settings, maximum)
    try:
        client = OpenAI(
            api_key=api_key,
            base_url=os.environ.get("LLM_BASE_URL") or llm.get("base_url"),
        )
        response = client.chat.completions.create(
            model=os.environ.get("LLM_MODEL") or llm.get("model", "qwen-plus"),
            temperature=float(llm.get("temperature", 0.1)),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "只输出 JSON，不要 Markdown。"},
                {"role": "user", "content": _prompt(posts, settings)},
            ],
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        choices = parsed.get("posts", parsed.get("selected", []))
        if not isinstance(choices, list):
            raise ValueError("unsupported X JSON response")
    except (OpenAIError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"[warning] X reranking failed ({type(exc).__name__}); using fallback.", file=sys.stderr)
        return _fallback(posts, settings, maximum)

    by_id = {post["id"]: post for post in posts}
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for choice in choices:
        post_id = str(choice.get("id", "")) if isinstance(choice, dict) else ""
        if post_id not in by_id or post_id in seen:
            continue
        try:
            score = max(1, min(100, int(choice.get("score", 1))))
        except (TypeError, ValueError):
            continue
        if score < int(settings.get("min_score", 65)):
            continue
        item = dict(by_id[post_id])
        item.update(
            {
                "score": score,
                "title": str(choice.get("title", "")).strip()[:80]
                or f"@{item['author_handle']} 的最新动态",
                "summary_zh": str(choice.get("summary_zh", "")).strip()[:200],
                "reason": str(choice.get("reason", "")).strip()[:120],
                "ranking_source": "batched-llm",
            }
        )
        output.append(item)
        seen.add(post_id)
        if len(output) >= maximum:
            break
    if len(output) < maximum:
        output.extend(
            _fallback([post for post in posts if post["id"] not in seen], settings, maximum)
        )
    unique = {item["id"]: item for item in output}
    ranked = sorted(unique.values(), key=lambda item: (-int(item.get("score") or 0), item["id"]))
    return _diverse(ranked, settings, maximum)
