---
name: rebuild-benchmark
description: Rebuild the REFIT + Nord Pool FI scenario sets of src/hems (hourly main set or 15-minute Q set) and verify them with the MILP, or update the thesis numbers that depend on the gateway thesis's data (Table 3.3); then rebuild and compile gateway_thesis.tex. Use when scenario rules, houses, prices, peak limit, tariff or the datasets in data/raw change.
---

# Rebuild the benchmark and keep the thesis in sync

The REFIT scenario sets belong to the `src/hems` code of the first thesis (its text is on the `old-thesis`
branch). The gateway thesis (`gateway_body.tex`) does not report them; its data-dependent numbers are listed at the
end.

## Build

```bash
# main set (hourly Sahkotin prices; type E = Dec 2022 crisis)
uv run hems build --refit data/raw/refit --prices data/raw/prices_fi_sahkotin.csv --out data/scenarios
# 15-minute set (Elering; only days since 2025-10-01; type E = highest-peak days)
uv run hems build --refit data/raw/refit --prices data/raw/prices_fi_elering.csv --out data/scenarios_15min \
  --from 2025-10-01 --spike-days top --id-prefix Q-
```
Prices: `uv run hems prices --source elering|sahkotin|entsoe`. REFIT sanity: `uv run hems refit-inspect --refit data/raw/refit`.

## Verify

- To prove a code change did not alter a set, build into the scratchpad and `cmp` every JSON with the
  committed files (manifest excluded); they must be byte-identical.
- For a new build, per type: MILP status Optimal for all 8, peak limit raised in none (`notes`),
  scenarios requiring coordination (`solvers.naive.has_coordination_conflict`), naive feasibility,
  mean MILP saving vs naive. Flag types whose saving is near zero (they cannot discriminate agents).

Any agent results computed on old scenarios are invalid; archive them (`run-evaluation` skill). The first
thesis's tables (`tab:benchmark`, `sec:dataset`, `sec:resolution`) live in `main.tex` on `old-thesis`; update them
there, not on `main`.

## Update the gateway thesis (hand-typed numbers)

When a dataset in `data/raw/` or a pilot that the gateway thesis cites changes, update `gateway_body.tex`, then
rebuild and compile `gateway_thesis.tex` with the `compile-thesis` skill
(`uv run python build_gateway_thesis.py`, then `latexmk -xelatex gateway_thesis`):
- `tab:data` (Table 3.3, "Data used in the evaluation"): the Size column (OPSD rows and period, DWD temperature
  and radiation values, day-ahead price count and period, When2Heat values, EV sessions, the number of pilot,
  development and held-out plans).
- Appendix A plan tables: regenerate them from `prototypes/plan_pilot/plans.json`,
  `archive/plans_exact_wording.json` and `plans_dev.json` rather than editing rows by hand.
- Chapter 5 tables and the numbers in CLAUDE.md's "Prototypes and their thesis numbers" when a pilot is rerun.
- Figure 4.5 (`tools/make_example_day_fig.py`) if the stored app output of plan S6 changes.
