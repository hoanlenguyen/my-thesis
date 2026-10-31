# OPSD/CoSSMic industrial prototype (exploratory)

Not part of the thesis evaluation. Twelve working days of site `DE_KN_industrial3` (a small business in
Konstanz) from the OPSD "Household data" package, scored by the thesis code (`hems run`, `core.evaluate`).
Uses the `industrial_machine` kind added for `prototypes/hipe`.

Data (gitignored, in `--raw-dir`):

| File | Source |
|---|---|
| `opsd_household/household_data_15min_singleindex.csv`, `datapackage.json` | <https://data.open-power-system-data.org/household_data/2020-04-15/> (CC BY 4.0; Open Power System Data, CoSSMic) |
| `opsd_household/industrial3_kw_15min.csv` | the site's cumulative kWh readings differenced to kW (`diff() * 4`, negative steps dropped), from 16 Oct 2015 |
| `prices_fi_elering_2015_2017.csv` | `uv run hems prices --source elering --start 2015-10-01 --end 2017-07-01 --out <raw-dir>/prices_fi_elering_2015_2017.csv` |

```bash
uv run python prototypes/opsd/build_scenarios.py --raw-dir D:/Study/my-thesis/data/raw
uv run hems run --scenarios prototypes/opsd/scenarios --systems milp naive timer cheapest_hours cheapest_window --runs 1 --out prototypes/opsd/results/runs.jsonl
```

Scenario rules and assumptions are in the docstring of `build_scenarios.py`. Days with fewer than 23 hourly
prices are skipped (Elering has one-day gaps in 2015-2017, which `to_daily_slots` would forward-fill into flat
days). Real deadlines and job order are unknown, so the numbers are not results.
