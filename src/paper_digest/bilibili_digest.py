from __future__ import annotations

import html
import json
import math
import os
import re
import sys
import time
from typing import Any, Callable

import requests
from openai import OpenAI, OpenAIError


SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
DETAIL_URL = "https://api.bilibili.com/x/web-interface/view"
TAG_RE = re.compile(r"<[^>]+>")


def _count(value: Any) -> int:
    raw = str(value or "0").strip().replace(",", "")
    try:
        if raw.endswith("万"):
            return int(float(raw[:-1]) * 10_000)
        return int(float(raw))
    except ValueError:
        return 0


def _plain(value: Any) -> str:
    return html.unescape(TAG_RE.sub("", str(value or ""))).strip()


def _search(keywords: list[str], count: int, cookie: str, interval: float) -> list[dict[str, Any]]:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (PaperLearning-Daily-Digest; personal research discovery)",
        "Referer": "https://search.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
    })
    if cookie.strip():
        session.headers["Cookie"] = cookie.strip()
    output: list[dict[str, Any]] = []
    per_query = max(1, math.ceil(count / max(len(keywords), 1)))
    for index, keyword in enumerate(keywords):
        if index:
            time.sleep(interval)
        response = session.get(
            SEARCH_URL,
            params={"search_type": "video", "keyword": keyword, "order": "pubdate", "page": 1},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"Bilibili API code {payload.get('code')}")
        for video in (payload.get("data") or {}).get("result") or []:
            item = dict(video)
            item["matched_keywords"] = [keyword]
            output.append(item)
            if len(output) >= count or len(output) % per_query == 0:
                break
        if len(output) >= count:
            break
    return output


def _fetch_video_stats(bvids: list[str], cookie: str, interval: float) -> dict[str, dict[str, int]]:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (PaperLearning-Daily-Digest; personal research discovery)",
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie.strip(),
    })
    output: dict[str, dict[str, int]] = {}
    for index, bvid in enumerate(bvids):
        if index:
            time.sleep(interval)
        try:
            response = session.get(DETAIL_URL, params={"bvid": bvid}, timeout=20)
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                continue
            stat = (payload.get("data") or {}).get("stat") or {}
            output[bvid] = {
                "like_count": _count(stat.get("like")),
                "favorite_count": _count(stat.get("favorite")),
            }
        except (requests.RequestException, ValueError):
            continue
    return output


def fetch_videos(
    settings: dict[str, Any],
    cookie: str = "",
    fetcher: Callable[[list[str], int, str, float], list[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    if not settings.get("enabled", True):
        return [], "disabled"
    if not cookie.strip():
        return [], "missing-cookie"
    keywords = [str(item).strip() for item in settings.get("keywords", []) if str(item).strip()]
    if not keywords:
        return [], "missing-keywords"
    fetcher = fetcher or _search
    try:
        videos = fetcher(
            keywords,
            int(settings.get("candidate_pool", 30)),
            cookie,
            float(settings.get("request_interval_seconds", 1.2)),
        )
    except Exception as exc:
        print(f"[warning] Bilibili fetch failed ({type(exc).__name__}); continuing without Bilibili.", file=sys.stderr)
        return [], "fetch-failed"

    by_id: dict[str, dict[str, Any]] = {}
    for video in videos:
        bvid = str(video.get("bvid") or video.get("id") or "").strip()
        if not bvid:
            continue
        existing = by_id.get(bvid)
        matched = set((existing or {}).get("matched_keywords", []))
        matched.update(str(item) for item in video.get("matched_keywords", []))
        cover = str(video.get("pic") or video.get("cover") or "").strip()
        if cover.startswith("//"):
            cover = "https:" + cover
        by_id[bvid] = {
            "id": bvid,
            "bvid": bvid,
            "title": _plain(video.get("title")) or "B站视频",
            "description": _plain(video.get("description")),
            "author": _plain(video.get("author")),
            "duration": str(video.get("duration") or "").strip(),
            "published_at": int(video.get("pubdate") or video.get("senddate") or 0),
            "view_count": _count(video.get("play")),
            "danmaku_count": _count(video.get("video_review")),
            "cover_url": cover,
            "url": f"https://www.bilibili.com/video/{bvid}",
            "matched_keywords": sorted(matched),
        }
    normalized = list(by_id.values())[: int(settings.get("candidate_pool", 30))]
    return normalized, "fetched" if normalized else "empty-or-cookie-expired"


def enrich_video_stats(
    videos: list[dict[str, Any]],
    cookie: str,
    interval: float = 1.2,
    fetcher: Callable[[list[str], str, float], dict[str, dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    if not videos:
        return [], "not-needed"
    if not cookie.strip():
        return [dict(video) for video in videos], "missing-cookie"
    fetcher = fetcher or _fetch_video_stats
    try:
        stats = fetcher([str(video["bvid"]) for video in videos], cookie, interval)
    except Exception as exc:
        print(f"[warning] Bilibili stats fetch failed ({type(exc).__name__}); keeping base metadata.", file=sys.stderr)
        return [dict(video) for video in videos], "fetch-failed"
    output = []
    enriched = 0
    for video in videos:
        item = dict(video)
        stat = stats.get(str(video["bvid"]))
        if stat is not None:
            item["like_count"] = _count(stat.get("like_count"))
            item["favorite_count"] = _count(stat.get("favorite_count"))
            enriched += 1
        output.append(item)
    if enriched == len(videos):
        return output, "fetched"
    return output, "partial" if enriched else "fetch-failed"


def _score(video: dict[str, Any]) -> float:
    engagement = math.log10(1 + _count(video.get("view_count")))
    discussion = math.log10(1 + _count(video.get("danmaku_count")))
    substance = min(len(video.get("description", "")) / 240, 1.0)
    breadth = min(len(video.get("matched_keywords", [])), 3) / 3
    return round(engagement * 1.4 + discussion * 0.5 + substance * 1.5 + breadth, 4)


def _fallback(videos: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    output = []
    for video in sorted(videos, key=lambda item: (-_score(item), item.get("id", "")))[:count]:
        item = dict(video)
        source = item.get("description") or item.get("title", "")
        item.update({
            "score": None,
            "summary_zh": source[:100] + ("…" if len(source) > 100 else ""),
            "reason": "热度、信息完整度与主题覆盖的确定性排序",
            "ranking_source": "deterministic-fallback",
        })
        output.append(item)
    return output


def _prompt(videos: list[dict[str, Any]], settings: dict[str, Any]) -> str:
    candidates = [{
        "id": video["id"], "title": video["title"], "description": video["description"][:600],
        "author": video["author"], "duration": video["duration"], "view_count": video["view_count"],
        "danmaku_count": video["danmaku_count"], "matched_keywords": video["matched_keywords"],
    } for video in videos]
    return f"""你是 AI 研究者的 B 站视频策展助手。请从候选中选择最多 {int(settings.get('max_items', 5))} 条。

优先：高质量访谈、产品实测、技术演讲、会议录播、论文解读和有证据的工程复盘。
降低：纯营销、标题党、搬运、无具体信息的泛谈以及同一事件的重复内容。
播放量和弹幕只作为弱信号。score 为 1-10 整数，只选择 score >= {int(settings.get('min_score', 6))}。
summary_zh 不超过 60 字，reason 不超过 40 字；只基于候选元数据，不虚构视频内容。
严格输出 JSON：{{"videos":[{{"id":"BV...","score":8,"summary_zh":"...","reason":"..."}}]}}

候选：
{json.dumps(candidates, ensure_ascii=False)}
"""


def rank_videos(videos: list[dict[str, Any]], settings: dict[str, Any], llm: dict[str, Any]) -> list[dict[str, Any]]:
    if not videos:
        return []
    maximum = int(settings.get("max_items", 5))
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not llm.get("enabled", True) or not api_key:
        return _fallback(videos, maximum)
    try:
        client = OpenAI(api_key=api_key, base_url=os.environ.get("LLM_BASE_URL") or llm.get("base_url"))
        response = client.chat.completions.create(
            model=os.environ.get("LLM_MODEL") or llm.get("model", "qwen-plus"),
            temperature=float(llm.get("temperature", 0.1)), response_format={"type": "json_object"},
            messages=[{"role": "system", "content": "只输出 JSON，不要 Markdown。"},
                      {"role": "user", "content": _prompt(videos, settings)}],
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        choices = parsed.get("videos", parsed.get("selected", []))
        if not isinstance(choices, list):
            raise ValueError("unsupported Bilibili JSON response")
    except (OpenAIError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"[warning] Bilibili reranking failed ({type(exc).__name__}); using fallback.", file=sys.stderr)
        return _fallback(videos, maximum)

    by_id = {video["id"]: video for video in videos}
    output, seen = [], set()
    for choice in choices:
        video_id = str(choice.get("id", "")) if isinstance(choice, dict) else ""
        if video_id not in by_id or video_id in seen:
            continue
        try:
            score = max(1, min(10, int(choice.get("score", 1))))
        except (TypeError, ValueError):
            continue
        if score < int(settings.get("min_score", 6)):
            continue
        item = dict(by_id[video_id])
        item.update({"score": score, "summary_zh": str(choice.get("summary_zh", ""))[:160],
                     "reason": str(choice.get("reason", ""))[:100], "ranking_source": "batched-llm"})
        output.append(item)
        seen.add(video_id)
        if len(output) >= maximum:
            break
    if len(output) < maximum:
        output.extend(_fallback([video for video in videos if video["id"] not in seen], maximum - len(output)))
    return output[:maximum]
