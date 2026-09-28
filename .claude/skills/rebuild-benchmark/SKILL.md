---
name: rebuild-benchmark
description: Rebuild the REFIT + Nord Pool FI scenario sets (hourly main set or 15-minute Q set), verify them with the MILP, and update every thesis number that depends on them. Use when scenario rules, houses, prices, peak limit or tariff change.
---

# Rebuild the benchmark and keep the thesis in sync

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
  committed files (manifest excluded) — they must be byte-identical.
- For a new build, per type: MILP status Optimal for all 8, peak limit raised in none (`notes`),
  scenarios requiring coordination (`solvers.naive.has_coordination_conflict`), naive feasibility,
  mean MILP saving vs naive. Flag types whose saving is near zero (they cannot discriminate agents).

## Update the thesis (hand-typed numbers)

After a rebuild, update in `main.tex` and recompile (`compile-thesis` skill):
- §5.1 text: households used/excluded, cycle counts per appliance type and monitor counts
  (`manifest.json` → `cycles_detected`, `profile_sources`), price period and day count
  (`price_period`, `price_days_available`), scenarios requiring coordination.
- Table 5.2 (`tab:benchmark`): per-type mean appliances, coordination, naive within limit, MILP saving.
- If the Q set changed: rerun `uv run hems resolution` (regenerates Table 5.3) and update the §5.2
  numbers (39/48 improved, ρ, largest case, starts changed, cents per day).
- Any agent results computed on the old scenarios are invalid — archive them (`run-evaluation` skill).
