import datetime as dt

from paper_digest.main import arxiv_query_date


def test_query_date_follows_arxiv_announcement_calendar():
    settings = {"submission_lag_days": 1, "reuse_latest_on_non_announcement_days": True}
    assert arxiv_query_date(dt.date(2026, 7, 17), settings) == dt.date(2026, 7, 16)
    assert arxiv_query_date(dt.date(2026, 7, 18), settings) == dt.date(2026, 7, 16)
    assert arxiv_query_date(dt.date(2026, 7, 19), settings) == dt.date(2026, 7, 16)
    assert arxiv_query_date(dt.date(2026, 7, 20), settings) == dt.date(2026, 7, 17)
