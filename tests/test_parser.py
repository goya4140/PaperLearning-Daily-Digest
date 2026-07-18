import datetime as dt

import paper_digest.papers_cool as papers_cool
from paper_digest.papers_cool import PapersCoolParser


def test_parser_extracts_paper():
    parser = PapersCoolParser()
    parser.feed(
        '<div class="panel paper" id="2601.12345">'
        '<a class="title-link">A Test Paper</a>'
        '<a class="author">Ada Lovelace</a>'
        '<a class="subject-cs" href="/arxiv/cs.AI">Artificial Intelligence</a>'
        '<p class="summary">A useful abstract.</p>'
        '<span class="date-data">2026-01-02 03:04:05 UTC</span>'
        '</div>'
    )
    assert parser.papers[0]["id"] == "2601.12345"
    assert parser.papers[0]["categories"] == ["cs.AI"]
    assert parser.papers[0]["published"] == "2026-01-02T03:04:05Z"


def test_empty_papers_cool_day_is_valid(monkeypatch):
    page = '<a class="date">2026-07-18</a><div>Total: 0</div>'
    monkeypatch.setattr(papers_cool, "_request", lambda url: page.encode())
    snapshot = papers_cool.fetch({"categories": ["cs.AI"]}, dt.date(2026, 7, 18))
    assert snapshot["total_reported"] == 0
    assert snapshot["papers"] == []
