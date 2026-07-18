from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any


STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it", "of",
    "on", "or", "our", "that", "the", "their", "this", "to", "via", "we", "with", "towards",
    "using", "based", "new", "model", "models", "learning", "method", "methods", "approach",
}


def tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z][a-z0-9-]{2,}", text.casefold())
        if token not in STOPWORDS
    }


def _idf(papers: list[dict[str, Any]]) -> dict[str, float]:
    document_frequency: Counter[str] = Counter()
    for paper in papers:
        document_frequency.update(tokens(f"{paper.get('title', '')} {paper.get('abstract', '')}"))
    total = max(len(papers), 1)
    return {term: math.log((total + 1) / (count + 1)) + 1 for term, count in document_frequency.items()}


def focus_score(paper: dict[str, Any], profiles: list[dict[str, Any]]) -> tuple[float, str, list[str]]:
    title = paper.get("title", "").casefold()
    abstract = paper.get("abstract", "").casefold()
    categories = set(paper.get("categories", []))
    best = (0.0, "", [])
    for profile in profiles:
        score = 0.0
        matched: list[str] = []
        for concept in profile.get("concepts", []):
            concept_hit = False
            for phrase in concept:
                term = str(phrase).casefold()
                if term in title:
                    score += 6.0
                    concept_hit = True
                elif term in abstract:
                    score += 2.2
                    concept_hit = True
            if concept_hit:
                matched.append(" / ".join(concept[:3]))
        if categories & set(profile.get("categories", [])):
            score += 0.5
        candidate = (score, str(profile.get("label", profile.get("id", ""))), matched)
        if candidate[0] > best[0]:
            best = candidate
    return best


def explore_score(paper: dict[str, Any], idf: dict[str, float], total: int) -> tuple[float, list[str]]:
    title_terms = tokens(paper.get("title", ""))
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".casefold()
    novelty = sum(sorted((idf.get(term, 1.0) for term in title_terms), reverse=True)[:8]) / max(len(title_terms), 1)
    source_rank = int(paper.get("rank") or total)
    source_signal = max(0.0, 1.0 - ((source_rank - 1) / max(total, 1)))
    category_breadth = min(len(set(paper.get("categories", []))), 3) / 3
    evidence_markers = sum(
        marker in text
        for marker in ("benchmark", "dataset", "open-source", "we release", "state-of-the-art", "ablation")
    )
    score = novelty * 2.0 + source_signal * 2.0 + category_breadth + min(evidence_markers, 3) * 0.35
    reasons = ["daily-corpus novelty"]
    if category_breadth >= 2 / 3:
        reasons.append("cross-category")
    if evidence_markers:
        reasons.append("empirical/release signal")
    return score, reasons


def _similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    a, b = tokens(left.get("title", "")), tokens(right.get("title", ""))
    return len(a & b) / max(len(a | b), 1)


def _diverse_top(items: list[dict[str, Any]], count: int, score_key: str, penalty: float) -> list[dict[str, Any]]:
    remaining = list(items)
    chosen: list[dict[str, Any]] = []
    while remaining and len(chosen) < count:
        def utility(item: dict[str, Any]) -> float:
            overlap = max((_similarity(item, other) for other in chosen), default=0.0)
            return float(item[score_key]) - penalty * overlap
        winner = max(remaining, key=lambda item: (utility(item), item.get("id", "")))
        chosen.append(winner)
        remaining.remove(winner)
    return chosen


def deterministic_candidates(papers: list[dict[str, Any]], settings: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = settings.get("focus_profiles", [])
    idf = _idf(papers)
    enriched: list[dict[str, Any]] = []
    for paper in papers:
        item = dict(paper)
        f_score, profile, f_reasons = focus_score(item, profiles)
        e_score, e_reasons = explore_score(item, idf, len(papers))
        item.update(
            {
                "focus_score": round(f_score, 4),
                "focus_profile": profile,
                "focus_reasons": f_reasons,
                "explore_score": round(e_score, 4),
                "explore_reasons": e_reasons,
            }
        )
        enriched.append(item)

    pool_size = int(settings.get("deterministic_pool_per_lane", 30))
    penalty = float(settings.get("diversity_penalty", 0.45))
    focus_ranked = sorted(enriched, key=lambda item: (-item["focus_score"], item.get("rank", 10**9)))
    explore_ranked = sorted(enriched, key=lambda item: (-item["explore_score"], item.get("rank", 10**9)))
    focus_pool = _diverse_top([item for item in focus_ranked if item["focus_score"] > 0], pool_size, "focus_score", penalty)
    explore_pool = _diverse_top(explore_ranked, pool_size, "explore_score", penalty)
    limit = int(settings.get("llm_candidate_limit", 36))
    lane_quota = limit // 2
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    # Reserve half of the LLM context for discovery outside the focus profiles.
    # Otherwise a broad focus profile can silently consume the whole batch.
    for pool, quota in ((focus_pool, lane_quota), (explore_pool, limit - lane_quota)):
        added = 0
        for item in pool:
            if item["id"] in seen:
                continue
            result.append(item)
            seen.add(item["id"])
            added += 1
            if added >= quota:
                break
    if len(result) < limit:
        for item in focus_pool + explore_pool:
            if item["id"] not in seen:
                result.append(item)
                seen.add(item["id"])
            if len(result) >= limit:
                break
    return result[:limit]


def deterministic_shortlist(candidates: list[dict[str, Any]], settings: dict[str, Any]) -> list[dict[str, Any]]:
    focus_count = int(settings.get("focus_count", 4))
    explore_count = int(settings.get("explore_count", 4))
    focus = sorted(candidates, key=lambda item: (-item["focus_score"], item.get("rank", 10**9)))[:focus_count]
    used = {item["id"] for item in focus}
    explore = [item for item in sorted(candidates, key=lambda item: (-item["explore_score"], item.get("rank", 10**9))) if item["id"] not in used][:explore_count]
    output = []
    for lane, items in (("focus", focus), ("explore", explore)):
        for item in items:
            current = dict(item)
            current.update(
                {
                    "lane": lane,
                    "llm_score": None,
                    "one_liner": item.get("abstract", "")[:220].rstrip() + ("…" if len(item.get("abstract", "")) > 220 else ""),
                    "reason": "; ".join(item.get(f"{lane}_reasons", [])) or "deterministic ranking",
                    "ranking_source": "deterministic-fallback",
                }
            )
            output.append(current)
    return output
