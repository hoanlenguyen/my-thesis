# HIPE industrial prototype (exploratory)

Not part of the thesis evaluation. Five scenarios, one per working day of the HIPE sample week (Mon 23 to
Fri 27 Oct 2017), scored by the thesis code (`hems run`, `core.evaluate`). The only change to `src/hems` is the
appliance kind `industrial_machine` (`core/models.py`, `tools/__init__.py`), which no thesis scenario uses.

Data (gitignored, in `--raw-dir`):

| File | Source |
|---|---|
| `hipe/hipe_week.zip` → `hipe/week/*.csv` | <https://zenodo.org/records/14054902>, one-week sample of HIPE v1.0.1 (CC BY 4.0; Bischof et al., 2018) |
| `hipe/week_1min.csv` | 1-minute mean `P_kW` per machine, made from `week/*.csv` (timestamps in ISO 8601, Europe/Berlin) |
| `prices_fi_elering_2017_10.csv` | `uv run hems prices --source elering --start 2017-10-01 --end 2017-11-01 --out <raw-dir>/prices_fi_elering_2017_10.csv` |

```bash
uv run python prototypes/hipe/build_scenarios.py --raw-dir D:/Study/my-thesis/data/raw
uv run hems run --scenarios prototypes/hipe/scenarios --systems milp naive timer cheapest_hours cheapest_window --runs 1 --out prototypes/hipe/results/runs.jsonl
```

Scenario rules and assumptions are in the docstring of `build_scenarios.py`: the flexible jobs are the runs of the
high-temperature oven, the soldering oven and the two vacuum pumps, movable within the 06:00-22:00 shift, under
the day's recorded plant peak, at Finnish prices of the same date. Real order deadlines and the production-line
order are unknown, so the windows are assumptions and the numbers are not results.
