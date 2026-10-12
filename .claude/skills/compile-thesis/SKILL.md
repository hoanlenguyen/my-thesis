---
name: compile-thesis
description: Compile main.tex with XeLaTeX, check the log for errors/warnings, and render changed pages to PNG to verify layout. Use after any edit to main.tex or to generated LaTeX tables.
---

# Compile and verify the thesis

1. Compile (XeLaTeX is required by `fontspec`; `.latexmkrc` and `% !TEX program = xelatex` enforce it):
   ```bash
   cd /d/Study/my-thesis && export PATH=/c/texlive/2026/bin/windows:$PATH
   latexmk -xelatex -interaction=nonstopmode -file-line-error main > /dev/null 2>&1; echo rc=$?
   ```
2. Check the log — all of these should be empty or explained:
   ```bash
   grep -E '^\./main|undefined|Overfull|tabularx Warning' main.log
   ```
   `'!h' float specifier changed to '!ht'` warnings are harmless.
3. Find the page of the edited section and render it (Ghostscript ships with TeX Live as `rungs`):
   ```bash
   S=<session scratchpad>
   N=$(grep -oE '\([0-9]+ pages' main.log | grep -oE '[0-9]+')
   for pg in $(seq 1 "$N"); do rungs -q -dNOPAUSE -dBATCH -sDEVICE=txtwrite -dFirstPage=$pg -dLastPage=$pg \
     -sOutputFile=- main.pdf 2>/dev/null | grep -q "<heading text>" && echo "page $pg"; done
   rungs -q -dNOPAUSE -dBATCH -sDEVICE=png16m -r75 -dFirstPage=<pg> -dLastPage=<pg> -sOutputFile="$S/page.png" main.pdf
   ```
   Read the PNG to check layout; send it to the author with SendUserFile when the change is visible.

## Conventions

- Tables: `booktabs`; full width (`tabularx` or `tabular*` with `\extracolsep{\fill}`); two-line headers
  with `\makecell`; captions above tables (Arial 10pt bold via `caption` setup).
- Every `\ref` needs a `\label`; section labels use `sec:` (e.g. `sec:dataset`, `sec:resolution`).
- Long URLs/DOIs break via `xurl`; do not hand-hyphenate them.
- Edit `main.tex` with the Edit tool (backslashes break in bash heredocs).
