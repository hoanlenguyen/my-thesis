"""SLR, arXiv part (thesis Appendix B): runs searches A and B through the arXiv API and saves the records.

    uv run python prototypes/slr/arxiv_search.py
"""

from __future__ import annotations

import csv
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).parent
API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
DATES = "submittedDate:[202201010000 TO 202612312359]"
SEARCHES = {
    "A": '(abs:"language model" OR abs:"language models" OR abs:LLM OR abs:LLMs) AND (abs:"home energy" OR '
         'abs:"demand response" OR abs:"smart home" OR abs:"energy gateway" OR abs:"building energy management")',
    # "energy" alone matches the energy the model itself uses, so search B names energy management
    "B": '(abs:"small language model" OR abs:"small language models" OR abs:"on-device LLM" OR abs:"edge LLM" '
         'OR abs:"local LLM" OR abs:"locally deployed") AND (abs:"energy management" OR abs:"home energy" '
         'OR abs:"smart grid" OR abs:"demand response" OR abs:"building energy")',
}  # fmt: skip


def fetch(query: str, start: int, size: int = 200) -> ET.Element:
    params = {"search_query": f"({query}) AND {DATES}", "start": start, "max_results": size,
              "sortBy": "submittedDate", "sortOrder": "descending"}  # fmt: skip
    url = f"{API}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "thesis-slr/0.1"}), timeout=60) as r:
        return ET.fromstring(r.read())


def main() -> None:
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    for name, query in SEARCHES.items():
        rows, start = [], 0
        while True:
            feed = fetch(query, start)
            total = int(feed.find("{http://a9.com/-/spec/opensearch/1.1/}totalResults").text)
            entries = feed.findall("a:entry", NS)
            for e in entries:
                rows.append({
                    "search": name, "id": e.find("a:id", NS).text.rsplit("/", 1)[-1],
                    "title": " ".join(e.find("a:title", NS).text.split()),
                    "authors": "; ".join(a.find("a:name", NS).text for a in e.findall("a:author", NS)),
                    "published": e.find("a:published", NS).text[:10],
                    "doi": (e.find("arxiv:doi", NS).text if e.find("arxiv:doi", NS) is not None else ""),
                    "journal_ref": (e.find("arxiv:journal_ref", NS).text
                                    if e.find("arxiv:journal_ref", NS) is not None else ""),
                    "abstract": " ".join(e.find("a:summary", NS).text.split()),
                })  # fmt: skip
            start += len(entries)
            if not entries or start >= total:
                break
            time.sleep(3)  # arXiv asks for at least 3 s between calls
        path = out / f"arxiv_{name}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["search"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"search {name}: {total} hits, {len(rows)} saved to {path.name}")
        time.sleep(3)


if __name__ == "__main__":
    main()
