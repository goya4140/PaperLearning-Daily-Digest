from paper_digest.selection import deterministic_candidates, deterministic_shortlist


SETTINGS = {
    "deterministic_pool_per_lane": 5,
    "llm_candidate_limit": 8,
    "focus_count": 1,
    "explore_count": 1,
    "diversity_penalty": 0.4,
    "focus_profiles": [
        {
            "id": "agents",
            "label": "Agent Skills",
            "categories": ["cs.AI"],
            "concepts": [["agent skill", "tool learning"]],
        }
    ],
}


def paper(paper_id, title, abstract, rank, categories=None):
    return {"id": paper_id, "title": title, "abstract": abstract, "rank": rank, "categories": categories or ["cs.AI"]}


def test_two_lane_selection_preserves_exploration():
    papers = [
        paper("2601.00001", "Agent Skill Discovery", "A reusable agent skill library.", 3),
        paper("2601.00002", "Novel Protein Geometry", "We release a benchmark dataset for molecular structures.", 1, ["cs.LG"]),
        paper("2601.00003", "Generic Classification", "A standard classifier.", 2, ["cs.LG"]),
    ]
    candidates = deterministic_candidates(papers, SETTINGS)
    shortlist = deterministic_shortlist(candidates, SETTINGS)
    assert {item["lane"] for item in shortlist} == {"focus", "explore"}
    assert next(item for item in shortlist if item["lane"] == "focus")["id"] == "2601.00001"
    assert next(item for item in shortlist if item["lane"] == "explore")["id"] != "2601.00001"
    assert any(item["focus_score"] == 0 for item in candidates)
