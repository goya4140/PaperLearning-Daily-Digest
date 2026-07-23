from __future__ import annotations

import html
import json
import math
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from openai import OpenAI, OpenAIError


SEARCH_URL = "https://www.zhihu.com/api/v4/search_v3"
TAG_RE = re.compile(r"<[^>]+>")
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SIGNER_PATH = ROOT / "vendor/mediacrawler/libs/zhihu.js"
DEFAULT_BLOCKED_TERMS = (
    "加微信",
    "私信领取",
    "训练营",
    "付费咨询",
    "课程优惠",
    "求职辅导",
    "保 offer",
    "招生",
    "软广",
    "多平台整理",
    "全网整理",
    "来源覆盖多个平台",
)
EXPERIENCE_TERMS = (
    "面经",
    "复盘",
    "亲历",
    "亲身",
    "流程",
    "时间线",
    "踩坑",
    "失败",
    "教训",
    "offer",
    "实习",
    "面试题",
)
RESEARCH_TERMS = (
    "科研",
    "研究方向",
    "读博",
    "博士",
    "实验室",
    "论文",
    "选题",
    "投稿",
    "审稿",
    "学术",
)
EXPLANATION_TERMS = (
    "原理",
    "机制",
    "解读",
    "推导",
    "为什么",
    "如何理解",
    "例子",
    "对比",
    "本质",
)
CONTENT_TYPES = {
    "大厂面经": ("面试", "面经", "实习", "校招", "社招", "offer", "求职"),
    "科研方向": ("科研", "研究方向", "读博", "博士", "实验室", "选题", "学术"),
    "知识解读": (
        "原理",
        "机制",
        "理论",
        "知识",
        "解读",
        "推导",
        "为什么",
        "如何理解",
        "本质",
    ),
    "成长复盘": ("复盘", "经验", "踩坑", "教训", "职业发展", "学习路线"),
}


class ZhihuAuthError(RuntimeError):
    pass


class ZhihuRateLimitError(RuntimeError):
    pass


def _plain(value: Any) -> str:
    return " ".join(html.unescape(TAG_RE.sub(" ", str(value or ""))).split())


def _count(value: Any) -> int:
    try:
        return max(0, int(float(str(value or "0").replace(",", ""))))
    except ValueError:
        return 0


def _signer_path() -> Path:
    configured = os.environ.get("ZHIHU_SIGNER_JS", "").strip()
    return Path(configured) if configured else DEFAULT_SIGNER_PATH


def _load_signer(path: Path | None = None) -> Callable[[str, str], dict[str, str]]:
    signer_path = path or _signer_path()
    if not signer_path.is_file():
        raise FileNotFoundError(
            f"Zhihu signer not found at {signer_path}; run the pinned MediaCrawler checkout step"
        )
    import execjs

    context = execjs.compile(signer_path.read_text(encoding="utf-8-sig"))

    def sign(uri: str, cookie: str) -> dict[str, str]:
        result = context.call("get_sign", uri, cookie)
        if not isinstance(result, dict) or not result.get("x-zse-96"):
            raise RuntimeError("Zhihu signer returned an invalid result")
        return {str(key): str(value) for key, value in result.items()}

    return sign


def _search(
    keywords: list[str],
    count: int,
    cookie: str,
    interval: float,
    search_time: str = "a_year",
    signer: Callable[[str, str], dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    signer = signer or _load_signer()
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cookie": cookie.strip(),
            "Referer": "https://www.zhihu.com/search?type=content",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36"
            ),
            "X-Api-Version": "3.0.91",
            "X-App-Za": "OS=Web",
            "X-Requested-With": "fetch",
            "X-Zse-93": "101_3_3.0",
        }
    )
    output: list[dict[str, Any]] = []
    per_query = max(1, math.ceil(count / max(len(keywords), 1)))
    for index, keyword in enumerate(keywords):
        if index:
            time.sleep(interval)
        params = {
            "gk_version": "gz-gaokao",
            "t": "general",
            "q": keyword,
            "correction": 1,
            "offset": 0,
            "limit": per_query,
            "filter_fields": "",
            "lc_idx": 0,
            "show_all_topics": 0,
            "search_source": "Filter",
            "time_interval": search_time,
            "sort": "",
            "vertical": "",
        }
        uri = f"/api/v4/search_v3?{urlencode(params)}"
        headers = signer(uri, cookie)
        response = session.get(SEARCH_URL, params=params, headers=headers, timeout=20)
        if response.status_code in (401, 403):
            raise ZhihuAuthError(f"Zhihu returned HTTP {response.status_code}")
        if response.status_code == 429:
            raise ZhihuRateLimitError("Zhihu returned HTTP 429")
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(str((payload.get("error") or {}).get("message") or "Zhihu API error"))
        for result in payload.get("data") or []:
            if result.get("type") not in ("search_result", "zvideo"):
                continue
            item = result.get("object")
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            normalized["matched_keywords"] = [keyword]
            output.append(normalized)
            if len(output) >= count:
                return output
    return output


def _normalize(raw: dict[str, Any]) -> dict[str, Any] | None:
    content_type = str(raw.get("type") or "").strip()
    if content_type not in ("answer", "article"):
        return None
    content_id = str(raw.get("id") or "").strip()
    if not content_id:
        return None
    question = raw.get("question") if isinstance(raw.get("question"), dict) else {}
    if content_type == "answer":
        question_id = str(question.get("id") or raw.get("question_id") or "").strip()
        if not question_id:
            return None
        url = f"https://www.zhihu.com/question/{question_id}/answer/{content_id}"
        title = _plain(raw.get("title") or question.get("title"))
    else:
        question_id = ""
        url = f"https://zhuanlan.zhihu.com/p/{content_id}"
        title = _plain(raw.get("title"))
    author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    content = _plain(raw.get("content"))
    excerpt = _plain(raw.get("excerpt") or raw.get("description"))
    created_at = _count(
        raw.get("created_time") or raw.get("created") or raw.get("created_at")
    )
    updated_at = _count(
        raw.get("updated_time") or raw.get("updated") or raw.get("updated_at")
    )
    published_date = ""
    if created_at:
        published_date = datetime.fromtimestamp(
            created_at, tz=ZoneInfo("Asia/Shanghai")
        ).date().isoformat()
    return {
        "id": f"{content_type}:{content_id}",
        "content_id": content_id,
        "question_id": question_id,
        "platform_type": content_type,
        "title": title or "知乎内容",
        "content": content,
        "excerpt": excerpt,
        "author": _plain(author.get("name")),
        "created_at": created_at,
        "updated_at": updated_at,
        "published_date": published_date,
        "voteup_count": _count(raw.get("voteup_count")),
        "comment_count": _count(raw.get("comment_count")),
        "url": url,
        "matched_keywords": sorted(
            {str(item) for item in raw.get("matched_keywords", []) if str(item).strip()}
        ),
    }


def fetch_contents(
    settings: dict[str, Any],
    cookie: str = "",
    fetcher: Callable[..., list[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    if not settings.get("enabled", True):
        return [], "disabled"
    if not cookie.strip():
        return [], "missing-cookie"
    if not re.search(r"(?:^|;\s*)d_c0=", cookie):
        return [], "invalid-cookie-missing-d_c0"
    keywords = [str(item).strip() for item in settings.get("keywords", []) if str(item).strip()]
    if not keywords:
        return [], "missing-keywords"
    fetcher = fetcher or _search
    try:
        raw_contents = fetcher(
            keywords,
            int(settings.get("candidate_pool", 32)),
            cookie,
            float(settings.get("request_interval_seconds", 1.5)),
            str(settings.get("search_time", "a_year")),
        )
    except ZhihuAuthError:
        print(
            "[warning] Zhihu Cookie expired or request was blocked; continuing without Zhihu.",
            file=sys.stderr,
        )
        return [], "cookie-expired-or-risk-control"
    except ZhihuRateLimitError:
        print("[warning] Zhihu rate limit reached; continuing without Zhihu.", file=sys.stderr)
        return [], "rate-limited"
    except Exception as exc:
        print(
            f"[warning] Zhihu fetch failed ({type(exc).__name__}); continuing without Zhihu.",
            file=sys.stderr,
        )
        return [], "fetch-failed"

    by_id: dict[str, dict[str, Any]] = {}
    for raw in raw_contents:
        item = _normalize(raw)
        if item is None:
            continue
        existing = by_id.get(item["id"])
        matched = set((existing or {}).get("matched_keywords", []))
        matched.update(item["matched_keywords"])
        item["matched_keywords"] = sorted(matched)
        if existing and len(existing.get("content", "")) > len(item.get("content", "")):
            item["content"] = existing["content"]
        by_id[item["id"]] = item
    output = list(by_id.values())[: int(settings.get("candidate_pool", 32))]
    return output, "fetched" if output else "empty-or-cookie-expired"


def _content_type(item: dict[str, Any]) -> str:
    title = str(item.get("title", "")).lower()
    title_scores = {
        label: sum(term.lower() in title for term in terms)
        for label, terms in CONTENT_TYPES.items()
    }
    title_label, title_score = max(title_scores.items(), key=lambda pair: pair[1])
    if title_score:
        return title_label
    fields = (
        (str(item.get("excerpt", "")).lower(), 2),
        (str(item.get("content", "")).lower(), 1),
    )
    scores = {
        label: sum(
            weight * sum(term.lower() in text for term in terms)
            for text, weight in fields
        )
        for label, terms in CONTENT_TYPES.items()
    }
    label, score = max(scores.items(), key=lambda pair: pair[1])
    return label if score else "经验讨论"


def _score(item: dict[str, Any], settings: dict[str, Any], now_ts: int | None = None) -> int:
    text = f"{item.get('title', '')} {item.get('excerpt', '')} {item.get('content', '')}".lower()
    relevance_hits = sum(
        term.lower() in text for terms in CONTENT_TYPES.values() for term in terms
    )
    relevance = min(
        30.0,
        16 + 4 * min(len(item.get("matched_keywords", [])), 2) + 2 * min(relevance_hits, 3),
    )
    evidence_hits = sum(term.lower() in text for term in EXPERIENCE_TERMS)
    evidence_hits += sum(term.lower() in text for term in RESEARCH_TERMS)
    evidence_hits += sum(term.lower() in text for term in EXPLANATION_TERMS)
    evidence = min(25.0, 7 + 3 * min(evidence_hits, 6))
    body_length = len(item.get("content") or item.get("excerpt", ""))
    depth = min(20.0, body_length / 50)
    credibility = min(
        10.0,
        (3 if item.get("author") else 0)
        + (3 if body_length >= 500 else 0)
        + (2 if _count(item.get("voteup_count")) >= 20 else 0)
        + (2 if _count(item.get("comment_count")) >= 5 else 0),
    )
    now_ts = now_ts or int(time.time())
    # First publication is the meaningful freshness signal for experience posts.
    # A minor edit must not make an old interview guide look current.
    age = max(0, now_ts - int(item.get("created_at") or item.get("updated_at") or now_ts))
    max_age_seconds = max(1, int(settings.get("max_age_days", 730))) * 86400
    freshness = max(0.0, 10 * (1 - age / max_age_seconds))
    engagement = min(
        5.0,
        math.log10(1 + _count(item.get("voteup_count"))) * 1.5
        + math.log10(1 + _count(item.get("comment_count"))),
    )
    return round(relevance + evidence + depth + credibility + freshness + engagement)


def prepare_content_candidates(
    contents: list[dict[str, Any]], settings: dict[str, Any], now_ts: int | None = None
) -> list[dict[str, Any]]:
    now_ts = now_ts or int(time.time())
    maximum_age = int(settings.get("max_age_days", 730)) * 86400
    minimum_chars = int(settings.get("min_content_chars", 120))
    blocked = tuple(
        str(term).lower() for term in settings.get("blocked_terms", DEFAULT_BLOCKED_TERMS)
    )
    output = []
    for content in contents:
        text = f"{content.get('title', '')} {content.get('excerpt', '')} {content.get('content', '')}".lower()
        published = int(content.get("created_at") or content.get("updated_at") or 0)
        if published and now_ts - published > maximum_age:
            continue
        if any(term in text for term in blocked):
            continue
        body = content.get("content") or content.get("excerpt", "")
        if len(body) < minimum_chars:
            continue
        item = dict(content)
        item["content_type"] = _content_type(item)
        item["pre_score"] = _score(item, settings, now_ts)
        output.append(item)
    return sorted(output, key=lambda item: (-item["pre_score"], item.get("id", "")))


def _diverse(
    contents: list[dict[str, Any]], settings: dict[str, Any], count: int
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    authors: dict[str, int] = {}
    types: dict[str, int] = {}
    questions: set[str] = set()
    for content in contents:
        author = str(content.get("author", "")).strip().lower()
        content_type = str(content.get("content_type", "经验讨论"))
        question_id = str(content.get("question_id", "")).strip()
        if author and authors.get(author, 0) >= int(settings.get("max_per_author", 1)):
            continue
        if types.get(content_type, 0) >= int(settings.get("max_per_content_type", 2)):
            continue
        if question_id and question_id in questions:
            continue
        output.append(content)
        if author:
            authors[author] = authors.get(author, 0) + 1
        types[content_type] = types.get(content_type, 0) + 1
        if question_id:
            questions.add(question_id)
        if len(output) >= count:
            break
    return output


def _fallback(
    contents: list[dict[str, Any]], settings: dict[str, Any], count: int
) -> list[dict[str, Any]]:
    output = []
    minimum = int(settings.get("min_score", 65))
    for content in sorted(
        contents, key=lambda item: (-_score(item, settings), item.get("id", ""))
    ):
        score = _score(content, settings)
        if score < minimum:
            continue
        item = dict(content)
        source = item.get("excerpt") or item.get("content") or item.get("title", "")
        item.update(
            {
                "score": score,
                "summary_zh": source[:110] + ("…" if len(source) > 110 else ""),
                "reason": "相关性、经验证据、内容深度、可信度与新鲜度综合评分",
                "ranking_source": "deterministic-fallback",
            }
        )
        output.append(item)
    return _diverse(output, settings, count)


def _prompt(contents: list[dict[str, Any]], settings: dict[str, Any]) -> str:
    candidates = [
        {
            "id": item["id"],
            "title": item["title"],
            "excerpt": item["excerpt"][:700],
            "content": item["content"][:1200],
            "author": item["author"],
            "voteup_count": item["voteup_count"],
            "comment_count": item["comment_count"],
            "published_date": item["published_date"],
            "content_type": item.get("content_type"),
            "pre_score": item.get("pre_score"),
            "matched_keywords": item["matched_keywords"],
        }
        for item in contents
    ]
    return f"""你是 AI 从业者与研究者的知乎内容策展助手。请从候选中选择最多 {int(settings.get('max_items', 5))} 条。

目标内容：
1. 大厂面试经验：优先第一手流程、具体问题、准备策略、失败教训与复盘。
2. 科研方向讨论：优先明确论据、适用边界、不同观点和真实研究经验。
3. 知识解读：优先讲清机制、推导、例子、对比和常见误区。

降低纯情绪输出、空泛鸡汤、课程/咨询导流、标题党、拼贴转载与过时经验的分数。
点赞和评论只作为弱信号；不得把个人经验表述成普遍事实。
按百分制综合判断主题相关性、经验或论据质量、内容深度、可信度、新鲜度与互动质量。
score 为 1-100 整数，只选择 score >= {int(settings.get('min_score', 65))}。
summary_zh 不超过 70 字，reason 不超过 45 字；只基于候选文本，不虚构外部事实。
严格输出 JSON：{{"contents":[{{"id":"answer:123","score":78,"summary_zh":"...","reason":"..."}}]}}

候选：
{json.dumps(candidates, ensure_ascii=False)}
"""


def rank_contents(
    contents: list[dict[str, Any]], settings: dict[str, Any], llm: dict[str, Any]
) -> list[dict[str, Any]]:
    if not contents:
        return []
    maximum = int(settings.get("max_items", 5))
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not llm.get("enabled", True) or not api_key:
        return _fallback(contents, settings, maximum)
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
                {"role": "user", "content": _prompt(contents, settings)},
            ],
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        choices = parsed.get("contents", parsed.get("selected", []))
        if not isinstance(choices, list):
            raise ValueError("unsupported Zhihu JSON response")
    except (OpenAIError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(
            f"[warning] Zhihu reranking failed ({type(exc).__name__}); using fallback.",
            file=sys.stderr,
        )
        return _fallback(contents, settings, maximum)

    by_id = {item["id"]: item for item in contents}
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for choice in choices:
        content_id = str(choice.get("id", "")) if isinstance(choice, dict) else ""
        if content_id not in by_id or content_id in seen:
            continue
        try:
            score = max(1, min(100, int(choice.get("score", 1))))
        except (TypeError, ValueError):
            continue
        if score < int(settings.get("min_score", 65)):
            continue
        item = dict(by_id[content_id])
        item.update(
            {
                "score": score,
                "summary_zh": str(choice.get("summary_zh", ""))[:180],
                "reason": str(choice.get("reason", ""))[:120],
                "ranking_source": "batched-llm",
            }
        )
        output.append(item)
        seen.add(content_id)
        if len(output) >= maximum:
            break
    if len(output) < maximum:
        output.extend(
            _fallback(
                [item for item in contents if item["id"] not in seen],
                settings,
                maximum - len(output),
            )
        )
    unique = {item["id"]: item for item in output}
    ranked = sorted(
        unique.values(), key=lambda item: (-int(item.get("score") or 0), item["id"])
    )
    return _diverse(ranked, settings, maximum)
