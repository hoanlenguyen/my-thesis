# SLR protocol (PRISMA-P 2015 structure), draft for the author's confirmation

Phase 1 output of the ARS `deep-research` `systematic-review` mode, 24 November 2026. Built from
`docs/protocol_home_gateway.md` section 13 and thesis Sections 2.1 (`sec:slrreview`) and 3.x (`sec:slr`) of
`gateway_body.tex`. Nothing here changes the thesis text. Items marked **DECIDE** need the author's decision before
Phase 2; items marked **DEVIATION** must be reported as deviations in the review.

## Administrative information

- **Title:** Language models for interpreting household plans and configuring optimisers in home energy management,
  and their use on local hardware: a systematic literature review (protocol).
- **Registration:** none so far. **DECIDE:** register this protocol on OSF (Generalized Systematic Review
  Registration form) before the author's screening check is finished. Kitchenham and Charters (2007) do not require
  registration; PRISMA 2020 item 24 asks the review to say whether it was registered.
- **Authors:** Hoan Le (reviewer 1, guarantor). Supervisors Yueqiang Xu and Paula Alavesa (planned sample check of
  screening decisions). **DECIDE:** whether a supervisor acts as second reviewer on a sample (see Selection).
- **Support:** none external (master's thesis, University of Oulu).
- **Amendments:** see the table at the end.

## Introduction

### Rationale

Optimisers such as MPC need parameters and settings that households cannot give. Studies that let a language model
read plain-language plans or set up an optimiser mostly use large cloud models. No review is known that covers
(a) language models turning household plans into optimiser inputs, (b) language models configuring an optimiser or
controller in home or building energy management, and (c) small or locally run language models for these tasks.
**DECIDE:** the claim "no review is known" must be backed by a documented search for existing reviews (Scopus with a
`review` document-type filter on run A, plus arXiv); the protocol names arXiv 2609.05314 as a review to check.

### Objectives (PICOC, Kitchenham; maps to PICOS)

| Element | Definition |
|---|---|
| Population | Home and building energy management: behind-the-meter assets (appliances, PV, batteries, heat pumps, EV chargers, whole homes or buildings); for LQ3 any energy management system |
| Intervention | A language model (any size) that interprets requirements, generates constraints, tunes parameters, schedules loads or controls devices |
| Comparison | Rules, optimisers without a language model, other language models (cloud vs local), human experts, or none |
| Outcomes | LQ1: accuracy of interpreting requirements, validity, clarification behaviour, checks and fallbacks; LQ2: cost, comfort or control performance vs the comparator, tuned parameters; LQ3: accuracy, latency, energy, cost, privacy, hardware |
| Context / Study design | Evaluated systems: simulation, data-driven, field or hardware studies; preprints included and rated separately |

Review questions (thesis Section 2.1): **LQ1** how language models turn what a household says into inputs for energy
management, and what makes their outputs reliable; **LQ2** how language models are used to set up an optimiser or
controller in home or building energy management, and what they are compared with; **LQ3** which language models run
on local hardware for energy or smart-home tasks, and how they compare with cloud models.

## Methods

### Eligibility criteria

| Criterion | Include | Exclude |
|---|---|---|
| I1 Date | 2022-2026 | earlier |
| Language | English | E3 other languages |
| I2 Setting | residential or behind-the-meter assets, homes, buildings; search B: any EMS with a small or local LM evaluated | E1 grid-scale operation (unit commitment, markets, data centres) without a household or building |
| I3 Role of the LM | interprets requirements, generates constraints, tunes parameters, schedules loads or controls devices | E2 forecasting, question answering, bill summaries or text analysis only, without control |
| I4 Evaluation | the system is evaluated with data | position papers without evaluation (kept as background) |
| Publication type | journal and conference papers, preprints, reviews (as background and for snowballing) | — |

**DECIDE (consistency):** three versions of the criteria exist. `protocol_home_gateway.md` excludes E1-E3 only;
`prescreen.py` also excludes the energy use of language models themselves and treats reviews and position papers as
background; the thesis text excludes position papers without evaluation. This protocol takes the union above. Confirm,
then align the thesis text and `prescreen.py` docstring.

### Information sources

| Source | Status (searched 11 Nov 2026) |
|---|---|
| Scopus | run A 543, run B 129 records, exported |
| ScienceDirect | A1+A2 63, B 1, exported |
| arXiv (cs, eess, math.OC) | A 126, B 1, exported |
| IEEE Xplore | 301 and 35 hits, **not exported** (no institutional access). **DEVIATION** |
| Web of Science | **not searched** (subscription not reachable). **DEVIATION** |
| Google Scholar | snowballing and grey literature only; not yet run |
| Backward and forward snowballing (Wohlin, 2014) | after full-text screening; not yet run |

### Search strategy

Strings as in `protocol_home_gateway.md` section 13 and thesis Appendix (`app:search`). 863 records, 732 after
de-duplication by DOI and title (`merge.py`).

**Sensitivity check against known studies (done 24 Nov 2026, `out/screening.csv`):**

| Known study (read before the search) | Retrieved |
|---|---|
| Michelon et al. (2025) | yes (R0496) |
| El Makroum et al. (2025) | yes (R0299, R0610) |
| Jonah et al. (2026) | yes (R0175) |
| HEMA, arXiv 2602.15219 | yes (R0138) |
| AgentiControl-MPC | yes (R0349) |
| **Sanguinetti et al. (2025), arXiv 2503.21360** "From user preferences to optimization constraints using large language models" | **no** |
| AutoControl-MPC (2026) | no (reference not yet verified) |
| review arXiv 2609.05314 | no (reference not yet verified) |
| NL4Opt, OptiMUS, Chain-of-Experts | no; expected, they are not about energy (related stream, background) |

Sanguinetti et al. is a core LQ1 study. Its abstract speaks of "home appliances", "energy optimization constraints"
and a "renewable energy community": the arXiv run A energy block does not match, and in Scopus "appliances" is four
words from "optimization", outside `W/3`. Recheck AutoControl-MPC and arXiv 2609.05314 once their references are
verified.

**Supplementary search C (decided by the author 24 Nov 2026; amendment).** Concept: a language model AND a household
asset or setting AND optimisation, constraints or control, without requiring "energy management". Terms come from the
concept; the missed study is used only as a known-item check. Script `prototypes/slr/supplementary_search.py`.

```text
arXiv (abstracts, 2022-2026), run 24 Nov 2026
("language model" OR "language models" OR LLM OR LLMs)
AND (appliance OR appliances OR household OR households OR residential OR "energy community" OR prosumer
  OR prosumers OR "electric vehicle" OR "electric vehicles" OR "heat pump" OR "heat pumps" OR thermostat OR HVAC)
AND (constraint OR constraints OR optimization OR optimisation OR scheduling OR "model predictive control"
  OR MPC OR controller)

Scopus (Advanced search; to be run by the author, export as out/scopus_C.csv)
TITLE-ABS-KEY ( ( "large language model*" OR "small language model*" OR LLM* OR "language model*" )
  AND ( appliance* OR household* OR residential OR "energy communit*" OR prosumer* OR "electric vehicle*"
  OR "heat pump*" OR thermostat* OR HVAC )
  AND ( constraint* OR optimi?ation OR schedul* OR "model predictive control" OR MPC OR controller* ) )
AND PUBYEAR > 2021 AND PUBYEAR < 2027 (same document-type and language limits as run A)
```

Result (arXiv): 171 hits; 21 already in `screening.csv`; **150 new** in `out/supplementary_C.csv` (ids S0001-S0150,
decision and reason empty); known-item check passed (Sanguinetti et al. = S0113). Most new records are household
robotics (the term "household" with "planning" or "control"); they are excluded at title screening under I2/I3. They
are screened in the same way as the main set and counted separately in the PRISMA flow ("records from supplementary
search"). Scopus C: not yet run.

AI pre-screen of the 150 (`prototypes/slr/prescreen_c.py`, 24 Nov 2026; same criteria and conventions as
`prescreen.py`): keyword triage excluded 91; the abstracts of the other 58 were read (plus S0033, kept on purpose as
LQ3 background although it fails the triage). Result: **7 include** (S0113 Sanguinetti et al., S0121, S0030, S0079,
S0046, S0069, S0039), **5 unsure** (S0131, S0020, S0036, S0140, S0033), **138 exclude**. S0146 is the arXiv
preprint (2308.10380) of R0696 (Jin et al., IEEE SmartGridComm 2024; same authors and method): merged by the author's
decision, the published version R0696 is kept and S0146 is counted as a duplicate removed in the PRISMA flow. S0023, a systematic review of 66 LLM studies for HVAC operations
(2023 to March 2026), is kept as background and as a source for snowballing; it also counts for the search for existing
reviews (Rationale). The author checks every decision, as for the main set.

### Study records

- **Data management:** CSV files in `prototypes/slr/out/` (`screening.csv`, one row per record with decision and
  reason); scripts `arxiv_search.py`, `merge.py`, `prescreen.py`.
- **Selection process (as done and planned):**
  1. De-duplication by DOI and normalised title (automatic, `merge.py`).
  2. Keyword triage (automatic, `prescreen.py`): records without both a language-model term and an energy term in
     title or abstract excluded (300 of 732 records).
  3. Title (and abstract where unclear) pre-screen of the remaining 432 by an AI assistant: 53 include, 69 unsure,
     310 exclude, each with a reason.
  4. The author checks every decision; unsure records are decided on the abstract or full text.
  5. Full-text eligibility by the author.
  6. A supervisor checks a random sample.
- **DEVIATION / DECIDE (single reviewer):** a single human reviewer plus an AI pre-screen is weaker than two
  independent reviewers. Proposal: the supervisor screens a random sample of 10% of the 732 records (about 73,
  stratified by AI decision, including some keyword-triage exclusions) blind to the author's decisions; report Cohen's
  kappa and resolve disagreements by discussion. Also check a random sample (e.g. 30) of the 300 keyword-triage
  exclusions by reading the abstract, because no person has looked at them.
- **Data collection:** the extraction form below, piloted on 3 included studies; one extractor (the author), a
  supervisor checks 2 studies. Missing data recorded as "not reported"; authors not contacted.

### Data items (extraction form)

Bibliographic data; publication type (journal, conference, preprint); LQ served; role of the LM (interpret plans,
generate constraints, configure or tune an optimiser, schedule directly, control devices); optimiser or controller
(MPC, MILP, rules, RL, none); assets; checks, clarifications and fallbacks around the LM; model name, version, size,
open or closed weights, where it runs (cloud, local GPU, CPU, edge board); data and horizon; baselines; metrics
(accuracy, cost, comfort, latency, energy, monetary cost per call, privacy); main results; code or data available.

### Quality (risk of bias) assessment

RoB 2 and ROBINS-I are designed for clinical and intervention studies and do not fit engineering evaluations of
software systems. **DECIDE:** use a Kitchenham-style quality checklist, scored yes / partly / no per study, by the
author with a supervisor check on a sample:

1. Model and version stated (so the result can be reproduced)
2. Data described (source, size, horizon)
3. Baseline without a language model reported
4. More than one run or a variance measure reported (language-model output varies between runs)
5. Test cases kept apart from the prompt development
6. Code or data available
7. Peer reviewed (preprints flagged)

The thesis text currently lists items 1, 2, 3 and 6; items 4, 5 and 7 are proposed additions.

### Synthesis

Meta-analysis is not feasible: the studies differ in task, assets, metrics and comparators, so no common effect size
exists. Synthesis is narrative and tabular, by review question (one table per LQ), grouping studies by the role of the
language model, following the SWiM items where they apply (grouping, standardised metric where possible, reporting of
heterogeneity, certainty). GRADE is not applied; confidence in each LQ answer is stated qualitatively from the number
of studies, their quality scores and whether they agree. **DECIDE:** confirm narrative synthesis without GRADE.

### Meta-bias

Publication bias is likely (positive results of new systems are published, failures rarely). Preprints are included
partly for this reason. Selective reporting is noted when a study reports only some of the metrics it describes.

## Devil's advocate checkpoint 1 (protocol)

Verdict: **REVISE** before Phase 2. No issue blocks the review; four are major.

| # | Severity | Issue | Proposed resolution |
|---|---|---|---|
| 1 | Major | The protocol was not registered or fixed before the search ran (11 Nov 2026); criteria were refined while screening | Register the protocol as run now; report it as retrospective, with every change in the amendments table |
| 2 | Major | Search missed a core LQ1 study (Sanguinetti et al., 2025) | **Addressed in part (24 Nov):** supplementary search C on arXiv retrieves it, 150 new records; Scopus C still to run; snowball from all included studies |
| 3 | Major | IEEE Xplore and Web of Science not screened; the claim that Scopus covers them is not tested | Take the IEEE titles that can be seen without export (or the first pages by relevance) and count how many are missing from Scopus; report the number |
| 4 | Major | One human reviewer; 300 records excluded by keyword with no human look | Supervisor sample with kappa; author checks a sample of keyword exclusions |
| 5 | Minor | Three versions of the eligibility criteria | Align on the table above |
| 6 | Minor | arXiv run B ("small language model" AND energy) returned 1 record; LQ3 rests mostly on Scopus run B | Consider an arXiv run B2 with "on-device" / "edge" / "local" near "language model" AND ("smart home" OR "energy") |
| 7 | Minor | Search date 11 Nov 2026; the field moves fast | Rerun the searches before submission and report the update |

## Amendments

| Date | Section | Change | Reason |
|---|---|---|---|
| 11 Nov 2026 | Sources | IEEE Xplore not exported, WoS not searched | access |
| 24 Nov 2026 | whole | PRISMA-P structure, sensitivity check, DA checkpoint | ARS systematic-review Phase 1 |
| 24 Nov 2026 | Search strategy | Supplementary search C (arXiv run; Scopus string defined) | known-item check found the main searches missed Sanguinetti et al. (2025) |
| 24 Nov 2026 | Selection | AI pre-screen of search C: 7 include, 6 unsure, 137 exclude | same procedure as the main set |
| 24 Nov 2026 | Selection | S0146 merged with R0696 (published version kept); search C now 7 include, 5 unsure, 138 exclude | preprint and conference paper of the same study |
| 24 Nov 2026 | Selection | S0131 included (author); search C now 8 include, 4 unsure, 138 exclude | user requests turned into an optimisation problem (LQ1) |
| 24 Nov 2026 | Selection | S0033 included as LQ3 background (author); search C now 9 include, 3 unsure, 138 exclude | on-device model defers to a cloud model; no energy objective, so it meets I3 for LQ3 only as background |
| 24 Nov 2026 | Selection | S0020 and S0140 included, S0036 excluded (author); search C now 11 include, 0 unsure, 139 exclude (138 plus the duplicate S0146) | author's check of the unsure records |
| 24 Nov 2026 | Selection | R0407 and R0513 included by the author (were unsure; evaluation and LLM role to check in the full text); main set 729 unique records: 88 include, 641 exclude, none unsure | author's decision |
| 24 Nov 2026 | Identification | R0408 (arXiv preprint) and R0464 (MobiCom poster) moved to identification as duplicates of R0034 (Huang et al., IEEE TMC 2026; journal version kept) by the author (`prescreen.py` DUPLICATES); main set 729 unique records: 86 include, 2 unsure, 641 exclude | three versions of one study |
| 24 Nov 2026 | Identification | R0675 moved from the exclusions to identification as a duplicate of R0668 (author); decision `duplicate` in `screening.csv`, as S0146 in `supplementary_C.csv`; main set 731 unique records: 88 include, 2 unsure, 641 exclude | same treatment for both duplicates found during screening |
| 24 Nov 2026 | Selection | Second look at the 53 main-set unsure records on their abstracts (R0100 abstract from OpenAlex): Claude proposed 19 include, 32 exclude, 2 full text (`out/unsure_proposals.csv`); approved by the author as a whole and applied in `prescreen.py`; main set now 88 include, 2 unsure (R0407, R0513), 642 exclude | R0675 excluded as a duplicate of R0668 (journal version kept); R0169 and R0456 have the same abstract, both excluded |
| 24 Nov 2026 | Selection | The 16 main-set LQ3 background records included (author; `prescreen.py`); main set now 69 include, 53 unsure, 610 exclude | same treatment as S0033: small or local models controlling smart-home devices, evidence for LQ3 |
| 25 Nov 2026 | Eligibility (full text) | Full-text screening protocol drafted (`prototypes/slr/fulltext/screening_protocol.md`, v0.2): exclusion order E3 language or date, E4 no evaluation (new; kept as background), E1 setting, E2 role. Rules added by the author: a small model is one run locally, called small by the study, or of at most about 10B parameters; command-to-device-action counts when checked offline; a concrete schedule or setting recommendation is an eligible role; one illustrative example without a measure is not an evaluation; aggregators, energy communities and peer-to-peer schemes count when the LM acts on household or building assets, greenhouses, farms and driving vehicles do not (unless the LQ3 rule applies) | the PRISMA-P criteria did not settle these cases; fixed before any full text is screened |
| 25 Nov 2026 | Selection (full text) | Full-text protocol confirmed as v1.0 by the author (boundary cases, six seed studies, two Claude Sonnet 5.5 reviewers plus a Sonnet adjudicator; the author checks every include and a sample of exclusions). The 99 title/abstract includes loaded into sr-screener as the author's decisions (`prototypes/slr/fulltext/sr_work`, `id_map.csv`); 34 PDFs matched, 65 not yet retrieved | before any full text is screened |
| 25 Nov 2026 | Selection (full text) | First full-text run on the 34 retrieved reports: two blinded Claude Sonnet 5.5 reviewers, one disagreement (R0219) adjudicated; 26 include, 8 exclude (E1 3, E2 4, E4 1); agreement 0.97, kappa 0.92. Reviewers read text extracted with poppler `pdftotext` (page markers added), because their PDF reader refused the files as "password-protected" although none is encrypted; figures are not visible to them. Decisions in `prototypes/slr/fulltext/ft_review_sheet.csv` for the author's check | AI decisions are decision support; the author checks every include and the exclusions |
| 25 Nov 2026 | Selection (full text) | S0033 kept as LQ3 background by the author, overriding the reviewers' E1 (`prototypes/slr/fulltext/ft_overrides.csv`); full text now 27 include, 7 exclude | same treatment as at title/abstract stage: on-device model that defers to a cloud model, evidence for LQ3 |
