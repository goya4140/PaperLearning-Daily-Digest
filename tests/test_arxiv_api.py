import datetime as dt
import urllib.parse
import urllib.error

from paper_digest.arxiv_api import build_query, fetch, parse_atom, parse_rss


ATOM = b'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>https://arxiv.org/abs/2607.12345v2</id>
    <updated>2026-07-18T03:00:00Z</updated>
    <published>2026-07-18T01:00:00Z</published>
    <title>A Test Paper</title>
    <summary>A useful abstract.</summary>
    <author><name>Ada Lovelace</name></author>
    <arxiv:primary_category term="cs.AI"/>
    <category term="cs.AI"/>
    <link href="https://arxiv.org/abs/2607.12345v2" rel="alternate" type="text/html"/>
    <link title="pdf" href="https://arxiv.org/pdf/2607.12345v2" rel="related" type="application/pdf"/>
  </entry>
</feed>'''

RSS = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
<channel><item>
  <title>RSS Test Paper</title>
  <link>https://arxiv.org/abs/2607.54321</link>
  <description>arXiv:2607.54321v1 Announce Type: new Abstract: Useful RSS abstract.</description>
  <pubDate>Sat, 18 Jul 2026 00:00:00 -0400</pubDate>
  <arxiv:announce_type>new</arxiv:announce_type>
  <dc:creator>Ada Lovelace, Alan Turing</dc:creator>
</item></channel></rss>'''


def test_query_uses_categories_and_utc_submitted_date():
    url = build_query({"categories": ["cs.AI", "cs.CL"], "page_size": 1000}, dt.date(2026, 7, 18))
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["search_query"] == ["(cat:cs.AI OR cat:cs.CL) AND submittedDate:[202607180000 TO 202607182359]"]
    assert query["sortBy"] == ["submittedDate"]


def test_atom_parser_normalizes_versioned_id():
    papers, total = parse_atom(ATOM)
    assert total == 1
    assert papers[0]["id"] == "2607.12345"
    assert papers[0]["primary_category"] == "cs.AI"


def test_fetch_returns_auditable_snapshot_without_cookie():
    snapshot = fetch(
        {"categories": ["cs.AI"], "page_size": 1000},
        dt.date(2026, 7, 18),
        requester=lambda url, user_agent: ATOM,
    )
    assert snapshot["source"] == "arxiv-api"
    assert snapshot["total_reported"] == 1
    assert snapshot["papers"][0]["rank"] == 1


def test_rss_parser_and_api_failure_fallback():
    papers = parse_rss(RSS, "cs.AI", dt.date(2026, 7, 18))
    assert papers[0]["id"] == "2607.54321"
    assert papers[0]["abstract"] == "Useful RSS abstract."

    def requester(url, user_agent):
        if "/api/query" in url:
            raise urllib.error.URLError("temporary TLS error")
        return RSS

    snapshot = fetch(
        {"categories": ["cs.AI"], "page_size": 1000, "rss_fallback": True},
        dt.date(2026, 7, 18),
        requester=requester,
        sleeper=lambda seconds: None,
    )
    assert snapshot["source"] == "arxiv-rss"
