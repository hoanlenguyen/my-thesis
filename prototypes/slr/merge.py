"""SLR: merges the database exports in ``out/`` into one screening sheet and removes duplicates.

Duplicates are matched by DOI, then by normalised title. Each record keeps every database and search (A, B) it came
from. Writes ``out/screening.csv`` (one row per unique record, with empty ``decision`` and ``reason`` columns for
title-and-abstract screening) and prints the counts per database for the review's flow table.

    uv run python prototypes/slr/merge.py
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "out"


def norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def read(path: Path, delimiter: str = ",") -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=delimiter))


def records() -> list[dict]:
    rows = []
    for search in "AB":
        for r in read(OUT / f"arxiv_{search}.csv") if (OUT / f"arxiv_{search}.csv").exists() else []:
            rows.append({"source": "arXiv", "search": search, "title": r["title"], "year": r["published"][:4],
                         "authors": r["authors"], "venue": r["journal_ref"] or "arXiv preprint", "doi": r["doi"],
                         "url": f"https://arxiv.org/abs/{r['id']}", "abstract": r["abstract"]})  # fmt: skip
        path = OUT / f"scopus_{search}.csv"
        for r in read(path) if path.exists() else []:
            rows.append({"source": "Scopus", "search": search, "title": r["Title"], "year": r["Year"],
                         "authors": r["Authors"], "venue": r["Source title"], "doi": r.get("DOI", ""),
                         "url": r.get("Link", ""), "abstract": r.get("Abstract", "")})  # fmt: skip
        path = OUT / f"ieee_{search}.csv"
        for r in read(path) if path.exists() else []:
            rows.append({"source": "IEEE Xplore", "search": search, "title": r["Document Title"],
                         "year": r["Publication Year"], "authors": r["Authors"], "venue": r["Publication Title"],
                         "doi": r.get("DOI", ""), "url": r.get("PDF Link", ""), "abstract": r.get("Abstract", "")})  # fmt: skip
        path = OUT / f"wos_{search}.txt"
        for r in read(path, "\t") if path.exists() else []:
            rows.append({"source": "Web of Science", "search": search, "title": r["TI"], "year": r["PY"],
                         "authors": r["AU"], "venue": r["SO"], "doi": r.get("DI", ""), "url": "",
                         "abstract": r.get("AB", "")})  # fmt: skip
    for name, search in (("sciencedirect_A1.tsv", "A"), ("sciencedirect_A2.tsv", "A"), ("sciencedirect_B.tsv", "B")):
        for r in read(OUT / name, "\t") if (OUT / name).exists() else []:
            rows.append({"source": "ScienceDirect", "search": search, "title": r["title"],
                         "year": (re.findall(r"20\d\d", r["venue_date"]) or [""])[-1], "authors": r["authors"],
                         "venue": r["venue_date"].rsplit(",", 1)[0], "doi": "", "url": r["url"], "abstract": ""})  # fmt: skip
    return rows


def main() -> None:
    rows = records()
    merged: dict[str, dict] = {}
    by_doi: dict[str, str] = {}
    for r in rows:
        doi = r["doi"].lower().strip()
        key = by_doi.get(doi) if doi else None
        key = key or norm(r["title"])
        if key in merged:
            m = merged[key]
            m["sources"].add(r["source"])
            m["searches"].add(r["search"])
            for field in ("doi", "abstract", "url", "venue", "authors", "year"):
                if not m[field] and r[field]:
                    m[field] = r[field]
        else:
            merged[key] = {**r, "sources": {r["source"]}, "searches": {r["search"]}}
        if doi:
            by_doi[doi] = key
    out = OUT / "screening.csv"
    fields = ["id", "title", "year", "authors", "venue", "doi", "url", "sources", "searches", "abstract",
              "decision", "reason"]  # fmt: skip
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for n, m in enumerate(sorted(merged.values(), key=lambda m: (m["year"], m["title"]), reverse=True), 1):
            writer.writerow({**{k: m[k] for k in fields if k in m}, "id": f"R{n:04d}",
                             "sources": "; ".join(sorted(m["sources"])), "searches": "".join(sorted(m["searches"])),
                             "decision": "", "reason": ""})  # fmt: skip
    found = Counter((r["source"], r["search"]) for r in rows)
    print("records found:", {f"{s} {q}": n for (s, q), n in sorted(found.items())})
    print(f"total {len(rows)}, unique after de-duplication {len(merged)} -> {out.name}")


if __name__ == "__main__":
    main()
