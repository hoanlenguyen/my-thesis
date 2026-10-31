# Proposal: ReAct multi-agent energy recommendations for an industrial site (SPARK)

Draft, 30 October 2026. Status: idea for discussion with the supervisor; nothing is registered or run.

## 1. Framing

**Working title:** *A hierarchical ReAct multi-agent system for energy recommendations in a small industrial
production area.* Design Science Research, with the SPARK dataset (KIT Campus North) as the case.

**Problem.** A site with heterogeneous machines, PV, cooling and dynamic prices must balance energy cost, peak
power, CO₂ and production deadlines at once. Plans are stated informally by plant staff, energy waste is hidden
in high-resolution data, and an optimiser alone cannot explain or justify its trade-offs.

**Lesson from the household thesis.** On fully specified scheduling problems (REFIT households, HIPE plant days)
a simple timer or the MILP reached the optimum, so the language model added no saving. This design therefore
gives the agents work that neither a rule nor a solver does alone, and keeps the solver for the search.

**Where the agents add value (the thesis argument):**

1. **Diagnosis:** finding and quantifying waste (machines idling outside shifts, peaks that did not need to
   coincide) from data rather than from a given problem.
2. **Interpretation:** turning informal production plans into solver constraints.
3. **Trade-offs:** choosing between cost-, peak- and CO₂-optimal plans and explaining the choice.
4. **Verification and explanation** for a plant manager who must approve the plan.

## 2. Research questions (draft)

- **RQ:** How can a hierarchical ReAct multi-agent system be designed to give a small industrial site reliable
  energy recommendations that lower cost, peak power and emissions?
- **SQ1 (diagnosis):** How accurately does the system identify and quantify energy waste, compared with a
  rule-based energy report?
- **SQ2 (planning):** How much do its weekly plans save in cost, peak and CO₂, and how often are they valid,
  compared with the recorded operation, rule-based scheduling, a language model without tools and the MILP
  optimum?
- **SQ3 (interpretation):** How accurately does it turn informal production plans into correct constraints?
- **SQ4 (structure):** Does dividing the work among agents beat a single agent in the same harness?

## 3. Data

SPARK: Sievers, Bischof, Blank & Simon (2026), *Scientific Data* 13, 310; data on RADAR4KIT,
<https://doi.org/10.35097/bjdg3m3rg5jv3skk>, CC BY 4.0. 22 machines and one PV system, 5-second resolution,
2018-2024, timestamps in Europe/Berlin. Layout `MACHINE/MEASUREMENT/YEAR_MEASUREMENT.csv.xz` (columns
`WsDateTime` and the value); validation files in `dataset_clean_validation/`; `00meta_data/` and
`01exogenous_data/` (prices, emission factors, weather, holidays).

- **EPI** (electronics production, the HIPE plant, 7 years): chip press, chip saw, high-temperature oven,
  pick-and-place unit, screen printer, solder oven, vacuum soldering, washing machine, two pump stations, total
  building load (160 A), PV (Sunny Tripower 8-10 kW, 1 year).
- **TEC** (machining workshop, 1 year): CNC milling and machining centres (Chiron 800, DMG Mori CTX 800TC,
  DMF 300/8, DMU 125 monoBLOCK, DNG 50 evo), lathes (VDF 48S, Weiler E30D2, E110), wire EDM (Mitsubishi MV
  2400 R), water chiller (CF ST 161), liquid cooler (JWA 24); rated 15-125 A at 400 V.

| Input | SPARK source | Processing |
|---|---|---|
| Machine power | active-power folder per machine | 5 s → 1 min and 15 min; machine states (off, standby, idle, processing) by per-machine power thresholds |
| Site load | `EPI_TotalLoad` | 15-min load and monthly peak |
| PV | `EPI_PV` | measured output, used as a forecast with added error |
| Prices, CO₂, weather, holidays | `01exogenous_data` | German day-ahead prices, emission factors, shift and holiday calendar |
| Jobs | processing runs of the TEC machines | each run becomes a job (energy, duration, profile); windows from the shift calendar plus documented deadline and order assumptions |

**Go/no-go checks once the data are downloaded:**

1. Idle share: the fraction of each machine's energy drawn in standby or idle, in and outside shifts.
2. Peak coincidence: how often the TEC machines' peaks overlap.
3. PV overlap: how much PV output falls in hours with flexible load.

If peaks rarely coincide, planning becomes the minor part and diagnosis the major one.

## 4. Artifact

```
Plant manager (plan in ordinary language, approves recommendations)
            │
     ┌──────▼──────┐
     │ Orchestrator│  splits the request, resolves goal conflicts, writes the recommendation
     └──┬───────┬──┘
        │       │
 ┌──────▼──┐ ┌──▼────────┐
 │ Energy  │ │ Planner   │
 │ Auditor │ │ (jobs,    │
 │         │ │ peak, PV, │
 │         │ │ CO₂)      │
 └────┬────┘ └────┬──────┘
      │           │
 ── deterministic harness: data access, state classification, MILP, independent checker ──
```

**Tools** (all arithmetic and search inside them):

| Tool | Used by | Returns |
|---|---|---|
| `machine_states(machine, period)` | Auditor | time and energy per machine state, in and outside shifts |
| `waste_report(period)` | Auditor | off-shift idle energy, standby energy, avoidable peaks (kWh, EUR, kgCO₂) |
| `site_profile(period)` | both | load, peak, PV and self-consumption |
| `get_prices`, `get_emissions`, `get_pv_forecast` | Planner | series for the planning horizon |
| `optimize_plan(jobs, objective_weights, limits)` | Planner | MILP schedule with order, operator-shift and peak constraints |
| `check_plan(plan)` | harness (always) | violations of deadlines, order, shifts and the peak limit |
| `compare_plans(a, b)` | Orchestrator | differences in cost, peak and CO₂ |

**Reused from the household thesis code:** harness pattern (`Checker`, `run_react`, recovery nudge, step
budgets), the optimiser-tool design, the `systems.py` registry, campaign runner and cost accounting, the
statistical analysis (Wilcoxon, Holm), the pre-registration workflow and the Nuxt demo.

## 5. Evaluation

**Task A, diagnosis (SQ1).** Input: one week of site data. Output: ranked waste findings with kWh, EUR and CO₂.
Ground truth computed deterministically from machine states and the shift calendar. Metrics: recall and
precision of findings, error of the estimates, and an expert rating of how actionable the recommendations are
(if available). Baselines: a rule-based report with fixed thresholds; a language model without tools given
summary statistics.

**Task B, weekly planning (SQ2, SQ3).** About 30-50 weeks of the TEC year. Jobs from recorded processing runs;
each week gets an informal plan text (for example "the DMU job must finish by Thursday noon, operators are in
07-16, keep the peak under X kW") with annotated constraints as the answer key.

- Systems: as recorded; earliest-deadline-first with a peak-aware rule; language model without tools;
  single agent in the harness; the multi-agent pipeline; MILP optimum (upper bound).
- Metrics: cost, peak, CO₂, valid plans, correctness of extracted constraints, latency, API cost.
- Held-out weeks with hypotheses registered before the run.

## 6. Timeline (about 5 months; check against the deadline)

| Month | Work |
|---|---|
| 1 | Literature (industrial demand response, energy-aware scheduling, LLM agents in manufacturing); data pipeline; state classification; go/no-go checks |
| 2 | MILP with order and shifts; waste ground truth; baselines; informal-plan benchmark with annotations |
| 3 | Agents and tools; exploratory design iterations |
| 4 | Pre-registration, held-out run, analysis |
| 5 | Writing |

## 7. Risks

| Risk | Mitigation |
|---|---|
| Job deadlines and order are not in SPARK | document them as assumptions, identical across systems; weight diagnosis, which needs none |
| The optimiser does all the work again | count interpretation, trade-offs and diagnosis as the agents' contribution and measure them directly (SQ1, SQ3) |
| TEC covers only 1 year; PV is small (8-10 kW) | use EPI's 7 years for diagnosis; treat PV as a secondary goal |
| German industrial tariff (power charge on the annual peak) | cite the tariff structure; set the peak price from a published tariff sheet |
| 5-second data volume | aggregate once to 1 min and 15 min (Parquet), keep active power only |
| Effort and timing of a full rewrite | see section 8 |

## 8. Rewrite or extend?

- **Full rewrite:** stronger if the go/no-go checks show real waste and peak conflicts; costs a new literature
  review, benchmark, pre-registration and results.
- **Lower risk:** keep the household thesis (finished, confirmatory results) and add an exploratory chapter
  "Transfer to an industrial site" with SPARK diagnosis and a planning pilot, showing that the design
  generalises without discarding the registered results.

Decide after the go/no-go checks, together with the supervisor.

## 9. Related exploratory work in this repository

- `prototypes/hipe/`: five HIPE plant days (the EPI plant, Oct 2017). MILP saved 4.9 % of the flexible jobs'
  cost; the smart timer, `multi_duo` and `single_harness` (GPT-6 Luna) all reached the optimum on 5 of 5 days.
- `prototypes/heatpump/`: REFIT + When2Heat + Norwegian EV sessions, a joint heating and charging LP.
