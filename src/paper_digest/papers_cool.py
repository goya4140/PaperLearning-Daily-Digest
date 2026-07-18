from __future__ import annotations

import datetime as dt
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any


USER_AGENT = "PaperLearning-Daily-Digest/0.1 (personal research discovery)"


def clean_text(value: str | None) -> str:
    value = value or ""
    value = re.sub(r"\$([^$]+)\$", r"\1", value)
    value = re.sub(r"\\[A-Za-z]+\{([^{}]*)\}", r"\1", value)
    value = re.sub(r"\\[A-Za-z]+", "", value)
    return re.sub(r"\s+", " ", value).strip()


class PapersCoolParser(HTMLParser):
    """Parse the server-rendered daily list without following paper links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.papers: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.paper_depth = 0
        self.capture: str | None = None
        self.capture_tag: str | None = None
        self.buffer: list[str] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key: value or "" for key, value in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = self._attrs(attrs)
        classes = set(values.get("class", "").split())
        if tag == "div" and {"panel", "paper"}.issubset(classes):
            self.current = {
                "id": values.get("id", ""),
                "rank": len(self.papers) + 1,
                "title": "",
                "authors": [],
                "abstract": "",
                "subjects": [],
                "categories": [],
                "published": "",
            }
            self.paper_depth = 1
            return
        if self.current is None:
            return
        if tag == "div":
            self.paper_depth += 1
        if tag == "a" and "title-link" in classes:
            self._start_capture("title", tag)
        elif tag == "a" and "author" in classes:
            self._start_capture("author", tag)
        elif tag == "a" and any(name.startswith("subject-") for name in classes):
            match = re.fullmatch(r"/arxiv/([A-Za-z-]+\.[A-Za-z-]+)", values.get("href", ""))
            if match and match.group(1) not in self.current["categories"]:
                self.current["categories"].append(match.group(1))
            self._start_capture("subject", tag)
        elif tag == "p" and "summary" in classes:
            self._start_capture("abstract", tag)
        elif tag == "span" and "date-data" in classes:
            self._start_capture("published", tag)

    def _start_capture(self, name: str, tag: str) -> None:
        self.capture = name
        self.capture_tag = tag
        self.buffer = []

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return
        if self.capture and tag == self.capture_tag:
            value = clean_text("".join(self.buffer))
            if self.capture == "author" and value:
                self.current["authors"].append(value)
            elif self.capture == "subject" and value and value not in self.current["subjects"]:
                self.current["subjects"].append(value)
            elif self.capture == "published":
                self.current["published"] = _normalize_time(value)
            else:
                self.current[self.capture] = value
            self.capture = self.capture_tag = None
            self.buffer = []
        if tag == "div":
            self.paper_depth -= 1
            if self.paper_depth == 0:
                paper_id = str(self.current.get("id", ""))
                if re.fullmatch(r"\d{4}\.\d{4,5}", paper_id) and self.current.get("title"):
                    self.current.update(
                        {
                            "url": f"https://arxiv.org/abs/{paper_id}",
                            "pdf_url": f"https://arxiv.org/pdf/{paper_id}",
                            "papers_cool_url": f"https://papers.cool/arxiv/{paper_id}",
                        }
                    )
                    self.papers.append(self.current)
                self.current = None


def _normalize_time(value: str) -> str:
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) UTC", value.strip())
    return f"{match.group(1)}T{match.group(2)}Z" if match else value.strip()


def build_url(settings: dict[str, Any], target_date: dt.date) -> str:
    categories = settings.get("categories", ["cs.CL", "cs.LG", "cs.CV", "cs.AI"])
    category_path = urllib.parse.quote(",".join(categories), safe=".")
    query = urllib.parse.urlencode({"date": target_date.isoformat(), "show": settings.get("page_size", 1000)})
    return f"{settings.get('base_url', 'https://papers.cool/arxiv')}/{category_path}?{query}"


def _request(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    waits = [2, 6, 15]
    for attempt, wait in enumerate(waits):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError):
            if attempt == len(waits) - 1:
                raise
            time.sleep(wait)
    raise RuntimeError("request retry exhausted")


def fetch(settings: dict[str, Any], target_date: dt.date) -> dict[str, Any]:
    url = build_url(settings, target_date)
    page = _request(url).decode("utf-8", errors="replace")
    parser = PapersCoolParser()
    parser.feed(page)
    page_date_match = re.search(r'class="date">(\d{4}-\d{2}-\d{2})</a>', page)
    total_match = re.search(r"\bTotal:\s*(\d+)", page)
    page_date = page_date_match.group(1) if page_date_match else target_date.isoformat()
    total_reported = int(total_match.group(1)) if total_match else len(parser.papers)
    if not parser.papers:
        raise RuntimeError(f"Papers Cool returned no parseable papers for {page_date}")
    if total_reported != len(parser.papers):
        raise RuntimeError(f"Papers Cool count mismatch: page={total_reported}, parsed={len(parser.papers)}")
    return {
        "source": "papers.cool",
        "source_url": url,
        "requested_date": target_date.isoformat(),
        "page_date": page_date,
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total_reported": total_reported,
        "papers": parser.papers,
    }

