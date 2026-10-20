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

## Note added after the confirmatory run (16 October 2026): design iteration 10, exploratory

This note does not change the registered plan, the analysis code or the registered results, which stay as
reported for the registered four-agent pipeline `multi_rag_opt`.

In the registered run the verification step never sent a schedule back to the Scheduler (0 of 289 runs;
2 of 288 on the exploratory set), and the Profiler's work is deterministic (reading the household data and
classifying each appliance). Design iteration 10 (system `multi_duo`, flag `duo=True` in
`hems.agents.multi_agent`) therefore reduces the pipeline to two language-model agents:

1. the Orchestrator plans and summarises, as before;
2. the Appliance Profiler is replaced by a deterministic step that builds the same appliance profiles from
   the household data;
3. the Conflict Resolver is removed: the Scheduler also receives the Resolver's tools (`sum_load`,
   `detect_conflicts`, `adjust_schedule`) and step budget, and the verification step returns any problem
   to it;
4. everything else is as in iteration 9 (retrieved examples, optimiser tool, completion of missing
   appliances, lean Scheduler and summary).

It is evaluated as an exploratory comparison on the exploratory main set (`configs/iteration10.json`),
interleaved per scenario with `multi_rag_opt` and `multi_lean`, three runs each, so that all three meet the
same API conditions. It is not a confirmatory test, and Q2 is not used for it.

## Note added after the confirmatory run (16 October 2026): design iteration 11, exploratory

This note does not change the registered plan, the analysis code or the registered results.

Every agent prompt asks for a ReAct Thought (one sentence before each tool call), but a trace of the
pipelines showed that GPT-4o-mini, with native tool calling, writes no Thought text before its tool calls:
the reasoning stays implicit, and the recorded trace holds only Actions and Observations. Design iteration 11
(system `multi_duo_thoughts`, flag `thoughts=True` in `hems.agents.multi_agent`) makes the Thought part of the
Action: every tool an agent may call gets a required first argument `thought` (`hems.tools.with_thought`),
which is recorded per agent in the run record (`thoughts`) and dropped before the tool runs, so the tools
answer exactly as before. Each agent's prompt gets one sentence telling it to write its Thought there.
Everything else is the two-agent pipeline of iteration 10.

It is evaluated as an exploratory comparison on the exploratory main set (`configs/iteration11.json`),
interleaved per scenario with `multi_duo`, three runs each, to measure what explicit Thoughts cost (tokens,
latency) and whether the schedules change. It is not a confirmatory test, and Q2 is not used for it.

## Note (16 October 2026): four-agent code removed

After iterations 10 and 11, the code keeps only the two-agent pipeline: the Orchestrator agent and the Scheduler
agent, with the deterministic steps `profile_data` and `verify_schedule` (graph nodes; the
latter was named `verification` in iterations 10 and 11). The flags `lean`, `duo`, `optimizer`, `cost_check` and
`complete_missing`, the Appliance Profiler and Conflict Resolver agents, and the systems `multi`, `multi_v3`,
`multi_rag`, `multi_rag_opt` and `multi_lean` were deleted from `hems.agents.multi_agent`, `hems.agents.prompts`
and `hems.systems`. `multi_duo` and `multi_duo_thoughts` behave exactly as evaluated (same prompts, tools, step
budget of 60, feedback and completion rule); only the node name `verification` became `verify_schedule`. The
recorded results of the removed systems (including `results/confirmation_q2.jsonl`) are kept, and the analysis
code still reads them, but they can no longer be rerun from this version of the code (use the git history).

## Note (16 October 2026): design iteration 12, the Scheduler agent reads the prices

Two changes to the two-agent pipeline (`multi_duo`, `multi_duo_thoughts`), made after testing the demo:

1. The Scheduler agent's prompt now asks it to call `get_spot_prices` once, without arguments, before
   `optimize_schedule`, so that the trace shows the prices the schedule is based on. The tool keeps the
   prices of a run in a cache: a repeated call (for example in a feedback round) returns the same table,
   marked "(cached)". The solver reads the same prices as before.
2. `profile_data` adds a `periods` list to an appliance that has several allowed periods (demo input
   only; every benchmark appliance has one window, so its profile message is unchanged).

Change 1 alters the evaluated pipeline: it adds one tool call and about 500 input tokens per run. The
recorded results of iterations 10 and 11 (`results/iteration10.jsonl`, `results/iteration11.jsonl`) were
produced with the previous prompt and are not comparable with new runs; a rerun is needed before any
result of the two-agent pipeline is reported.

## Note (17 October 2026): one agent in the harness, for comparison (exploratory, not yet run)

The deterministic parts of the two-agent pipeline were moved into a shared module, `hems.agents.harness`
(appliance profiles, the verification check, placing a missing appliance, the cost figures for the message,
running a ReAct agent with recovery). The pipeline's behaviour is unchanged (same prompts, messages and checks;
all tests pass unchanged). A new design, `hems.agents.harness_agent` (systems `single_harness` and
`single_harness_thoughts`), runs one agent inside the same harness: it receives the request and the appliance
profiles, has the Scheduler agent's tools and a step budget of 66 per round (Scheduler 60 + Orchestrator 6),
receives verification feedback in the same conversation (at most 2 rounds) and finally writes the household
message itself, with its conversation in view. It serves the comparison of one agent with two; no campaign has
been run yet. The research questions are to be revised before that comparison is reported.

## Note (19 October 2026): GPT-6 Luna for new runs; design iteration 13, response time

From 19 October 2026 new runs use GPT-6 Luna (`gpt-6-luna`, reasoning effort none, temperature 0;
`hems.agents.llm.DEFAULT_MODEL`). All results recorded before, including the registered Q2 run, used GPT-4o-mini and
stay attributed to it.

Design iteration 13 shortens the response time of both agent designs (two-agent pipeline and single agent in the
harness) without changing what they do:

1. The acting agent makes its first two tool calls in one response: `get_spot_prices` and `optimize_schedule`
   (the solver reads the same prices itself). This removes one model round trip.
2. `get_spot_prices` without arguments returns the whole day in brief (24 hourly means, the four cheapest and
   dearest 15-minute slots, minimum, mean and maximum) instead of 96 rows, which every later model call carried again;
   15-minute prices remain available for a time range.
3. Shorter outputs: the schedule's explanation is limited to one sentence of at most 20 words, each explicit Thought
   to at most 15 words.

A check on three exploratory scenarios (PH03-35, VL02-80, SH05-35; one run each, GPT-6 Luna) gave the same valid,
optimal schedules as before. Two-agent pipeline: 5 to 4 model calls, mean time 12.0 to 8.4 s, input tokens 8,590 to
5,430, cost USD 0.0011 to 0.00075 per run. Single agent: 4 to 3 model calls, mean time 8.3 to 8.3 s (no change on
this small sample), input tokens 11,410 to 7,610, cost USD 0.0013 to 0.0009. Three scenarios with one run each are
too few to estimate the time effect; the campaigns will measure it.

Also from 19 October 2026, campaigns run the agent systems without the household message unless their plan asks
for it (`"message": true`): the message is one more model call and is not scored. Response time and API cost of
new campaigns therefore cover the schedule only, whereas every earlier campaign, including the registered Q2 run,
included the message; the earlier plans now say `"message": true` so that they rerun as before.

## Note (19 October 2026): design iteration 14, fewer tokens; cost of cached input

Design iteration 14 reduces the tokens of both agent designs without changing what they decide:

1. The acting agent's first round offers only the two tools a normal run uses (`get_spot_prices`,
   `optimize_schedule`); the other five tools (`calculate_schedule_cost`, `find_cheapest_window`, `sum_load`,
   `detect_conflicts`, `adjust_schedule`) come with a feedback round. Every tool description is sent with every
   model call. If the solver finds no schedule, the agent returns each appliance at its earliest start and the
   check sends it back with all tools.
2. The worked examples (RAG) leave out their "Pattern" line, which restated the plan's overlaps in prose; two
   examples are still retrieved.
3. The appliance profiles are one line per appliance instead of indented JSON.
4. The agents answer with `FinalSchedule` (start times only) instead of `ScheduleOutput`, whose cost estimate was
   recomputed anyway and whose explanation the household message replaces. The baselines keep `ScheduleOutput`.

The Scheduler's first model call fell from about 2,540 to 1,630 input tokens (SH04-35, counted offline). On the
three check scenarios (one run each, GPT-6 Luna, with the message) both designs gave the same valid, optimal
schedules as in iteration 13; input tokens fell by 26 % (two agents) and 22 % (single agent), and the cost per run
by about 35 %, of which about a third comes from the corrected cost measurement below.

Cost measurement: OpenAI reads a repeated prompt start of at least 1,024 tokens from a cache and charges it at a lower
rate. From 19 October 2026 the cost of a run prices cached input tokens at the cached rate (GPT-6 Luna USD 0.01 per
million, GPT-4o-mini USD 0.075, to be verified on OpenAI's page) and the records carry `tokens_cached`. All earlier
results priced every input token in full and are not recomputed.

The 84 runs on REFIT house 1 (iteration 13) were archived as `results/luna_v2_iter13.jsonl`; the `luna_v2`
campaign starts afresh with iteration 14.

## Note (19 October 2026): defect in the recovery nudge inside the pipelines, found and fixed

The gpt-oss-20b pilot of iteration 14 failed in every run: the model solved the day correctly but wrote its answer as
a Markdown table instead of calling the structured-answer tool, and the recovery nudge did not repair it. Tracing
showed a defect in `hems.agents.errors.invoke_with_recovery`: the nudge was sent alone, relying on the agent's
checkpointed conversation, but inside a LangGraph node (every agent of the pipelines, not the single-agent baseline)
that conversation is not resumed. The model received the nudge without context ("Call the tool now") and could not
answer. Fixed: every nudge now carries the whole conversation so far, on a fresh thread, inside or outside a graph.
With the fix, both agent designs give the optimal schedule on NH04-35 with gpt-oss-20b after one nudge.

Impact on recorded results (runs of agents inside a pipeline that needed a nudge):

- GPT-4o-mini, every file including the registered Q and Q2 runs: 1 to 12 such runs per file, none invalid; the 9 in
  `results/confirmation_q2.jsonl` all reached the optimum. The registered results are unaffected in validity and
  saving; their response time and tokens include the failed nudges.
- gpt-oss-20b, earlier design (`results/runs.jsonl`): 63 of 68 pipeline runs needed a nudge and 52 of them ended
  invalid; the pilots behave the same. The earlier finding that the pipeline worked poorly with gpt-oss-20b is
  therefore largely an artifact of this defect, and the comparison with the single-agent baseline (whose nudge
  worked) was biased against the pipeline. These runs must not be reported as a model result.
- The two gpt-oss-20b runs of the stopped iteration-14 pilot (`results/oss_v2.jsonl`) were made with the defect and
  are removed before the pilot restarts.

## Note (20 October 2026): the LLM without tools in iteration 14; nudge at the step limit

The no-tools baseline (`oneshot`) now (1) answers with the agents' `FinalSchedule` (start times only; the cost
estimate and explanation of `ScheduleOutput` were never scored), (2) receives the price and base-load table as one row
per hour with the four 15-minute values (the same values) and (3) a household text without what does not apply to a
system without tools (tool names, fixed appliances, the windows already stated in the request). Input per model call:
2,165 to 1,532 tokens. The aim is the same answer form as the agents and no irrelevant input, not a better or worse
baseline.

The shared recovery (`hems.agents.errors.invoke_with_recovery`) now also nudges, with the conversation so far, when a
run reaches its step limit without a valid answer (before, the run ended there); the limit of two nudges is unchanged.
It applies to every system and model. In the gpt-oss-20b pilot the baseline wrote its schedule as text and then sent
empty replies until the step limit, so the nudge never fired.

On U-NH04-35: GPT-6 Luna 6 s, 1,487 input tokens, valid; gpt-oss-20b valid after one nudge (it failed in all three
earlier runs on that day), but still 250 s and about 50,000 input tokens, because it reasons at length and loops on
empty replies before the nudge.

The 18 baseline runs of the gpt-oss-20b pilot on v3 were made with the old baseline and moved to
`results/oss_v3_oneshot_before_iter14b.jsonl`; the 36 agent runs of the pilot did not reach the step limit and stay.

Also on 20 October 2026, the baseline's step limit was lowered from 6 to 3 (`oneshot.RECURSION_LIMIT`): a valid
answer needs one step, and a model that writes its schedule as text and then sends empty replies reaches the nudge
after fewer wasted calls. On U-NH04-35, GPT-6 Luna was unchanged (6 s, valid, no nudge); gpt-oss-20b stayed valid
after one nudge with 30,412 instead of 49,950 input tokens, but took 402 s instead of 250 s because it produced more
reasoning output (11,075 against 7,591 tokens) in that single run.
