---
name: compile-thesis
description: Build gateway_thesis.tex from gateway_body.tex, compile it with XeLaTeX, check the log for errors/warnings, and render changed pages to PNG to verify layout. Use after any edit to gateway_body.tex, gateway_preamble.tex, build_gateway_thesis.py or a thesis figure.
---

# Build, compile and verify the thesis

The thesis text is `gateway_body.tex`; `build_gateway_thesis.py` joins it with the Oulu preamble in
`gateway_preamble.tex` and writes the citations out as APA author-year text, giving `gateway_thesis.tex`. Never
edit `gateway_thesis.tex` by hand.

1. Build the `.tex` (a citation key missing from `AUTHORS` in the script stops the build):
   ```bash
   uv run python build_gateway_thesis.py
   ```
2. Wait for VS Code's LaTeX auto-build: it starts when `gateway_thesis.tex` changes, and two builds at once
   corrupt the `.aux`. Wait about 25 s, then check that no TeX process is left:
   ```bash
   tasklist | grep -i 'xelatex\|latexmk\|perl\|xdvipdfmx'    # must print nothing
   ```
3. Delete the aux files and compile (XeLaTeX is required by `fontspec`; `.latexmkrc` sets `pdf_mode = 5`):
   ```bash
   rm -f gateway_thesis.aux gateway_thesis.fdb_latexmk gateway_thesis.fls gateway_thesis.log gateway_thesis.out \
         gateway_thesis.toc gateway_thesis.xdv gateway_thesis.lof gateway_thesis.lot
   export PATH=/c/texlive/2026/bin/windows:$PATH
   latexmk -xelatex -interaction=nonstopmode gateway_thesis > /dev/null 2>&1; echo rc=$?
   ```
   Run it in the background if it may take over two minutes.
4. Check the log; all of these should be empty or explained:
   ```bash
   grep -c '^!' gateway_thesis.log                        # errors
   grep -E 'undefined|Overfull|tabularx Warning' gateway_thesis.log
   pdfinfo gateway_thesis.pdf | grep Pages
   ```
   `'!h' float specifier changed to '!ht'` warnings are harmless.
5. Find the page of the edited part and render it (poppler's `pdftotext` / `pdftoppm` are on the PATH):
   ```bash
   S=<session scratchpad>
   N=$(pdfinfo gateway_thesis.pdf | awk '/Pages/{print $2}')
   for pg in $(seq 1 "$N"); do pdftotext -f $pg -l $pg gateway_thesis.pdf - | grep -q "<text on the page>" && echo "page $pg"; done
   pdftoppm -f <pg> -l <pg> -r 75 -png gateway_thesis.pdf "$S/page"
   ```
   Read the PNG to check layout; for many pages, paste them into one contact sheet (`uv run --with pillow`).
   Send a page to the author with SendUserFile when the change is visible.

Refresh `gateway_thesis_overleaf.zip` only when the author asks (the `.tex`, every image it includes,
`attachments/uni_logo.jpeg`, and README.txt and latexmkrc from the old zip).

## Conventions

- Citations: `\parencite{key}` and `\textcite{key}`; every key needs an entry in `AUTHORS` in
  `build_gateway_thesis.py` and a verified entry in the References (`hangparas` block, APA, alphabetical).
- Tables: `booktabs`; full width (`tabularx` or `tabular*` with `\extracolsep{\fill}`); left-aligned
  `>{\raggedright\arraybackslash}p{..}` columns; long tables use `longtable`. Captions above tables; the build
  script makes only the label bold ("Table 5.1.").
- Figures: PNGs in `attachments/gateway/` (sources in the README's figure table); captions below.
- Every `\ref` needs a `\label`; section labels use `sec:`, tables `tab:`, figures `fig:`.
- Long URLs/DOIs break via `xurl`; do not hand-hyphenate them.
- No em dashes; no repository file paths in the text; parts without results say "In process."
- Edit `gateway_body.tex` with the Edit tool (backslashes break in bash heredocs).
