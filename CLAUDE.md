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
| `data/scenarios_v3/` | U-*-80: v2 days with windows from REFIT usual run times, 8 kW (48; `hems build-usage`) |
| `data/scenarios_v4/` | v3 + U-?E??-80: each heavy day with a 3.7 kW car charge and a fixed 6.8 kW sauna (72; `hems build-electrified`) |
| `data/scenarios_q3/` | held out: the Q2 days at 8 kW with v3 windows + electrified heavy days (72; `hems build-q3`); no runs before registration |
| `data/pilot/` | synthetic SYN-* scenarios — development only, never thesis results |
| `data/raw/` | gitignored: REFIT CSVs (6.5 GB), price CSVs; also data of the follow-up prototypes (see "Follow-up thesis") |
| `prototypes/` | follow-up thesis prototypes (home gateway, HIPE, OPSD, heat pump); exploratory, never thesis results |
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
  `results/`. The thesis text describes the two-agent pipeline and its Q3 results. **SQ1 (value and cost)**: saving and validity vs the LLM without tools,
  latency < 60 s and API cost < $0.10 per recommendation (H1a–c). **SQ2 (conditions)**: under which price
  pattern / load / peak limit the pipeline beats or matches existing home energy management tools (cheapest window, cheapest
  hours, EMHASS) (H2a–c; per-condition breakdown descriptive). **Reworded and registered (commit f1d187c, 21 Oct
  2026, `docs/preregistration_q3.md`)**: under the 8 kW threshold, price pattern × load (light, heavy, electrified =
  car charge + sauna); H2a/b beat the HA rules, H2c ≈ EMHASS ±1 pt, H2d/e larger advantage on electrified days.
  **Run done on the held-out Q3** (GPT-6 Luna, `results/confirmation_q3.jsonl`, `results/tools/scenarios_q3.jsonl`,
  `hems.analysis.confirm_q3`): 7 of 9 supported, H2d/H2e not. v4 (`results/luna_v4.jsonl`) is the exploratory set.
  Never rerun or re-analyse Q3 differently; Chapters 5–7 of `main.tex` report these results.
- **Wording in `main.tex`** (22 Oct 2026, same meaning as registered): RQ "How can a hierarchical ReAct multi-agent
  system (the Multi-Agent Pipeline) be designed to give households reliable, cost-saving daily appliance
  recommendations under dynamic electricity prices?"; SQ1 "How much do the Multi-Agent Pipeline's recommendations
  save, how often are they valid, and what do they cost to produce, compared with a base language model without
  tools?"; SQ2 "Under which price patterns and household loads do the pipeline's recommendations save at least as
  much as existing home energy management tools?" (the 8 kW limit, the tools and the electrified load are explained
  in the paragraph after the questions).
- **SQ3 (added 23 Oct 2026, after the Q3 run)**: "Does dividing the work between two agents make the recommendations
  more reliable, cheaper or faster than a single agent in the same harness?" The registration reports
  `single_harness` without hypotheses, so SQ3 is answered descriptively (paired Wilcoxon reported without a
  confirmatory claim); H1/H2 and their Holm families stay exactly as registered (SQ1 = H1a-c, SQ2 = H2a-e).
  Answer: same schedules in every run; the single agent is faster (5.0 vs 7.4 s) and cheaper.
- **Thesis text no longer mentions GPT-4o-mini or its runs** (author's decision, 21 Oct 2026); only the literature
  review names it for other authors' studies. Results files and code keep their attribution.
- Primary outcome: **saving vs no scheduling** (`metrics.scored_runs` saving_pct); gap to MILP secondary.
- The single agent and the MILP are no longer compared systems (Amendment 2); old H1–H2c stay confirmed
  on Q as history. Benchmarks: factorial `data/scenarios_v2` (exploratory) and `data/scenarios_q2`
  (held out, run only after the Q2 registration is committed).
- **Scope of the text (30 Oct 2026):** the evaluation stays household-only, but `main.tex` now states that the
  problem is general (shiftable loads with windows under a power limit): a scope paragraph in `sec:problem`, a new
  `sec:transferability` (6.4, "Transferability to smart devices and industrial loads": smart devices in three
  groups, industrial sites, what carries over and what does not), Future research item 1 widened to storage,
  smart-device and industrial loads, and the closing paragraph of the Conclusions. No numbers or results changed.

## Follow-up thesis (this branch: `new-thesis/home-gateway`)

This branch is the current thesis (merged from `claude/thesis-scope-expansion-47c694`, PR #1) plus exploratory
work for a follow-up thesis: a language-model agent as the interface of a home energy gateway (PV, battery, heat
pump, EV). Design and plan: `docs/protocol_home_gateway.md` (reframed 30 Oct 2026) and `docs/gateway_thesis_plan.html`
(the published plan page with diagrams); `docs/proposal_spark.md` is an earlier industrial idea (SPARK, KIT).

- **Keep the two theses apart.** `main.tex`, `src/hems/` campaigns, `data/scenarios*` and `results/` belong to the
  current thesis; never cite prototype numbers in `main.tex`. Prototype code and outputs stay in `prototypes/`.
  The only shared-code change is the `industrial_machine` appliance kind (`core/models.py`, `tools/__init__.py`),
  which no thesis scenario uses.
- `prototypes/home_gateway/`: `twin.py` (one year of OPSD `residential4` with a virtual battery: recorded, battery,
  rules, perfect-foresight LP; `--market fi|de`, `--export spot|feedin`) and `gateway.py` (12 sample days with
  forecasts, a control layer with fallbacks, day-ahead LP, MPC, perfect foresight and the ReAct agent;
  `--forecast noise|weather`, `--models gpt-6-luna gpt-oss-20b`). Run from the repo root, e.g.
  `uv run python prototypes/home_gateway/gateway.py --raw-dir D:/Study/my-thesis/data/raw --market de --forecast weather`.
  `prototypes/hipe/`, `prototypes/opsd/`: industrial scenarios for `hems run`; `prototypes/heatpump/`: REFIT +
  When2Heat + Norwegian EV sessions. Each folder has a README with its data and assumptions.
- **Lessons to keep** (they decided results): value the battery and heat left at midnight the same way in the
  optimiser and the score; the control layer holds the planned grid exchange (the battery absorbs forecast error),
  never the planned battery power; tool descriptions never suggest a default for a decision the agent makes (a
  suggested 50 % reserve was copied by both models); report savings in EUR when export income cancels the bill.
- **Main finding so far:** on cost, MPC with a fixed PV derating of 0.8-0.9 closed 46-51 % of the rules-to-optimum
  gap, more than the agents (36-39 %, GPT-6 Luna and gpt-oss-20b). The follow-up is therefore framed around plan
  interpretation and configuration, with a tuned MPC as the cost reference, not around beating the optimiser.
- Prototype data in `data/raw/` (gitignored, shared with the main checkout): `when2heat.csv` (+ `when2heat_fi.csv`,
  `when2heat_de_2015_2018.csv`), `hipe/`, `opsd_household/`, `dwd_konstanz/`, `ev_norway/`,
  `prices_de_energycharts_2015_2019.csv`, `prices_fi_elering_2015_2017.csv`, `prices_fi_elering_2018_2021.csv`,
  `prices_fi_elering_2017_10.csv`. Agent runs need `.env` (found by walking up from the script) and, for
  gpt-oss-20b, the Ollama server; set `LANGSMITH_TRACING=false` (the trace quota is exhausted).

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
OpenAI's current small model, USD 0.10/0.50 per 1M tokens, cached input 0.01 (checked on OpenAI's pricing page
21 Oct 2026; cache writes, 0.125/0.25, are not priced by `usage_cost_usd`, bound in `sec:stack`), called with
`reasoning_effort="none"` (the API rejects `temperature` otherwise) and temperature 0. No dated snapshot exists,
so only the id `gpt-6-luna` can be pinned. Every result recorded before that date, the design iterations and the
registered Q2 confirmation used `gpt-4o-mini` and stay attributed to it (`confirm.py` / `confirm_q2.py` keep
`MODEL = "gpt-4o-mini"`). `main.tex` describes the change in `sec:stack`; its results still need the new campaign.
**Thesis text (author's decision, 21 Oct 2026): the thesis does not mention GPT-4o-mini or its runs** (done with the
GPT-6 Luna rewrite of Chapters 5–7). Literature-review mentions of other authors' GPT-4o-mini studies stay. Results
files and code keep the attribution (never relabel a run's model).

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
