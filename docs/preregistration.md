# Pre-registration: confirmatory evaluation of H1 and H2

Thesis: *A Hierarchical ReAct Multi-Agent Pipeline for Residential Appliance Load Scheduling Under
Dynamic Electricity Pricing* (Hoan Le, University of Oulu; supervisor Yueqiang Xu).

Registered: **the date of the git commit that adds this file.** The commit also fixes the code, prompts,
tools and analysis used for the confirmatory run. No confirmatory run (`results/confirmation.jsonl`)
exists at that commit.

## 1. Background

The main benchmark (`data/scenarios`, 48 scenarios, hourly Nord Pool FI prices) served as the
exploratory stage. The pipeline was refined on it over several design iterations, and the hypotheses
below were formulated after its GPT-4o-mini results had been inspected (thesis §5.5 and §5.6). This
document fixes those hypotheses before they are tested on data that no language model has been run on.

## 2. Data

- Benchmark: `data/scenarios_15min`, scenarios Q-A01 to Q-F08 (48 scenarios, six types of 8), native
  fifteen-minute prices from Elering, October 2025 to September 2026. Built with seed 2026 and a 3.5 kW
  peak limit, with days kept disjoint across types. Only the MILP and naive reference schedulers have been run on it so far (thesis §5.2); no
  language model has.
- SHA-256 of `cat data/scenarios_15min/Q-*.json`: `0485d3688e80b7ae1ce58036635d383f207ee59f44abdb1b5602f4c9aa28fb7f`.
  The scenarios are not changed after registration.

## 3. Systems and runs

| System | Description | Runs per scenario |
|---|---|---|
| `single` | single ReAct agent, all 8 tools, 75 steps | 3 |
| `multi` | hierarchical pipeline (Orchestrator, Profiler, Scheduler, Resolver, verification gate), 15 + 35 + 25 steps | 3 |
| `oneshot` | the same model without tools, all data in one prompt | 3 |
| `timer`, `milp`, `naive` | deterministic references | 1 |

- Model: `gpt-4o-mini-2024-07-18` (OpenAI API), temperature 0.
- Plan: `configs/confirmation.json`.
- Command: `uv run hems campaign run --plan configs/confirmation.json`.
- Provider and network failures are not recorded and are retried, as in the exploratory runs. Every
  completed run is kept, including infeasible runs and runs that return no schedule.

## 4. Outcomes

- **Optimality gap** = (scored cost − MILP cost) / MILP cost × 100. An infeasible run, or one that
  returns no schedule, is scored at the naive cost (`core.evaluate`, `analysis.metrics.scored_runs`).
- **Input tokens, API cost (USD), latency (s)**: as recorded per run.
- **Unit of analysis**: the mean over the 3 runs per scenario. N = 48 paired scenarios.

## 5. Hypotheses and tests

All tests are two-sided at α = 0.05. p-values are Holm-adjusted within each sub-question. A directional
hypothesis is supported when its adjusted p < 0.05 **and** the mean paired difference has the predicted
sign. The exact implementation is `src/hems/analysis/confirm.py` (`uv run hems confirm`).

| ID | Hypothesis | Test | Family |
|---|---|---|---|
| H1-single | single agent gap < oneshot gap | Wilcoxon signed-rank (Pratt) | SQ1 (2 tests) |
| H1-multi | pipeline gap < oneshot gap | Wilcoxon signed-rank (Pratt) | SQ1 |
| H2a | pipeline and single agent equivalent in gap within ±1 percentage point | paired t TOST; equivalent if p < 0.05 (90 % CI inside ±1) | SQ2 (4 tests) |
| H2b-tokens | pipeline input tokens < single agent | Wilcoxon signed-rank (Pratt) | SQ2 |
| H2b-cost | pipeline API cost < single agent | Wilcoxon signed-rank (Pratt) | SQ2 |
| H2c | pipeline latency > single agent | Wilcoxon signed-rank (Pratt) | SQ2 |

**Margin for H2a.** ±1 percentage point of the optimal cost is below one cent per household and day on
the main benchmark (mean optimal cost €0.85), which a household would not notice. The margin was chosen
after the exploratory results. On those results the TOST would have 0.86 power (SD of paired differences
2.2 points, N = 48); the power falls to about 0.5 if that SD reaches 3 points. If H2a is not supported,
the result is reported as *not shown to be equivalent*, never as *different*, unless a separate
two-sided Wilcoxon test is also significant.

## 6. Reporting

- All six tests are reported whether or not they are supported, together with the Wilcoxon effect size r
  and the mean paired difference.
- Also reported, without hypotheses:
  - results by scenario type;
  - feasibility rates;
  - the comparison of each design with the smart timer (Wilcoxon);
  - TOST at ±0.5 and ±2 points;
  - the Wilcoxon version of the TOST.
- Any deviation from this plan (for example a rerun after a bug fix) is described in the thesis together
  with the result under the original plan.

## 7. Not covered here

- **H3 (SQ3, local model)** is tested on the main benchmark (`configs/full_evaluation.json`), as stated
  in thesis §3.2.
- **H4 (SQ4, informal requests)** will be registered in a separate section of this file before any system
  is run on the informal-request benchmark.

## Amendment 1 (4 October 2026): research questions consolidated

Recorded after the confirmatory run (`results/confirmation.jsonl`) was completed and analysed; nothing in
sections 1 to 6 above has been changed.

- The thesis now frames the artifact as giving each household a **daily recommendation** from its
  appliance plan for the day (the cycles to run with their ready times and deadlines, the base load, the
  peak limit and the prices). This is the same input the systems received in every run so far; no prompt,
  tool, scenario or scoring was changed.
- The four sub-questions were consolidated into two:
  - **SQ1** (cost reduction compared with no scheduling, a language model without tools, rule-based
    scheduling and a deployed optimizer) contains **H1** unchanged.
  - **SQ2** (multi-agent vs single agent, and whether this holds with a small local model) contains
    **H2a–H2c** unchanged and the separately tested **H3** (main benchmark, both models).
- The Holm families of section 5 are unchanged: H1-single and H1-multi form one family (2 tests);
  H2a, H2b-tokens, H2b-cost and H2c form the other (4 tests). The reported results already follow them.
- **H4 (informal requests) is not pursued** and will not be registered; it was never run.

## Amendment 2 (5 October 2026): thesis redesign around retrieval, an optimiser tool and real tools

Recorded after the confirmatory run and Amendment 1. Sections 1 to 6 and Amendment 1 are unchanged, and the
confirmatory results (`results/confirmation/confirmatory_tests.csv`, all six hypotheses supported) stay on
record exactly as computed by `src/hems/analysis/confirm.py`, which is not modified. A pilot of the new
systems on the 16 type C and D scenarios of the main benchmark (`results/rag_pilot.jsonl`, 1 run each) had
already been run and inspected when this amendment was written, so every result about them is exploratory.

**1. The single agent is removed from the thesis comparison.**
- The thesis no longer asks whether a multi-agent pipeline beats a single agent. H2a to H2c remain confirmed
  in this document and in the repository; the thesis mentions them once, as the earlier design comparison,
  and does not build its research questions on them.
- **H3** (multi vs single with a small local model) is **withdrawn**. The local-model campaign
  (`configs/full_evaluation.json`, stopped at 521 of 672 runs) is not completed for this purpose. If a
  local-model question is kept, it is registered anew before its run.
- The single agent stays in the code base so that the recorded results remain reproducible.

**2. The MILP optimum is no longer a compared system, and the primary outcome changes.**
- **Primary outcome: saving against no scheduling**, in euros and as a share of the naive cost,
  pooled over runs: (Σ naive cost − Σ scored cost) / Σ naive cost. The per-scenario saving
  (naive − scored) / naive × 100 is the unit for paired tests. The scoring convention is unchanged: an
  infeasible run or one without a schedule is scored at the naive cost.
- The optimality gap is still computed (`analysis.metrics`) and H1 to H2c keep their registered gap-based
  results. Any savings-based test of the same comparisons is reported as secondary and unregistered.
- The MILP is still used, in roles other than a competitor: it confirms during benchmark construction that
  every scenario has a feasible schedule, it solves the cases of the retrieval library, and it is the solver
  behind the optimiser tool below.

**3. New systems (design iteration 7, `src/hems/rag.py`, `src/hems/agents/multi_agent.py`).**
- `multi_rag`: the pipeline, unchanged otherwise, with the two most similar solved days from a case library
  given to the Scheduler and the Resolver as worked examples.
- `multi_rag_opt`: as `multi_rag`, and the Scheduler also has `optimize_schedule`, which solves the whole
  day with the MILP; the agents call it, check the result and explain it.
- Case library (`data/rag/cases.jsonl`, manifest beside it): 164 days (30 per type, 14 for type D) from the
  hourly prices up to 30 September 2025, excluding all 94 days of the main and Q benchmarks, composed like the
  benchmark scenarios (seed 7) and solved with the MILP. Retrieval is a fixed similarity on the price shape
  and the appliance structure (`rag.features`, `rag.similarity`); no text embeddings and no tuning on the
  benchmark.

**4. New and relabelled baselines (real tools, `src/hems/solvers/naive.py`).**
- `cheapest_window`: the lowest-average block of whole hours inside the appliance window, as computed by the
  Home Assistant Nordpool Planner (dala318/nordpool_planner, static planner) and by the sequential
  cheapest-hours mode of shelly-porssisahko (jisotalo).
- `cheapest_hours_hourly` (unchanged rule) also represents the scattered cheapest-hours mode of
  shelly-porssisahko, since for a cycle appliance both start at the first hour inside the cheapest set.
- EMHASS (`emhass_rest`, Docker REST API) remains the main real-tool comparison.

**5. What will be confirmatory.**
- The Q set is used and is not reused for new claims. Confirmatory claims about iteration 7 need a new
  held-out set **Q2**: 48 scenarios from the Elering 15-minute prices of 1 October 2025 to 25 September 2026,
  with no day of the Q set, built with a new seed before any run on it.
- Q2 is built with the factorial design of point 6 (`data/scenarios_q2`, seed 2029, 96 scenarios, no day
  of any other set or of the case library).
- Planned hypotheses, to be fixed in `docs/preregistration_q2.md` after the full main-benchmark run of
  `multi_rag` and `multi_rag_opt` (3 runs per scenario) and before any run on Q2:
  - the optimiser arm saves as much as EMHASS (equivalence on the per-scenario saving, margin to be stated);
  - the retrieval arm saves more than the pipeline without retrieval;
  - both arms save more than the deployed cheapest-hours rules.

**5b. One reported system.** The thesis presents one system, the *Multi-Agent Pipeline*, which is
`multi_rag_opt`. The base pipeline (`multi`) and the pipeline with retrieval only (`multi_rag`) are
reported as design iterations from the exploratory run and are not run on Q2. SQ1 becomes a question
about value and cost (saving and validity against the LLM without tools; response time and API cost
against the design objectives); the hypotheses in `docs/preregistration_q2.md` follow from that.
- **Design iteration 8** (6 October 2026), after the exploratory run on `data/scenarios_v2`: in 2 of 288
  runs the final pipeline left one appliance out of its schedule even after the feedback round (a rare
  slip of the model, not reproduced in 8 reruns of the same days). The verification step now places an
  appliance that is still missing after the last round at its cheapest start within the peak limit,
  keeping the agents' other start times, and the Scheduler's missing-appliance retry lists the day's
  appliances (`complete_missing`, `multi_rag_opt` only). The earlier runs are archived in
  `results/main_v2_iter7_multi_rag_opt.jsonl`, and `multi_rag_opt` is rerun on `data/scenarios_v2`.

**6. Benchmark redesign (factorial).**
- The six scenario types A to F varied the price pattern, the number of appliances and the window style
  together, so an effect could not be attributed to one of them (types A and B, for example, share the
  price pattern and differ only in the appliances). New scenario sets use a factorial design
  (`src/hems/data/factorial.py`): price pattern (stable, volatile, spike, negative) x household load
  (light, heavy) x peak limit (strict 3.5 kW, realistic 8 kW). Six price days per pattern x load cell;
  each day is scheduled under both limits with the same appliances, giving 96 scenarios per set.
- New exploratory main set `data/scenarios_v2` (hourly prices up to 30 September 2025, seed 2028); every
  system of the redesigned study is rerun on it (`configs/main_v2.json`). The first main benchmark and its
  results, including the pilot and the interrupted full run of iteration 7 (`results/iteration7.jsonl`),
  remain as archived exploratory evidence.
- The case library is rebuilt with the same design: 20 days per cell under both limits, 320 cases, hourly
  prices up to 30 September 2025, no day of any benchmark.
- The sets Q (first confirmation) and the first main benchmark keep the A to F types; they are not rebuilt.
