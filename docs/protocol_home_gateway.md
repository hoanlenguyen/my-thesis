# Protocol: a language-model agent as the interface of a home energy gateway

Draft, 30 October 2026 (reframed after the gateway pilot). Status: plan for discussion with the supervisor for a
follow-up thesis; nothing in it is registered. The prototypes in `prototypes/` are exploratory.

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

**Artifact.** A home energy gateway in which a tuned MPC does the planning and a ReAct language-model agent is
the interface: it turns the household's plain-language plan and its changes into constraints, configures the MPC
from the house's own history, checks every plan through a deterministic checker, and explains the result. A
control layer with fallback rules executes the plan. The agent can run on a local open-weight model or a cloud
model.

**What is new (to be confirmed by a systematic literature search; section 13):**

1. the agent as **configurator** of an MPC: it learns the house's settings (flexible loads, comfort, forecast
   caution) from meter and weather history instead of an expert;
2. the agent as **plan interpreter** in closed-loop control: plain-language plans and changes during the day
   become constraints, checked before execution, for PV, battery, heat pump and EV together;
3. evaluation against a **tuned MPC**, not a default one, so that the agent is credited only for what an
   optimiser cannot do;
4. the net energy balance of a local model: inference and idle energy against the energy and cost it saves.

Design Science Research: build, demonstrate, evaluate, with design iterations on an exploratory set and a
registered confirmation on a held-out set.

## 2. Research questions (draft)

- **RQ:** How can a language-model agent make a home energy gateway usable without expert configuration, by
  interpreting the household's plans and configuring and explaining an optimiser, while keeping control
  reliable?
- **SQ1 (interpretation):** How accurately does the agent turn plain-language daily plans and their changes into
  constraints, and how often are the household's requirements then met?
- **SQ2 (configuration):** Can the agent configure the MPC from a house's history so that its cost comes close to
  an expert-tuned MPC?
- **SQ3 (reliability and cost):** How often are its plans rejected or overridden by the checker and fallback,
  and what does it cost (tokens, time, energy) locally and in the cloud?
- **SQ4 (conditions):** Under which weather, price patterns, household loads and plan types does interpretation
  or configuration fail?

**Draft hypotheses** (fixed only at registration, after the exploratory phase):

| | Hypothesis | Test |
|---|---|---|
| H1 | Constraint recall from plain-language plans is at least 0.9 and precision at least 0.9 | one-sided tests on pooled proportions |
| H2 | With the agent's constraints, the household's requirements (comfort band, EV energy by departure, away periods) are met on at least 95 % of house-days | exact binomial |
| H3 | A plain-language plan through the agent costs no more than the same plan given as exact parameters to the tuned MPC (within a margin set at registration) | paired non-inferiority test |
| H4 | The agent-configured MPC reaches at least X % of the expert-tuned MPC's saving over the default MPC (X set at registration) | paired test over house-days |
| H5 | The local model meets H1-H2 within a margin of the cloud model | paired comparison |
| H6 | The gateway's yearly saving exceeds its own energy use (gateway idle plus inference) | year simulation, descriptive |

Holm correction within the SQ1 family (H1-H3).

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

**Agent tools:**

| Tool | Returns |
|---|---|
| `read_plan` | the household's plan text and any changes received |
| `get_situation` | time, indoor temperature, battery charge, EV status, forecast error so far |
| `get_forecast` | hourly PV, load, heat demand and prices, with the day's weather class and expected forecast error |
| `history_summary(item)` | from the house's own history: load runs and windows, comfort, EV arrivals and energy, forecast error by weather class |
| `set_constraints(...)` | EV energy and departure, comfort bands by time, away periods, appliance windows (the plan as constraints) |
| `configure_mpc(...)` | forecast caution (PV derating), battery reserve, grid limit (validated ranges) |
| `run_mpc` / `check_plan` | the plan and its violations |
| `explain_plan` | cost, comfort and EV figures of the committed plan for the household message |

**Checkpoints:** start of day, each plan change from the household, each EV plug-in, and a deviation trigger.
Between checkpoints the tuned MPC replans hourly on its own; the agent is not in that loop.

## 4. Data

| Data | Source | Licence | Use |
|---|---|---|---|
| PV, grid, heat pump, EV, appliances, 15 min | OPSD Household data 2020-04-15 (CoSSMic, Konstanz), sites `residential1`-`6` (`residential4`: PV, heat pump, EV) | CC BY 4.0 | house-days |
| Weather, hourly | DWD station 02712 Konstanz: air temperature (`TU`, 1971-2025), global radiation (`ST`, 1977-Sep 2026), UTC; Oct 2015-May 2019 0.2-0.3 % of hours missing; global radiation correlates 0.95 hourly and 0.97 daily with `residential4` PV in 2016 | DWD open data (CC BY 4.0) | weather classes, forecast models |
| German day-ahead prices | Energy-Charts API (Fraunhofer ISE; Bundesnetzagentur / SMARD): DE-AT-LU to 30 Sep 2018, DE-LU from 1 Oct 2018; hourly Oct 2015-May 2019, two hours missing at the zone change; 97 negative hours in 2016 | CC BY 4.0 | spot component of the import price |
| German household tariff 2016 | BDEW-Strompreisanalyse Dec 2023: 28.80 ct/kWh = procurement and sales 6.26, grid fee 7.01, concession fee 1.66, EEG surcharge 6.354, other levies 0.866, electricity tax 2.05, VAT 4.60; dynamic tariff = (spot + margin + 17.94) x 1.19 | n/a | import price (a counterfactual dynamic tariff) |
| Feed-in tariff | EEG rooftop PV up to 10 kWp from Nov 2015: 12.31 ct/kWh (municipal and industry tables; to be checked against the Bundesnetzagentur table) | n/a | export price |
| Heat pump efficiency | When2Heat (OPSD 2023-07-27), Germany | CC BY 4.0 | heat demand from measured electricity |
| EV sessions (optional) | Norwegian residential sessions (Sørensen et al., 2024) | CC BY 4.0 | plug-in and departure times |
| Battery, charger, heat pump limits | product data sheets | n/a | model parameters (to be cited) |

## 5. Benchmark

**Unit:** a house-day (24 h at 15 min) with a plain-language plan and, where the design calls for it, a change
during the day. Battery and indoor temperature start at reference values; the state left at midnight is valued
in the cost.

**Factorial design:**

| Factor | Levels |
|---|---|
| Plan type | structured parameters; plain language; plain language with a change during the day; ambiguous or conflicting request |
| Weather | sunny, variable, overcast (DWD radiation); cold, mild, warm (DWD temperature) |
| Price pattern | flat, evening peak, volatile (including negative prices) |
| Load | base, + heat pump, + heat pump + EV |
| House | several OPSD homes (configuration is learned per house) |

**Plans and answer keys:** written before any system is run; each with the constraints it implies (EV energy and
departure, comfort bands by time, away periods, appliance windows) and, for ambiguous requests, the expected
clarifying question. A second person checks the answer keys.

**Sets:** exploratory (about 100 house-days) for design iterations; held-out (same design, other dates and houses)
run once after registration.

## 6. Systems compared

All systems use the same house-days, forecasts, plans and control layer.

| Level | System |
|---|---|
| Lower bound | as recorded |
| Products | self-consumption battery; evcc-style EV + SG Ready + battery rules; EMHASS (REST, default settings) |
| Optimiser, default | MPC hourly, default settings, plan given as exact parameters |
| **Optimiser, tuned** | MPC hourly with settings tuned by grid search on the exploratory set (the expert configuration), plan given as exact parameters |
| AI without tools | language model reading the plan and data, writing the schedule itself |
| **Agent** | agent interprets the plan and configures the MPC (cloud model; local model) |
| Upper bound | perfect foresight with the exact plan |

The tuned MPC with exact parameters is the cost reference: the agent is expected to match it, not beat it, while
starting from plain language and no expert configuration.

## 7. Metrics

| Goal | Metric |
|---|---|
| Interpretation | precision and recall of extracted constraints against the answer key; clarifying questions asked when, and only when, needed |
| Requirements met | comfort degree-hours outside the household's bands; EV energy delivered by departure; away periods honoured |
| Configuration | agent-configured MPC saving as a share of the tuned MPC's saving over default MPC |
| Cost | adjusted cost (net cost minus the value of battery charge and stored heat left at midnight); gap closed between rules and perfect foresight, pooled |
| Solar use, grid | self-consumption %, self-sufficiency %, peak import |
| Reliability | plans rejected by the checker; fallbacks used; failed model calls |
| Cost of the AI | tokens, USD, latency; Wh per house-day (GPU power with `nvidia-smi`); gateway idle power |
| Explanation (optional) | correctness of the figures in the household message against the plan |

## 8. Procedure

1. Build: house-days, weather classes, forecasts, plans and answer keys, systems, tuned-MPC grid search.
2. Exploratory phase: agent design iterations (prompt, tools, checkpoints) on the exploratory set only.
3. Registration: freeze code, prompts, tools, models, tuned MPC settings, held-out set, hypotheses, analysis.
4. Confirmation: every system on the held-out set (LLM systems 3 runs per house-day, temperature 0).
5. Year simulation of the best systems for annual EUR, kWh and the gateway's net energy balance (H6).
6. Demonstration in Home Assistant with simulated devices, replaying a recorded day with a plan change.

## 9. Analysis

Pooled proportions with one-sided tests for H1-H2; paired non-inferiority (Wilcoxon) for H3-H5; Holm within
SQ1. SQ4 descriptive per factor level. Bootstrap confidence intervals. Sensitivity: battery size, forecast error,
tariff with and without a power charge.

## 10. Validity

| Threat | Handling |
|---|---|
| Plans written by the author | written and answer-keyed before any run, second-person check, registered |
| Tuned MPC tuned on the evaluation days | tune on the exploratory set only; report the held-out result |
| Synthetic forecast errors | fitted to published accuracy; forecast quality as a sensitivity factor |
| Mixed sources (house, weather, prices) | same real dates and place (Konstanz); counterfactual dynamic tariff stated as such |
| Simulation only | Home Assistant demonstration; field study as future work |
| LLM non-determinism | 3 runs per house-day |

## 11. Work plan (about 20 weeks)

| Phase | Weeks | Output |
|---|---|---|
| Literature review (systematic) | 1-3 | gap statement |
| House-days, weather classes, tariffs | 2-4 | exploratory and held-out sets |
| Plans and answer keys | 3-6 | plan benchmark |
| Systems incl. tuned MPC and EMHASS | 4-8 | systems registry |
| Agent tools and design iterations | 8-11 | design iterations |
| Registration and held-out run | 12-13 | confirmation results |
| Year simulation, energy balance, demo | 13-15 | H6, demo |
| Writing | 13-20 | thesis |

## 12. Risks

| Risk | Mitigation |
|---|---|
| Interpretation is easy for modern models (ceiling effect) | include changes during the day, ambiguous and conflicting requests; measure clarifying questions |
| Configuration from history gives no gain over defaults | report it; tuned MPC remains the reference |
| Local model unreliable or slow | fallback to the tuned MPC; compare with cloud |
| Gateway energy use cancels the savings | measure idle and inference energy |
| Scope | community coordination stays future work |

## 13. Related work to read in full

HEMA (arXiv 2602.15219; SoftwareX 2026); Michelon et al., Large Language Model Interface for HEMS (ACM e-Energy
2025); AgentiControl-MPC and AutoControl-MPC (2026); Jonah et al. (2026); El Makroum et al. (2026); EMHASS;
evcc; SEM for Home Assistant; studies of PV forecast error in home energy management (arXiv 1906.09902; Elkazaz
et al., Energies 2020; Nair et al., IEEE TEC 2021); Antonanzas et al. (2016) on PV forecasting; Skoplaki and
Palyvos (2009) on PV temperature dependence. Run a systematic search (Scopus or Web of Science).

## 14. Evidence from the prototypes (30 October 2026)

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
- Weather: the PV model fitted to DWD radiation reproduces `residential4` PV with r = 0.96 hourly and 0.98
  daily; overcast, variable and sunny days average 16.1, 31.6 and 43.6 kWh of PV.
- Other prototypes: `prototypes/hipe/` (HIPE plant days) and `prototypes/opsd/` (OPSD `industrial3`): the agents
  and the smart timer reached the MILP optimum on every day; `prototypes/heatpump/` (REFIT + When2Heat +
  Norwegian EV sessions).
- Not yet built: plans with answer keys, `history_summary` / `set_constraints` / `configure_mpc` tools, the
  tuned-MPC grid search on an exploratory set, EMHASS baseline, inference-energy logging, Home Assistant demo.
