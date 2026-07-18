from __future__ import annotations

import json
import math
import os
import sys
from typing import Any, Callable

from openai import OpenAI, OpenAIError


def _count(value: Any) -> int:
    raw = str(value or "0").strip().replace(",", "")
    try:
        if "万" in raw:
            return int(float(raw.replace("万", "")) * 10_000)
        return int(raw)
    except ValueError:
        return 0


def fetch_notes(
    settings: dict[str, Any],
    cookie: str,
    fetcher: Callable[[list[str], int, str], list[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    if not settings.get("enabled", True):
        return [], "disabled"
    if not cookie.strip():
        return [], "missing-cookie"
    if fetcher is None:
        # Runtime dependency is pinned and checked out by GitHub Actions.
        from fetchers.xhs_fetcher import fetch_xhs_notes

        fetcher = fetch_xhs_notes
    try:
        notes = fetcher(
            [str(item) for item in settings.get("keywords", [])],
            int(settings.get("candidate_pool", 24)),
            cookie,
        )
    except Exception as exc:
        print(f"[warning] XHS fetch failed ({type(exc).__name__}); continuing without XHS.", file=sys.stderr)
        return [], "fetch-failed"
    normalized = []
    for note in notes:
        item = dict(note)
        item["liked_count"] = _count(item.get("liked_count"))
        item["content"] = str(item.get("content", "")).strip()
        item["title"] = str(item.get("title", "")).strip() or "小红书笔记"
        normalized.append(item)
    return normalized, "fetched" if normalized else "empty-or-cookie-expired"


def _deterministic_score(note: dict[str, Any]) -> float:
    engagement = math.log10(1 + _count(note.get("liked_count")))
    substance = min(len(note.get("content", "")) / 300, 1.0)
    keyword_breadth = min(len(note.get("matched_keywords", [])), 3) / 3
    return round(engagement * 1.7 + substance * 2.0 + keyword_breadth, 4)


def _fallback(notes: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    ranked = sorted(notes, key=lambda item: (-_deterministic_score(item), item.get("id", "")))[:count]
    output = []
    for note in ranked:
        item = dict(note)
        content = item.get("content", "") or item.get("title", "")
        item.update(
            {
                "score": None,
                "summary_zh": content[:90] + ("…" if len(content) > 90 else ""),
                "reason": "热度、内容完整度与关键词覆盖的确定性排序",
                "ranking_source": "deterministic-fallback",
            }
        )
        output.append(item)
    return output


def _prompt(notes: list[dict[str, Any]], settings: dict[str, Any]) -> str:
    items = [
        {
            "id": note["id"],
            "title": note.get("title", ""),
            "content": note.get("content", "")[:700],
            "liked_count": note.get("liked_count", 0),
            "matched_keywords": note.get("matched_keywords", []),
        }
        for note in notes
    ]
    return f"""你是 AI 研究者的小红书内容策展助手。请从候选中选择最多 {int(settings.get('max_items', 5))} 条。

目标：补充论文之外的工具实践、开源项目、真实使用经验和新兴趋势，同时保持话题多样性。
规则：
1. 优先有操作步骤、对比、复盘、可验证链接或具体经验的内容。
2. 降低纯营销、课程售卖、无信息量转载、标题党和同一事件重复内容的分数。
3. 不因点赞数高就自动入选；点赞数只作为弱信号。
4. score 为 1-10 整数；只选择 score >= {int(settings.get('min_score', 6))} 的内容。
5. summary_zh 不超过 60 字；reason 不超过 40 字。
6. 只基于给定标题和正文，不虚构外部事实。

输出严格 JSON，可为数组，也可为 {{"notes": [...]}}：
[
  {{"id":"原始ID","score":8,"summary_zh":"一句话总结","reason":"入选理由"}}
]

候选：
{json.dumps(items, ensure_ascii=False)}
"""


def rank_notes(notes: list[dict[str, Any]], settings: dict[str, Any], llm: dict[str, Any]) -> list[dict[str, Any]]:
    if not notes:
        return []
    maximum = int(settings.get("max_items", 5))
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not llm.get("enabled", True) or not api_key:
        return _fallback(notes, maximum)
    try:
        client = OpenAI(api_key=api_key, base_url=os.environ.get("LLM_BASE_URL") or llm.get("base_url"))
        response = client.chat.completions.create(
            model=os.environ.get("LLM_MODEL") or llm.get("model", "qwen-plus"),
            temperature=float(llm.get("temperature", 0.1)),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "只输出 JSON，不要 Markdown。"},
                {"role": "user", "content": _prompt(notes, settings)},
            ],
        )
        parsed = json.loads(response.choices[0].message.content or "[]")
        choices = parsed if isinstance(parsed, list) else parsed.get("notes", parsed.get("selected", []))
        if not isinstance(choices, list):
            raise ValueError("unsupported XHS JSON response")
    except (OpenAIError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"[warning] XHS reranking failed ({type(exc).__name__}); using deterministic fallback.", file=sys.stderr)
        return _fallback(notes, maximum)

    by_id = {str(note.get("id", "")): note for note in notes}
    output = []
    seen = set()
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        note_id = str(choice.get("id", ""))
        if note_id not in by_id or note_id in seen:
            continue
        try:
            score = max(1, min(10, int(choice.get("score", 1))))
        except (TypeError, ValueError):
            continue
        if score < int(settings.get("min_score", 6)):
            continue
        item = dict(by_id[note_id])
        item.update(
            {
                "score": score,
                "summary_zh": str(choice.get("summary_zh", ""))[:160],
                "reason": str(choice.get("reason", ""))[:100],
                "ranking_source": "batched-llm",
            }
        )
        output.append(item)
        seen.add(note_id)
        if len(output) >= maximum:
            break
    if len(output) < maximum:
        for item in _fallback([note for note in notes if str(note.get("id")) not in seen], maximum - len(output)):
            output.append(item)
    return output[:maximum]

