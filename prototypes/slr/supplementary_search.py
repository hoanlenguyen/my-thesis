"""SLR supplementary search C (protocol amendment, 24 November 2026), arXiv part.

Why: the sensitivity check against studies read before the search found that searches A and B missed Sanguinetti et
al. (2025, arXiv 2503.21360), a core LQ1 study. Its abstract speaks of "home appliances", "energy optimization
constraints" and a "renewable energy community", none of which matches the energy block of search A. Search C covers
that concept: a language model AND a household asset or setting AND optimisation, constraints or control, without
requiring the phrase "energy management". The terms come from the concept, not from one abstract; the missed study
is used only to check that the search now retrieves it.

Writes ``out/arxiv_C.csv`` (all hits) and ``out/supplementary_C.csv`` (only records not already in
``out/screening.csv``, matched by DOI, arXiv id and normalised title; ids S0001...). It never touches
``screening.csv``, because ``merge.py`` would renumber it and drop the screening decisions.

    uv run python prototypes/slr/supplementary_search.py           # count hits only
    uv run python prototypes/slr/supplementary_search.py --save    # fetch and save
"""

from __future__ import annotations

import argparse
import csv
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "out"
API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
OS = "{http://a9.com/-/spec/opensearch/1.1/}"
DATES = "submittedDate:[202201010000 TO 202612312359]"

LM = '(abs:"language model" OR abs:"language models" OR abs:LLM OR abs:LLMs)'
SETTING = ('(abs:appliance OR abs:appliances OR abs:household OR abs:households OR abs:residential '
           'OR abs:"energy community" OR abs:prosumer OR abs:prosumers OR abs:"electric vehicle" '
           'OR abs:"electric vehicles" OR abs:"heat pump" OR abs:"heat pumps" OR abs:thermostat OR abs:HVAC)')
TASK = ('(abs:constraint OR abs:constraints OR abs:optimization OR abs:optimisation OR abs:scheduling '
        'OR abs:"model predictive control" OR abs:MPC OR abs:controller)')
QUERY = f"{LM} AND {SETTING} AND {TASK}"

# Scopus string for the same concept (run by the author in Scopus Advanced search; export as scopus_C.csv):
SCOPUS_C = """TITLE-ABS-KEY ( ( "large language model*" OR "small language model*" OR LLM* OR "language model*" )
  AND ( appliance* OR household* OR residential OR "energy communit*" OR prosumer* OR "electric vehicle*"
  OR "heat pump*" OR thermostat* OR HVAC )
  AND ( constraint* OR optimi?ation OR schedul* OR "model predictive control" OR MPC OR controller* ) )
AND PUBYEAR > 2021 AND PUBYEAR < 2027
AND ( LIMIT-TO ( DOCTYPE , "ar" ) OR LIMIT-TO ( DOCTYPE , "cp" ) OR LIMIT-TO ( DOCTYPE , "re" ) )
AND ( LIMIT-TO ( LANGUAGE , "English" ) )"""


def fetch(start: int, size: int) -> ET.Element:
    params = {"search_query": f"({QUERY}) AND {DATES}", "start": start, "max_results": size,
              "sortBy": "submittedDate", "sortOrder": "descending"}  # fmt: skip
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "thesis-slr/0.1"})
    for attempt in range(4):  # the network drops now and then
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return ET.fromstring(r.read())
        except OSError:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("arXiv API not reachable")


def norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--save", action="store_true")
    args = p.parse_args()
    total = int(fetch(0, 1).find(f"{OS}totalResults").text)
    print(f"search C (arXiv): {total} hits")
    if not args.save:
        return
    rows, start = [], 0
    while start < total:
        time.sleep(3)  # arXiv asks for at least 3 s between calls
        entries = fetch(start, 200).findall("a:entry", NS)
        if not entries:
            break
        for e in entries:
            doi = e.find("arxiv:doi", NS)
            ref = e.find("arxiv:journal_ref", NS)
            rows.append({
                "search": "C", "id": e.find("a:id", NS).text.rsplit("/", 1)[-1],
                "title": " ".join(e.find("a:title", NS).text.split()),
                "authors": "; ".join(a.find("a:name", NS).text for a in e.findall("a:author", NS)),
                "published": e.find("a:published", NS).text[:10],
                "doi": doi.text if doi is not None else "", "journal_ref": ref.text if ref is not None else "",
                "abstract": " ".join(e.find("a:summary", NS).text.split()),
            })  # fmt: skip
        start += len(entries)
    with (OUT / "arxiv_C.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    with (OUT / "screening.csv").open(encoding="utf-8") as f:
        old = list(csv.DictReader(f))
    dois = {r["doi"].lower().strip() for r in old if r["doi"].strip()}
    titles = {norm(r["title"]) for r in old}
    ids = {m.group(1) for r in old for m in [re.search(r"arxiv\.org/abs/(\d{4}\.\d{4,5})", r["url"])] if m}
    new = []
    for r in rows:
        base = re.sub(r"v\d+$", "", r["id"])
        if (r["doi"] and r["doi"].lower() in dois) or norm(r["title"]) in titles or base in ids:
            continue
        new.append({"id": f"S{len(new) + 1:04d}", "title": r["title"], "year": r["published"][:4],
                    "authors": r["authors"], "venue": r["journal_ref"] or "arXiv preprint", "doi": r["doi"],
                    "url": f"https://arxiv.org/abs/{r['id']}", "sources": "arXiv", "searches": "C",
                    "abstract": r["abstract"], "decision": "", "reason": ""})  # fmt: skip
    with (OUT / "supplementary_C.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(new[0]) if new else ["id"])
        w.writeheader()
        w.writerows(new)
    hit = any("2503.21360" in r["id"] for r in rows)
    print(f"saved {len(rows)} to arxiv_C.csv; {len(rows) - len(new)} already in screening.csv; "
          f"{len(new)} new -> supplementary_C.csv")
    print(f"known-item check, Sanguinetti et al. 2503.21360 retrieved: {hit}")


if __name__ == "__main__":
    main()
