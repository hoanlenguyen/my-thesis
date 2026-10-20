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
| `src/hems/tools/` | 8 shared tools (the Scheduler agent gets the scheduling and load tools, the single agent gets all) + `optimize_schedule` (MILP call, Scheduler agent only) + `with_thought` (explicit Thoughts) |
| `src/hems/agents/` | `single_agent.py`, `multi_agent.py` (two agents: Orchestrator → `profile_data()` → Scheduler → `verify_schedule()` loop → Orchestrator summary), `harness.py` (shared deterministic harness: profiles, `Checker`, `run_react`, cost facts), `harness_agent.py` (one agent in the same harness: `single_harness`, `single_harness_thoughts`), `prompts.py`, `llm.py` (model registry), `errors.py` (recovery nudge) |
| `src/hems/solvers/` | `milp.py` (PuLP/CBC ground truth), `naive.py` |
| `src/hems/data/` | REFIT loader, price fetch/load, day selection, scenario composition, benchmark build |
| `src/hems/analysis/` | metrics, Wilcoxon/Spearman, LaTeX tables, `resolution.py` (hourly vs 15-min) |
| `data/scenarios/` | main benchmark A01–F08 (hourly Sahkotin prices, frozen, seed 2026) |
| `data/scenarios_15min/` | Q-A01–Q-F08 (native 15-min Elering prices, Oct 2025 – Sep 2026) |
| `data/pilot/` | synthetic SYN-* scenarios — development only, never thesis results |
| `data/raw/` | gitignored: REFIT CSVs (6.5 GB), price CSVs |
| `results/` | `runs.jsonl` / `pilot_real.jsonl` (+ archived `*_vN.jsonl`), `resolution/`, tables |
| `demo/` | Nuxt 4 demo replaying recorded results (theme/components from Low-carbon-alerts); data from `tools/export_demo_data.py` → `demo/public/data`; `pnpm dev` on :3001 |

## Commands

```bash
uv run pytest                                   # offline tests with scripted fake models (must pass)
uv run hems run --scenarios data/scenarios --systems milp naive single multi_duo --models gpt-6-luna --runs 3 --out results/runs.jsonl
uv run hems analyze --runs results/runs.jsonl --scenarios data/scenarios --out results
uv run hems resolution --scenarios data/scenarios_15min   # regenerates tab:resolution
uv run hems demo data/scenarios/D01.json --system multi_duo --model gpt-6-luna
latexmk -xelatex main                           # TeX Live at C:\texlive\2026\bin\windows
```

Python 3.12 via `uv` (not the system 3.14). Skills: `compile-thesis`, `run-evaluation`, `rebuild-benchmark`.

## Research questions (since 5 Oct 2026, pre-registration Amendment 2 and draft `docs/preregistration_q2.md`)

- Framing: the artifact gives each household a **daily recommendation** from its appliance plan for the
  day (the scenario's `user_request` field holds that plan; the agent input is unchanged).
- **RQ**: how to design a hierarchical ReAct multi-agent system for reliable, cost-saving daily
  recommendations. The registered Q2 run used the four-agent **"Multi-Agent Pipeline" = `multi_rag_opt`**
  (retrieval + optimiser tool). **Since 16 Oct 2026 the code has only the two-agent pipeline**
  (`multi_duo`, `multi_duo_thoughts`; design iterations 10 and 11, exploratory); the four-agent systems
  (`multi`, `multi_v3`, `multi_rag`, `multi_rag_opt`, `multi_lean`) were deleted, their results stay in
  `results/`. The thesis text and its results are to be redesigned around the two-agent pipeline. **SQ1 (value and cost)**: saving and validity vs the LLM without tools,
  latency < 60 s and API cost < $0.10 per recommendation (H1a–c). **SQ2 (conditions)**: under which price
  pattern / load / peak limit the pipeline beats or matches existing home energy management tools (cheapest window, cheapest
  hours, EMHASS) (H2a–c; per-condition breakdown descriptive).
- Primary outcome: **saving vs no scheduling** (`metrics.scored_runs` saving_pct); gap to MILP secondary.
- The single agent and the MILP are no longer compared systems (Amendment 2); old H1–H2c stay confirmed
  on Q as history. Benchmarks: factorial `data/scenarios_v2` (exploratory) and `data/scenarios_q2`
  (held out, run only after the Q2 registration is committed).

## Methodology invariants (keep these true)

- Every system is scored by `core.evaluate.evaluate`; cost = consumer price × flexible appliance energy
  (`data/tariff.py`); base load counts toward the peak limit only.
- Tools: the Scheduler agent gets `SCHEDULER_TOOLS + OPTIMIZER_TOOLS + RESOLVER_TOOLS`
  (`multi_agent.SCHEDULER_AGENT_TOOLS`); `PROFILER_TOOLS` work is done by the deterministic `profile_data()`.
  Since iteration 14 the first round offers only `FIRST_ROUND_TOOLS` (`get_spot_prices`, `optimize_schedule`) and a
  feedback round all of them; the agents answer with `FinalSchedule` (start times only), the baselines (`oneshot`,
  `single`) keep `ScheduleOutput`. Costs price cached input tokens at the cached rate (`llm.usage_cost_usd`;
  records carry `tokens_cached`); results recorded before 19 Oct 2026 priced every input token in full.
  Only `optimize_schedule` (MILP call) solves the whole problem. The single-agent prompt is built from the
  role texts in `prompts.py`.
- Step budgets: Scheduler agent 60 (`multi_agent.SCHEDULER_STEP_LIMIT`), Orchestrator 6, at most 2 rounds;
  the single agent has 75 (`tests/test_core.py` checks the Scheduler stays within it).
- Recovery nudge (`agents/errors.py`) applies identically to every model and agent; recoveries are logged.
- Infeasible agent schedules are scored at the naive cost; feasibility is reported separately.
- **Household message is opt-in** (since 19 Oct 2026): campaigns skip the agents' message call unless the plan
  says `"message": true` (`campaign.Plan.message`, default false; `hems run --message`). Every existing config
  ran with it and says `"message": true`. Records carry `message`. The demo API returns it unless the request
  says `"message": false`.
- **Pre-registration** (`docs/preregistration.md`): H1/H2 are confirmed on the held-out Q set
  (`configs/confirmation.json` → `results/confirmation.jsonl`, analysed only by `hems confirm` /
  `analysis/confirm.py`; Q2: `configs/confirmation_q2.json` → `results/confirmation_q2.jsonl`,
  `analysis/confirm_q2.py`). Once registered, never change the confirm script, the held-out scenarios,
  prompts or tools before that run; report any deviation. The main benchmark is exploratory.
- All systems are registered in `src/hems/systems.py` (kind reference / external / llm); `run.execute`
  looks them up. Adding a system = one registry entry; `tests/test_regression.py` must keep reproducing
  the recorded deterministic results exactly.
- Real HEMS tools (secondary, descriptive; added after the pre-registration): `emhass` / `emhass_nominal`
  (EMHASS 0.18.4 in its own env `.venv-emhass`, conflicting pins; called as a subprocess by
  `solvers/emhass.py` → `tools/emhass_adapter.py --stdin`, so `hems run --systems emhass` works);
  `cheapest_hours` / `cheapest_hours_hourly` = HA "Nordpool cheapest hours actions" blueprint rule
  (`solvers/naive.py`). Results in `results/tools/{scenarios,scenarios_15min}.jsonl`.
- **Thesis EMHASS numbers = REST "as deployed"** (`emhass_rest`, `emhass_rest_nominal`): Docker container
  `emhass-thesis` on localhost:5000 (image ghcr.io/davidusb-geek/emhass, 0.18.4, default settings,
  `-e SUPERVISOR_TOKEN= -e EMHASS_URL=empty` so it never contacts Home Assistant), driven by
  `tools/emhass_rest.py`. The direct call (`emhass`, exact MIP gap) is only a cross-check.
- **Savings captured is pooled** over runs (`metrics.pooled_savings_captured`); never quote the mean of the
  per-run ratio, which explodes on days with a near-zero achievable saving.
- Extra baselines (`configs/baselines.json` → `results/baselines.jsonl`): `timer` = rule-based smart timer
  (`solvers/naive.smart_timer_schedule`, deterministic) and `oneshot` = LLM without tools
  (`agents/oneshot.py`, all data incl. per-slot base load in one prompt). Analyse together with
  `hems analyze --runs results/runs.jsonl results/baselines.jsonl`.
- Benchmark settings: 18 REFIT houses (12 and 19 excluded — reasons in `refit.EXCLUDED_HOUSES`),
  type E windows anchored at the daily price peak, seed 2026.
- **Peak limit = 8 kW only** (since 20 Oct 2026): the Energy Authority's power-charge threshold (60-min average,
  optional charge), applied as a hard limit per 15-min slot (`factorial.LIMIT_KW`). The stylised 3.5 kW level had
  no source and was dropped: `data/scenarios_v3` has 48 scenarios (`-80`), its 3.5 kW result rows are archived in
  `results/*_v3_strict35.jsonl`. The older sets (`scenarios`, `scenarios_15min`, `scenarios_v2`, `scenarios_q2`)
  keep their 3.5 kW scenarios as recorded; never quote 3.5 kW results as current findings.

## Open design issues (fixing either changes results: version, archive, rerun)

- `time_to_slot` rejects `"24:00"`, so `get_spot_prices(to_time="24:00")` returns an error turn (Gemini review).
- `requested_ids` in `multi_agent.build_pipeline` trusts the Orchestrator's brief: a fixed appliance id in it would cause
  false "MISSING" feedback. Not observed with GPT-4o-mini; check the gpt-oss-20b traces first.

## Models (`agents/llm.py`)

**Since 19 Oct 2026 new runs use `gpt-6-luna`** (`llm.DEFAULT_MODEL`; CLI, Studio and the live demo):
OpenAI's current small model, USD 0.10/0.50 per 1M tokens (third-party figures, verify), called with
`reasoning_effort="none"` (the API rejects `temperature` otherwise) and temperature 0. No dated snapshot exists,
so only the id `gpt-6-luna` can be pinned. Every result recorded before that date, the design iterations and the
registered Q2 confirmation used `gpt-4o-mini` and stay attributed to it (`confirm.py` / `confirm_q2.py` keep
`MODEL = "gpt-4o-mini"`). `main.tex` describes the change in `sec:stack`; its results still need the new campaign.

The registered Q2 confirmation uses `gpt-4o-mini` only. The earlier-design campaign
(`configs/full_evaluation.json`) used two models: commercial cloud vs small open-weight model run locally.

- `gpt-6-luna` (OpenAI API) — primary for new runs; 3 runs per scenario.
- `gpt-4o-mini` (OpenAI API) — primary until 19 Oct 2026 (all recorded results); 3 runs per scenario.
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
  are regenerated by code; hand-typed numbers (`tab:benchmark`, the counts in `sec:dataset`, the statistics in `sec:resolution`) must be updated
  whenever the benchmark or analysis changes — see `rebuild-benchmark` skill.
- APA-style references in the `hangparas` block, alphabetical; cite data sources (REFIT dataset DOI,
  Nord Pool via Sahkotin/Elering).
- After editing `main.tex`, compile and visually check the changed pages (`compile-thesis` skill).
- **Avoid em dashes** (`---`, "—"): they read as AI-generated style. Rewrite with commas, parentheses,
  "such as", "namely", a colon or a separate sentence. Use one only when nothing else works, and then
  tie it to the preceding word (`word~--- next`) so it never starts a line. The same applies to table cells.
- Hyphenation is disabled (no words split across lines); table text is left-aligned (`\tabularxcolumn`).
