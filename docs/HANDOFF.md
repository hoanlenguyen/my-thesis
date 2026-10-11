# Handoff note (11 October 2026)

For a new Claude Code session started in `D:\Study\my-thesis`. The previous session ran from a worktree of the
low-carbon-alerts repo and worked on this repo through an added folder. Read `CLAUDE.md` first, then this note.

## Standing rules from the user

- Never commit or push. The user commits this repo (`hoanlenguyen/my-thesis`, branch `main`) themselves.
- No em dashes in thesis prose.
- Never print key values from `.env` (`ENTSOE_API_KEY`, `OPENAI_API_KEY`).
- Edit LaTeX and Python with the Edit/Write tools, not heredocs, sed or printf (backslashes get mangled).
  Keep `main.tex` with LF line endings (writing it from Python on Windows can turn it into CRLF).
- Do not modify the low-carbon-alerts repo (`D:\work\Nuxt\low-carbon-alerts`, auto-deploys to hiilivahti.fi).
  Reading it is fine.
- Do not name the Low Carbon Alert / Hiilivahti project anywhere in the thesis. The only exception is the
  Foreword, which says, without a name, that the idea came from the author's traineeship.
- Never change the evaluation silently. The registered analysis (`src/hems/analysis/confirm_q2.py`) and the
  registered results stay as they are; any later change is a new design iteration, reported as exploratory and
  noted in `docs/preregistration_q2.md`.
- The user prefers free options.

## State of the thesis (`main.tex`, 63 pages, compiles cleanly)

Compile: `latexmk -xelatex -interaction=nonstopmode -halt-on-error main.tex`; if the aux files are stale
("File ended while scanning use of \@writefile"), run `latexmk -C` first.

- Chapters 1 to 7 are written, including Discussion (6) and Conclusions (7), and the Foreword.
- Chapter 5 order: dataset and factorial benchmarks (5.1, with the "held out in time" sentence in 5.1.4),
  15-minute prices (5.2), demonstration on Q2-PH01-35 plus design iterations 1 to 5 (5.3), earlier design
  summary (5.4), exploratory factorial results with iterations 6 to 8 (5.5), confirmatory Q2 (5.6, ends with
  the UK 2015 robustness numbers), post-registration iteration 9 on response time (5.7).
- Appendices A (UK 2015 robustness) and B (earlier single-agent design) were removed from the thesis and
  parked, unchanged, in `parked/appendices.tex`. Instructions to restore them are at the top of that file
  (one `\input{parked/appendices}` line plus two reference entries).
- Known small items: the Foreword's place and date ("Oulu, October 2026") and "his guidance" were not
  confirmed by the user. Two overfull boxes (abstract area and a paragraph in chapter 6) are pre-existing.

## Key results (for checking any edit)

- Q2 (registered, `results/confirmation/confirmatory_tests_q2.csv`): H1a +15.4 pp supported; H1b +3.5 pp not
  supported (p_holm 0.091); H1c latency 63.5 s not supported (API slowed 4.5x during the run), cost $0.0025
  supported; H2a +8.6 pp, H2b +10.0 pp, H2c +0.10 pp [0.04, 0.16] supported.
- Q2 pooled saving: pipeline 27.40 % (= optimum, 288/288 valid), timer 27.34, EMHASS 27.30, EMHASS nominal
  25.39, cheapest window 12.49, cheapest hours 10.71, hourly 10.09, LLM without tools 6.24.
- Iteration 9 (`multi_lean`, exploratory, `results/iteration9.jsonl`, interleaved with `multi_rag_opt` on the
  exploratory set): latency 9.6 s vs 18.0 s, tokens 5,405 vs 14,101, cost $0.0011 vs $0.0025, saving 27.59 %
  vs 27.58 %, 288/288 valid each; summaries state the cost in 288/288 runs.
- UK 2015 (exploratory): pipeline 6.69 % = optimum, timer 6.55, EMHASS 6.45, cheapest tools 2.6 to 3.6,
  LLM without tools 0.18.

## Code

- Systems are in `src/hems/systems.py`. `multi_rag_opt` is the registered Multi-Agent Pipeline; `multi_lean`
  is iteration 9 (`lean=True` in `src/hems/agents/multi_agent.py`). `parallel_start=True` (Orchestrator and
  Profiler start together) is demo only and was never evaluated.
- Tests: `uv run --extra demo pytest -q` (104 passed at handoff, about 3.5 minutes).

## Demo (`demo/`, Try it page at http://localhost:3001/try)

Nothing was running at handoff. Start, each in its own window:

- API: `scripts\demo-api.cmd` (uvicorn `hems.demo_api:app` on :8001).
- Web: `scripts\demo-dev.cmd` (Nuxt dev on :3001, proxies `/api` to :8001).
- EMHASS (optional): Docker container on :5000. If Docker Desktop's engine is stuck, the page leaves EMHASS out
  after a 3-second check instead of hanging.

What the page does now: the pipeline (lean, parallel start) streams agent by agent from
`POST /api/plan/agent/stream` into the "How the agents worked" panel (`demo/app/components/AgentActivity.vue`),
in parallel with the comparison tools; about 8.5 s from click to recommendation. Each appliance row has
prefilled runtime and power inputs; measured REFIT cycles keep their shape when these are changed. Prices come
from ENTSO-E (cached in `results/demo_cache/`).

## Uncommitted changes at handoff

`main.tex`, `main.pdf`, `parked/` (new), `src/hems/demo_api.py`, `src/hems/agents/multi_agent.py`,
`demo/app/pages/try.vue`, `demo/app/composables/useTryIt.ts`, `demo/app/utils/format.ts`,
`demo/app/components/AgentActivity.vue` (new), `tests/test_agents_wiring.py`, `tests/test_demo_api.py`,
`results/demo_cache/prices_2026-10-08.json` (new), and this note.

## Open points

- The rebuttal promised to restate the RQ, SQ1 and SQ2 in the methods chapter. Chapter 3 refers to SQ1 and
  SQ2 (and the hypotheses table groups them) but does not repeat the full wording; not done yet.
- Optional: one sentence in the thesis saying the demo's parallel start goes beyond the evaluated design.
- Optional: decide whether to restore the parked appendices before submission.
