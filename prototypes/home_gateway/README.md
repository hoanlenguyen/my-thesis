# Home energy gateway digital twin (exploratory)

Not part of the thesis evaluation. Replays one year (2016) of OPSD/CoSSMic site `DE_KN_residential4` (a Konstanz
home with PV, heat pump and EV charger) with a virtual 10 kWh / 5 kW home battery, and compares four control
strategies on the same prices: recorded operation, battery in self-consumption mode, rules (evcc-style "min + PV"
EV charging, SG Ready-style heat pump boost on PV surplus, self-consumption battery) and a daily LP optimum with
perfect foresight. Details and assumptions are in the docstring of `twin.py`.

```bash
uv run python prototypes/home_gateway/twin.py --raw-dir D:/Study/my-thesis/data/raw --year 2016
```

Data in `--raw-dir` (gitignored):

| File | Source |
|---|---|
| `opsd_household/household_data_15min_singleindex.csv` | <https://data.open-power-system-data.org/household_data/2020-04-15/> (CC BY 4.0) |
| `when2heat_de_2015_2018.csv` | German COP columns of `when2heat.csv` (<https://data.open-power-system-data.org/when2heat/2023-07-27/>, CC BY 4.0), Oct 2015 to Feb 2018 |
| `prices_fi_elering_2015_2017.csv` | `uv run hems prices --source elering --start 2015-10-01 --end 2017-07-01 --out <raw-dir>/prices_fi_elering_2015_2017.csv` |

Outputs go to `prototypes/home_gateway/out/` (per-day CSV, yearly summary JSON, plots of two days).

Assumptions to be sourced: battery size, power and efficiency; house heat capacity and loss; EV charger power
and the 12-hour plug-in window from each recorded charging start; Finnish prices for a German home; export
paid at the spot price. The numbers are not results.
