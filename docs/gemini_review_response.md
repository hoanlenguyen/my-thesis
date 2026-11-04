# Response to Gemini's review of the home energy gateway thesis plan

1 November 2026. A point-by-point assessment of
`thesis_review_methodology_and_20_plan_benchmark_specification.md`. Each point says **Agree**, **Partly** or
**Disagree**, why, and the options. My recommended option is marked (rec.). I checked every number in Gemini's
answer keys and the citations it adds.

Summary: most of the review is sound and several points are already in the plan. The most useful new ideas are
separating *candidate* constraints from the *commit* decision, the clarification F1 score, the p95 latency, the
C3 reclassification, and the Simplex safety framing. The main problems are: H4 lacks a non-LLM auto-tuner
baseline, H2 partly tests the harness instead of the agent, the H6 hardware bounds cannot run the local model, the
benchmark uses a dryer the house does not have and drops calendar dates, and the plans are again written by a
language model, which undercuts its own fix for weakness 2.

---

## 1. Review (five weaknesses)

### 1.1 Scope overload: **Agree, partly on the fix**

The 20-week plan is tight; a Home Assistant demo is the easiest part to cut. Making SQ1 and SQ3 primary is
reasonable. But SQ2 (configuration) is one of the two novelty claims; demoting it weakens the contribution.

Options:
- **A (rec.)** Keep SQ1 and SQ2 both confirmatory, make the Home Assistant demo optional (a replay script), and
  keep SQ2 small: one Configurator decision per week on PV derating and battery reserve only.
- B. Gemini's version: SQ2 secondary and descriptive. Safer schedule, weaker novelty.
- C. Drop SQ2 entirely and focus on interpretation and safety. Simplest; the thesis then resembles existing
  NL-to-constraint work (Sanguinetti et al., Michelon et al.).

### 1.2 Usability claims without users: **Agree**

H1-H6 measure translation, cost and reliability; nothing measures usability. A claim of "usable without an
expert" needs people, or a weaker wording.

Options:
- **A (rec.)** Soften the RQ to "without expert configuration, from plain-language plans" and recruit 3-5 people
  (not the author) to write plans for given scenarios; score the agent on their wording as well as the author's.
  Cheap, and directly tests phrasing bias.
- B. Only soften the wording. No human work, but the plans stay author-written.
- C. A small usability study (SUS questionnaire, 8-10 participants, Home Assistant demo). Strongest claim, needs
  ethics review and the demo, so it conflicts with 1.1.

### 1.3 Circularity of the tuned MPC: **Agree; already in the plan**

The plan already tunes on the exploratory set only and freezes the settings (protocol section 10). Gemini adds
that the Configurator starts from defaults and uses only past weeks, which should be written down explicitly.

One thing Gemini misses: the reference is tuned on *other* house-days but the Configurator tunes on *the same
house's past*. That gives the Configurator a legitimate advantage (house-specific), so it could beat the
reference. The hypothesis should allow that.

### 1.4 Local model latency: **Agree**

Reporting p95 latency per event is right, and the two-agent split is better argued from latency and timing than
from anything else. Pilot numbers: gpt-oss-20b took about 74 s per plan on average, so a p95 under 90 s (H5) is
unlikely as measured. See 3.5.

### 1.5 EMHASS with the same forecasts: **Partly**

Feeding EMHASS the same forecasts isolates the optimiser. But part of what a product does is its own forecasting;
a fair comparison and an "as deployed" comparison answer different questions. The previous thesis reported EMHASS
"as deployed".

Options:
- **A (rec.)** Report both: EMHASS with the shared forecasts (primary, fair) and EMHASS with its default
  forecasts (secondary, as deployed).
- B. Shared forecasts only (Gemini).
- C. As deployed only. Easier to explain to practitioners, but differences then mix forecast and optimiser.

---

## 2. Systematic literature review protocol

### 2.1 Kitchenham guidelines: **Agree**

Fine for a software-engineering-style review. For Information Processing Science, Okoli (2015) or Webster and
Watson (2002) are also accepted; Kitchenham is the more procedural choice and suits a protocol-driven thesis.

### 2.2 Search string: **Partly; needs changes**

- `"HEMS"` also means *helicopter emergency medical services* and will add noise in Scopus. Keep it only joined
  with an energy term, or drop it.
- `"MPC"` and `"optimization"` in the third block are very broad; but the third block may also exclude relevant
  papers that use an LLM as an interface without naming the solver. Consider running the search with and without
  it and reporting both counts.
- `"LLM*"` matches unrelated acronyms (LLM is also a law degree). Use `"large language model*"` and `"LLM-based"`.
- Scopus and Web of Science index few 2025-2026 arXiv preprints, which are most of the directly related work
  (El Makroum, Jonah, Sanguinetti). Add arXiv and Google Scholar searches and backward/forward snowballing
  (Wohlin, 2014). Gemini mentions an "Emerging literature" bucket but no search to fill it.

### 2.3 Inclusion and exclusion: **Agree with one change**

E3 excludes "unvalidated opinion pieces" but then keeps preprints; say plainly that preprints are included and
quality-assessed separately. Add I4: the paper evaluates the system (not a position paper).

### 2.4 Missing related work: **Partly**

- **NL4Opt / OptiMUS / Chain-of-Experts: Agree.** OptiMUS is real
  ([AhmadiTeshnizi et al., ICML 2024](https://mlanthology.org/icml/2024/ahmaditeshnizi2024icml-optimus)).
  Chain-of-Experts (Xiao et al., ICLR 2024) exists to my knowledge but I could not confirm it in this search;
  check before citing. Add the NL4Opt competition (Ramamonjison et al., 2022). These are the right stream for
  "plain language to constraints".
- **"Zhang et al. (2024/2025) on LLM-assisted MPC weight tuning": Disagree as cited.** I found no such paper.
  Related work exists: an LLM adjusting reward weights of an RL HVAC controller
  ([Building Simulation 2026](https://www.sciopen.com/article/10.1007/s12273-026-1467-3)), an LLM-enhanced MPC
  for HVAC ([Energies 2025](https://www.mdpi.com/1996-1073/18/7/1813)), and a
  [2026 review of LLMs for HVAC](https://arxiv.org/pdf/2609.05314). Cite those instead; the absence of an
  LLM-tunes-MPC paper supports the novelty of SQ2.
- **Simplex / runtime assurance: Agree, strongly.** The Simplex architecture (Sha, 2001) is exactly the
  pattern of an unverified controller inside a verified envelope with a safe fallback, and gives the harness a
  theoretical basis it currently lacks.

---

## 3. Design Science Research framework

### 3.1 Peffers et al. and Hevner et al.: **Agree**

### 3.2 Three artifacts: **Partly**

Splitting into Assistant, Configurator and Harness makes contributions visible, but evaluating three artifacts
triples the reporting. The harness is mostly carried over and is not new.

Options:
- **A (rec.)** One artifact, the gateway agent system, with three components, evaluated as a whole plus
  component ablations (single-agent variant; no checker; no Configurator).
- B. Three artifacts as Gemini says. Clearer contributions, more writing.

### 3.3 Cycle mapping: **Agree with one change**

Cycle 1 lists HIPE and OPSD industrial. Those prototypes did not change the gateway design; cite them as
background, not as a design cycle. The gateway pilot and the plan pilot are the real Cycle 1.

---

## 4. Hypotheses

### 4.1 H1 extraction plus clarification F1 >= 0.85: **Agree on content, disagree on the test**

Adding clarification F1 is good: it also punishes unnecessary questions. But:
- Items are clustered within plans (one plan has 1-3 items), so pooled Clopper-Pearson intervals treat them as
  independent and are too narrow. Use a cluster bootstrap over plans, or a test per plan.
- Showing recall **>= 0.90** needs the lower confidence bound above 0.90. With a true recall of 0.95, that needs
  roughly 150-200 items. The held-out set must be sized for this (a power calculation belongs in the
  registration). Twenty plans are not enough.

### 4.2 H2 requirements met on >= 95 % of house-days: **Partly**

"Zero grid limit violations" is enforced by the checker and the control layer, so it tests the harness, not the
agent, and will pass by construction. EV energy and comfort do depend on the agent's interpretation.

Options:
- **A (rec.)** Keep H2 on household requirements only (EV, comfort, away, appliances), scored against the
  *answer key's* requirements, not the agent's own constraints. Report grid-limit violations as a safety
  invariant (expected zero), outside the hypothesis family.
- B. Keep Gemini's H2. It will pass trivially on the grid part.

The 0.5 degree-hour comfort tolerance and +-1 kWh EV tolerance are sensible.

### 4.3 H3 non-inferiority margin 5 % of the rules-to-optimum gap: **Agree**

Expressing the margin as a share of the gap is better than EUR, because daily costs vary widely. Justify 5 % in
the registration (for example, it is smaller than the gap between tuned and default MPC in the pilot, about 20
points).

### 4.4 H4 Configurator closes >= 70 % of default-to-tuned gap: **Partly; a baseline is missing**

The 70 % is arbitrary but acceptable if justified. The larger problem: in the pilot, almost all of the tuned
MPC's gain came from one parameter (PV derating). A deterministic script running the same `backtest` over a small
grid on past weeks would likely find it too. Without that baseline, H4 cannot show the language model adds
anything.

Options:
- **A (rec.)** Add a **deterministic auto-tuner** (rolling grid search with the same backtest and the same
  history) as a baseline. H4a: the Configurator reaches X % of the tuned gap; H4b: it is non-inferior to the
  auto-tuner and better at what the auto-tuner cannot use (household-stated changes, explaining why). If the
  auto-tuner matches it, report that honestly; it is a real finding.
- B. Keep H4 alone. Risk: an examiner asks why an LLM is needed for a grid search.
- C. Narrow the Configurator to settings that need interpretation (comfort defaults, flexible-load windows
  from history plus what the household said), leaving numeric tuning to the auto-tuner.

### 4.5 H5 local parity within 10 % recall, 5 % requirements, p95 < 90 s: **Partly**

- In the pilot, gpt-oss-20b reached recall 0.43 against 0.95 for GPT-6 Luna, even with retries. H5 as written
  will most likely fail. Registering a hypothesis expected to fail is legitimate but should be a deliberate
  choice.
- "Within 10 %" must say relative or absolute (0.95 vs 0.86 or vs 0.855).
- 74 s mean in the pilot makes p95 < 90 s unlikely on the current laptop.

Options:
- **A (rec.)** Compare 2-3 local models in the exploratory phase (for example a stronger local model alongside
  gpt-oss-20b) and register H5 with the best one; keep the latency threshold but state the hardware.
- B. Keep gpt-oss-20b and expect a negative H5; report it as a finding about local deployment.
- C. Make H5 descriptive.

### 4.6 H6 net energy balance with 4 W RPi5 vs 15 W mini-PC: **Disagree with the hardware bounds**

A Raspberry Pi 5 cannot run a 20-billion-parameter model at usable speed, and a 15 W mini-PC would be far slower
than the 74 s per plan measured on a laptop GPU. The bounds do not match a device that runs the model.

Options:
- **A (rec.)** Two configurations: (1) a low-power gateway (RPi-class, a few W) with cloud inference, counting
  API cost; (2) a gateway plus a local inference box (measured GPU energy per call with `nvidia-smi`, plus idle
  power of that box). Compare each with the yearly saving.
- B. Count only inference energy per call, ignoring idle power. Simpler but flattering.

---

## 5. Benchmark specification

### 5.1 Adjudication rules

| Rule | Verdict | Why |
|---|---|---|
| C3 is infeasible, move to conflict/infeasible | **Agree** | 23:30 to 05:00 is 5.5 h; at 3.7 kW that is 20.35 kWh, less than 25. Checked. |
| Drop past items from an updated plan | **Agree** | The MPC plans from now with the measured state; past items cannot be acted on. |
| Separate candidate constraints from the commit decision | **Agree, strongly** | It lets recall be scored on ambiguous plans and matches the `AssistantDecision` design. |
| Away as a macro for a setback band 17-24 °C | **Partly** | Use the household's stated temperature when given (our S1 says "cool down to 18"); fall back to the house default only when none is said. The upper bound of 24 °C matters only in summer. |

### 5.2 Schema: **Partly**

- **Times as "HH:MM" and "+1d HH:MM"** are fragile around midnight and cannot express a weekend away. Keep full
  ISO date-times as in the current pilot.
- **`is_physically_feasible` and `added_energy_kwh` in the model's output** should not be asked of the
  language model: feasibility is the checker's job. Keep them in the answer key only.
- **`dryer`**: the main house (`DE_KN_residential4`) has a dishwasher and a washing machine but no dryer. S6 and
  A5 use one. Drop the dryer or use another OPSD house that has one.
- **Default duration 120 min** for every appliance: the house context says the dishwasher cycle is about 2.5 h.
  Durations should come from the house's measured cycles.
- **Clarification reasons** lack `missing_temperature` (A4 "extra warm" has no temperature) and a reason for
  sequences (A5 washer then dryer). Add them, or keep the reason list open with free text plus a category.
- **No dates.** Gemini's plans have clock times only. To score H2 in closed loop, each plan must be bound to a
  real house-day (season, weather, prices). The current pilot plans carry dates for this reason.

### 5.3 The 20 cases

**Arithmetic: all correct.** I checked S1, S3, S5, S6, C1, C4, C5, X1 and X4: energies, state-of-charge targets
and charging hours match a 40 kWh battery and a 3.7 kW charger (X1: 8 + 20.35 kWh = 70.9 %, latest feasible
departure about 06:15; X4: 7.4 kWh possible in 2 h, 28.5 %). Charging losses (about 10 %) are ignored; with them
the margins shrink but no feasible case becomes infeasible.

**Cases: mostly good, with these issues:**

| Case | Issue | Option |
|---|---|---|
| S6, A5 | dryer not in the house | replace with washing machine or dishwasher |
| A4 | reason should be `missing_temperature`, not only a vague window | add the reason |
| A5 | washer-then-dryer sequence not expressible | drop the sequence or add a dependency field |
| C2 | away [13:00-14:30] starts at "now"; fine, but test that the agent does not reinstate the old 18:00 end | keep |
| X3 | good conflict (car away while charging is requested) | keep |
| all | written by a language model | see below |

**Coverage lost from the current draft:** the "no grid electricity tonight" conflict (needs PV or battery to
judge feasibility, so it tests `preview_plan`), multi-day requests ("away for the weekend"), and seasonal
variety (winter heating vs summer PV). Keep these.

**Who writes the plans.** Gemini's fix for weakness 2 is to have people other than the author write plans, but
its benchmark is again written by a language model. LLM-written plans are likely easier for LLMs (same style,
explicit numbers). Options:
- **A (rec.)** Use Gemini's 20 cases (fixed as above) as the *edge-case pilot set* for the exploratory phase; the
  held-out benchmark is written by 3-5 people from scenario prompts, keyed by the author, checked by a second
  person.
- B. Use LLM-written plans throughout and state it as a limitation.

**Size.** Twenty plans are a pilot, not the benchmark. The plan already calls for about 100 exploratory
house-days and a held-out set sized by a power calculation (4.1).

---

## 6. Decisions for the author

1. Scope: keep SQ2 confirmatory but small (1.1 A), or demote it (1.1 B)?
2. People writing held-out plans (1.2 A, 5.3 A)?
3. Add the deterministic auto-tuner baseline to H4 (4.4 A)?
4. Which local models to compare before registering H5 (4.5 A)?
5. Adopt Gemini's 20 cases with the fixes above as the edge-case pilot set?
