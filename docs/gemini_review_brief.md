# Review brief: a language-model agent for a home energy gateway (new thesis)

Prepared 1 November 2026 for an external review (for example by Gemini). It covers the new thesis only: the
exploratory prototypes and the draft thesis plan. Nothing in
the plan is registered yet; all prototype numbers are exploratory.

## How to use this file (instructions for the reviewer)

Please evaluate the **thesis plan (Part 2)** as a supervisor and an examiner would. Use the prototypes (Part 1) as
the evidence it builds on. In particular:

1. Is the research problem real and well motivated, and is the gap against existing work (sections 2.1 and 2.11)
   convincing? Name related work that is missing.
2. Are the research questions and hypotheses clear, answerable with the planned data, and testable as stated?
3. Is the design (MPC plans, agent interprets and configures, checker and control layer execute) sound and safe?
   Is the split into two agents justified?
4. Is the evaluation fair, in particular the choice of a **tuned MPC** as the cost reference and the plan
   benchmark written by the author?
5. Are the datasets suitable (one German house region, 2015-2019, a counterfactual dynamic tariff)?
6. What are the biggest threats to validity and feasibility in about 20 weeks for a master's student?
7. Is the contribution enough for a master's thesis in Information Processing Science using Design Science
   Research? What would make it stronger?

Please answer with: an overall verdict, the five most important weaknesses, concrete fixes for each, and any
factual or methodological errors you notice.

---

## Part 1. Exploratory prototypes (evidence for the plan)

All are exploratory, run on small samples, with assumptions still to be sourced. Code lives under `prototypes/`.

| Prototype | Data | What it showed |
|---|---|---|
| Industrial plant days (`prototypes/hipe`) | HIPE electronics factory, one sample week | Agents and a simple smart timer reached the MILP optimum on every day |
| Small business (`prototypes/opsd`) | OPSD `DE_KN_industrial3`, 12 working days | Same: agents and timer reached the optimum |
| Heat pump + EV house (`prototypes/heatpump`) | REFIT base load, When2Heat heat demand and COP, Norwegian EV sessions, Finnish prices | Joint scheduling of space heating, hot water and EV under 8 kW is feasible; numbers not results |
| Home gateway digital twin (`prototypes/home_gateway/twin.py`) | OPSD `DE_KN_residential4` (PV, heat pump, EV), year 2016, virtual 10 kWh / 5 kW battery | Perfect-foresight saving against the recorded year, German prices with feed-in: battery self-consumption 223, rules 217, optimum 311 EUR |
| Home gateway with agents (`prototypes/home_gateway/gateway.py`) | Same house, German day-ahead prices, DWD weather-driven forecasts, 12 days | See below |

**Gateway pilot, 12 days, share of the cost gap between rules and perfect foresight closed:**

| Strategy | Gap closed |
|---|---|
| Rules (evcc-style PV surplus EV charging, SG Ready heat pump boost, self-consumption battery) | 0 % |
| Day-ahead plan | 19 % |
| Default MPC at checkpoints / hourly | 23 % / 31 % |
| Agent, GPT-6 Luna (cloud) | 36 % |
| Agent, gpt-oss-20b (local, Ollama) | 39 % |
| MPC with PV forecast derated to 90 %, at checkpoints / hourly | 46 % / 51 % |
| Perfect foresight | 100 % |

The derating was chosen on the same 12 days (0.8 gives 45 % and 49 %). The agents' gain over default MPC came from
being cautious about the PV forecast; a fixed setting did it better. GPT-6 Luna: 63 checks, 0 errors, USD 0.025 for
12 days. gpt-oss-20b: 63 checks, 3 malformed calls caught by the fallback, about 152 s per day.

Other lessons that changed the design: the control layer must hold the planned grid exchange (the battery absorbs
forecast error), otherwise every forecast-based strategy loses to rules; end-of-day battery and heat must be valued
the same way in the optimiser and the score; tool descriptions must not suggest default values (both models copied
a suggested "50 % reserve"); the PV model fitted to DWD radiation reproduces the house's PV with r = 0.96 hourly.

**Plan-interpretation pilot (`prototypes/plan_pilot`), 20 draft plans.** Plans of four kinds: simple (6), a change
during the day (5), ambiguous (5), conflicting (4), for one German house (40 kWh car, 3.7 kW charger, comfort
20-22 °C). The model extracts a structured `HouseholdPlan` (EV departures and targets, appliance windows, away
periods, comfort bands, clarifying questions), scored against answer keys (tolerances 15 min, 5 %, 1 kWh).

| Run | Item precision | Item recall | Comfort hours agree | Clarify recall | False questions |
|---|---|---|---|---|---|
| GPT-6 Luna, default structured output | 1.00 | 0.81 | 1.00 | 0.89 | 0.09 |
| GPT-6 Luna, function calling | 1.00 | 0.90 | 1.00 | 0.89 | 0.09 |
| GPT-6 Luna, function calling + 2 validation retries | 1.00 | 0.95 | 1.00 | 0.89 | 0.18 |
| gpt-oss-20b, default (empty plans) | 0.00 | 0.00 | 0.85 | 0.33 | 0.09 |
| gpt-oss-20b, function calling (14 invalid) | 1.00 | 0.10 | 0.75 | 0.11 | 0.09 |
| gpt-oss-20b, function calling + 2 retries (17 of 20 valid, about 74 s per plan) | 0.69 | 0.43 | 0.75 | 0.78 | 0.09 |

Caveats: the answer keys are drafts written by Claude and not yet checked by the author or a second person; one
change case (C3: 25 kWh between 23:30 and 05:00 at 3.7 kW) is probably infeasible, so its key is likely wrong;
open key questions are whether items already in the past belong in an updated plan, whether conflicting items
should also be listed as constraints, and how away periods relate to comfort bands.

---

## Part 2. Thesis plan: a language-model agent as the interface of a home energy gateway

### 2.1 Problem

A home energy gateway is the device in the meter cabinet or on the home network that reads the smart meter and
controls the home's energy assets: solar inverter, battery, EV charger, heat pump and smart appliances. It decides
every few minutes when each asset draws, stores or exports power, to lower the bill, use more own solar power and
stay within grid limits.

How gateways plan today, and where they fall short:

- **Devices do not speak one language.** A market study counted 26 protocols and communication methods in home
  energy devices and found no interoperability across the board; Modbus dominates in the home, with S2, EEBUS,
  Matter and OCPP competing as standards. Many devices are reachable only through their maker's cloud.
  Sources: [ElaadNL 2025](https://elaad.nl/wp-content/uploads/downloads/Residential-Flexibility-march-2025.pdf),
  [ACEEE 2026](https://www.aceee.org/sites/default/files/proceedings/ssb26/pdfs/323_0959_1434_001151.pdf).
- **Several controllers fight over one device.** An EV charger can receive commands from the car's app, the
  charger's app, a smart-charging service, a flexibility service and the supplier.
  Source: [Energy Systems Catapult 2026](https://es.catapult.org.uk/insight/making-home-energy-management-work-for-consumers/).
- **The grid operator now sets limits too.** In Germany, heat pumps and wallboxes above 4.2 kW installed since 2024
  must accept power reductions through the smart meter gateway and a control box (§14a EnWG).
  Sources: [evcc docs](https://docs.evcc.io/en/docs/features/14a-enwg-steuve),
  [gridX](https://www.gridx.ai/knowledge/meter-box-14a-enwg-compliance-explained).
- **Planning is mostly by fixed rules** (author's characterisation; no market survey found yet). Rules leave
  savings unused: MPC cut the energy cost of a PV and battery home by 13.5 % against a rule-based strategy, and
  stochastic MPC did best under realistic forecast errors.
  Sources: [Seal et al. 2019](https://arxiv.org/pdf/1912.06943),
  [NREL](https://research-hub.nrel.gov/en/publications/home-energy-management-under-realistic-and-uncertain-conditions-a-2/).
- **An optimiser needs an expert to set it up.** MPC needs exact parameters (EV departure and target, comfort band
  by time, battery reserve, trust in the PV forecast); households do not think in them, settings go stale when
  routines, seasons or tariffs change, and complicated set-up holds adoption back.
  Sources: [ACEEE 2012](https://www.aceee.org/files/proceedings/2012/data/papers/0193-000022.pdf),
  [Tuomela et al. 2021](https://oulurepo.oulu.fi/handle/10024/34035).

Where AI agents fit: recent work turns plain-language preferences into optimisation constraints
([Sanguinetti et al. 2025](https://arxiv.org/html/2503.21360v1),
[Michelon et al. 2025](https://www.qeios.com/read/EVPWM7/pdf)) or schedules appliances directly with ReAct agents
([El Makroum et al. 2025](https://arxiv.org/abs/2510.26603v1),
[Jonah et al. 2026](https://arxiv.org/abs/2607.04569)). Direct schedulers come close to the MILP optimum, but Jonah
et al. report fabricated schedules and misstated deadlines and recommend a deterministic validator before
actuation, which matches what the prototypes showed: an optimiser plus a deterministic checker was reliable. The thesis therefore gives the agent what an optimiser cannot do: interpret
the household's plans and changes into constraints, configure the MPC from the house's own history, and explain
the plan. The MPC computes the schedule; a checker and a control layer switch the devices.

Several sources above are preprints or industry reports; peer-reviewed versions should be preferred in the thesis.

### 2.2 Research questions and draft hypotheses

- **RQ:** How can a language-model agent make a home energy gateway usable without expert configuration, by
  interpreting the household's plans and configuring and explaining an optimiser, while keeping control reliable?
- **SQ1 Interpretation:** How accurately does the agent turn plain-language plans and changes into constraints,
  and are the requirements then met?
- **SQ2 Configuration:** Can the agent configure the MPC from the house's history close to an expert-tuned MPC?
- **SQ3 Reliability and cost:** How often do the checker and fallback intervene, and what does it cost (tokens,
  USD, seconds, Wh) locally and in the cloud?
- **SQ4 Conditions:** Under which weather, prices, loads and plan types does it fail? (descriptive)

| | Hypothesis (fixed only at registration) | Test |
|---|---|---|
| H1 | Constraint recall and precision both at least 0.9 | one-sided tests on pooled proportions |
| H2 | Requirements (comfort band, EV energy by departure, away periods) met on at least 95 % of house-days | exact binomial |
| H3 | A plain-language plan through the agent costs no more than the same plan as exact parameters to the tuned MPC (margin set at registration) | paired non-inferiority |
| H4 | Agent-configured MPC reaches at least X % of the expert-tuned MPC's saving over default MPC | paired test over house-days |
| H5 | Local model meets H1-H2 within a margin of the cloud model | paired comparison |
| H6 | Yearly saving exceeds the gateway's own energy use (idle plus inference) | year simulation, descriptive |

Holm correction within SQ1 (H1-H3).

**Claimed novelty (to be confirmed by a systematic literature search):** (1) the agent as configurator of an MPC
learned from meter and weather history; (2) the agent as plan interpreter in closed-loop control for PV, battery,
heat pump and EV together, with changes during the day, checked before execution; (3) evaluation against a tuned,
not default, MPC so the agent is credited only for what an optimiser cannot do; (4) the net energy balance of a
local model.

### 2.3 System design

Three layers; the language model sits in only one.

1. **Agent layer (ReAct).** A *Household Assistant* (event-driven: new plan, change, EV plug-in, large deviation)
   and a *Configurator* (weekly). An optional cloud model receives summaries only.
2. **Harness (deterministic).** Tools, the tuned MPC (LP/MILP from the current state to the horizon), a checker
   (comfort band, EV energy by departure, battery limits, grid limit; a failing plan is never executed, violations
   go back to the agent), and a history store.
3. **Control layer (deterministic, every 15 min).** Holds the planned grid exchange (the battery absorbs forecast
   error), keeps comfort, EV deadline and battery limits, falls back to the tuned MPC with default constraints or
   fixed rules if the agent, model or network fails. Device integration through Home Assistant (Modbus/SunSpec for
   PV and battery, OCPP for the charger, SG Ready/EEBUS for the heat pump).

Safety rules: the language model never computes a schedule or switches a device; every plan passes the checker.
The MPC replans hourly on its own; the agent is not in that loop.

Why two agents: splitting one task between agents adds cost without reliability when the agents do the same job. Here the two
agents differ in inputs, timing and model needs (interpretation is frequent and private, configuration is weekly
and analytical). A single-agent variant is kept as an ablation.

**Household Assistant tools:** `read_plan()`, `get_situation()`, `get_forecast()` (with weather class),
`propose_constraints(items)` (validated ranges, unknown fields rejected), `preview_plan()` (runs MPC and checker),
`ask_household(question)` (only for ambiguity or conflict). Final answer `AssistantDecision`: commit or keep,
constraints, message to the household; commit only if the checker passes.

**Configurator tools:** `history_summary(item)` (loads, EV, comfort, PV vs weather, forecast error),
`backtest(settings, weeks)`. Final answer `MpcSettings`: PV derating by weather class, battery reserve, grid limit,
default comfort bands, flexible-load windows, reason; applied only if the backtest beats current settings.

Design changes motivated by the pilots: no default values in tool descriptions; agent sets constraints and
settings, MPC computes the schedule; agent on events only; one structured output per call, validated; the harness
pre-computes situation and history summaries; control layer holds grid exchange; end-of-day energy valued
consistently.

### 2.4 Datasets

All core data are open, from the same place (Konstanz, Germany) and the same dates (Oct 2015 to 2019).

| Dataset | Provides | Period, resolution | Role | Link |
|---|---|---|---|---|
| OPSD Household data, `DE_KN_residential4` | PV, grid import/export, heat pump, EV, appliances | Oct 2015 - Feb 2018, 15 min | main house | [OPSD](https://data.open-power-system-data.org/household_data/2020-04-15/) |
| OPSD `residential1`, `3`, `6` (and `2`, `5` optional) | PV, heat pump, appliances | 2014 - 2019, 15 min | more houses for configuration | same |
| DWD station 02712 Konstanz | hourly temperature, global radiation | 1971/1977 - 2026, 1 h | weather classes, forecasts | [DWD open data](https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/) |
| Energy-Charts / SMARD day-ahead prices | DE-AT-LU then DE-LU spot | Oct 2015 - May 2019, 1 h | import and export price | [Energy-Charts](https://www.energy-charts.info/charts/price_spot_market/chart.htm?l=en), [SMARD](https://www.smard.de/en) |
| BDEW price analysis (Dec 2023) | 2016 household price components, 28.80 ct/kWh | yearly | counterfactual dynamic tariff = (spot + margin + 17.94) x 1.19 | [BDEW](https://www.bdew.de/media/original_images/2023/12/12/231212_bdew-strompreisanalyse_dezember_2023_12122023.pdf) |
| EEG feed-in tariff | 12.31 ct/kWh, rooftop up to 10 kWp from Nov 2015 | monthly | export price | [Bundesnetzagentur](https://www.bundesnetzagentur.de/DE/Fachthemen/ElektrizitaetundGas/ErneuerbareEnergien/EEG_Foerderung/Archiv_VergSaetze/start.html) |
| When2Heat, Germany | heat pump COP | 2008 - 2022, 1 h | heat demand from HP electricity | [OPSD When2Heat](https://data.open-power-system-data.org/when2heat/2023-07-27/) |
| Plan benchmark (to be written) | plans, changes, ambiguous and conflicting requests with answer keys | one per house-day | SQ1 ground truth | n/a |
| Norwegian residential EV sessions (optional) | 35,377 sessions | 2018 - 2021 | realistic departure times | [Zenodo](https://zenodo.org/records/12730566) |
| REFIT (optional) | appliance cycles, 18 UK homes | 2013 - 2015, 8 s | extra appliance runs | [DOI](https://doi.org/10.15129/9ab14b0e-19ac-4279-938f-27f643078cec) |
| Finnish prices (comparison) | FI spot | 2015 - 2026 | comparison market | [Elering](https://dashboard.elering.ee/), [Sahkotin](https://sahkotin.fi) |
| Product data sheets | battery, charger, heat pump limits | n/a | model parameters | to be sourced |

### 2.5 Benchmark

Unit: a house-day (24 h at 15 min) with a plain-language plan and, where designed, a change during the day; state
left at midnight is valued in the cost. Factors: plan type (structured; plain language; plain language with a
change; ambiguous or conflicting), weather (sunny/variable/overcast; cold/mild/warm), price pattern (flat, evening
peak, volatile incl. negative), load (base; + heat pump; + heat pump + EV), house (several OPSD homes). Plans and
answer keys written before any run, checked by a second person. Exploratory set of about 100 house-days for design
iterations; held-out set (other dates and houses) run once after registration.

### 2.6 Systems compared

All use the same house-days, forecasts, plans and control layer.

| Level | System |
|---|---|
| Lower bound | as recorded |
| Products | self-consumption battery; evcc-style rules; EMHASS (REST, default settings) |
| Optimiser, default | hourly MPC, default settings, plan as exact parameters |
| **Optimiser, tuned (cost reference)** | hourly MPC tuned by grid search on the exploratory set, plan as exact parameters |
| AI without tools | language model reading plan and data and writing the schedule |
| **Agent** | agent interprets the plan and configures the MPC (cloud model; local model) |
| Upper bound | perfect foresight with the exact plan |

The agent is expected to match the tuned MPC, not beat it, while starting from plain language and no expert tuning.

### 2.7 Metrics

Interpretation (precision, recall, clarifying questions when and only when needed); requirements met (comfort
degree-hours outside bands, EV energy by departure, away periods); configuration (share of the tuned MPC's saving
over default MPC); cost (adjusted cost, pooled gap closed between rules and perfect foresight); self-consumption,
self-sufficiency, peak import; reliability (plans rejected, fallbacks, failed calls); cost of the AI (tokens, USD,
latency, Wh per house-day, gateway idle power); optional correctness of figures in the household message.

### 2.8 Procedure and analysis

Build (house-days, weather classes, forecasts, plans and keys, systems, tuned-MPC grid search) -> exploratory design
iterations -> registration (freeze code, prompts, tools, models, tuned settings, held-out set, hypotheses,
analysis) -> confirmation (LLM systems 3 runs per house-day, temperature 0) -> year simulation for annual EUR, kWh
and net energy balance (H6) -> Home Assistant demonstration with simulated devices. Pooled proportions with
one-sided tests (H1-H2), paired Wilcoxon non-inferiority (H3-H5), Holm within SQ1, bootstrap intervals; SQ4
descriptive; sensitivity to battery size, forecast error and a power charge.

### 2.9 Validity

| Threat | Handling |
|---|---|
| Plans written by the author | written and keyed before any run, second-person check, registered |
| Tuned MPC tuned on evaluation days | tune on the exploratory set only |
| Synthetic forecast errors | fitted to published accuracy; forecast quality as a sensitivity factor |
| Mixed sources (house, weather, prices) | same real dates and place; dynamic tariff stated as counterfactual |
| Simulation only | Home Assistant demonstration; field study as future work |
| LLM non-determinism | 3 runs per house-day |

### 2.10 Work plan (about 20 weeks) and risks

| Phase | Weeks |
|---|---|
| Systematic literature review | 1-3 |
| House-days, weather classes, tariffs | 2-4 |
| Plans and answer keys | 3-6 |
| Systems incl. tuned MPC and EMHASS | 4-8 |
| Agent tools and design iterations | 8-11 |
| Registration and held-out run | 12-13 |
| Year simulation, energy balance, demo | 13-15 |
| Writing | 13-20 |

| Risk | Handling |
|---|---|
| Interpretation too easy for current models (ceiling effect) | changes during the day, ambiguous and conflicting requests; score clarifying questions |
| Configuration from history adds nothing over defaults | report it; tuned MPC stays the reference; thesis rests on SQ1 and SQ3 |
| Local model too slow or unreliable | event-driven assistant; fallback to tuned MPC; cloud comparison |
| Gateway energy use cancels the savings | measure idle and inference energy (H6) |
| Author-written plans bias the result | keyed before runs, second-person check, registered |
| Simulation only | Home Assistant demo; field study as future work |

### 2.11 Related work to read in full

HEMA (arXiv 2602.15219; SoftwareX 2026); Michelon et al., LLM interface for HEMS (ACM e-Energy 2025);
AgentiControl-MPC and AutoControl-MPC (2026); Jonah et al. (2026); El Makroum et al. (2025); Sanguinetti et al.
(2025); EMHASS; evcc; SEM for Home Assistant; PV forecast error in home energy management (arXiv 1906.09902;
Elkazaz et al., Energies 2020; Nair et al., IEEE TEC 2021); Antonanzas et al. (2016); Skoplaki and Palyvos (2009).
A systematic search (Scopus or Web of Science) is still to be done.

### 2.12 Status

Not built yet: the full plan benchmark with checked keys, `history_summary` / `propose_constraints` / `backtest`
tools, the tuned-MPC grid search on an exploratory set, the EMHASS baseline in this setting, inference-energy
logging, the Home Assistant demo. Nothing is registered.
