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
