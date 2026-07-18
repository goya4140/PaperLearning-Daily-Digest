from __future__ import annotations

import datetime as dt
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any, Callable


ATOM = {"atom": "http://www.w3.org/2005/Atom"}
ARXIV = {"arxiv": "http://arxiv.org/schemas/atom"}
OPENSEARCH = {"opensearch": "http://a9.com/-/spec/opensearch/1.1/"}
DEFAULT_ENDPOINT = "https://export.arxiv.org/api/query"
DEFAULT_RSS = "https://arxiv.org/rss"
DC = {"dc": "http://purl.org/dc/elements/1.1/"}


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _paper_id(raw: str) -> str:
    return re.sub(r"v\d+$", "", raw.rstrip("/").rsplit("/", 1)[-1])


def build_query(settings: dict[str, Any], target_date: dt.date, start: int = 0) -> str:
    categories = [str(value).strip() for value in settings.get("categories", []) if str(value).strip()]
    if not categories:
        raise ValueError("arxiv.categories must contain at least one category")
    category_query = " OR ".join(f"cat:{category}" for category in categories)
    day = target_date.strftime("%Y%m%d")
    search_query = f"({category_query}) AND submittedDate:[{day}0000 TO {day}2359]"
    params = urllib.parse.urlencode(
        {
            "search_query": search_query,
            "start": start,
            "max_results": int(settings.get("page_size", 1000)),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    return f"{settings.get('api_url', DEFAULT_ENDPOINT)}?{params}"


def _user_agent(settings: dict[str, Any]) -> str:
    contact = os.environ.get("ARXIV_CONTACT_EMAIL", "").strip() or str(settings.get("contact_email", "")).strip()
    suffix = f"; contact: {contact}" if contact else ""
    return f"PaperLearning-Daily-Digest/0.2 (personal research discovery{suffix})"


def _request(url: str, user_agent: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    waits = (3, 9, 20)
    for attempt, wait in enumerate(waits):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == len(waits) - 1:
                raise
        except urllib.error.URLError:
            if attempt == len(waits) - 1:
                raise
        time.sleep(wait)
    raise RuntimeError("arXiv request retry exhausted")


def parse_atom(payload: bytes) -> tuple[list[dict[str, Any]], int]:
    root = ET.fromstring(payload)
    total_text = root.findtext("opensearch:totalResults", default="0", namespaces=OPENSEARCH)
    total = int((total_text or "0").strip())
    papers: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ATOM):
        raw_id = _clean(entry.findtext("atom:id", default="", namespaces=ATOM))
        if not raw_id:
            continue
        paper_id = _paper_id(raw_id)
        links: dict[str, str] = {}
        for node in entry.findall("atom:link", ATOM):
            href = node.attrib.get("href", "")
            if node.attrib.get("rel") == "alternate":
                links["url"] = href
            if node.attrib.get("title") == "pdf":
                links["pdf_url"] = href
        primary = entry.find("arxiv:primary_category", ARXIV)
        papers.append(
            {
                "id": paper_id,
                "title": _clean(entry.findtext("atom:title", default="", namespaces=ATOM)),
                "authors": [
                    _clean(author.findtext("atom:name", default="", namespaces=ATOM))
                    for author in entry.findall("atom:author", ATOM)
                ],
                "abstract": _clean(entry.findtext("atom:summary", default="", namespaces=ATOM)),
                "categories": [node.attrib.get("term", "") for node in entry.findall("atom:category", ATOM)],
                "primary_category": primary.attrib.get("term", "") if primary is not None else "",
                "published": _clean(entry.findtext("atom:published", default="", namespaces=ATOM)),
                "updated": _clean(entry.findtext("atom:updated", default="", namespaces=ATOM)),
                "comment": _clean(entry.findtext("arxiv:comment", default="", namespaces=ARXIV)),
                "url": links.get("url", f"https://arxiv.org/abs/{paper_id}"),
                "pdf_url": links.get("pdf_url", f"https://arxiv.org/pdf/{paper_id}"),
            }
        )
    return papers, total


def parse_rss(payload: bytes, category: str, target_date: dt.date) -> list[dict[str, Any]]:
    root = ET.fromstring(payload)
    papers: list[dict[str, Any]] = []
    for item in root.findall("./channel/item"):
        published_raw = _clean(item.findtext("pubDate", default=""))
        if not published_raw or parsedate_to_datetime(published_raw).date() != target_date:
            continue
        announce_type = _clean(item.findtext("arxiv:announce_type", default="new", namespaces=ARXIV))
        if announce_type not in {"new", "cross"}:
            continue
        url = _clean(item.findtext("link", default=""))
        if not url:
            continue
        paper_id = _paper_id(url)
        description = _clean(item.findtext("description", default=""))
        description = re.sub(rf"^arXiv:{re.escape(paper_id)}v\d+\s+Announce Type:\s*\w+\s+Abstract:\s*", "", description)
        creator = _clean(item.findtext("dc:creator", default="", namespaces=DC))
        papers.append(
            {
                "id": paper_id,
                "title": _clean(item.findtext("title", default="")),
                "authors": [value.strip() for value in creator.split(",") if value.strip()],
                "abstract": description,
                "categories": [category],
                "primary_category": category,
                "published": parsedate_to_datetime(published_raw).astimezone(dt.timezone.utc).isoformat(),
                "updated": "",
                "comment": "",
                "url": f"https://arxiv.org/abs/{paper_id}",
                "pdf_url": f"https://arxiv.org/pdf/{paper_id}",
                "announce_type": announce_type,
            }
        )
    return papers


def _fetch_rss(
    settings: dict[str, Any],
    target_date: dt.date,
    requester: Callable[[str, str], bytes],
    sleeper: Callable[[float], None],
) -> dict[str, Any]:
    categories = [str(value).strip() for value in settings.get("categories", []) if str(value).strip()]
    base = str(settings.get("rss_url", DEFAULT_RSS)).rstrip("/")
    user_agent = _user_agent(settings)
    urls: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for index, category in enumerate(categories):
        if index:
            sleeper(max(3.0, float(settings.get("request_interval_seconds", 3.1))))
        url = f"{base}/{urllib.parse.quote(category, safe='.') }"
        urls.append(url)
        for paper in parse_rss(requester(url, user_agent), category, target_date):
            existing = by_id.get(paper["id"])
            if existing:
                existing["categories"] = sorted(set(existing["categories"] + paper["categories"]))
            else:
                by_id[paper["id"]] = paper
    papers = sorted(by_id.values(), key=lambda item: item["id"], reverse=True)
    for rank, paper in enumerate(papers, 1):
        paper["rank"] = rank
        paper["metadata_source"] = "arxiv-rss"
    if not papers:
        raise RuntimeError(f"official arXiv RSS has no new/cross items for {target_date}")
    return {
        "source": "arxiv-rss",
        "source_url": urls[0],
        "source_urls": urls,
        "requested_date": target_date.isoformat(),
        "query_window_utc": [f"{target_date.isoformat()}T00:00:00Z", f"{target_date.isoformat()}T23:59:59Z"],
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total_reported": len(papers),
        "papers": papers,
    }


def fetch(
    settings: dict[str, Any],
    target_date: dt.date,
    requester: Callable[[str, str], bytes] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    requester = requester or _request
    page_size = int(settings.get("page_size", 1000))
    if not 1 <= page_size <= 2000:
        raise ValueError("arxiv.page_size must be between 1 and 2000")
    user_agent = _user_agent(settings)
    papers: list[dict[str, Any]] = []
    total = 0
    start = 0
    urls: list[str] = []
    try:
        while start == 0 or start < total:
            if start:
                sleeper(max(3.0, float(settings.get("request_interval_seconds", 3.1))))
            url = build_query(settings, target_date, start)
            urls.append(url)
            page, total = parse_atom(requester(url, user_agent))
            papers.extend(page)
            if not page or len(papers) >= total:
                break
            start += page_size
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ET.ParseError) as exc:
        if not settings.get("rss_fallback", True):
            raise
        print(f"[warning] arXiv Atom API unavailable ({type(exc).__name__}); using official RSS fallback.")
        return _fetch_rss(settings, target_date, requester, sleeper)
    unique = {paper["id"]: paper for paper in papers}
    papers = sorted(unique.values(), key=lambda item: (item.get("published", ""), item["id"]), reverse=True)
    for rank, paper in enumerate(papers, 1):
        paper["rank"] = rank
        paper["metadata_source"] = "arxiv-api"
    if total != len(papers):
        raise RuntimeError(f"arXiv API count mismatch: reported={total}, unique={len(papers)}")
    return {
        "source": "arxiv-api",
        "source_url": urls[0],
        "source_urls": urls,
        "requested_date": target_date.isoformat(),
        "query_window_utc": [f"{target_date.isoformat()}T00:00:00Z", f"{target_date.isoformat()}T23:59:59Z"],
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total_reported": total,
        "papers": papers,
    }
