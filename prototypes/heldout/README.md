# Held-out set: materials for the registered evaluation (draft, 21 Nov 2026)

Nothing here is registered, and no system has read any held-out message. Keep it that way until the registration
commit (keys, hypotheses with thresholds, `config_heldout.json` and the confirm script).

| File | What it is |
|---|---|
| `power.py`, `power_output.txt` | power calculation that sizes the set |
| `make_scenarios.py` → `scenarios.json` | 120 scenario cards: real house-days of `DE_KN_residential4` 2016, stratified by season x weather, with plan type and writer |
| `writer_instructions.md` | what a plan writer reads (the house, what the app knows, how to write) |
| `writer_sheets/W1.md` ... `W4.md` | one sheet per writer: the instructions and their 30 cards, without plan type or facts |
| `writer_sheets/returned/` | put the filled-in sheets here |
| `collect.py` → `plans_heldout.json` | messages from the returned sheets in the plan format of `plan_pilot/plans.json`, keys empty |
| `keying_guide.md` | how the author keys the plans and how the second person checks them |
| `config_heldout.json` | the frozen run configuration (draft; `TO FIX` items open) |
| `run_heldout.py` | the runner: models x set-ups x runs, cloud fallback, closed loop with EMHASS, resumes |
| `confirm_heldout.py` | the confirmatory analysis (H1-H3 with Holm, H4, H5), reads only the registered outputs |
| `year_balance.py` | year simulation, energy balance: the yearly saving against the model's energy and cost (H5) |

## Steps and who does them

1. **Author:** read the writer sheets and adjust any card that reads oddly (then rerun `make_scenarios.py`; it is
   seeded, so edit the generator rather than the JSON).
2. **Author:** recruit four writers (not involved in the thesis), send each their sheet, collect them in
   `writer_sheets/returned/`; run `collect.py`.
3. **Author:** key all 120 plans (`keying_guide.md`); run the self-test.
4. **Second person:** key them independently; compare, report agreement, resolve, log disagreements.
5. **Done 22 Nov 2026:** the runner pieces (below), tested on the development plans only.
6. **Author:** fix the `TO FIX` values, commit everything: this is the registration.
7. Run the held-out evaluation, the Configurator weeks and the year simulation; analyse with the confirm script only.

## Decisions for the registration (from `power.py`)

- **H1 margin.** At the drafted margin of 0.05 and the pilot's discordance (Gemma 4 E4B and GPT-6 Luna disagreed on
  4 of 36 decisions), power 0.8 needs about 390 plans; 120 plans give 0.33. With a margin of 0.10, 120 plans give
  0.89 (about 100 needed). **Decided 21 Nov 2026: margin 0.10** (H1 and H3).
- **H2 null rate.** Against p0 = 0.95, at least 80 feasible committed house-days are needed even if every one is
  met; the 120 cards have 80 plans keyed to commit at most (simple and change). With p0 = 0.90, 80 days give power
  0.78 at a true rate of 0.98. **Decided 21 Nov 2026: p0 = 0.90.**
- **Houses.** **Decided 21 Nov 2026: `residential4` only** (thesis text changed to match). The cards use `residential4` only, the house of the pilots and the only OPSD house with a heat pump
  and an EV. The thesis text (Section 5.5) says "more houses of the OPSD data"; either the text changes or cards on
  `residential3` / `residential6` (PV only, no heat pump or EV in the data) are added for appliance and away plans.
- **Configurator weeks** in `config_heldout.json` (winter and summer 2016, not used by the pilots or the tuning).
  **Confirmed 22 Nov 2026.**

## Runner pieces (built 22 Nov 2026, tested on the development plans only)

- `Gateway(checks=False)` in `react_gateway/agent.py`: the set-up without the checks and the rules in code
  (`plan_unchecked`: no vague-word question, time rule, feasibility or conflict check, or empty-plan refusal; the
  usual car settings are still filled in so the optimiser can plan; the gateway applies whatever the model commits).
  The default (`checks=True`) is unchanged. `run_plan` also records `failed_answer` and `checker_rejected`.
- The cloud fallback (`run_heldout.py`): on a failed answer or a committed plan the gateway refused, the cloud model
  answers the same plan in the same agent and passes the same checks. One small-model run gives the `slm_checks` and
  `slm_checks_fallback` rows. The time trigger of Section 4.2 (first deadline within 30 minutes) is not modelled:
  every card leaves at least an hour.
- The closed loop with EMHASS (`--emhass`): `closed_loop.run` replans hourly through `emhass_gateway.emhass_mpc`;
  results are cached by plan and constraints (`<out>.loopcache.jsonl`), so identical requirements run once.
- `run_heldout.py` resumes, and does not record a unit that failed outside the model (network, Ollama, EMHASS).
- `confirm_heldout.py`: `REGISTERED = False` until the registration commit; H4 margin 0.20 EUR per week (both
  comparisons), H5 limit 15 minutes (decided 22 Nov 2026); the tested small model is `BEST_SLM = gemma4-e4b`, the main candidate, named before the run.

## Year simulation (built 22 Nov 2026; runs after the registration)

The year is the Configurator's weekly simulation over 49 weeks of `residential4` 2016 (18 Jan to 24 Dec, scaled to
365 days); `configurator.py` now also records grid import and export kWh (additive: costs unchanged, checked on the
week of 7 Mar 2016). `year_balance.py` weighs the HEMS's saving over rules against the model's energy per year
(one plan per day, one configuration per week, Wh per event and idle power from the edge-board runs) for the model on
the gateway and on a companion device, and also reports what the model adds over the expert-tuned MPC. The year
contains the Configurator's held-out weeks, so it runs only after the registration commit. Command in
`config_heldout.json`; about 4-5 hours with both models.

**Optimiser (decided 22 Nov 2026):** the Household Assistant's plans and closed-loop days use EMHASS
(`run_heldout.py --emhass`); the Configurator's held-out weeks and the year simulation keep the thesis MPC (PuLP),
because each needs thousands of simulated days. Sections 3.5 and 5.5 of the thesis say so.

## Selection rules (from `make_scenarios.py`)

Days with data for the day and the next; not a date of the development or test plans or the day after; not in the
four September weeks on which the expert MPC setting was tuned. Weather class = tertile of daily DWD radiation among
the eligible days of the season (over the year, winter has no sunny days). Price pattern (descriptive): volatile when
the day's hourly spread is in the top third of the year, else evening peak when the dearest hour is 17-20, else flat.
Simple and change cards are checked feasible (charger and appliance cycle); conflict cards are built infeasible or
contradictory, with a `conflict_note`.
