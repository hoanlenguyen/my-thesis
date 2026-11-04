# Master's Thesis Review, Methodology & 20-Plan Benchmark Specification
**Topic:** A Language-Model Agent as the Interface of a Home Energy Gateway  
**Field:** Information Processing Science (Design Science Research)  
**Date:** 1 November 2026  

---

## Part 1: Supervisor & Examiner Review of the Thesis Plan

### 1.1 Overall Verdict
**Strong Approve (with structural and scope refinements).**  
The proposal addresses a genuine bottleneck in residential energy flexibility: Model Predictive Control (MPC) outperforms static rules by ~13.5%, but requires mathematical parameter tuning and schedule updates that ordinary households cannot maintain. Grounding the proposal in exploratory prototypes (`prototypes/`) provides strong empirical maturity. To succeed as an Information Processing Science thesis within a 20-week window, the work must strictly protect its scope and balance the *energy optimization math* with *software architecture, deterministic safety guardrails, and rigorous evaluation of agentic behavior*.

### 1.2 Five Key Weaknesses & Actionable Fixes

1. **Scope Overload (The "Do Everything" Trap)**
   * *Problem:* Building a natural language plan interpreter, a historical auto-configurator, a deterministic safety harness, a 4-asset closed-loop simulator (PV, battery, heat pump, EV), and a physical Home Assistant demo in 20 weeks carries high schedule risk.
   * *Fix:* Downgrade the Home Assistant demo to a lightweight "Proof-of-Concept Integration Script" (or optional demonstration). Center the primary thesis contribution on **SQ1 (Plan Interpretation)** and **SQ3 (Safety/Reliability via the Deterministic Checker)**, treating **SQ2 (Weekly Configurator)** as a secondary enhancement.

2. **Human Usability Claims vs. Purely Algorithmic Metrics**
   * *Problem:* The RQ asks how to make a gateway "usable without expert configuration," yet hypotheses H1–H6 measure precision/recall, energy cost, and tokens—with zero human participants.
   * *Fix:* Either soften the claim from "human usability" to "automated intent-to-constraint translation and self-configuration," or have a second person (and optionally 2–3 peers) author natural-language prompts during the benchmark creation phase to prove the agent handles non-author phrasing.

3. **Circularity Risk in the "Tuned MPC" Baseline**
   * *Problem:* If the reference "Tuned MPC" is tuned via global grid search with hindsight while the Agent Configurator tunes weekly from rolling history, the comparison must be strictly separated across datasets.
   * *Fix:* Tune the reference MPC *once* via grid search on the 100 house-day **exploratory set** and freeze its parameters for the **held-out test set**. The Agent Configurator starts from uncalibrated defaults and adapts weekly using only past rolling windows via `backtest(settings, weeks)`.

4. **Local Model Latency & Real-Time Feasibility (`gpt-oss-20b`)**
   * *Problem:* Taking ~74 seconds per plan or ~152 seconds per day locally is acceptable for a weekly configurator, but over a minute of latency during an interactive user plan change degrades user experience.
   * *Fix:* Explicitly evaluate 95th-percentile turn latency in **SQ3/H5** and justify the **two-agent split** (fast event-driven Household Assistant vs. slow weekly analytical Configurator) around latency and compute boundaries.

5. **Fair Baseline Configuration for EMHASS**
   * *Problem:* Comparing against EMHASS with out-of-the-box defaults is unfair if EMHASS is fed inferior weather/price forecasts compared to your MPC.
   * *Fix:* Ensure EMHASS receives the exact same DWD weather and SMARD/BDEW price forecasts and runs over the exact same 15-minute control layer.

---

## Part 2: Systematic Literature Review (SLR) Protocol

Follow Kitchenham’s guidelines for Software Engineering SLRs during Weeks 1–3.

### 2.1 Search String (Scopus / Web of Science)
Query against Title, Abstract, and Keywords (`TITLE-ABS-KEY`):

```text
( "home energy management" OR "HEMS" OR "smart home energy" OR "residential demand response" OR "building energy management" OR "home energy gateway" ) 
AND 
( "large language model*" OR "LLM*" OR "language-model agent*" OR "agentic" OR "ReAct" OR "natural language interface*" OR "foundation model*" ) 
AND 
( "model predictive control" OR "MPC" OR "MILP" OR "linear programming" OR "optimisation" OR "optimization" OR "load scheduling" OR "constraint*" )
```

### 2.2 Inclusion and Exclusion Criteria

| Criterion | Rule | Rationale |
|---|---|---|
| **I1: Recency** | 2022 – 2026 | Modern LLM tool-calling, structured outputs, and ReAct loops emerged post-2022. |
| **I2: Domain** | Residential / behind-the-meter assets | Must involve scheduling or control of PV, battery, EV, heat pump, or household appliances. |
| **I3: LLM Role** | Interface, translator, configurator, or scheduler | Must examine LLMs generating constraints, tuning parameters, or scheduling loads. |
| **E1: Grid-Scale** | Utility/transmission unit commitment | Out of scope for single-home gateway architectures. |
| **E2: Passive NLP** | Pure Q&A chatbots or bill summarization | Lacks closed-loop control or mathematical solver integration. |
| **E3: Non-Technical** | Non-English or unvalidated opinion pieces | Retain recent 2025–2026 arXiv preprints in a dedicated "Emerging Literature" bucket. |

### 2.3 Missing Related Work Streams to Integrate
1. **Natural Language to Optimization (NL4Opt):** *OptiMUS* (AhmadiTeshnizi et al., 2024) and *Chain-of-Experts* (Xiao et al., 2023) — foundational patterns for LLM-to-MILP constraint formulation and solver feedback loops.
2. **LLM Building & HVAC Control:** Work by Zhang et al. (2024/2025) on LLM-assisted MPC weight tuning in building energy systems.
3. **Neuro-Symbolic / Simplex Safety Architectures:** Theoretical grounding for wrapping an unverified AI agent inside a deterministic safety envelope (your **Harness + Checker + Control Layer**).

---

## Part 3: Design Science Research (DSR) Framework

Mapped to Peffers et al. (2007) and Hevner et al. (2004) for Information Processing Science:

### 3.1 Defined DSR Artifacts
* **Artifact 1 (Household Assistant Agent):** Event-driven ReAct loop translating plain-language plans and intra-day changes into validated `HouseholdPlan` constraints.
* **Artifact 2 (Weekly Configurator Agent):** Analytical agent using `history_summary` and `backtest` to tune `MpcSettings` (PV derating by weather class, battery reserve, comfort defaults).
* **Artifact 3 (Deterministic Harness, Checker & Control Layer):** Middleware that validates physical feasibility before commit, runs the LP/MILP solver hourly, holds planned grid exchange every 15 minutes, and triggers deterministic fallbacks on failure.

### 3.2 DSR Cycle Mapping
* **Cycle 1 (Exploratory Prototypes — Completed):** HIPE factory, OPSD industrial, and 12-day `DE_KN_residential4` + 20-plan pilot. *Design changes triggered:* Removed default values from tool docstrings (stopped models copying "50% reserve"); forced battery to absorb forecast errors in the 15-min control layer; aligned end-of-day SoC/thermal valuation between solver and evaluation metric; added 2 validation retries.
* **Cycle 2 (Exploratory Benchmark & Tooling — Weeks 4–11):** Build full toolset and iterate on the 100 house-day exploratory split; perform static grid search for the reference Tuned MPC.
* **Cycle 3 (Pre-Registered Held-Out Evaluation — Weeks 12–15):** Freeze prompts, tools, models, and code; execute 3 runs per house-day (`temperature = 0`) on the held-out dataset + full-year simulation for H6.

---

## Part 4: Refined, Pre-Registrable Hypotheses (H1–H6)

* **H1 (Extraction & Clarification Accuracy — SQ1):** On the held-out plan benchmark, the Household Assistant achieves a pooled constraint item precision $\ge 0.90$, item recall $\ge 0.90$, and a clarification F1-score $\ge 0.85$ on identifying ambiguous or conflicting plans requiring `ask_household`. *(Test: One-sided Clopper-Pearson exact binomial intervals).*
* **H2 (Operational Feasibility & Safety — SQ1):** Across all feasible held-out house-days, closed-loop execution meets household requirements (EV energy within $\pm 1\text{ kWh}$ by departure, zero grid limit violations, and thermal comfort within $< 0.5\text{ degree-hours}$ outside the band) on $\ge 95\%$ of house-days. *(Test: One-sided exact binomial test, $p_0 = 0.95$).*
* **H3 (Economic Non-Inferiority of Plain Language — SQ1):** The daily adjusted energy cost of a plain-language plan interpreted by the agent is non-inferior to the identical plan entered as exact mathematical parameters into the Tuned MPC, within a margin of $\Delta = 5\%$ of the cost gap between rule-based control and perfect foresight. *(Test: Paired one-sided Wilcoxon signed-rank test, Holm-Bonferroni corrected across H1–H3).*
* **H4 (Configurator Effectiveness — SQ2):** Starting from uncalibrated default MPC settings, the weekly Agent Configurator closes at least $70\%$ of the cost-saving gap between Default MPC and the statically Grid-Search-Tuned MPC over the held-out set. *(Test: Paired bootstrap 95% CI on cost-gap ratio).*
* **H5 (Local Model Parity with Harness Support — SQ3):** When wrapped in the deterministic validation harness (with up to 2 validation retries), the local model (`gpt-oss-20b`) achieves within $\Delta = 10\%$ of the cloud model’s constraint recall (H1) and within $\Delta = 5\%$ of its requirement satisfaction rate (H2), with a 95th-percentile response latency $< 90\text{ s}$ per event. *(Test: Paired McNemar and Wilcoxon tests).*
* **H6 (Net Energy & Economic Balance — SQ3):** Over a 1-year simulation, annual monetary and kWh savings over rule-based control exceed the combined annual cost of gateway idle power, local inference energy (Wh), and cloud API fees. *(Test: Annual simulation accounting with hardware power sensitivity bounds: 4W RPi5 vs. 15W Mini-PC).*

---

## Part 5: The 20-Plan Edge-Case Benchmark Specification

### 5.1 Adjudication Rules for the Four Open Pilot Questions

1. **Resolution of Infeasible Change Case C3 (25 kWh in 5.5h at 3.7 kW):**
   * *Physical Math:* From `23:30` to `05:00` is $5.5\text{ hours}$. At $3.7\text{ kW}$, maximum energy delivery is $5.5 \times 3.7 = 20.35\text{ kWh}$. Requesting $+25\text{ kWh}$ is physically impossible by $4.65\text{ kWh}$.
   * *Rule:* Reclassify C3 into **Category D (Conflicting/Infeasible Plans — X1)** and replace C3 in Category B with a feasible intra-day change. For X1, the ground-truth key requires `expected_action = "keep_previous_and_ask"`, flagging `infeasible_ev_charge_rate` after `preview_plan()` fails the checker.
2. **Handling Past Items in Intra-Day Changes ($t_{\text{now}} > 00:00$):**
   * *Rule:* **Exclude completed past events ($t_{\text{end}} \le t_{\text{now}}$) from the updated `HouseholdPlan`.** Because the MPC optimizes from $t_{\text{now}}$ forward using the measured physical state of charge and indoor temperature at $t_{\text{now}}$, past constraints are obsolete. The answer key only contains active/future constraints ($t_{\text{end}} > t_{\text{now}}$).
3. **Scoring Constraints on Conflicting/Ambiguous Plans:**
   * *Rule:* Separate **extracted candidate parameters** from **committed execution**. When a plan has an unresolved conflict or critical missing parameter, `commit` MUST be `false` (`keep_previous_and_ask`). However, the model should still populate the unambiguous candidate items in `propose_constraints` (or `candidate_constraints`) so item recall and checker feedback can be evaluated.
4. **Relationship Between `away_periods` and `comfort_bands`:**
   * *Rule:* Define `away_periods` as a semantic macro that maps to the house’s setback temperature band (`17.0–24.0 °C`, compared to baseline `20.0–22.0 °C`). Scoring evaluates **both** item-level match (start/end within $\pm 15\text{ min}$) and the flattened 96-step (15-min) `comfort_hours_agree` vector, crediting the agent whether it uses `away_periods` or an explicit `comfort_overrides` setback.

### 5.2 Canonical Pydantic / JSON Schema (`HouseholdPlan` & Answer Key)

House constants (`DE_KN_residential4`): EV battery = $40\text{ kWh}$, EV charger = $3.7\text{ kW}$ ($9.25\%\text{ SoC/h}$), default comfort = $20\text{--}22\text{ }^\circ\text{C}$, away setback = $17\text{--}24\text{ }^\circ\text{C}$. Evaluation tolerances: time $\pm 15\text{ min}$, SoC $\pm 5\%$, energy $\pm 1.0\text{ kWh}$.

```python
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

class EVConstraint(BaseModel):
    departure_time: str = Field(..., description="HH:MM (or +1d HH:MM for next day)")
    target_soc_pct: Optional[float] = Field(None, ge=0, le=100, description="Target SoC % (on 40 kWh battery)")
    added_energy_kwh: Optional[float] = Field(None, ge=0, le=40, description="Added energy in kWh")
    is_physically_feasible: bool = Field(True, description="True if required_kwh <= (available_hours * 3.7)")

class ApplianceWindow(BaseModel):
    appliance: Literal["dishwasher", "washing_machine", "dryer"]
    earliest_start: str = Field(..., description="HH:MM")
    latest_finish: str = Field(..., description="HH:MM (or +1d HH:MM)")
    duration_min: int = Field(120, ge=15, le=300, description="Default cycle length if not specified")

class AwayPeriod(BaseModel):
    start_time: str = Field(..., description="HH:MM")
    end_time: str = Field(..., description="HH:MM")

class ComfortOverride(BaseModel):
    start_time: str = Field(..., description="HH:MM")
    end_time: str = Field(..., description="HH:MM")
    min_temp_c: float = Field(..., ge=15.0, le=26.0)
    max_temp_c: float = Field(..., ge=16.0, le=28.0)

class BenchmarkPlanKey(BaseModel):
    plan_id: str
    category: Literal["simple", "change", "ambiguous", "conflicting"]
    timestamp_now: str = Field("00:00", description="Current clock time HH:MM when message arrives")
    initial_ev_soc_pct: float = Field(50.0, description="EV SoC % at timestamp_now")
    ev_plugged_in: bool = True
    prior_active_plan_summary: Optional[str] = None
    household_message: str

    # Ground-Truth Active/Future Constraints (for t > timestamp_now)
    ev_constraints: List[EVConstraint] = []
    appliance_windows: List[ApplianceWindow] = []
    away_periods: List[AwayPeriod] = []
    comfort_overrides: List[ComfortOverride] = []

    # Ground-Truth Decision & Clarification
    expected_decision: Literal["commit", "keep_previous_and_ask"]
    requires_clarification: bool
    clarification_reasons: List[
        Literal[
            "missing_departure_time",
            "missing_target_soc",
            "vague_time_window",
            "infeasible_ev_charge_rate",
            "contradictory_ev_availability",
            "conflicting_comfort_instructions"
        ]
    ] = []
```

---

### 5.3 The 20-Case Benchmark Matrix & Ground-Truth Answer Keys

#### Category A: Simple Plans (6 Cases — `timestamp_now = 00:00`, `expected_decision = commit`)

* **S1 (Standard Morning Commute)**
  * *State:* `t_now = 00:00`, `initial_ev_soc = 50%` (20 kWh).
  * *Prompt:* `"I need the car at 80% by 07:30 tomorrow morning. Keep the house at normal temperature."`
  * *Key:* `ev_constraints`: `[dep="07:30", target_soc_pct=80.0, added_energy_kwh=12.0, feasible=True]` (needs 3.24h $\le$ 7.5h). `comfort`: default `20–22°C`. `requires_clarification`: `False`.
* **S2 (Workday Away + Dishwasher)**
  * *State:* `t_now = 00:00`, `initial_ev_soc = 60%`.
  * *Prompt:* `"We will be away at the office from 08:30 to 17:00. Run the dishwasher so it's finished before we get home."`
  * *Key:* `away_periods`: `[08:30–17:00]` (maps to `17–24°C`). `appliance_windows`: `[app="dishwasher", start="00:00", finish="17:00"]`. `requires_clarification`: `False`.
* **S3 (Morning Warm-Up Boost + kWh EV Target)**
  * *State:* `t_now = 00:00`, `initial_ev_soc = 40%`.
  * *Prompt:* `"Warm the house to 22–23 °C between 06:00 and 08:00, and add 15 kWh to the car by 08:00."`
  * *Key:* `comfort_overrides`: `[06:00–08:00, 22.0–23.0°C]`. `ev_constraints`: `[dep="08:00", added_energy_kwh=15.0, target_soc_pct=77.5, feasible=True]` (needs 4.05h $\le$ 8.0h). `requires_clarification`: `False`.
* **S4 (Work from Home + Solar Laundry)**
  * *State:* `t_now = 00:00`, `initial_ev_soc = 70%`.
  * *Prompt:* `"Working from home all day, don't need the car. Run the washing machine between 10:00 and 15:00."`
  * *Key:* `ev_constraints`: `[]`. `appliance_windows`: `[app="washing_machine", start="10:00", finish="15:00"]`. `requires_clarification`: `False`.
* **S5 (Full Charge + Night Setback)**
  * *State:* `t_now = 00:00`, `initial_ev_soc = 50%`.
  * *Prompt:* `"Charge the EV to 100% by 06:30, and lower the heating to 18–20 °C from midnight until 06:00."`
  * *Key:* `ev_constraints`: `[dep="06:30", target_soc_pct=100.0, added_energy_kwh=20.0, feasible=True]` (needs 5.41h $\le$ 6.5h). `comfort_overrides`: `[00:00–06:00, 18.0–20.0°C]`. `requires_clarification`: `False`.
* **S6 (Evening Errand + Dryer Deadline)**
  * *State:* `t_now = 00:00`, `initial_ev_soc = 45%`.
  * *Prompt:* `"We're going out from 18:00 to 22:00. Have the car at 70% by 18:00 and finish the dryer by 17:30."`
  * *Key:* `ev_constraints`: `[dep="18:00", target_soc_pct=70.0, added_energy_kwh=10.0, feasible=True]`. `appliance_windows`: `[app="dryer", start="00:00", finish="17:30"]`. `away_periods`: `[18:00–22:00]`. `requires_clarification`: `False`.

#### Category B: Intra-Day Changes (5 Cases — `timestamp_now > 00:00`, `expected_decision = commit`)

* **C1 (Completed Morning Trip + New Afternoon Departure)**
  * *State:* `t_now = 10:00`, `initial_ev_soc = 30%`. *Prior Plan:* 08:00 EV departure (completed) and 20–22 °C comfort.
  * *Prompt:* `"I'm back and plugged in. Something came up—I need the car at 75% by 16:30 today."`
  * *Key:* Past 08:00 item omitted. `ev_constraints`: `[dep="16:30", target_soc_pct=75.0, added_energy_kwh=18.0, feasible=True]` (needs 4.86h $\le$ 6.5h available). `requires_clarification`: `False`.
* **C2 (Early Return from Work + Comfort Boost)**
  * *State:* `t_now = 13:00`, `initial_ev_soc = 60%`. *Prior Plan:* `away_periods = [08:30–18:00]`.
  * *Prompt:* `"Heading home early! I'll be back at 14:30 instead of 18:00, and please warm the house to 22–23 °C from 14:30 until 21:00."`
  * *Key:* `away_periods`: `[13:00–14:30]`. `comfort_overrides`: `[14:30–21:00, 22.0–23.0°C]`. `requires_clarification`: `False`.
* **C3 (Feasible Replacement — Evening Trip Cancelled + Dishwasher Delayed)**
  * *State:* `t_now = 19:00`, `initial_ev_soc = 65%`. *Prior Plan:* `away [19:30–22:30]`, `dishwasher finish by 21:00`.
  * *Prompt:* `"We cancelled our evening plans and are staying home tonight. Also, no rush on the dishwasher—just have it done by 07:00 tomorrow."`
  * *Key:* `away_periods`: `[]` (comfort returns to `20–22°C`). `appliance_windows`: `[app="dishwasher", start="19:00", finish="+1d 07:00"]`. `requires_clarification`: `False`.
* **C4 (Deferred EV Deadline to Next Morning)**
  * *State:* `t_now = 15:00`, `initial_ev_soc = 40%`. *Prior Plan:* `ev dep="18:00", target=65%`.
  * *Prompt:* `"Skipping the 18:00 gym trip today. Instead, charge the car to 85% by 07:00 tomorrow morning."`
  * *Key:* `ev_constraints`: `[dep="+1d 07:00", target_soc_pct=85.0, added_energy_kwh=18.0, feasible=True]` (needs 4.86h $\le$ 16.0h). `requires_clarification`: `False`.
* **C5 (Late-Night Target Bump + Added Laundry)**
  * *State:* `t_now = 21:00`, `initial_ev_soc = 60%`. *Prior Plan:* `ev dep="+1d 07:00", target=70%`.
  * *Prompt:* `"Actually, bump the car target to 90% for my 07:00 departure tomorrow, and run the washing machine overnight so it's ready by 06:00."`
  * *Key:* `ev_constraints`: `[dep="+1d 07:00", target_soc_pct=90.0, added_energy_kwh=12.0, feasible=True]` (needs 3.24h $\le$ 10.0h). `appliance_windows`: `[app="washing_machine", start="21:00", finish="+1d 06:00"]`. `requires_clarification`: `False`.

#### Category C: Ambiguous Plans (5 Cases — `expected_decision = keep_previous_and_ask`)

* **A1 (Missing EV Time and Target SoC)**
  * *State:* `t_now = 00:00`, `initial_ev_soc = 35%`.
  * *Prompt:* `"I have a long highway trip tomorrow morning, so make sure the car is well charged."`
  * *Key:* `requires_clarification`: `True`. `clarification_reasons`: `["missing_departure_time", "missing_target_soc"]`.
* **A2 (Vague Afternoon Away Window)**
  * *State:* `t_now = 00:00`, `initial_ev_soc = 50%`.
  * *Prompt:* `"We're visiting friends for a few hours this afternoon, you can turn down the heat while we're gone."`
  * *Key:* `requires_clarification`: `True`. `clarification_reasons`: `["vague_time_window"]`.
* **A3 (Target SoC Given, Departure Time Missing)**
  * *State:* `t_now = 00:00`, `initial_ev_soc = 40%`.
  * *Prompt:* `"Charge the car to 90% before I head out, and run the dishwasher by 18:00."`
  * *Key:* Extracts candidate `dishwasher [00:00–18:00]` and `target_soc_pct=90.0`, but `requires_clarification`: `True`, `clarification_reasons`: `["missing_departure_time"]`.
* **A4 (Departure Time Given, Target SoC & Exact Temp Missing)**
  * *State:* `t_now = 00:00`, `initial_ev_soc = 30%`.
  * *Prompt:* `"Plugged the car in for my 07:00 commute tomorrow. Also make the house extra warm tonight."`
  * *Key:* `requires_clarification`: `True`. `clarification_reasons`: `["missing_target_soc", "vague_time_window"]`.
* **A5 (Ambiguous "Lunchtime" + Sequential Laundry Dependency)**
  * *State:* `t_now = 00:00`, `initial_ev_soc = 45%`.
  * *Prompt:* `"I need the car charged up by lunchtime, and run a load of laundry through the washer and dryer today."`
  * *Key:* `requires_clarification`: `True`. `clarification_reasons`: `["missing_target_soc", "vague_time_window"]`.

#### Category D: Conflicting / Physically Infeasible Plans (4 Cases — `expected_decision = keep_previous_and_ask`)

* **X1 (Former Pilot C3 — Physical Charger Rate Limit Exceeded)**
  * *State:* `t_now = 23:30`, `initial_ev_soc = 20%` (8 kWh).
  * *Prompt:* `"Just got home. I need +25 kWh added to the car before I leave at 05:00."`
  * *Key:* `ev_constraints`: `[dep="+1d 05:00", added_energy_kwh=25.0, target_soc_pct=82.5, is_physically_feasible=False]` (Max possible in 5.5h at 3.7 kW is **20.35 kWh** / 70.9% SoC). `requires_clarification`: `True`. `clarification_reasons`: `["infeasible_ev_charge_rate"]`. Agent must offer ~20.3 kWh by 05:00 or departing at ~06:15.
* **X2 (Simultaneous Away Setback and 23 °C Comfort Boost)**
  * *State:* `t_now = 00:00`, `initial_ev_soc = 50%`.
  * *Prompt:* `"We're away from 09:00 to 17:00 so put the heating into away saving mode, and keep the house at a steady 23 °C from 08:00 to 18:00."`
  * *Key:* `requires_clarification`: `True`. `clarification_reasons`: `["conflicting_comfort_instructions"]`.
* **X3 (EV Scheduled to Charge on Midday Solar While Away at Work)**
  * *State:* `t_now = 00:00`, `initial_ev_soc = 40%`.
  * *Prompt:* `"I'm driving the EV to the office from 08:00 to 17:00 tomorrow. Make sure you charge the car to 90% using our midday rooftop solar between 11:00 and 15:00."`
  * *Key:* `requires_clarification`: `True`. `clarification_reasons`: `["contradictory_ev_availability"]`.
* **X4 (Extreme Short-Notice Charger Infeasibility)**
  * *State:* `t_now = 18:00`, `initial_ev_soc = 10%` (4 kWh).
  * *Prompt:* `"Charge the car to 100% before we leave for dinner at 20:00."`
  * *Key:* `ev_constraints`: `[dep="20:00", target_soc_pct=100.0, added_energy_kwh=36.0, is_physically_feasible=False]` (Max possible in 2.0h at 3.7 kW is **7.4 kWh** / 28.5% SoC). `requires_clarification`: `True`. `clarification_reasons`: `["infeasible_ev_charge_rate"]`.