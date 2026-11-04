# Protocol: a language-model agent as the interface of a home energy gateway

**Working title (author's decision, 3 November 2026):** *Design of a Multi-Agent Home Energy Gateway: Interpreting
Household Plans and Configuring an Optimiser*

Draft, 1 November 2026 (revised after an external review; first reframed 30 October 2026 after the gateway pilot).
Status: plan for discussion with the supervisor for a follow-up thesis; nothing in it is registered. The prototypes
in `prototypes/` are exploratory. Changes from the review are listed in section 15.

## 1. Purpose and framing

**Lesson from the prototypes.** In every setting tried, the household thesis (REFIT appliances), HIPE and OPSD
plant days, and the home gateway (PV, battery, heat pump, EV), an optimiser or a simple tuned rule matched or beat
the language-model agent on cost. In the gateway pilot the agents closed 36-39 % of the gap between rules and
perfect foresight, but model predictive control (MPC) with one fixed setting (plan with 90 % of the PV forecast)
closed 46-51 % (section 14). The agent's cost advantage over default MPC was a tuning effect.

**Reframed problem.** The optimisation is solved; what stops households from using it is everything around it.
An MPC needs an expert to configure it for a house (which loads can move, comfort bands, battery reserve,
forecast caution), it cannot read what the household says ("the car must be full by 7", "we are away until 17",
"guests at 18, make it warm"), it cannot take a change during the day, and it does not explain what it did.

**Artifact.** One artifact, a home energy gateway, with an agent layer of four agents and a deterministic harness.
The *Household Assistant* turns the household's plain-language plan and its changes into constraints; the
*Explainer* words the committed plan as messages and a daily report; the *Monitor* handles EV plug-ins and large
deviations from the plan; the *Configurator* sets the MPC from the house's own history. The *harness* holds the
tools, the tuned MPC, the checker and the control layer with fallback rules, and routes each event to one agent.
It follows the Simplex pattern (Sha, 2001): unverified controllers (the agents) run inside a verified envelope
(checker and control layer) with a safe fallback. The agents can run on a local open-weight model or a cloud model.

**What is new (to be confirmed by the systematic literature review; section 13):**

1. the agent as **configurator** of an MPC: it learns the house's settings from meter and weather history and
   from what the household says, compared with a deterministic auto-tuner using the same history (no
   LLM-tunes-MPC study was found in a first search);
2. the agent as **plan interpreter** in closed-loop control: plain-language plans and changes during the day
   become candidate constraints and a commit decision, checked before execution, for PV, battery, heat pump and
   EV together;
3. evaluation against a **tuned MPC**, not a default one, so that the agent is credited only for what an
   optimiser cannot do;
4. the net energy balance of a local model: inference and idle energy against the energy and cost it saves.

Design Science Research (Hevner et al., 2004; Peffers et al., 2007): build, demonstrate, evaluate, with design
iterations on an exploratory set and a registered confirmation on a held-out set.

**Scope.** Usability is not measured with users. The claim is "without expert configuration, from plain-language
plans written by people other than the author" (section 5), not "usable" in a human-factors sense. A usability
study is future work.

## 2. Research questions and hypotheses (draft)

- **RQ:** How can a language-model agent let a home energy gateway work from the household's plain-language plans
  without expert configuration, by interpreting the plans and configuring and explaining an optimiser, while
  keeping control reliable?
- **SQ1 (interpretation):** How accurately does the agent turn plain-language daily plans and their changes into
  constraints and a commit-or-ask decision, and how often are the household's requirements then met?
- **SQ2 (configuration):** Can the agent configure the MPC from a house's history close to an expert-tuned MPC,
  and does it do better than a deterministic auto-tuner with the same history?
- **SQ3 (reliability and cost):** How often are its plans rejected or overridden by the checker and fallback, what
  does it cost (tokens, time, energy) locally and in the cloud, and does splitting the work into four agents make
  it more reliable, cheaper or faster than one or two agents? (the agent-count part descriptive)
- **SQ4 (conditions):** Under which weather, price patterns, household loads and plan types does interpretation
  or configuration fail? (descriptive)

**Draft hypotheses** (thresholds fixed only at registration, after the exploratory phase):

| | Hypothesis | Test |
|---|---|---|
| H1 | On the held-out plans, constraint item precision and recall are each at least 0.90, and the clarification F1 (asking when, and only when, a question is needed) is at least 0.85 | lower 95 % bound of a cluster bootstrap over plans above the threshold |
| H2 | In closed loop, the household's requirements in the **answer key** (EV energy within 1 kWh by departure, comfort less than 0.5 degree-hours outside the band, away periods, appliance deadlines) are met on at least 95 % of feasible house-days | one-sided exact binomial, p0 = 0.95 |
| H3 | The adjusted cost of a plain-language plan through the agent is non-inferior to the same plan given as exact parameters to the tuned MPC, margin 5 % of the gap between rules and perfect foresight | paired one-sided Wilcoxon |
| H4a | Starting from default settings and using only past weeks, the agent-configured MPC closes at least X % of the gap between default MPC and the tuned MPC (X, for example 70, set at registration) | paired bootstrap 95 % interval of the pooled ratio |
| H4b | The agent-configured MPC is non-inferior to the deterministic auto-tuner (same history, same backtest), margin set at registration | paired one-sided Wilcoxon |
| H5 | The best local model (chosen in the exploratory phase) is within 0.10 absolute of the cloud model's recall and within 5 percentage points of its H2 rate, with a 95th-percentile latency per event under a threshold stated with the hardware | paired McNemar (H2), cluster bootstrap (recall), descriptive latency |
| H6 | The yearly saving over rules exceeds the gateway's own cost in each of two set-ups: (a) low-power gateway with cloud inference (idle power + API fees); (b) gateway plus local inference box (idle power of both + measured inference energy) | year simulation, descriptive with power bounds |

Holm correction within SQ1 (H1-H3) and within SQ2 (H4a-b). The checker's invariants (grid limit, battery
limits) are reported separately as safety checks, expected to be zero violations by construction; they are not a
hypothesis because they test the harness, not the agent.

**Sample size.** Showing a recall of at least 0.90 with a lower bound above 0.90 needs roughly 150-200 constraint
items if the true recall is about 0.95. The held-out plan set is sized by a power calculation at registration.

## 3. System architecture

```
 Household (chat, voice, app): daily plan, changes during the day
        │                                       Cloud model (optional; receives summaries only)
┌───────▼───────────────────────────────────────────────▲──────────────┐
│ Gateway (local device)                                │              │
│  Agent layer (ReAct)   interprets plans, configures the MPC, explains │
│        │ tools                                                        │
│  Harness (deterministic)                                              │
│   - history tools: load runs, comfort, PV vs weather, forecast error │
│   - MPC (tuned LP/MILP from the current state to the horizon)        │
│   - checker: comfort band, EV energy by departure, battery limits,   │
│     grid limit; a plan that fails is never executed                  │
│        │ approved plan                                                │
│  Control layer (deterministic, every 15 min or faster)                │
│   - holds the planned grid exchange (battery absorbs forecast error),│
│     keeps comfort, EV deadline and battery limits; fallback rules    │
│  Device integration (Home Assistant)                                  │
└────┬──────────────┬───────────────┬──────────────┬───────────────────┘
     │ Modbus/SunSpec │ OCPP          │ SG Ready/EEBus│ prices, weather
  PV + battery     EV charger      heat pump        (day-ahead market, DWD/FMI)
```

**Safety rules:** the language model never switches a device; every plan passes the checker; the control layer
keeps comfort, the EV deadline and battery limits whatever the plan says; device protections stay active; if the
agent, the model or the network fails, the control layer falls back to the tuned MPC with default constraints, or
to fixed rules.

**Four agents, one per event.** The harness routes each event to one agent by its type (no orchestrator agent:
routing needs no language model); no agent calls another, and they share state only through the harness.

| Agent | Started by | Job | Needs |
|---|---|---|---|
| Household Assistant | a message from the household | plan or change → constraints, preview, commit or ask | answer within about a minute; private, so a local model |
| Explainer | each commit; once a day | message and daily report from the committed plan's figures | figures must match the plan (checked) |
| Monitor | an EV plug-in; a deviation raised by the control layer | finds the cause (forecast error, unexpected load, late car), adjusts constraints within what the household said, or alerts | must never remove a household requirement |
| Configurator | once a week | MPC settings from history, backtested | analytical, may take minutes; may use a larger model |

Why more than two: each agent has its own trigger, inputs, tools and output, so prompts stay small and each output
is checked on its own (constraints by the checker, messages against the plan's figures, settings by backtest). The
household thesis found that splitting *one* task between agents added cost without reliability; here the agents do
different tasks at different times, so cost grows with the number of events, not agents. The agent count is tested
as part of SQ3: four agents against one agent with all tools and against two (Assistant and Configurator).

**Household Assistant tools:**

| Tool | Returns |
|---|---|
| `read_plan` | the household's plan text and any changes received |
| `get_situation` | time, indoor temperature, battery charge, EV status and charge, forecast error so far, active constraints |
| `get_forecast` | hourly PV, load, heat demand and prices, with the day's weather class and expected forecast error |
| `propose_constraints(items)` | EV energy and departure, comfort bands by time, away periods, appliance windows; validated ranges |
| `preview_plan` | the tuned-MPC plan with the proposed constraints and the checker's violations (including infeasible requests) |
| `ask_household(question)` | a queued question, only for ambiguity, conflict or infeasibility |
| Final answer `AssistantDecision` | `commit` (true or false), candidate constraints, message to the household; commit only if the checker passes |

Feasibility (for example more energy than the charger can deliver before departure) is computed by the checker
through `preview_plan`, not by the language model.

**Explainer tools:** `explain_plan` (the committed plan's figures, pre-computed: when each device runs, cost against
rules, EV energy by departure, comfort, what changed and why) and `get_situation` (the day so far). Final answer
`HouseholdMessage`: text plus the figures it cites; every cited figure is compared with the plan, and a mismatch
sends a fixed template instead.

**Monitor tools:** `get_situation` (the event, forecast error so far, battery and EV state, active constraints),
`get_forecast`, `propose_constraints` and `preview_plan`. Final answer `MonitorDecision`: no action, commit adjusted
constraints, or alert the household with a reason (sent through the Explainer). The control layer raises a
deviation when the grid exchange or a requirement drifts past a threshold set in the exploratory phase.

**Configurator tools:** `history_summary(item)` (loads, EV, comfort, PV vs weather, forecast error) and
`backtest(settings, weeks)`. Final answer `MpcSettings`: PV derating by weather class and battery reserve
(the confirmatory scope), plus default comfort bands and flexible-load windows (exploratory). Applied only if the
backtest on past weeks beats the current settings.

**Checkpoints:** start of day, each plan change from the household, each EV plug-in, and a deviation trigger.
Between checkpoints the tuned MPC replans hourly on its own; the agent is not in that loop.

## 4. Data

| Data | Source | Licence | Use |
|---|---|---|---|
| PV, grid, heat pump, EV, appliances, 15 min | OPSD Household data 2020-04-15 (CoSSMic, Konstanz), sites `residential1`-`6` (`residential4`: PV, heat pump, EV, dishwasher, washing machine; no dryer) | CC BY 4.0 | house-days, appliance cycle lengths |
| Weather, hourly | DWD station 02712 Konstanz: air temperature (`TU`, 1971-2025), global radiation (`ST`, 1977-Sep 2026), UTC; Oct 2015-May 2019 0.2-0.3 % of hours missing; global radiation correlates 0.95 hourly and 0.97 daily with `residential4` PV in 2016 | DWD open data (CC BY 4.0) | weather classes, forecast models |
| German day-ahead prices | Energy-Charts API (Fraunhofer ISE; Bundesnetzagentur / SMARD): DE-AT-LU to 30 Sep 2018, DE-LU from 1 Oct 2018; hourly Oct 2015-May 2019, two hours missing at the zone change; 97 negative hours in 2016 | CC BY 4.0 | spot component of the import price |
| German household tariff 2016 | BDEW-Strompreisanalyse Dec 2023: 28.80 ct/kWh = procurement and sales 6.26, grid fee 7.01, concession fee 1.66, EEG surcharge 6.354, other levies 0.866, electricity tax 2.05, VAT 4.60; dynamic tariff = (spot + margin + 17.94) x 1.19 | n/a | import price (a counterfactual dynamic tariff) |
| Feed-in tariff | EEG rooftop PV up to 10 kWp from Nov 2015: 12.31 ct/kWh (municipal and industry tables; to be checked against the Bundesnetzagentur table) | n/a | export price |
| Heat pump efficiency | When2Heat (OPSD 2023-07-27), Germany | CC BY 4.0 | heat demand from measured electricity |
| EV sessions (optional) | Norwegian residential sessions (Sørensen et al., 2024) | CC BY 4.0 | plug-in and departure times |
| Battery, charger, heat pump limits | product data sheets | n/a | model parameters (to be cited) |

## 5. Benchmark

**Unit:** a house-day (24 h at 15 min) with a plain-language plan and, where the design calls for it, a change
during the day. Every plan is bound to a real date of the house (season, weather, prices), so H2 can be scored in
closed loop. Battery and indoor temperature start at reference values; the state left at midnight is valued in
the cost.

**Factorial design:**

| Factor | Levels |
|---|---|
| Plan type | structured parameters; plain language; plain language with a change during the day; ambiguous; conflicting or infeasible |
| Weather | sunny, variable, overcast (DWD radiation); cold, mild, warm (DWD temperature) |
| Price pattern | flat, evening peak, volatile (including negative prices) |
| Load | base, + heat pump, + heat pump + EV |
| House | several OPSD homes (configuration is learned per house) |

**Answer-key rules** (from the review, adopted 1 Nov 2026):

1. A request that the charger or the house cannot meet (for example 25 kWh between 23:30 and 05:00 at 3.7 kW,
   at most 20.35 kWh) is a *conflicting or infeasible* plan: the expected decision is keep-and-ask.
2. After a change during the day, the key holds only requirements still in force from the change on; completed
   items are dropped. A period that has already started is scored from the time of the change.
3. Candidate constraints and the commit decision are scored separately: on an ambiguous or conflicting plan the
   agent must not commit, but the clear parts of the plan still count towards precision and recall.
4. An away period is recorded as such; the gateway applies the house's setback (17 °C minimum unless the
   household names another temperature). A comfort band is expected only when the household names a temperature.
5. Times are absolute date-times; appliance cycle lengths come from the house's measured cycles; only
   appliances the house has are used.

**Who writes the plans.**

- *Edge-case pilot set* (exploratory): 22 plans in `prototypes/plan_pilot/plans.json`, based on the review's 20
  edge cases plus two restored cases (a weekend away and a "no grid tonight" conflict). Written by language models,
  keyed by the author.
- *Exploratory set* (about 100 house-days) for design iterations.
- *Held-out set*: plans written by 3-5 people other than the author from scenario prompts (the house-day, who is
  home, what they want), keyed by the author, checked by a second person, registered before any run. Its size
  follows the power calculation in section 2.

## 6. Systems compared

All systems use the same house-days, forecasts, plans and control layer.

| Level | System |
|---|---|
| Lower bound | as recorded |
| Products | self-consumption battery; evcc-style EV + SG Ready + battery rules; EMHASS (REST) with the shared forecasts (primary) and with its default forecasts (secondary, as deployed) |
| Optimiser, default | MPC hourly, default settings, plan given as exact parameters |
| **Optimiser, tuned** | MPC hourly with settings tuned once by grid search on the exploratory set and frozen (the expert configuration), plan given as exact parameters |
| **Auto-tuner** | MPC whose settings a deterministic script chooses each week by grid search with `backtest` on the house's past weeks (the non-LLM baseline for SQ2) |
| AI without tools | language model reading the plan and data, writing the schedule itself |
| **Agent** | Assistant interprets the plan; Configurator sets the MPC from defaults using past weeks only (cloud model; best local model) |
| Ablations | one agent with all tools; two agents (Assistant and Configurator, the Explainer's and Monitor's jobs folded in); agents without the checker (scored, never executed); no Monitor (deviations left to the MPC); Assistant only (tuned settings, no Configurator) |
| Upper bound | perfect foresight with the exact plan |

The tuned MPC with exact parameters is the cost reference: the agent is expected to match it, not beat it, while
starting from plain language and no expert configuration. The Configurator learns from the same house's past, so
it may exceed the reference tuned on other house-days; H4a allows that.

## 7. Metrics

| Goal | Metric |
|---|---|
| Interpretation | item precision and recall against the answer key (cluster bootstrap over plans); clarification precision, recall and F1; commit-decision accuracy |
| Requirements met | against the answer key: comfort degree-hours outside the bands; EV energy delivered by departure; away periods honoured; appliance deadlines |
| Safety invariants | grid-limit and battery-limit violations after the checker (expected zero) |
| Configuration | agent-configured MPC saving as a share of the tuned MPC's saving over default MPC; difference to the auto-tuner |
| Cost | adjusted cost (net cost minus the value of battery charge and stored heat left at midnight); gap closed between rules and perfect foresight, pooled |
| Solar use, grid | self-consumption %, self-sufficiency %, peak import |
| Reliability | plans rejected by the checker; fallbacks used; failed model calls; retries |
| Cost of the AI | tokens, USD; mean and 95th-percentile latency per event; Wh per event and per house-day (GPU power with `nvidia-smi`); idle power of gateway and inference box |
| Explanation | share of messages whose cited figures match the plan; template fallbacks |
| Monitoring | deviations handled; requirements kept after a Monitor adjustment; unnecessary alerts |
| Agent design | the reliability and cost metrics above for four, two and one agents on the same events |

## 8. Procedure

1. Systematic literature review (section 13).
2. Build: house-days, weather classes, forecasts, plans and answer keys, systems, tuned-MPC grid search, auto-tuner.
3. Exploratory phase: agent design iterations (prompt, tools, checkpoints) on the exploratory set only; compare
   2-3 local models and choose one for H5.
4. Registration: freeze code, prompts, tools, models, tuned MPC settings, held-out set, hypotheses, thresholds,
   sample size, analysis.
5. Confirmation: every system on the held-out set (LLM systems 3 runs per house-day, temperature 0).
6. Year simulation of the best systems for annual EUR, kWh and the two H6 set-ups.
7. Optional: replay of a recorded day with a plan change in Home Assistant with simulated devices (a script, not
   a deployed integration).

## 9. Analysis

Cluster bootstrap over plans for H1 (items within a plan are not independent); one-sided exact binomial for H2;
paired one-sided Wilcoxon non-inferiority for H3 and H4b; paired bootstrap for H4a; McNemar and cluster bootstrap
for H5; Holm within SQ1 and within SQ2. SQ4 descriptive per factor level. Sensitivity: battery size, forecast
error, tariff with and without a power charge, charging losses.

## 10. Validity

| Threat | Handling |
|---|---|
| Plans written by the author or by a language model | held-out plans written by 3-5 other people, keyed before any run, second-person check, registered; the LLM-written edge-case set is exploratory only |
| Tuned MPC tuned on the evaluation days | tuned once on the exploratory set and frozen; Configurator and auto-tuner use only past weeks |
| H2 passing by construction | scored against the answer key's requirements, not the agent's own constraints; safety invariants reported apart |
| An LLM is not needed for configuration | deterministic auto-tuner baseline (H4b) |
| Synthetic forecast errors | fitted to published accuracy; forecast quality as a sensitivity factor |
| EMHASS disadvantaged by its forecasts | EMHASS with the shared forecasts as the primary comparison |
| Mixed sources (house, weather, prices) | same real dates and place (Konstanz); counterfactual dynamic tariff stated as such |
| No human participants | claim limited to "without expert configuration"; usability study as future work |
| Simulation only | optional Home Assistant replay; field study as future work |
| LLM non-determinism | 3 runs per house-day |

## 11. Work plan (about 20 weeks)

| Phase | Weeks | Output |
|---|---|---|
| Systematic literature review | 1-3 | gap statement |
| House-days, weather classes, tariffs | 2-4 | exploratory and held-out sets |
| Plans and answer keys (edge cases, exploratory; recruit 3-5 plan writers for held-out) | 3-6 | plan benchmark |
| Systems incl. tuned MPC, auto-tuner and EMHASS | 4-8 | systems registry |
| Agent tools, design iterations, local-model choice | 8-11 | design iterations |
| Registration and held-out run | 12-13 | confirmation results |
| Year simulation, energy balance, optional replay | 13-15 | H6 |
| Writing | 13-20 | thesis |

## 12. Risks

| Risk | Mitigation |
|---|---|
| Interpretation is easy for modern models (ceiling effect) | changes during the day, ambiguous, conflicting and infeasible requests; plans by other people; measure clarification F1 |
| Configuration by the agent gives no gain over the auto-tuner | report it (H4b); the thesis then rests on SQ1 and SQ3 |
| Local model unreliable or slow (pilot: recall 0.43, about 74 s per plan for gpt-oss-20b) | compare 2-3 local models before registration; fallback to the tuned MPC; compare with cloud |
| Gateway energy use cancels the savings | measure idle and inference energy; two H6 set-ups |
| Plan writers not found in time | start recruiting in week 3; fall back to the author plus a second person, stated as a limitation |
| Scope | Home Assistant replay optional; community coordination stays future work |

## 13. Systematic literature review

Guidelines: Kitchenham and Charters (2007), with backward and forward snowballing (Wohlin, 2014).

**Sources:** Scopus and Web of Science (peer-reviewed), plus arXiv and Google Scholar for 2025-2026 preprints, which
Scopus indexes poorly.

**Search string** (`TITLE-ABS-KEY`, Scopus syntax):

```text
( "home energy management" OR "smart home energy" OR "residential demand response"
  OR "building energy management" OR "home energy gateway" OR ( "HEMS" AND ( energy OR electricity ) ) )
AND
( "large language model*" OR "LLM-based" OR "language model agent*" OR "agentic" OR "ReAct"
  OR "natural language interface*" OR "foundation model*" )
[ AND ( "model predictive control" OR "MILP" OR "linear programming" OR "optimi*ation" OR "scheduling" ) ]
```

Run with and without the bracketed third block and report both counts (the third block may drop papers that use
an LLM as an interface without naming the solver). `"HEMS"` alone also matches helicopter emergency medical
services; `"LLM*"` alone also matches law degrees.

**Inclusion:** I1 2022-2026; I2 residential or behind-the-meter assets (PV, battery, EV, heat pump, appliances);
I3 the LLM generates constraints, tunes parameters, schedules loads or controls devices; I4 the system is
evaluated. **Exclusion:** E1 grid-scale unit commitment; E2 question answering or bill summaries without control;
E3 non-English. Preprints are included and quality-assessed separately.

**Related streams to cover:**

- natural language to optimisation models: NL4Opt competition (Ramamonjison et al., 2022); OptiMUS
  (AhmadiTeshnizi et al., ICML 2024); Chain-of-Experts (Xiao et al., ICLR 2024; to be checked before citing);
- LLMs in home and building energy control: Sanguinetti et al. (2025); Michelon et al. (ACM e-Energy 2025);
  El Makroum et al. (2025); Jonah et al. (2026); HEMA (arXiv 2602.15219); AgentiControl-MPC and AutoControl-MPC
  (2026); LLM-supervised HVAC control and reward-weight tuning (Energies 2025; Building Simulation 2026; review
  arXiv 2609.05314);
- safety envelopes for learning controllers: Simplex architecture (Sha, 2001) and runtime assurance;
- MPC versus rules in homes and PV forecast error: Seal et al. (2019); arXiv 1906.09902; Elkazaz et al.
  (Energies 2020); Nair et al. (IEEE TEC 2021); Antonanzas et al. (2016); Skoplaki and Palyvos (2009);
- products: EMHASS, evcc, SEM for Home Assistant.

## 14. Evidence from the prototypes (30 October - 1 November 2026)

- `prototypes/home_gateway/twin.py`, OPSD `residential4`, 2016 with a virtual 10 kWh / 5 kW battery, perfect
  foresight, saving against the recorded year: Finnish prices (307 days) battery 118, rules 121, optimum 174
  EUR; German prices with feed-in (363 days) 223, 217, 311 EUR; German prices with spot export (364 days) 370,
  391, 484 EUR.
- `prototypes/home_gateway/gateway.py`, German setup (`--market de --forecast weather`), 12 sample days, share of
  the rules-to-optimum gap closed: day-ahead 19 %, default MPC at checkpoints 23 %, default MPC hourly 31 %,
  agent GPT-6 Luna 36 %, agent gpt-oss-20b local 39 %, **MPC with PV derating 0.9: 46 % at checkpoints, 51 %
  hourly** (0.8: 45 % and 49 %). The agents' gain over default MPC came from derating the PV forecast; a fixed
  setting does it better. GPT-6 Luna: 63 checks, 0 errors, USD 0.025 for 12 days; gpt-oss-20b: 63 checks,
  3 failed calls caught by the fallback, 152 s per day.
- `prototypes/plan_pilot/` (first version, 20 draft plans, archived in `results_v1.jsonl`): GPT-6 Luna with
  function calling and two validation retries reached item precision 1.00, recall 0.95, clarification recall
  0.89; gpt-oss-20b with the same settings 0.69, 0.43 and 0.78, 17 of 20 answers valid, about 74 s per plan. The
  second version (22 plans, commit decision, plans bound to dates, answer-key rules of section 5; run 3 Nov 2026,
  function calling, two retries, `results.jsonl`): GPT-6 Luna precision 1.00, recall 1.00, clarification F1 0.95,
  decision accuracy 0.95, 2.7 s and USD 0.003 for all 22 (one error: A3, it invented an 18:00 departure and
  committed); gpt-oss-20b precision 0.63, recall 0.44, clarification F1 0.75, decision accuracy 0.59, 116 s per
  plan, 4 invalid answers (it still leaves numbers such as the EV target out). Scores after adding the away period
  to the X3 key (the trip 08:00-17:00 that Luna had extracted); the stored outputs were rescored, not rerun. Keys
  still drafts. Local models qwen3:8b, gemma4:e4b and qwen3:30b-a3b (same settings, running since 3 Nov 2026):
  their output is capped at 8,000 tokens per call (`ModelSpec.ollama_num_predict`, set 4 Nov 2026) after qwen3:8b
  looped in its reasoning phase for 37,000+ tokens on plan A6; a capped call is scored as a failed answer and not
  retried. GPT-6 Luna and gpt-oss-20b ran without a cap (they stayed far below it). No call hit the cap.
  qwen3:30b-a3b failed to start on the 8 GB GPU (CUDA out of memory; those 22 rows are in
  `results_qwen30b_oom.jsonl`) and ran CPU-only (`ModelSpec.ollama_num_gpu=0`). Results (precision, recall,
  clarification F1, decision accuracy, s per plan): qwen3:8b 0.96, 1.00, 0.67, 0.68, 71 s; gemma4:e4b 1.00, 0.91,
  0.78, 0.82, 7.7 s; qwen3:30b-a3b (CPU) 1.00, 0.96, 0.84, 0.86, 150 s. Candidates for H5: gemma4:e4b (speed) and
  qwen3:30b-a3b (accuracy).
- `prototypes/configurator_pilot/` (3 Nov 2026, 8 weeks March-April 2016, German setup, checkpoint MPC, one run):
  saving against default MPC: expert setting tuned on four September weeks (derate 0.7) 2.83 EUR, Configurator agent
  (GPT-6 Luna, two weeks of history, backtest tool) 2.82 EUR, deterministic auto-tuner (best grid point on the same
  two weeks) 0.10 EUR; perfect foresight 14.45 EUR. The auto-tuner overfits two weeks (jumps between 0.6 and 0.9);
  the agent stayed between 0.75 and 0.9. USD 0.003, about 16 s and 5 tool calls per week. A setting tuned on a single
  other week was worse than the default, so the earlier "derate 0.9" result was partly tuning on the same days.
- Weather: the PV model fitted to DWD radiation reproduces `residential4` PV with r = 0.96 hourly and 0.98
  daily; overcast, variable and sunny days average 16.1, 31.6 and 43.6 kWh of PV.
- Other prototypes (background, not design cycles of the gateway): `prototypes/hipe/` (HIPE plant days) and
  `prototypes/opsd/` (OPSD `industrial3`): the agents and the smart timer reached the MILP optimum on every day;
  `prototypes/heatpump/` (REFIT + When2Heat + Norwegian EV sessions).
- Not yet built: exploratory and held-out plans, `history_summary` / `propose_constraints` / `preview_plan` /
  `backtest` tools, the tuned-MPC grid search, the auto-tuner, EMHASS in this setting, inference-energy logging.

**Design Science cycles.** Cycle 1 (done): the gateway pilot and the plan pilot. Cycle 2 (weeks 4-11): tools and
design iterations on the exploratory set. Cycle 3 (weeks 12-15): registered held-out evaluation and year
simulation.

## 15. Changes after the external review (1 November 2026)

Adopted: claim limited to "without expert configuration" and held-out plans written by 3-5 other people; SQ2
kept confirmatory but limited to PV derating and battery reserve, with a deterministic auto-tuner baseline (H4b);
Home Assistant demo made an optional replay; EMHASS with shared forecasts as primary; clarification F1 and
commit-decision accuracy in H1 with a cluster bootstrap and a power calculation; H2 scored against the answer key,
grid and battery limits moved to safety invariants; H3 margin as 5 % of the rules-to-optimum gap; H5 with 2-3
local models, absolute margins and p95 latency; H6 with two hardware set-ups; one artifact (agent layer plus
harness) with ablations; the Simplex framing; the SLR protocol (section 13); the answer-key rules and the revised pilot
plans (section 5). Not adopted: three separate artifacts; `"HEMS"` and `"LLM*"` as bare search terms; a
"Zhang et al." LLM-MPC-tuning citation (not found); the RPi 5 and 15 W mini-PC as local-inference bounds; clock
times without dates; a dryer, which the main house does not have.

**Four agents (author's decision, 1 November 2026).** The two-agent design (Assistant, Configurator) became four
agents: the Explainer (messages and daily report, checked against the plan's figures) and the Monitor (EV plug-ins
and deviations raised by the control layer) were split out. Routing stays deterministic (no orchestrator agent).
The agent count is part of SQ3, with one-agent and two-agent ablations on the same events.
