from openai import OpenAIError

import paper_digest.llm_ranker as ranker


def test_llm_error_falls_back_to_deterministic(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    def broken_client(*args, **kwargs):
        raise OpenAIError("provider unavailable")

    monkeypatch.setattr(ranker, "OpenAI", broken_client)
    candidates = [
        {
            "id": "2601.00001",
            "title": "Agent Skill Discovery",
            "abstract": "A reusable skill library.",
            "rank": 1,
            "categories": ["cs.AI"],
            "focus_score": 8.0,
            "focus_reasons": ["agent skill"],
            "explore_score": 2.0,
            "explore_reasons": ["novelty"],
        },
        {
            "id": "2601.00002",
            "title": "A New Geometry Benchmark",
            "abstract": "We release a broad benchmark.",
            "rank": 2,
            "categories": ["cs.LG"],
            "focus_score": 0.0,
            "focus_reasons": [],
            "explore_score": 7.0,
            "explore_reasons": ["novelty"],
        },
    ]
    result = ranker.rerank(candidates, {"focus_count": 1, "explore_count": 1}, {"enabled": True})
    assert len(result) == 2
    assert {item["ranking_source"] for item in result} == {"deterministic-fallback"}
