# CLAUDE.md — Master's thesis: hierarchical ReAct multi-agent HEMS

University of Oulu, Information Processing Science (Oulu IPS template), Design Science Research.
Thesis text in `main.tex`; the DSR artifact (LangGraph multi-agent appliance scheduler + baselines +
evaluation) in `src/hems/`. Author: Hoan Le. Supervisor: Yueqiang Xu.

## Ground rules

- **Never commit or push.** The author commits and pushes this repository themselves. Make and verify
  changes, then list the changed files.
- **Do not change the evaluation silently.** Anything that alters agents, prompts, tools, scoring or
  scenarios changes results: say so, archive affected results (see `run-evaluation` skill) and rerun.
- Report failures and surprising numbers as they are; never tune the multi-agent pipeline against the
  baseline on individual scenarios.

## Layout

| Path | Contents |
|---|---|
| `main.tex` | thesis (XeLaTeX, Times New Roman/Arial, Oulu cover with `attachments/uni_logo.jpeg`) |
| `attachments/` | Word draft, research plan, Oulu template, figures |
| `src/hems/core/` | `Scenario` model (96 × 15-min slots), `evaluate()` — the only scoring function |
| `src/hems/tools/` | 8 tools; specialists get subsets, the single agent gets all (fairness rule) |
| `src/hems/agents/` | `single_agent.py`, `multi_agent.py` (Orchestrator → Profiler → Scheduler → Resolver + verification gate), `prompts.py`, `llm.py` (model registry), `errors.py` (recovery nudge) |
| `src/hems/solvers/` | `milp.py` (PuLP/CBC ground truth), `naive.py` |
| `src/hems/data/` | REFIT loader, price fetch/load, day selection, scenario composition, benchmark build |
| `src/hems/analysis/` | metrics, Wilcoxon/Spearman, LaTeX tables, `resolution.py` (hourly vs 15-min) |
| `data/scenarios/` | main benchmark A01–F08 (hourly Sahkotin prices, frozen, seed 2026) |
| `data/scenarios_15min/` | Q-A01–Q-F08 (native 15-min Elering prices, Oct 2025 – Sep 2026) |
| `data/pilot/` | synthetic SYN-* scenarios — development only, never thesis results |
| `data/raw/` | gitignored: REFIT CSVs (6.5 GB), price CSVs |
| `results/` | `runs.jsonl` / `pilot_real.jsonl` (+ archived `*_vN.jsonl`), `resolution/`, tables |

## Commands

```bash
uv run pytest                                   # offline tests with scripted fake models (must pass)
uv run hems run --scenarios data/scenarios --systems milp naive single multi --models gpt-4o-mini --runs 3 --out results/runs.jsonl
uv run hems analyze --runs results/runs.jsonl --scenarios data/scenarios --out results
uv run hems resolution --scenarios data/scenarios_15min   # regenerates Table 5.3
uv run hems demo data/scenarios/D01.json --system multi --model gpt-4o-mini
latexmk -xelatex main                           # TeX Live at C:\texlive\2026\bin\windows
```

Python 3.12 via `uv` (not the system 3.14). Skills: `compile-thesis`, `run-evaluation`, `rebuild-benchmark`.

## Methodology invariants (keep these true)

- Every system is scored by `core.evaluate.evaluate`; cost = consumer price × flexible appliance energy
  (`data/tariff.py`); base load counts toward the peak limit only.
- Tool fairness: `set(PROFILER_TOOLS) | SCHEDULER_TOOLS | RESOLVER_TOOLS == ALL_TOOLS`; no tool solves the
  whole problem (no MILP tool). The single-agent prompt is built from the same role texts.
- Step budget parity: specialists get profiler 15 + scheduler 35 + resolver 25 = single agent 75
  (`multi_agent.STEP_LIMITS`, split by workload after the pilot).
- Recovery nudge (`agents/errors.py`) applies identically to every model and agent; recoveries are logged.
- Infeasible agent schedules are scored at the naive cost; feasibility is reported separately.
- Benchmark settings: 18 REFIT houses (12 and 19 excluded — reasons in `refit.EXCLUDED_HOUSES`),
  peak limit 3.5 kW, type E windows anchored at the daily price peak, seed 2026.

## Models (`agents/llm.py`)

The evaluation uses **two models**: commercial cloud vs small open-weight model run locally.

- `gpt-4o-mini` (OpenAI API) — primary; 3 runs per scenario.
- `gpt-oss-20b` — local via Ollama (`gpt-oss:20b`, 32k context, CPU/GPU split on the RTX 4070 laptop),
  no API cost or rate limit. The Ollama server must be running:
  `"/c/Users/Admin/AppData/Local/Programs/Ollama/ollama.exe" serve`.
- `gpt-oss-120b` (Groq) — **pilot only**. Dropped from the full evaluation: Groq's free tier allows
  ~200k tokens/day and the paid Developer tier was unavailable (Sept 2026). Keep its pilot rows as an
  observation, not a result.
- Llama-3.3-70B was planned but Groq made Llama enterprise-only (26 Aug 2026); the thesis text must
  reflect the change of the second model to gpt-oss-20b (local).

## Environment gotchas (Windows, Git Bash)

- **Edit LaTeX and Python with the Edit/Write tools, not heredoc/sed scripts**: backslashes (`\n`,
  `\section`, `\\`) get mangled when passed through bash heredocs into Python, and `main.tex` may use CRLF.
- `/tmp` is not writable from Git Bash here; use the session scratchpad for logs.
- The network drops intermittently (DNS failures): retry, and never record API failures as agent results
  (the runner already leaves them unrecorded).
- LangSmith account is EU-region: `.env` needs `LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com`.
- Keys live in `.env` (gitignored); never print their values.

## Thesis writing conventions

- Numbers in the text must match the data. Generated tables (`results/**/*.tex`, `\input` in `main.tex`)
  are regenerated by code; hand-typed numbers (Table 5.2, §5.1 counts, §5.2 statistics) must be updated
  whenever the benchmark or analysis changes — see `rebuild-benchmark` skill.
- APA-style references in the `hangparas` block, alphabetical; cite data sources (REFIT dataset DOI,
  Nord Pool via Sahkotin/Elering).
- After editing `main.tex`, compile and visually check the changed pages (`compile-thesis` skill).
