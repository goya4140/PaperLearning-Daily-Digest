from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI

from .selection import deterministic_shortlist


SYSTEM_PROMPT = """You rank daily AI research papers for a research learning system.
Return JSON only. Use title and abstract as discovery evidence, never claim to have read the paper.
Select two lanes:
- focus: strong fit to the configured research profiles, including semantic variants beyond literal phrases.
- explore: important, technically interesting, or emerging work outside the focus profiles; maximize directional diversity.
Prefer papers with a concrete research question, mechanism, evaluation, dataset, benchmark, or reusable system insight.
Avoid near-duplicates and generic application papers with weak methodological contribution.
For every selected paper return id, lane, score (1-10), reason (Chinese, <=60 chars), one_liner (Chinese, <=90 chars).
"""


def _payload(candidates: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    papers = []
    for item in candidates:
        papers.append(
            {
                "id": item["id"],
                "title": item["title"],
                "abstract": item.get("abstract", "")[:1800],
                "categories": item.get("categories", []),
                "focus_profile": item.get("focus_profile", ""),
                "focus_score": item.get("focus_score", 0),
                "explore_score": item.get("explore_score", 0),
            }
        )
    return {
        "focus_count": int(settings.get("focus_count", 4)),
        "explore_count": int(settings.get("explore_count", 4)),
        "papers": papers,
    }


def rerank(candidates: list[dict[str, Any]], selection: dict[str, Any], llm: dict[str, Any]) -> list[dict[str, Any]]:
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not llm.get("enabled", True) or not api_key:
        return deterministic_shortlist(candidates, selection)
    client = OpenAI(api_key=api_key, base_url=os.environ.get("LLM_BASE_URL") or llm.get("base_url"))
    response = client.chat.completions.create(
        model=os.environ.get("LLM_MODEL") or llm.get("model", "gpt-4.1-mini"),
        temperature=float(llm.get("temperature", 0.1)),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(_payload(candidates, selection), ensure_ascii=False)},
        ],
    )
    parsed = json.loads(response.choices[0].message.content or "{}")
    selected = parsed.get("papers", parsed.get("selected", []))
    by_id = {item["id"]: item for item in candidates}
    limits = {"focus": int(selection.get("focus_count", 4)), "explore": int(selection.get("explore_count", 4))}
    counts = {"focus": 0, "explore": 0}
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for choice in selected:
        paper_id = str(choice.get("id", ""))
        lane = str(choice.get("lane", ""))
        if paper_id not in by_id or lane not in limits or paper_id in seen or counts[lane] >= limits[lane]:
            continue
        item = dict(by_id[paper_id])
        item.update(
            {
                "lane": lane,
                "llm_score": max(1, min(10, int(choice.get("score", 1)))),
                "reason": str(choice.get("reason", ""))[:160],
                "one_liner": str(choice.get("one_liner", ""))[:240],
                "ranking_source": "batched-llm",
            }
        )
        output.append(item)
        seen.add(paper_id)
        counts[lane] += 1
    if counts != limits:
        fallback = deterministic_shortlist([item for item in candidates if item["id"] not in seen], selection)
        for item in fallback:
            lane = item["lane"]
            if counts[lane] < limits[lane]:
                output.append(item)
                counts[lane] += 1
    return sorted(output, key=lambda item: (0 if item["lane"] == "focus" else 1, -(item.get("llm_score") or 0), item.get("rank", 10**9)))

