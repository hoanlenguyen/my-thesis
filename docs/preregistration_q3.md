# Pre-registration draft: SQ1 and SQ2 under the 8 kW limit, held-out set Q3

**Status: DRAFT (21 October 2026), not registered.** It counts as registered once the author commits it together
with the analysis script `src/hems/analysis/confirm_q3.py` and its tests, before any run of any system on
Q3. Q3 was built on 21 October 2026; only its benchmark characteristics (section 2) were computed, no system was
scored on it. On the exploratory set v4, one unrecorded smoke run per agent design was made on U-VE01-80 of its
first build (see the note of 20 October 2026 in `docs/preregistration_q2.md`).

## 1. Why SQ2 is reworded

The registered SQ2 (`docs/preregistration_q2.md`) asked under which price patterns, household loads and peak limits
the recommendations save more than, or as much as, the tools households deploy today. Two of its premises fell away:

- The strict 3.5 kW limit had no source and was dropped (20 October 2026). The only sourced figure is the Energy
  Authority's 8 kW power-charge threshold, so the peak limit is no longer a factor.
- Under 8 kW the REFIT laundry and dishwasher loads rarely compete for capacity (2 of the 48 v3 days need
  coordination), so the conditions of the old SQ2 showed nothing. The household load therefore gets a third level,
  "electrified" (an electric car charge and a fixed sauna, benchmark v4), the loads that make Finnish houses reach
  8 kW.

The H2 results of the registered Q2 run stay as recorded; they are not re-analysed.

## 2. Data

Both sets have 72 scenarios: 4 price patterns x 3 household loads x 6 days, with the 8 kW limit as a hard limit per
15-minute slot. Light and heavy loads have windows from the households' usual run times in REFIT (as v3). The
electrified load is a heavy day plus a 3.7 kW, 2-hour car charge (ready 17:00, finished by midnight) and a fixed
6.8 kW sauna at 19:00-20:30 (in the base load). Sources and assumptions: `src/hems/data/electrified.py`.

- **Exploratory set v4** (`data/scenarios_v4`, `hems build-electrified`): the v3 days (hourly prices up to
  30 September 2025). Its days were used in design iterations 10-14, and the electrified load and its 2-hour charge
  were chosen after the rule systems' results on these days were seen. Not used to test the hypotheses.
- **Held-out set Q3** (`data/scenarios_q3`, `hems build-q3`): the 48 days of Q2 (native 15-minute prices,
  2 October 2025 to 24 September 2026), each with its 8 kW scenario, built with the same rules: Q2's cycles and base
  loads, the v3 windows, and the electrified version of each heavy day. No Q3 day is in any other benchmark or in the
  case library. The two-agent design has never been run on these days; the registered Q2 run used the four-agent
  design, other windows and the 3.5 kW level as well. Characteristics (no system scored): coordination needed on
  0 light, 2 heavy and 9 electrified days; no scheduling and the optimum valid on all 72; the optimum saves 15.7 %
  (light), 15.7 % (heavy) and 16.0 % (electrified) of the cost without scheduling, and never costs more than it.
- Runs: `configs/confirmation_q3.json` -> `results/confirmation_q3.jsonl`; EMHASS REST -> `results/tools/scenarios_q3.jsonl`.

## 3. Systems and runs

- **The pipeline**: the two-agent design `multi_duo` (design iteration 14), GPT-6 Luna (`gpt-6-luna`, reasoning
  effort none, temperature 0), 3 runs per scenario, no household message (`"message": false`).
- **Tools households deploy today** (deterministic, 1 run): `cheapest_window` (HA Nordpool planner rule),
  `cheapest_hours` (HA cheapest-hours blueprint rule), `emhass_rest` (EMHASS 0.18.4 REST service, default
  settings, measured profiles).
- Reported without hypotheses: the single agent in the harness `single_harness` (same model and runs; its comparison
  with the pipeline belongs to the RQ), the smart timer `timer` (own heuristic, not a deployed tool),
  `emhass_rest_nominal`, the LLM without tools `oneshot`, the MILP optimum and no scheduling `naive`.
- Prompts, tools, step limits and the scoring function are frozen at the registration commit.

## 4. Outcomes

- **Saving** (primary): (naive cost - scored cost) / naive cost x 100 per run; an invalid run or one without a
  schedule is scored at the naive cost (saving 0).
- **Validity rate**, **latency**, **API cost** and **tokens**, as in the Q2 registration.
- **Unit of analysis**: the mean over the runs of a Q3 scenario; N = 72 (24 per load). An electrified scenario shares
  its day, prices and laundry cycles with a heavy scenario; the two are treated as separate scenarios, since the
  added loads change the problem.

## 5. Research question, hypotheses and tests

**SQ2 (conditions), reworded:** Under the 8 kW power-charge threshold, for which price patterns and household loads,
from a light load to a household with an electric car and a sauna, do the pipeline's recommendations save more
than, or as much as, the tools households deploy today (the Home Assistant cheapest-window and cheapest-hours
automations and the EMHASS optimiser)?

**SQ1 (value and cost), unchanged wording**, tested again on Q3 for the current pipeline and model: How much do the
pipeline's recommendations save, how often are they valid, and what do they cost to produce, compared with a
language model that answers without tools?

| ID | Hypothesis | Test | Scenarios |
|---|---|---|---|
| H1a | the pipeline saves more than `oneshot` | Wilcoxon signed-rank (Pratt), two-sided | all 72 |
| H1b | the pipeline's validity rate is higher than `oneshot`'s | Wilcoxon signed-rank (Pratt), two-sided | all 72 |
| H1c | the pipeline's mean latency per recommendation is below 60 s | one-sided one-sample t test (upper 95 % bound < 60 s) | all 72 |
| H1c | the pipeline's mean API cost per recommendation is below $0.10 | one-sided one-sample t test (upper 95 % bound < $0.10) | all 72 |

**Tests.** Tests at alpha = 0.05, Holm-adjusted within each sub-question (SQ1: 4 tests, SQ2: 5 tests). A
directional hypothesis is supported when its adjusted p < 0.05 **and** the mean difference has the predicted sign.
Implementation: `src/hems/analysis/confirm_q3.py` (`uv run python -m hems.analysis.confirm_q3`), tested on stand-in
data in `tests/test_confirm_q3.py`. Two rules fixed in advance for tests that cannot be computed: a Wilcoxon test
whose differences are all zero counts as p = 1 (no difference shown); for H2c, if every paired difference is zero
the 90 % CI is [0, 0], inside the margin, and equivalence holds (the t statistic is undefined then).

| ID | Hypothesis | Test | Scenarios |
|---|---|---|---|
| H2a | the pipeline saves more than `cheapest_window` | Wilcoxon signed-rank (Pratt), two-sided | all 72 |
| H2b | the pipeline saves more than `cheapest_hours` | Wilcoxon signed-rank (Pratt), two-sided | all 72 |
| H2c | the pipeline and `emhass_rest` save the same within +-1 percentage point | paired t TOST (90 % CI inside +-1) | all 72 |
| H2d | the pipeline's saving advantage over `cheapest_hours` is larger on electrified days than on light and heavy days | Mann-Whitney U on the per-scenario differences, two-sided | 24 vs 48 |
| H2e | the pipeline's saving advantage over `cheapest_window` is larger on electrified days than on light and heavy days | Mann-Whitney U on the per-scenario differences, two-sided | 24 vs 48 |

H2d and H2e make the "under which conditions" part of SQ2 testable for the new factor; the price patterns and the
per-cell results stay descriptive (section 6).

**Margin for H2c.** One percentage point of the naive cost is about 0.9 cents per household and day on Q3 (median
naive cost EUR 0.90, interquartile range EUR 0.37 to 1.66, maximum EUR 4.49). A failed TOST is reported as *not
shown to be equivalent*, never as *different*, unless a separate two-sided Wilcoxon test is also significant.

**What is already known on the exploratory set v4 (stated so that no result is read as a surprise).** Computed from
the deterministic systems on v4, not on Q3, assuming the pipeline reaches the optimum:
- The optimum saves more than both rules on 68 of 72 scenarios (mean 1.9 points over `cheapest_window`, 6.1 over
  `cheapest_hours`), so H2a and H2b test mainly whether the pipeline reaches the optimum, not whether the rules can
  be beaten.
- The optimum's advantage over `cheapest_hours` is larger on electrified days (10.6 points against 3.4 to 4.4;
  Mann-Whitney p = 0.02), over `cheapest_window` it is not (2.5 against 1.3 to 1.9; p = 0.61). H2e is therefore
  expected not to be supported, and H2d may not survive the Holm adjustment.
- The smart timer, a greedy load-aware rule, reaches the optimum on every v4 scenario. A finding that the pipeline
  beats the deployed rules does not show that a language model is needed to beat them; the thesis must say so.

## 6. Reporting

- All nine tests (four for SQ1, five for SQ2), supported or not, with the effect size (r for Wilcoxon,
  rank-biserial for Mann-Whitney) and the mean difference.
- Without hypotheses: results by price pattern and by load and per cell; validity rates (the rules' invalid
  schedules on electrified days); total EUR saved; `single_harness`, `timer`, `emhass_rest_nominal`, `oneshot`; the
  gap to the MILP optimum; TOST at +-0.5 and +-2 points.
- Any deviation is described in the thesis with the result under the original plan.
