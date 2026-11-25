# Protocol: a language-model agent as the interface of a home energy gateway

**Title (author's decision, 12 November 2026):** *Small Language Models for Smart Home Energy Management:
Interpreting Household Plans and Configuring an Optimiser on Local Hardware* (4 November: *Small Language Models for
a Home Energy Gateway: ...*) (working title of 3 November: *Design of a
Multi-Agent Home Energy Gateway: Interpreting Household Plans and Configuring an Optimiser*). Research questions
and hypotheses were redesigned around small language models on 4 November (section 2; changes in section 16).

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

Wording shortened on 25 November 2026 (author's decision; same scope, H1-H5 unchanged), as in thesis Section 1.2:

- **RQ:** How can small language models on a home energy gateway reliably interpret household plans and configure
  an optimiser?

Three sub-questions, one per part of the title (reduced from four on 12 November 2026: the old SQ3, checker and
fallback, is now the last part of SQ1; the old SQ4, deployment, is now SQ3):

- **SQ1 (interpreting household plans):** How accurately does a small model turn household plans into optimiser
  requirements, and what do checks and a cloud fallback add?
- **SQ2 (configuring an optimiser):** Can a small model configure the optimiser from the house's history as well
  as a cloud model and better than an automatic tuner?
- **SQ3 (on local hardware):** Does the saving of running the model on the gateway outweigh its cost in time,
  energy, money and privacy?

The small model is compared with the cloud LLM in each sub-question; SQ1 also measures whether the model commits a
plan or asks the household (constraints and the commit-or-ask decision, including changes to a plan) and how often
the household's requirements are then met, and the automatic tuner of SQ2 is deterministic and sees the same history
as the model. The conditions in which interpretation or configuration fails (weather, price pattern, load, plan type)
are reported descriptively under each SQ, and an exploratory comparison of one agent with the four-agent design tests
whether narrow tasks help a small model more than a large one.

Previous wording (18 November 2026): RQ "How can small language models on a home energy gateway reliably interpret
household plans and configure an optimiser, and how close do they come to a cloud language model?"; SQ1 "How
accurately does a small language model turn a household's plans into requirements for the optimiser, and how much do
deterministic checks and a cloud fallback help?"; SQ2 "Can a small language model set up the optimiser from the
house's history as well as a cloud model, and better than an automatic tuner?"; SQ3 "What does running the model on
the gateway cost in time, energy, money and privacy, and does the saving outweigh it?"

**Models.** SLM = open model below about 10 billion parameters (Belcak et al., 2025): Gemma 4 E4B (main
candidate), Qwen3 8B, and one or two more of similar size. Larger local: Qwen3 30B-A3B, gpt-oss-20b. Cloud LLM:
GPT-6 Luna. **Set-ups (SQ1):** SLM alone; SLM + checker; SLM + checker + cloud fallback; LLM alone.
**Prompts (author's decision, 13 November 2026):** the local models use prompt v3 (`pilot.py --prompt v3`, tuned only
on `plans_dev.json`), the cloud LLM keeps prompt v2, on which it did better (0.95 against 0.86 on the pilot plans).
The cloud fallback therefore answers with v2. Both prompts are frozen from here until the held-out run; any further
change is a new design iteration on the development plans only.
**Hardware (author's decision, 11 November 2026, "plan A"):** laptop with RTX 4070 (8 GB) for all runs; for SQ3 the plan benchmark (`prototypes/edge_bench/bench.py`) and the optimiser timing (`mpc_time.py`) are repeated on a Raspberry Pi 5 with 16 GB (low end, comparable with Islam et al., 2025) and a Ryzen 7 mini PC with 32 GB (middle). A 4 GB board (e.g. Arduino UNO Q) can host the control layer, checker and MPC, with the language model on another device.

**Draft hypotheses** (thresholds fixed only at registration, after the exploratory phase):

| | Hypothesis | Test |
|---|---|---|
| H1 (SQ1) | On the held-out plans, the best SLM is within 0.10 of the cloud LLM on constraint recall and decision accuracy (non-inferiority; margin chosen 21 Nov 2026 from `prototypes/heldout/power.py`: 0.05 would need about 390 plans, 0.10 about 100) | paired cluster bootstrap over plans; McNemar on decisions |
| H2 (SQ1) | With the best SLM in closed loop, the household's requirements in the **answer key** (EV energy within 1 kWh by departure, comfort less than 0.5 degree-hours outside the band, away periods, appliance deadlines) are met on more than 90 % of feasible house-days | one-sided exact binomial, p0 = 0.90 (changed from 0.95 on 21 Nov 2026: with at most 80 feasible commit plans among the 120, 0.95 had no slack) |
| H3 (SQ1) | With the checker and the cloud fallback, the SLM's decision accuracy is within 0.10 of the LLM's, and the fallback is used on at most 20 % of plans | paired cluster bootstrap; exact binomial for the fallback share |
| H4 (SQ2) | The SLM-configured MPC costs at most 0.20 EUR per week more than the deterministic auto-tuner (same history, same backtest) and than the LLM-configured MPC (non-inferiority; margin fixed 22 Nov 2026: less than half of the expert setting's 0.45 EUR per week on the main house; power 0.94 over 31 weeks if equal) | paired one-sided Wilcoxon, both comparisons |
| H5 (SQ3) | On each device the p95 of the time per plan is at most 15 minutes (fixed 22 Nov 2026: plans due within 30 minutes go to the fallback, so every plan kept locally is committed at least 15 minutes ahead), plans due sooner go to the fallback, and the yearly saving over rules exceeds the energy and cost of inference | descriptive with measured power; year simulation |

The earlier hypotheses (H1-H6 of 1 November) are replaced; the cost comparison of plain-language vs exact
parameters (old H3) and the default-to-tuned share (old H4a) can be kept as descriptive results.

Holm correction within each SQ. The checker's invariants (grid limit, battery
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
(exploratory) as part of SQ1: four agents against one agent with all tools and against two (Assistant and Configurator).

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
| House | plans (SQ1): `residential4` only, the one OPSD home with a heat pump and an EV (author's decision 21 Nov 2026); configuration (SQ2): `residential4`, `3`, `6` |

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
  home, what they want) on 120 new days of `residential4` (`prototypes/heldout/`), keyed by the author, checked by a second person, registered before any run. Its size
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
for H5; Holm within SQ1 and within SQ2. SQ3 descriptive per factor level. (This paragraph predates the
12 November renumbering; the current mapping is the table in section 2: H1-H3 under SQ1, H4 under SQ2, H5 under SQ3.) Sensitivity: battery size, forecast
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
| Configuration by the agent gives no gain over the auto-tuner | report it (H4); the thesis then rests on SQ1 and SQ3 |
| Local model unreliable or slow (pilot: recall 0.43, about 74 s per plan for gpt-oss-20b) | compare 2-3 local models before registration; fallback to the tuned MPC; compare with cloud |
| Gateway energy use cancels the savings | measure idle and inference energy; two H6 set-ups |
| Plan writers not found in time | start recruiting in week 3; fall back to the author plus a second person, stated as a limitation |
| Scope | Home Assistant replay optional; community coordination stays future work |

## 13. Systematic literature review

Guidelines: Kitchenham and Charters (2007), with backward and forward snowballing (Wohlin, 2014).

**Sources (revised 11 November 2026 for the SLM framing):** Scopus, Web of Science Core Collection, IEEE Xplore and
ScienceDirect (peer-reviewed); arXiv for 2025-2026 preprints, which the databases index poorly; Google Scholar only
for snowballing and grey literature. Years 2022-2026; articles, conference papers and reviews; English.

**Two runs.** Run A (LQ1, LQ2): language models of any size AND home or building energy management. Run B (LQ3):
small or locally run language models AND energy management in general, because studies of small models on edge
hardware rarely name a home energy system. `LLM*` is used only inside a block that is ANDed with an energy block
(alone it also matches law degrees); bare `HEMS` is not used (it also matches helicopter emergency medical services).

Scopus (Advanced search):

```text
Run A
TITLE-ABS-KEY ( ( "large language model*" OR "small language model*" OR LLM* OR "language model agent*"
  OR "language agent*" OR "agentic AI" OR "natural language interface*" )
  AND ( "home energy management" OR "home energy gateway" OR "energy gateway*" OR "smart home*"
  OR "demand response" OR "building energy management" OR "household energy"
  OR ( ( appliance* OR "electric vehicle*" OR "heat pump*" OR batter* OR load* ) W/3 ( schedul* OR control* OR optimi* ) ) ) )
AND PUBYEAR > 2021 AND PUBYEAR < 2027
AND ( LIMIT-TO ( DOCTYPE , "ar" ) OR LIMIT-TO ( DOCTYPE , "cp" ) OR LIMIT-TO ( DOCTYPE , "re" ) )
AND ( LIMIT-TO ( LANGUAGE , "English" ) )

Run B
TITLE-ABS-KEY ( ( "small language model*"
  OR ( ( edge OR "on-device" OR local* OR embedded OR quanti?ed ) W/3 ( "language model*" OR LLM* ) ) )
  AND ( ( ( energy OR electricity OR power ) W/3 ( management OR gateway* OR control* OR system* ) )
  OR "smart home*" OR "smart grid*" ) )
AND PUBYEAR > 2021 AND PUBYEAR < 2027 (same document-type and language limits as run A)
```

Web of Science Core Collection (Advanced Search; then Refine: years 2022-2026, Article, Proceedings Paper, Review
Article, English):

```text
Run A
TS=(("large language model*" OR "small language model*" OR LLM* OR "language model agent*" OR "language agent*"
  OR "agentic AI" OR "natural language interface*")
  AND ("home energy management" OR "home energy gateway" OR "energy gateway*" OR "smart home*" OR "demand response"
  OR "building energy management" OR "household energy"
  OR ((appliance* OR "electric vehicle*" OR "heat pump*" OR batter* OR load*) NEAR/3 (schedul* OR control* OR optimi*))))

Run B
TS=(("small language model*" OR ((edge OR "on-device" OR local* OR embedded OR quanti?ed) NEAR/3 ("language model*" OR LLM*)))
  AND (((energy OR electricity OR power) NEAR/3 (management OR gateway* OR control* OR system*))
  OR "smart home*" OR "smart grid*"))
```

IEEE Xplore (Command Search; filter years 2022-2026):

```text
Run A
("All Metadata":"large language model*" OR "All Metadata":"small language model*" OR "All Metadata":LLM*
  OR "All Metadata":"agentic AI" OR "All Metadata":"language agent*")
AND ("All Metadata":"home energy management" OR "All Metadata":"energy gateway" OR "All Metadata":"smart home*"
  OR "All Metadata":"demand response" OR "All Metadata":"appliance scheduling"
  OR "All Metadata":"building energy management" OR "All Metadata":"electric vehicle charging")

Run B
("All Metadata":"small language model*" OR "All Metadata":"edge LLM*" OR "All Metadata":"on-device LLM*"
  OR "All Metadata":"local LLM*" OR "All Metadata":"quantized language model*")
AND ("All Metadata":"energy management" OR "All Metadata":"smart home*" OR "All Metadata":"smart grid*")
```

ScienceDirect (field "Title, abstract or author-specified keywords"; years 2022-2026; research and review articles).
The field allows at most eight Boolean operators and no wildcards (plurals are matched), so run A is split in two:

```text
Run A1  ("large language model" OR "small language model" OR "LLM agent" OR "agentic AI")
        AND ("home energy management" OR "demand response" OR "smart home" OR "energy gateway")
Run A2  ("large language model" OR "small language model" OR "LLM agent" OR "agentic AI")
        AND ("appliance scheduling" OR "electric vehicle charging" OR "heat pump" OR "building energy management")
Run B   ("small language model" OR "on-device language model" OR "edge LLM" OR "local LLM")
        AND ("energy management" OR "smart home" OR "smart grid")
```

arXiv (Advanced Search, abstracts, 2022-2026; cs, eess and math.OC): run A `"language model"` AND (`"home energy"` OR
`"demand response"` OR `"smart home"` OR `"energy gateway"`); run B `"small language model"` AND `energy`.

Google Scholar (snowballing and grey literature only; first 100 results of each, by relevance):

```text
"small language model" "home energy management"
"large language model" "home energy management" gateway
"language model" "model predictive control" household OR residential
"on-device" OR "edge" "language model" "energy management"
```

**Optional narrowing block** (Scopus and WoS, run A only): `AND ( "model predictive control" OR MPC OR MILP OR
"linear programming" OR optimi?ation OR schedul* )`. Report the counts with and without it; it may drop papers that
use a language model as an interface without naming the solver.

**Inclusion:** I1 2022-2026; I2 residential or behind-the-meter assets (PV, battery, EV, heat pump, appliances), or,
for run B, any energy management system in which a small or locally run language model is evaluated; I3 the
language model interprets requirements, generates constraints, tunes parameters, schedules loads or controls
devices; I4 the system is evaluated. **Exclusion:** E1 grid-scale unit commitment; E2 question answering or bill summaries without control;
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

## 16. Redesign around small language models (4 November 2026)

**Author's decisions.** New title (see the top), RQ and SQ1-SQ4 around small language models (section 2), with the
cloud LLM as the reference and as a fallback. The one-agent vs four-agent comparison stays only if the SLMs allow
it (exploratory, no hypothesis). Hardware: the laptop for all runs; an SQ4 subset on a Jetson Orin Nano if bought.
Method: mixed, a systematic literature review (rigor cycle) inside Design Science Research (Hevner, 2007; Peffers
et al., 2007; FEDS by Venable et al., 2016); review questions LQ1-LQ3 (roles, evaluation, frontier vs small models).

**Design change.** A model layer in the harness runs the local SLM first and calls the cloud LLM only when the SLM's
answer fails validation twice or the checker rejects its plan; the fallback can be switched off (the gateway then
asks the household). New requirement R6: the household's plans stay in the house unless the fallback is needed,
and plan interpretation works without an internet connection.

**Evidence so far.** The plan pilot (section 14) is the "SLM alone" set-up: the small models read plans almost as
well as GPT-6 Luna but are weaker at the commit-or-ask decision (Gemma 4 E4B 0.82, Qwen3 8B 0.68, Luna 0.95).
**Checker rescoring (4 November 2026, `prototypes/plan_pilot/rescore_checker.py`, `out/rescore_checker.json`).** The
stored answers were rescored without calling a model. Checker rules use only the model's output and the car's
charge: an EV item without a target is incomplete; an EV item or appliance window is infeasible when the charger
or cycle cannot meet it before the deadline; comfort min above max is invalid. A flagged answer that the model
would commit becomes a question; with the fallback, GPT-6 Luna's stored answer replaces a flagged or failed answer
and is checked in turn. Decision accuracy (clarification F1), alone / + checker / + checker + fallback, fallback
share: Gemma 4 E4B 0.82 (0.78) / 0.91 (0.90) / 0.91 (0.90), 9 %; Qwen3 8B 0.68 / 0.73 / 0.73, 5 %; gpt-oss-20b
0.59 / 0.46 / 0.77, 36 %; Qwen3 30B-A3B 0.86 / 0.91 / 0.86, 5 %; Luna 0.95 throughout. Gemma's two remaining errors
(X2 away vs comfort, X5 no grid at night) cannot be expressed in the output schema. The fallback can hurt: for
Qwen3 30B-A3B it replaced a failed answer (which would have become a question) with Luna's wrong commit on A3.
Exploratory: the rules were written from the gateway's constraints, not the keys, but tested on the same 22 plans.
**Configurator pilot with SLMs (4-7 November 2026, `out/results_slm.jsonl`; same 8 weeks, settings and gate as the
GPT-6 Luna run; resumed for the last week with `--resume` after the machine slept).** Saving vs default MPC, gap
closed, seconds per week: Gemma 4 E4B 2.85 EUR, 48 %, 44 s (derate 0.8 from week 2; one proposal rejected by the
backtest gate); Qwen3 8B 2.42 EUR, 46 %, about 300 s (derate 0.75-0.9, mostly 20 % reserve; two rejected); GPT-6
Luna 2.82 EUR, 48 %, 16 s; expert setting 2.83 EUR; auto-tuner 0.10 EUR. No failed calls. One run on one house:
the small model can configure the MPC; the cents between Gemma, Luna and the expert cannot rank them.

**Closed-loop pilot (9 November 2026, `prototypes/closed_loop/closed_loop.py`, `out/results.jsonl`; Cycle 2).** The
stored plan-pilot answers go through the checker, an hourly MPC (MILP: comfort band per slot, EV energy by
departure, non-interruptible appliance runs; shortfalls at a penalty) on the weather forecasts, and the control
layer, from the last message to the end of the next day on the real house-days; the key's requirements are judged
on what was executed (EV within 1 kWh by departure, appliance inside its window, < 0.5 degree-hours outside the
band). The 11 "commit" plans only; no model calls. Assumed appliances: dishwasher 1.0 kWh / 2.5 h, washing machine
0.9 kWh / 2 h. Executed / met / asked / extra cost vs exact parameters: exact parameters 11/10/0/0; Gemma 4 E4B,
Qwen3 30B-A3B and GPT-6 Luna 11/10/0/0.00 (identical to the exact parameters on every plan); Qwen3 8B 10/9/1/+1.46
(S2: away turned into a 17-17 C band, cooled and reheated); gpt-oss-20b 0/0/11; rules 11/8/0/+5.56. S5 is missed by
every system: the house cannot cool 1 K in the 1.5 h before midnight (about 2 degree-hours too warm).

**Models for a 4 GB gateway board (10 November 2026).** Gemma 4 E4B (6.6 GB) and Qwen3 8B (5.2 GB) do not fit a 4 GB
board such as the Arduino UNO Q, so three models of 1.4-2.5 GB were run in the plan pilot (laptop GPU, same
settings, 8,000-token cap) and rescored with the checker. Precision / recall / clarification F1 / decision, mean
output tokens and s per plan: Qwen3 4B with reasoning 0.95 / 0.87 / 0.95 / 0.95, about 4,800 tokens, 126 s;
Qwen3 4B instruct (no reasoning) 0.82 / 0.78 / 0.46 / 0.41, about 110 tokens, 2.9 s; Llama 3.2 3B 0.25 / 0.13 /
0.30 / 0.18 (11 of 22 answers failed validation); Qwen3 1.7B 0.52 / 0.52 / 0.29 / 0.32. The checker does not change
Qwen3 4B (0.95). In the closed loop Qwen3 4B met 10 of 11 at zero extra cost (as Gemma); the instruct build, 1.7B
and Llama asked on 9-11 of the 11 plans. Finding: at 4B, commit-or-ask accuracy comes from the reasoning phase,
which costs tens of minutes per plan on a board generating a few tokens a second. Ollama's `qwen3:4b` is the 2507
thinking build: with think=False it still reasons in its answer, so that run was discarded
(`plan_pilot/results_qwen3_4b_think_false_ignored.jsonl`) and `qwen3:4b-instruct` was used instead.

**Edge benchmark set-up (11 November 2026, `prototypes/edge_bench/`).** `bench.py` sends the 22 pilot plans to an
Ollama server on a device (`--host`) and records Ollama's timings per call (load, prefill and generation tokens/s)
plus time per plan, and scores the answers; power is read from a meter (`--idle-w`, `--load-w`). `mpc_time.py`
times the closed-loop MPC on the device. Laptop results: Gemma 4 E4B on the GPU 140 tokens/s, 3.3 s per plan
(3 plans); CPU only, 4 threads, 18 tokens/s, 39 s mean, 72 s p95 (22 plans); MPC 0.08 s mean, 0.12 s p95, 0.49 s
max over 363 solves. The CPU run's decision accuracy was 0.64 against 0.82 on the GPU with nothing else changed:
single runs are noisy, so the registered evaluation repeats each run three times. Raspberry Pi 5 16 GB and Ryzen
mini PC: in process (devices to be bought).

**Search run (11 November 2026; records in `prototypes/slr/out/`, merged by `prototypes/slr/merge.py`).** Scopus
A 543, B 129 (CSV exports with abstracts, via the author's Chrome); ScienceDirect A1 29, A2 34, B 1 (public result
pages); arXiv A 126, B 1 (`prototypes/slr/arxiv_search.py`; search B uses energy-management phrases, because
`energy` alone matched the models' own energy use). Total 863, 732 unique after de-duplication by DOI and title
(`screening.csv`, with empty decision and reason columns). IEEE Xplore was searched (A 301, B 35) but could not be
exported without institutional access; Web of Science could not be searched (personal profile only, no
subscription in the browser). Both are reported as a limitation; Scopus covers most IEEE venues and overlaps with
WoS. Known noise: in Scopus A, `load*` W/3 `control*` matches "cognitive load"; left unchanged and screened out.
Known studies found (sensitivity check): Michelon et al., El Makroum et al., Jonah et al., HEMA, Zhang and Chen,
LLM-MAC; missed: Sanguinetti et al. (abstract says "energy community"), to be caught by snowballing.

**Pre-screening (11 November 2026, `prototypes/slr/prescreen.py`, decisions in `out/screening.csv`).** First pass by
Claude, for the author to check: keyword triage (no language-model and energy terms together: 285 excluded), then
title screening of the remaining records (abstract where unclear). Result: 53 include, 69 unsure (16 of them "LQ3
background": small or local models controlling smart-home devices without an energy objective, e.g. LUMI, AdaHome,
SLB, LLMSwitchBench), 610 exclude (177 outside scope, 58 language-model computing or energy use, 48 grid or market
level, 26 forecasting only, 16 reviews kept as background). Declared in thesis 3.2 (AI-assisted first pass, author
checks every decision, supervisor checks a sample). Next: author's check, then full texts of include and unsure.

**Sub-questions reduced to three (12 November 2026, author's request).** One SQ per part of the title: SQ1
interpreting household plans (now including the checker and the cloud fallback, the old SQ3), SQ2 configuring an
optimiser, SQ3 on local hardware (the old SQ4). Hypotheses keep their content; H3 and H4 swap numbers so they run in
SQ order: H1-H3 under SQ1 (H3 = checker and fallback), H4 under SQ2 (Configurator), H5 under SQ3. Entries above
this note that cite SQ3 or SQ4 use the old numbering.

**Review questions aligned with the sub-questions (12 November 2026, author's request).** LQ1 interpreting household
plans (incl. scheduling and the checks, clarifications and fallbacks around the model; SQ1), LQ2 configuring an
optimiser (SQ2), LQ3 language models on local hardware vs cloud (accuracy, latency, energy, cost, privacy; SQ3).
Evaluation (baselines, metrics, data) is extracted for every study instead of being its own LQ. Searches unchanged:
run A answers LQ1 and LQ2, run B LQ3. Pre-screen reasons written before this date use "LQ2" for evaluation studies.

**Ministral 3 8B (12 November 2026, exploratory, laptop RTX 4070).** `ministral-3:8b` via Ollama (`llm.py` key
`ministral-3-8b`, instruct, no reasoning, cap 8000), plan pilot with function calling and 2 retries: item precision
0.82, recall 0.96, clarification F1 0.57, decision accuracy 0.50, about 7 s and 120 output tokens per plan, no failed
call. It asked on 9 of the 13 commit plans (mostly to confirm the car's charge, which the plan states) and committed
2 ambiguous plans (A2, A6). The checker and fallback change nothing (it never commits a flagged plan). Closed loop: 2
executed and met, 9 asked. All earlier closed-loop rows reproduce exactly. Not yet in the thesis text.

**Prompt v3 (12 November 2026, design iteration, exploratory).** Tuned only on 14 new development plans
(`plans_dev.json`, draft keys); `pilot.py --prompt v3` adds commit-or-ask rules (no EV item unless charge is asked,
never ask about the stated car charge or given values, ask on vague numbers, the EV and appliance feasibility
arithmetic, conflicts) and three worked examples written for the prompt. Dev set, decision accuracy v2 -> v3: Gemma
0.86 -> 0.93, Ministral 0.50 -> 0.79. Tested once on the 22 pilot plans (`results_v3.jsonl`; `rescore_v3.py`, fallback
= Luna's v2 answers). Decision alone / with checker, v2 -> v3: Gemma 4 E4B 0.82/0.91 -> 0.86/0.95 (2 failed calls,
recall 0.91 -> 0.87); Qwen3 8B 0.68/0.73 -> 0.95/1.00 (85 s per plan); Ministral 3 8B 0.50 -> 0.68 (precision 0.81 ->
0.91); Qwen3 4B instruct 0.41 -> 0.50; Llama 3.2 3B worse (19 failed calls); GPT-6 Luna worse, 0.95 -> 0.86 (asks
needlessly on S3, S5, C2). v2 results unchanged in `results.jsonl`; the thesis still reports v2. A prompt per model
family, or v3 for the local models only, would need registering before the held-out run.

**Closed loop with prompt v3 (13 November 2026).** `closed_loop.py --answers results_v3.jsonl --out
out/results_v3.jsonl` (rows for models without v3 answers count as asked and are ignored): Gemma 4 E4B 11 executed,
10 met, +0.00 EUR; Qwen3 8B 11/10, -0.03 (the S2 misreading is gone); Ministral 3 8B 6 executed, 6 met, 5 asked;
Qwen3 4B instruct 2/2; GPT-6 Luna with v3 8/8, 3 asked (not used: the cloud model keeps v2). In thesis 5.4.

**Prompt v3, remaining four models (13 November 2026).** Same command with `--models qwen3-1.7b qwen3-4b gpt-oss-20b
qwen3-30b-a3b --prompt v3`. Precision v2 -> v3 and decision with checker (with fallback): gpt-oss-20b 0.62 -> 0.95,
0.45 -> 0.91 (0.95), 116 -> 65 s per plan; Qwen3 4B 0.95 -> 0.95, 0.95 -> 1.00 (0.95; the fallback replaced one correct
question), 176 s; Qwen3 30B-A3B 1.00 -> 1.00, 0.91 -> 0.91 (0.91), recall 0.96 -> 0.78, 198 s on the CPU; Qwen3 1.7B
0.52 -> 0.76, 0.50 -> 0.64 (0.68), 21 s. Closed loop (`out/results_v3.jsonl`, all ten models): Qwen3 4B 11 executed /
10 met; Qwen3 30B-A3B 10/9, 1 asked (its miss is S5, which the key misses too); gpt-oss-20b 10/7, 1 asked (S4: dropped
the washing machine's earliest start; C2: comfort band without temperatures; both pass the checker); Qwen3 1.7B 8/6,
3 asked, +1.14 EUR. In thesis Table 5.4 and 5.4 text.

**Speed pilot (13 November 2026, development plans only).** `prototypes/plan_pilot/speed_pilot.py` runs prompt v3 on
the 14 dev plans with Ollama overrides (registry unchanged) -> `results_speed.jsonl`. Median s per plan, decision
accuracy. Smaller context window (`num_ctx` 8k/16k instead of 32k; the KV cache no longer pushes layers to the CPU):
Ministral 6.7 -> 3.7 s (outputs identical), Qwen3 8B 46 -> 25 s, Qwen3 4B 101 -> 43 s, gpt-oss-20b 34 -> 30 s, Gemma
4.6 -> 4.6 s (fits already; outputs identical). Reasoning models' outputs differ on 5-7 of 14 plans between the two
settings (decision 0.71 -> 0.86 Qwen3 8B, 0.71 -> 0.93 gpt-oss, 0.79 -> 0.86 Qwen3 4B): run-to-run variation, not a
gain. Reasoning off or low: much faster but worse decisions: Gemma 0.7 s, decision 0.93 -> 0.64; Qwen3 8B 2.2 s, 0.57;
Qwen3 1.7B 1.2 s, precision 0.85 -> 0.48; gpt-oss low 11 s, 0.71. Conclusion: a smaller context is a free speed-up,
the reasoning phase is what buys the decision accuracy. Not adopted; adopting it changes the frozen settings.

**ReAct gateway (13 November 2026, exploratory; status at the end of the day).** Author's decisions of the day:
- Plan calls use a plan-sized Ollama context (8k, 16k with reasoning; `pilot.plan_num_ctx`). One prompt only (no
  v2/v3 versions in code); earlier results archived in `prototypes/plan_pilot/archive/` (README there).
- Model set: Gemma 4 E4B and E2B, Ministral 3 8B and 3B, Nemotron 3 Nano 4B (`nemotron-3-nano:4b`), GPT-6 Luna
  (cloud, fallback). Dropped: Llama 4 (Scout 109B; licence excludes EU-domiciled users of multimodal models), Qwen3
  and gpt-oss, Phi-4-mini and SmolLM3 (no tool calls with the stock Ollama templates; with custom templates,
  `prototypes/react_gateway/*-tools.Modelfile`, they called tools but never planned a schedule on the dev plans).
- New design `prototypes/react_gateway/agent.py`: a ReAct agent reads the household's message and calls tools
  (`get_home_state`, `get_prices`, `get_weather_forecast`, `get_appliances` = measured OPSD cycles from
  `appliance_cycles.py`, `plan_schedule` = deterministic checks + MPC). The model never writes the schedule; the app
  output (one JSON per plan in `out/app/<model>/<plan>.json`: message, decision, message to household, schedule
  with a reason per device, cost and saving, warnings, requirements, hourly timeline, answer key, check, actions)
  shows the last `plan_schedule` result. Rules in code: empty plan refused; usual car settings (80 %, 07:30) fill a
  missing target/time; a car charge that cannot be reached is committed with a warning; a charge allowed to start
  only after its deadline is a conflict; "too warm" counts only while the heat pump heats; clock times without
  am/pm get their next occurrence (`Gateway.next_occurrence`, tested on all 36 keys); vague words are copied into
  `unclear` by the model and become a question; a comfort band without a temperature is a problem.
- Plans rewritten in everyday wording with usual settings (`prototypes/plan_pilot/rewrite_plans.py`; exact-wording
  plans archived). Key changes: X1, X4, DX1 commit with warning; DA1 ("trip on Saturday") commit at 07:30 Saturday;
  DA2 ("washing sometime when cheap") commit within the known prices. Keys are DRAFTS for the author to check.
- Last complete results (before the X3/S5 bug fixes and the `unclear` list; archived in
  `prototypes/react_gateway/out/archive/results_dev_test_before_bugfixes.jsonl`): test plans, decisions right: Luna
  17/22, Gemma 4 E4B 16, E2B 15, Ministral 3B 12, Ministral 8B 10. The 22 test plans have now been inspected in
  detail; changes since then were developed on the dev plans only.
- Interrupted run (laptop off): six models on the dev plans, then the test plans, current code; 39 dev rows saved in
  `prototypes/react_gateway/out/results.jsonl`. Resume (skips finished plans):
  `uv run python prototypes/react_gateway/agent.py --raw-dir D:/Study/my-thesis/data/raw --loop --plans prototypes/plan_pilot/plans_dev.json`
  then the same with `--plans prototypes/plan_pilot/plans.json`; tables with
  `uv run python prototypes/react_gateway/summary.py --plans <plans file>`. Thesis text not yet updated.

**ReAct gateway, final run (14 November 2026, exploratory).** Rules added after the entry above, developed on the dev
plans: one `unclear` list (the model copies vague words, the code asks) instead of a label per item; an appliance
without a deadline runs at the cheapest time within the known prices; prompt rules saying what is NOT unclear (car
request with only a day or no time, appliance without a deadline, vague word made precise with numbers); a provider
`ResponseError` (Ollama's tool-call parser) counts as a failed answer, not a crash. Nemotron 3 Nano 4B added
(reasoning on; turning it off was rejected by the author). Results in `prototypes/react_gateway/out/results.jsonl`,
one run per model. Decisions right, dev / test; test precision / recall, s per plan, met on the real day, failed:
GPT-6 Luna 14/14, 21/22, 1.00/1.00, 6.9 s, 9/12, 0 (USD 0.008 for 22 plans); Gemma 4 E4B 14/14, 19/22, 0.86/0.83,
9.9 s, 9/12, 0; Gemma 4 E2B 13/14, 17/22, 0.67/0.61, 6.8 s, 8/13, 0; Ministral 3 3B 11/14, 15/22, 0.33/0.30, 3.7 s,
4/12, 0; Nemotron 3 Nano 4B 10/14, 12/22, 0.50/0.52, 26.5 s, 2/4, 7 (4 without final answer, 3 parser rejections);
Ministral 3 8B 4/14, 9/22, never called `plan_schedule` on the test plans. Real-day misses of Gemma E4B and Luna: X1,
X4 (warning) and S5 (physics); extra cost vs the key's exact parameters +0.05 EUR (Gemma) and 0.00 (Luna). Two rules
came from test-plan errors (X3 conflict, S5 "too warm" only while heating), so the 22 plans are no longer a clean
test. In thesis Section 5.5 (`sec:reactpilot`, Tables 5.7-5.8); appendix A notes the everyday wording; Abstract,
1.3, 6.1 (SQ1, SQ3, RQ) and Conclusions cite it.
