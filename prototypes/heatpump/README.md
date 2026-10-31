# Heat pump and EV prototype (exploratory)

Not part of the thesis evaluation: no scenarios, agents, prompts or results of `src/hems` are changed. It is a
sketch for a possible follow-up study on heat pumps and EV charging.

One Finnish house over 24 hours from noon to noon (most car charging runs overnight):

- a REFIT household's base load and appliance cycles (from a REFIT day with the same month and weekday);
- an air-to-water heat pump driven by When2Heat Finland (heat demand and COP) of the same real day;
- a measured Norwegian residential EV session plugged in that afternoon or evening (plug-in, plug-out, energy,
  the user's estimated charging power);
- Nord Pool FI prices of the same real day.

Space heating (a one-node house model, 20-22 °C comfort band), the hot water tank and the car's charging power
are scheduled together under the 8 kW limit and compared with a thermostat that charges the car at full power
from plug-in. The EV data cover Feb 2018 to Aug 2021, so EV days are 2018-2021; `--no-ev` runs any day of
When2Heat (to 2022).

```bash
uv run python prototypes/heatpump/heatpump_prototype.py --raw-dir D:/Study/my-thesis/data/raw --house 2 --date 2021-04-14
uv run python prototypes/heatpump/heatpump_prototype.py --raw-dir D:/Study/my-thesis/data/raw --house 2 --date 2021-04-14 --ev-session KRO_418
```

Data in `--raw-dir` (gitignored):

| File | Source |
|---|---|
| `refit/` | REFIT (Murray et al., 2017) |
| `when2heat.csv` | <https://data.open-power-system-data.org/when2heat/2023-07-27/> (CC BY 4.0; Ruhnau & Muessel, 2023) |
| `ev_norway/Dataset1_charging_reports.csv`, `Dataset2_user_predictions.csv` | <https://zenodo.org/records/12730566> (CC BY 4.0; Sørensen et al., 2024) |
| `prices_fi_elering_2018_2021.csv` | `uv run hems prices --source elering --start 2018-01-01 --end 2022-01-01 --out <raw-dir>/prices_fi_elering_2018_2021.csv` |
| `prices_fi_entsoe.csv` | the thesis price file (2022 onwards) |

Plots go to `prototypes/heatpump/out/`.

Assumptions: the house parameters in `House` (annual heat demand, heat capacity, heat loss, heat pump size,
tank) still need a cited source; the EV charging power is the dataset's estimate; Norwegian plug-in times are
read as Finnish local times; the thesis tariff (2025-26) prices every year. The numbers are not results.
