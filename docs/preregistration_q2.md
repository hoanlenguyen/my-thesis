# Pre-registration 2: confirmatory evaluation on the held-out set Q2

Thesis: *A Hierarchical ReAct Multi-Agent Pipeline for Residential Appliance Load Scheduling Under
Dynamic Electricity Pricing* (Hoan Le, University of Oulu; supervisor Yueqiang Xu).

Registered: **the date of the first git commit of this file without the DRAFT note** (an earlier draft
was committed in 8f5eb7f). That commit also fixes the code, prompts, tools, case library and analysis used
for the run. No run on `data/scenarios_q2` exists at that commit. It
follows Amendment 2 of `docs/preregistration.md`, which explains why the single agent and the MILP optimum
are no longer compared systems and why the primary outcome is the saving against no scheduling.

## 1. Background

In the last design iterations the pipeline was extended with retrieval of solved similar days
(`multi_rag`), then with an optimiser tool (`multi_rag_opt`, design iteration 7), and finally with the
completion of an appliance still missing after the last feedback round (design iteration 8); see
Amendment 2. A pilot on the 16 type C and D days of the first main benchmark motivated the hypotheses.
The exploratory run on the factorial main set (`data/scenarios_v2`, `results/main_v2.jsonl`, EMHASS in
`results/tools/scenarios_v2.jsonl`) checked them before registration: applied to that set, all seven tests
below are supported (pipeline 100 % valid in 288 runs, saving 27.58 % against an optimum of 27.59 %,
EMHASS 27.36 %, LLM without tools 7.76 %, mean latency 21.5 s). These are exploratory results and are
reported as such. The set Q (`data/scenarios_15min`) was used by the first confirmatory run and is not
reused.

## 2. Data

- **Design** (`src/hems/data/factorial.py`): price pattern (stable, volatile, spike, negative) x household
  load (light: dishwasher and washing machine with separate daytime windows; heavy: two washes, two
  dryings and a dishwasher sharing one window) x peak limit (strict 3.5 kW; realistic 8 kW). Six price
  days per pattern x load cell, 48 days; each day is scheduled under both limits with the same appliances,
  giving **96 scenarios** (ids `Q2-<pattern><load><nn>-35` and `-80`). Negative: at least one hour below
  zero; spike: the highest daily maxima among days without negative prices; volatile: top 15 % by standard
  deviation; stable: bottom 25 %.
- **Q2** (`data/scenarios_q2`): built with `uv run hems build-factorial --prices
  data/raw/prices_fi_elering.csv --out data/scenarios_q2 --from 2025-10-01 --seed 2029 --id-prefix Q2-
  --exclude data/scenarios data/scenarios_15min data/scenarios_v2`. Native 15-minute Elering prices,
  1 October 2025 to 25 September 2026, identical to the official ENTSO-E day-ahead prices
  (`data/README.md`). No day of Q2 is in the exploratory main set (`data/scenarios_v2`, hourly prices up
  to 30 September 2025), in the first benchmarks or in the case library (`data/rag/cases.jsonl`, 320
  cases, prices up to 30 September 2025).
- 30 of the 96 scenarios need coordination (the appliances' individually cheapest starts exceed the peak
  limit together), almost all of them heavy-load days under the strict limit. Every scenario has a
  feasible schedule (MILP check during construction).
- Same tariff and REFIT cycle pool as the earlier sets. Manifest: `data/scenarios_q2/manifest.json`.

## 3. Systems and runs

| System | Description | Runs per scenario |
|---|---|---|
| `multi_rag_opt` | **the Multi-Agent Pipeline**: retrieved examples of solved days, the `optimize_schedule` tool, and completion of an appliance still missing after the last feedback round (design iteration 8) | 3 |
| `oneshot` | the same model without tools | 3 |
| `emhass_rest` | EMHASS 0.18.4, Docker REST API, measured power profiles | 1 |
| `cheapest_window` | HA Nordpool Planner / shelly-porssisahko sequential: lowest-average hour block | 1 |
| `cheapest_hours` | HA Nordpool cheapest-hours blueprint, 15-minute prices | 1 |
| `cheapest_hours_hourly`, `timer`, `naive`, `milp` | reported without hypotheses; `naive` defines the saving | 1 |

The thesis presents one system, the Multi-Agent Pipeline (internal name `multi_rag_opt`). The base
pipeline (`multi`) and the pipeline with retrieval only (`multi_rag`) are earlier design iterations,
reported from the exploratory run on `data/scenarios_v2`; they are not run on Q2.

- Model: `gpt-4o-mini-2024-07-18` (OpenAI API), temperature 0. Retrieval: top 2 cases, fixed similarity.
- LLM and rule systems: `uv run hems campaign run --plan configs/confirmation_q2.json`
  (writes `results/confirmation_q2.jsonl`).
- EMHASS: `uv run python tools/emhass_rest.py data/scenarios_q2 results/tools/rest_scenarios_q2_profile.json`,
  then `uv run hems import-schedules results/tools/rest_scenarios_q2_profile.json --system emhass_rest
  --scenarios data/scenarios_q2 --out results/tools/scenarios_q2.jsonl`; the same with `--mode nominal`
  and `--system emhass_rest_nominal` for the secondary configuration.
- Provider and network failures are retried and not recorded. Every completed run is kept, including
  infeasible runs and runs without a schedule.

## 4. Outcomes

- **Saving** (primary) = (naive cost − scored cost) / naive cost × 100 per run, in percent of the cost of
  starting every appliance when ready. An infeasible run or one without a schedule is scored at the naive
  cost, so its saving is 0.
- **Validity rate**: the share of a scenario's runs whose schedule is valid (every appliance scheduled,
  inside its window, total load within the peak limit).
- **Latency** (s), **API cost** (USD) and **tokens** (input + output) per run, as recorded.
- **Unit of analysis**: the mean over the runs of a scenario. N = 96 paired scenarios (48 days under two
  peak limits; the two scenarios of a day are treated as separate pairs, since the limit changes the
  problem).

## 5. Research questions, hypotheses and tests

Research questions (thesis §1.2). **RQ:** How can a hierarchical ReAct multi-agent system be designed to
give households reliable, cost-saving daily appliance recommendations under dynamic electricity prices?
**SQ1 (value and cost):** How much do the pipeline's recommendations save, how often are they valid, and
what do they cost to produce, compared with a language model that answers without tools? **SQ2
(conditions):** Under which price patterns, household loads and peak limits do the recommendations save
more than, or as much as, the tools households deploy today?

Tests at α = 0.05, Holm-adjusted within each sub-question. A directional hypothesis is supported when its
adjusted p < 0.05 **and** the mean paired difference has the predicted sign. Implementation:
`src/hems/analysis/confirm_q2.py`.

| ID | Hypothesis | Test | Family |
|---|---|---|---|
| H1a | the pipeline saves more than `oneshot` | Wilcoxon signed-rank (Pratt), two-sided | SQ1 (4 tests) |
| H1b | the pipeline's validity rate is higher than `oneshot`'s | Wilcoxon signed-rank (Pratt), two-sided | SQ1 |
| H1c | the pipeline's mean latency per recommendation is below 60 s | one-sided one-sample t test (upper 95 % bound < 60 s) | SQ1 |
| H1c | the pipeline's mean API cost per recommendation is below $0.10 | one-sided one-sample t test (upper 95 % bound < $0.10) | SQ1 |
| H2a | the pipeline saves more than `cheapest_window` | Wilcoxon signed-rank (Pratt), two-sided | SQ2 (3 tests) |
| H2b | the pipeline saves more than `cheapest_hours` | Wilcoxon signed-rank (Pratt), two-sided | SQ2 |
| H2c | the pipeline and `emhass_rest` save the same within ±1 percentage point | paired t TOST (90 % CI inside ±1) | SQ2 |

The two H1c limits are the design objectives of thesis §4.1. A bound is a one-sided claim by nature, so
these two tests are one-sided; all other tests are two-sided with the direction check.

The "under which conditions" part of SQ2 is answered descriptively, without further hypotheses: the
same comparisons are reported per price pattern, per load and per peak limit (section 6).

**Margin for H2c.** One percentage point of the naive cost is about 0.6 cents per household and day on Q2
(median naive cost €0.56, interquartile range €0.29 to €0.91, maximum €2.81), which a household would not
notice. If H2c is not supported, the result is reported as *not shown to be equivalent*, never as
*different*, unless a separate two-sided Wilcoxon test is also significant.

**Expected weak point.** H1b may have little power: in the exploratory runs the LLM without tools gave a
valid schedule in 92 % of runs, so the validity difference rests on few scenarios. On light-load days
most systems reach nearly the same saving, so the saving differences come mainly from heavy-load days.

## 6. Reporting

- All seven tests, whether supported or not, with the effect size r and the mean paired difference.
- Without hypotheses: results by price pattern, by load and by peak limit (each factor averaged over the
  others) and per cell; the change from the strict to the realistic limit on the same days (paired by
  day); validity rates; total € saved; the smart timer (own heuristic written for this study, not a
  deployed tool) and `cheapest_hours_hourly`; EMHASS with constant nominal power; the gap to the MILP
  optimum as a secondary measure; TOST at ±0.5 and ±2 points and its Wilcoxon version.
- Any deviation (for example a rerun after a bug fix) is described in the thesis with the result under
  the original plan.

## Note added after the confirmatory run (7 October 2026): design iteration 9, exploratory

This note does not change the registered plan, the analysis code (`hems.analysis.confirm_q2`) or the
registered results, which stay as reported, including H1c (latency) *not supported*.

After the run, the pipeline's response time was profiled: about 97 % of a run is spent waiting for
11–13 sequential language-model calls; the tools, including the optimiser, take under 0.5 s. Design
iteration 9 (system `multi_lean`, flag `lean=True` in `hems.agents.multi_agent`) reduces the number of
calls without changing the tools, the model or the optimiser:

1. the Profiler receives the household data and the classification of every appliance in its message
   (the same deterministic tool outputs) and answers in one call;
2. the Scheduler starts with `optimize_schedule` and returns its start times without re-costing them;
3. the Resolver runs only when the Scheduler's proposal fails the verification step;
4. the Orchestrator's summary is given the schedule's cost and its saving against no scheduling.

It is evaluated as an exploratory comparison on the exploratory main set (`configs/iteration9.json`),
interleaved per scenario with the registered pipeline `multi_rag_opt` so that both meet the same API
conditions. It is not a confirmatory test, and Q2 is not used for it.
