# Protocol: an agentic home energy gateway for PV, battery, heat pump and EV

Draft, 30 October 2026. Status: plan for discussion with the supervisor. Nothing in it is registered; the
prototypes in `prototypes/home_gateway/` are exploratory.

## 1. Purpose

**Problem.** A home with rooftop PV, a battery, a heat pump and an EV charger can save money and use more of
its own solar power if the devices are planned together against dynamic prices and the weather. The tools that
exist today either follow fixed rules (self-consumption battery mode, evcc-style solar charging, SG Ready boost)
or need expert configuration (EMHASS, model predictive control). Households describe their day in plain words
("the car must be full by 7", "we are away until 17"), forecasts are wrong, and nobody explains what the system
did.

**Artifact.** A home energy gateway in which a ReAct language-model agent plans and replans the day from
forecasts, measurements and the household's daily plan, while a deterministic harness does the arithmetic and
the optimisation, checks every plan, and a control layer with fallback rules executes it. The agent can run on
a local open-weight model or a cloud model.

**What is new (to be confirmed by a systematic literature search; see section 13):**

1. the agent turns a plain-language daily plan into constraints and replans during the day under forecast
   error, instead of answering once with perfect information;
2. closed-loop control with an independent checker and fallback rules for PV, battery, heat pump and EV
   together, evaluated over real household data against EMHASS, rule-based products and model predictive
   control;
3. the net energy balance of a local model: inference and idle energy against the energy and cost it saves.

Design Science Research, as in the household thesis: build, demonstrate, evaluate, with design iterations on an
exploratory set and a registered confirmation on a held-out set.

## 2. Research questions (draft)

- **RQ:** How can a ReAct agent layer in a home energy gateway plan and replan PV, battery, heat pump and EV
  charging so that the household's daily plan is met reliably and electricity cost falls?
- **SQ1 (value):** How much does the agent save, and how reliably does it meet comfort and EV needs, compared
  with the rules households can install, EMHASS and model predictive control?
- **SQ2 (conditions):** Under which weather, price patterns, household loads and plan types does the agent pay
  off?
- **SQ3 (understanding):** How accurately does the agent turn plain-language daily plans into constraints?
- **SQ4 (local or cloud):** Is a locally installed open-weight model as reliable as a cloud model, and does the
  gateway save more energy than it uses?

**Draft hypotheses** (fixed only at registration, after the exploratory phase):

| | Hypothesis | Test |
|---|---|---|
| H1 | The agent's adjusted cost is lower than the rules' | one-sided paired Wilcoxon, house-days |
| H2 | The agent closes at least as much of the rules-to-optimum gap as model predictive control at the same checkpoints | paired Wilcoxon, non-inferiority margin set at registration |
| H3 | The agent meets every comfort and EV requirement in at least 95 % of house-days | exact binomial |
| H4 | Constraint recall from plain-language plans is at least 0.9 | one-sided test on the pooled proportion |
| H5 | The local model's adjusted cost is within the H2 margin of the cloud model's | paired Wilcoxon |
| H6 | The gateway's yearly energy saving exceeds its own consumption (gateway idle + inference) | year simulation, descriptive |

Holm correction within the SQ1 family (H1-H3), as in the household thesis.

## 3. System architecture

```
 Household (chat, voice, app): daily plan, changes during the day
        │                                       Cloud model (optional; receives summaries only)
┌───────▼───────────────────────────────────────────────▲──────────────┐
│ Gateway (local device)                                │              │
│  Agent layer (ReAct)   reads the situation, chooses planner settings, │
│                        commits or keeps a plan, explains              │
│        │ tools                                                        │
│  Harness (deterministic)                                              │
│   - forecasts: PV, household load, heat demand, prices               │
│   - optimiser: LP/MILP from the current state to the horizon         │
│   - checker: comfort band, EV energy by departure, battery limits,   │
│     grid limit; a plan that fails is never executed                  │
│        │ approved plan                                                │
│  Control layer (deterministic, every 15 min or faster)                │
│   - follows the plan; keeps comfort, EV deadline and battery limits  │
│     with fallback rules if there is no valid plan                    │
│  Device integration (Home Assistant)                                  │
└────┬──────────────┬───────────────┬──────────────┬───────────────────┘
     │ Modbus/SunSpec │ OCPP          │ SG Ready/EEBus│ prices, weather
  PV + battery     EV charger      heat pump        (day-ahead market, DWD/FMI)
```

**Safety rules (non-negotiable):** the language model never switches a device; every plan passes the checker;
the control layer keeps comfort, the EV deadline and battery limits whatever the plan says; device protections
(battery management, heat pump controller, charger current limit) stay active; if the agent, the model or the
network fails, the control layer falls back to fixed rules.

**Agent tools (as in the prototype, extended):**

| Tool | Returns |
|---|---|
| `get_situation` | time, indoor temperature, battery charge, EV status, forecast error so far |
| `get_forecast` | hourly PV, load, heat demand and prices for the rest of the horizon |
| `read_plan` | the household's daily plan and changes |
| `optimize_plan(settings)` | the cheapest plan with the agent's settings: PV forecast derating, battery reserve, comfort band, grid limit, EV target and departure |
| `check_plan` | violations of the last computed plan |
| `explain_plan` | cost, comfort and EV figures of the committed plan for the household message |

**Checkpoints:** 00:00, 06:00, 12:00, 18:00, each EV plug-in, each change of the daily plan, and when the
measured PV or load deviates from the forecast by more than a threshold (set in the exploratory phase).

## 4. Data

| Data | Source | Licence | Use |
|---|---|---|---|
| PV, grid, heat pump, EV, appliances, 15 min | OPSD Household data 2020-04-15 (CoSSMic, Konstanz), sites `residential1`-`6` (`residential4`: PV, heat pump, EV) | CC BY 4.0 | house-days |
| Weather, hourly | DWD station 02712 Konstanz: air temperature (`TU`, 1971-2025), global radiation (`ST`, 1977-Sep 2026), timestamps UTC; for Oct 2015-May 2019 0.2-0.3 % of hours missing; global radiation correlates 0.95 (hourly) and 0.97 (daily) with `residential4` PV in 2016 | DWD open data (CC BY 4.0) | day classes, forecasts, heat demand check |
| German day-ahead prices | Energy-Charts API (Fraunhofer ISE; data Bundesnetzagentur / SMARD): DE-AT-LU to 30 Sep 2018, DE-LU from 1 Oct 2018; hourly, Oct 2015-May 2019, two hours missing at the zone change; 97 negative hours in 2016 | CC BY 4.0 | spot component of the import price and export value |
| Heat pump efficiency | When2Heat (OPSD 2023-07-27), Germany | CC BY 4.0 | heat demand from measured electricity |
| Finnish prices (comparison only) | Nord Pool FI via Elering, same dates | Elering terms | comparability with the household thesis |
| German household tariff | spot plus the fixed parts of the German household price of the year (grid fee, EEG surcharge, taxes, VAT 19 %), and the EEG feed-in tariff for export; values to be taken from BDEW / Bundesnetzagentur | n/a | import and export price (dynamic tariffs were rare in Germany in 2016, so this is a counterfactual tariff) |
| EV sessions (optional) | Norwegian residential sessions (Sørensen et al., 2024) | CC BY 4.0 | plug-in and departure times |
| Appliance cycles (optional) | REFIT | CC BY 4.0 | shiftable appliances |
| Battery, charger, heat pump limits | product data sheets | n/a | model parameters (to be cited) |

Processing: cumulative meter readings differenced to kW; days with missing data or fewer than 23 hourly prices
dropped; DST days dropped; everything at 15-min resolution in local time.

## 5. Benchmark

**Unit:** a house-day (24 h at 15 min), with the battery and indoor temperature at reference values at the start
and the state left at the end valued in the cost (section 7).

**Factorial design:**

| Factor | Levels |
|---|---|
| Weather | sunny, variable, overcast (DWD radiation); cold, mild, warm (DWD temperature) |
| Price pattern | flat, evening peak, volatile |
| Load | base, + heat pump, + heat pump + EV |
| Daily plan | structured, plain language, plain language with a change during the day |
| Forecast quality | realistic (fitted to published PV and temperature forecast errors); poor (sensitivity only) |

**Sets:** an exploratory set (about 100 house-days, all factor combinations represented) for design iterations;
a held-out set of the same design and size, built from other dates and houses, run once after registration.

**Daily plans:** for each house-day a plain-language plan written before any system is run, with an answer key
of the constraints it implies (EV energy and departure, comfort bands by time, away periods, appliance
windows). A second person checks the answer keys. Plans with a change during the day state when the household
sends the change.

## 6. Systems compared

All systems use the same house-days, forecasts, plan texts and control layer.

| Level | System |
|---|---|
| Lower bound | as recorded (no battery, no control) |
| Products | battery in self-consumption mode; evcc-style EV + SG Ready heat pump + self-consumption battery; EMHASS (REST, default settings, as in the household thesis) |
| Classical | day-ahead LP; model predictive control hourly; model predictive control at the agent's checkpoints |
| AI | language model without tools; agent with a cloud model (GPT-6 Luna); agent with a local model (gpt-oss-20b on the RTX 4070 laptop; smaller models on a low-power device if feasible) |
| Upper bound | the LP with perfect foresight |

Structured plans are given to the non-AI systems as parameters; plain-language plans are given to them as their
answer key (the best case for them), so the comparison isolates planning and replanning.

## 7. Metrics

| Goal | Metric |
|---|---|
| Cost | net cost = import bill minus export income (EUR); adjusted cost = net cost minus the value of the battery charge and stored heat left at midnight relative to the start, at the day's mean import price; gap closed = (rules - system) / (rules - optimum), pooled |
| Solar use | self-consumption %, self-sufficiency % |
| Grid | peak import (kW), power-charge cost where a tariff applies |
| Comfort | degree-hours outside the household's band; minimum indoor temperature |
| EV | energy delivered by departure (% of requested); unmet kWh |
| Understanding | precision and recall of extracted constraints against the answer key |
| Reliability | plans rejected by the checker, fallbacks used, failed model calls |
| Stability | replans per day; slots whose setpoint changed |
| Cost of the AI | tokens, USD, latency; Wh per house-day (GPU power logged with `nvidia-smi`); gateway idle power |

Rules already learned in the prototypes: value the end-of-day state the same way in the score and in every
optimiser; report savings in EUR when export income cancels most of the bill; pool sums over days.

## 8. Procedure

1. **Build** (data pipeline, house-days, forecasts, plan texts and answer keys, systems).
2. **Exploratory phase:** design iterations of the agent (prompt, tools, checkpoints, settings) on the
   exploratory set only, each iteration documented with its results, as in the household thesis.
3. **Registration:** freeze code, prompts, tools, models, held-out set, hypotheses and analysis script; commit
   the registration before the run.
4. **Confirmation:** run every system on the held-out set (LLM systems 3 runs per house-day, temperature 0);
   record every run (system, model, house-day, run, costs, metrics, tokens, latency, energy, decisions).
5. **Year simulation:** the best systems over a full year of one or more houses, state carried across days,
   for annual EUR, kWh, CO2 and the gateway's net energy balance (H6).
6. **Demonstration:** the gateway in Home Assistant with simulated devices (Modbus battery simulator, OCPP
   charger simulator, SG Ready switch), replaying a recorded day.

## 9. Analysis

Paired comparisons per house-day (one-sided Wilcoxon signed-rank) for H1, H2, H5; exact binomial for H3; pooled
proportion for H4; Holm correction within SQ1. SQ2 descriptive: the agent's advantage per factor level. Effect
sizes with bootstrap confidence intervals. Sensitivity: battery size, comfort band, forecast error, tariff with
and without a power charge.

## 10. Validity

| Threat | Handling |
|---|---|
| Synthetic forecasts | error levels fitted to published accuracy; forecast quality as a factor |
| Mixed sources (house, weather, prices) | same real dates; state remaining mismatches |
| Plans written by the author | written and answer-keyed before any run, second-person check, registered |
| Tuning on the evaluation days | exploratory set for design, held-out set once |
| Simulation only | Home Assistant demonstration; field study as future work |
| One house type and climate | several OPSD homes; sensitivity on battery and house parameters |
| LLM non-determinism | 3 runs per house-day; report spread |

## 11. Work plan

| Phase | Weeks | Output |
|---|---|---|
| Literature review (systematic search; HEMA, Michelon et al., AgentiControl-MPC, EMHASS, evcc) | 1-3 | gap statement |
| Data: OPSD homes, DWD weather, prices; house-day builder | 2-4 | exploratory and held-out sets |
| Plan texts and answer keys | 3-5 | benchmark of daily plans |
| Systems: rules, EMHASS, LP, MPC, LLM without tools, agent | 4-8 | systems registry |
| Exploratory iterations | 8-11 | design iterations chapter |
| Registration and held-out run | 12-13 | confirmation results |
| Year simulation and energy balance | 13-14 | H6, annual figures |
| Home Assistant demonstration | 14-15 | demo |
| Writing | 13-20 | thesis |

## 12. Risks

| Risk | Mitigation |
|---|---|
| Model predictive control matches the agent on cost | the agent's measurable value is plan understanding, judgement on uncertainty and explanation; evaluate them directly (SQ3, stability, explanations) |
| Local model unreliable or slow | fallback rules; keep arithmetic in tools; compare with cloud |
| Gateway energy use cancels the savings | measure idle and inference energy; run the model only at checkpoints |
| Scope (community layer, many houses) | community coordination stays future work unless time allows |
| Data gaps in OPSD | drop incomplete days; use several homes |

## 13. Related work to read in full before committing

HEMA, Multi-Agent Home Energy Management Assistant (arXiv 2602.15219; SoftwareX 2026); Michelon et al., Large
Language Model Interface for HEMS (ACM e-Energy 2025); AgentiControl-MPC and AutoControl-MPC (2026); Jonah et al.,
LLMs for Agentic Home Energy Management (2026); El Makroum et al. (2026); EMHASS; evcc; SEM for Home Assistant;
LLM bidding agents in P2P markets (arXiv 2609.05462). Run a systematic search (Scopus or Web of Science) for the
literature review.

## 14. Status of the prototypes (30 October 2026)

- `prototypes/home_gateway/twin.py`: year 2016 of OPSD `residential4` with a virtual 10 kWh battery. Against the
  recorded year: battery alone 118 EUR, rules 121 EUR, perfect-foresight optimum 174 EUR saved.
- `prototypes/home_gateway/gateway.py`: 12 sample days with forecasts, a control layer with fallbacks, day-ahead
  LP, model predictive control, perfect foresight, and the agent with GPT-6 Luna and gpt-oss-20b. Without the
  agent: perfect foresight 0.32 EUR, model predictive control hourly 2.67 EUR, rules 2.80 EUR adjusted cost over
  the 12 days; forecast error, not the optimisation, limits the saving. Agent pilot running.
- German setup (`--market de --forecast weather`; German day-ahead prices, BDEW 2016 household tariff, 12.31 ct
  feed-in, PV and heat forecasts from DWD weather models; control layer holds the planned grid exchange), same 12
  days, adjusted cost and share of the rules-to-optimum gap closed: rules -4.79 EUR (0 %), day-ahead -5.50 (19 %),
  MPC at checkpoints -5.65 (23 %), MPC hourly -5.97 (31 %), agent GPT-6 Luna -6.13 (36 %), agent gpt-oss-20b
  local -6.25 (39 %), perfect foresight -8.54 (100 %). The agents beat MPC at the same checkpoints on 5-6 of 12
  days, mainly by derating the PV forecast on uncertain days; the gain is small (about 0.5 EUR over 12 days) and
  12 days are too few for a test. GPT-6 Luna: 63 checks, 0 errors, USD 0.025; gpt-oss-20b: 63 checks, 3 failed
  calls (fallback kept the plan), 152 s per day. An earlier run (Finnish prices, synthetic forecasts) is not
  comparable: its control layer followed the planned battery power and the tool text suggested a 50 % reserve.
- Tuned baseline (same 12 days): MPC with a fixed PV derating of 0.9 closes 46 % of the gap at the checkpoints and
  51 % hourly (0.8: 45 % and 49 %), more than either agent. The agents' cost advantage over default MPC is a
  tuning effect that a fixed setting reproduces (tuned in-sample here, but 0.8 and 0.9 give similar results).
  The agent's case must therefore rest on what MPC cannot do (plain-language plans, changes during the day,
  configuration, explanation), with a tuned MPC as the cost baseline.
- Not yet built: plan texts with answer keys, appliance runs, EMHASS baseline, comfort and EV metrics as defined
  above, inference-energy logging, Home Assistant demonstration.
