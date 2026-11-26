"""Re-match the full-text PDFs after new ones were saved (as <record id>.pdf, e.g. R0007.pdf or S0113.pdf).

The sr-screener work folder numbers the 99 title/abstract includes R00001-R00099 (`id_map.csv` links them to the
screening.csv / supplementary_C.csv IDs). This script rewrites `pdf_map.csv` from the PDFs on disk and reruns the
skill's prepare_fulltext.py, so the next `build_workflow.py ft --jobs pending` (after a merge) picks up the new ones.

Usage: uv run python prototypes/slr/fulltext/refresh_pdfs.py [--pdf-dir D:/Study/my-thesis/data/raw/slr_fulltext]
"""
import argparse
import csv
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
SKILL = Path.home() / ".claude/plugins/cache/academic-research-skills/academic-research-skills/3.24.4/sr-screener/scripts"

ap = argparse.ArgumentParser()
ap.add_argument("--pdf-dir", default="D:/Study/my-thesis/data/raw/slr_fulltext")
ap.add_argument("--txt-dir", default="D:/Study/my-thesis/data/raw/slr_fulltext_txt")
a = ap.parse_args()
pdf_dir, txt_dir = Path(a.pdf_dir), Path(a.txt_dir)
txt_dir.mkdir(parents=True, exist_ok=True)
ids = list(csv.DictReader((HERE / "id_map.csv").open(encoding="utf-8")))
found = []
for row in ids:
    pdf = pdf_dir / f"{row['record_id']}.pdf"
    if not (pdf.exists() and pdf.read_bytes()[:4] == b"%PDF"):
        continue
    # The reviewers' Read tool refuses these PDFs ("password-protected", although pdfinfo reports no encryption),
    # so they read a text version in reading order (poppler pdftotext), with a marker line per page for `where`.
    txt = txt_dir / f"{row['record_id']}.txt"
    if not txt.exists():
        raw = txt_dir / f"{row['record_id']}.raw"
        subprocess.run(["pdftotext", str(pdf), str(raw)], check=True, capture_output=True)
        pages = raw.read_text(encoding="utf-8", errors="replace").split("\f")
        if pages and not pages[-1].strip():
            pages = pages[:-1]
        body = "".join(f"=== Page {i} ===\n{p.rstrip()}\n" for i, p in enumerate(pages, 1))
        txt.write_text(body + f"=== END OF REPORT ({len(pages)} pages) ===\n", encoding="utf-8")
        raw.unlink()
    found.append((row["sr_id"], str(txt)))
with (HERE / "pdf_map.csv").open("w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "pdf"])
    w.writerows(found)
print(f"{len(found)} of {len(ids)} PDFs found")
subprocess.run([sys.executable, "-I", str(SKILL / "prepare_fulltext.py"), "--work", str(HERE / "sr_work"),
                "--pdf-dir", str(pdf_dir), "--map", str(HERE / "pdf_map.csv"),
                "--config", str(HERE / "screening_config.json")], check=True)
