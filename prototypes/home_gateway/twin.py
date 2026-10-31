"""Digital twin of a home energy gateway (exploratory, not part of the thesis evaluation).

One year of OPSD/CoSSMic site DE_KN_residential4 (a Konstanz home with PV, heat pump and EV charger; Open Power
System Data "Household data" 2020-04-15, CC BY 4.0) is replayed day by day, with a virtual home battery added.
Each day is controlled by four strategies and scored on the same prices:

- recorded:  the loads as measured, no battery (what the house did);
- battery:   the recorded loads plus a battery in the usual self-consumption mode (charge from PV surplus,
             discharge to cover the load);
- rules:     battery as above, the EV charges from PV surplus and at full power only when its deadline needs it
             (evcc-style "min + PV"), the heat pump raises its set point to the comfort maximum while there
             is PV surplus (SG Ready-style boost);
- optimum:   an LP with perfect foresight of the day that schedules battery, heat pump and EV charging together.

Heat pump: the recorded electricity times the When2Heat Germany COP (Ruhnau & Muessel, 2023) is the heat that
held the house at the set point; a one-node house model (heat capacity C, loss H) lets the indoor temperature
move within a comfort band, as in prototypes/heatpump. EV: each recorded charging run is a session that must
receive its energy between the recorded start and ``EV_WINDOW_H`` hours later (or midnight). Battery, house and
EV parameters below are assumptions that still need a source.

Prices (``--market``):

- ``fi``: Nord Pool FI day-ahead prices of the same date (as in the other prototypes); import at the thesis
  consumer tariff, export at the spot price; clock times of the house are read as Finnish local times;
- ``de``: the home's own market, German day-ahead prices (Energy-Charts / SMARD, DE-AT-LU) in German local time.
  Import at a dynamic household tariff built from the BDEW average of the year (``DE_HOUSEHOLD``): the spot
  price plus the supplier margin (procurement and sales minus the year's mean spot price), grid fee, concession
  fee, EEG surcharge, other levies and electricity tax, all with 19 % VAT, so its yearly mean equals the BDEW
  average. Export at the EEG feed-in tariff (``--export feedin``, default) or the spot price.

Weather: DWD station 02712 Konstanz, hourly global radiation and air temperature (UTC), on the same slots.

Every
strategy carries its battery charge and indoor temperature from one day to the next (the year starts at
``soc_start`` and the set point); the optimum must also end each day with at least ``soc_start`` and the set
point, so it never borrows from the next day. EV energy outside the detected sessions stays where recorded.

    uv run python prototypes/home_gateway/twin.py --raw-dir D:/Study/my-thesis/data/raw --year 2016
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pulp

from hems.core.models import SLOT_HOURS, SLOTS_PER_DAY
from hems.data.prices import load_price_csv, to_daily_slots
from hems.data.tariff import Tariff

SITE = "DE_KN_residential4"
PLANT_TZ = "Europe/Berlin"
EV_WINDOW_H = 12
STRATEGIES = ("recorded", "battery", "rules", "optimum")

# German household price 2016, ct/kWh (BDEW-Strompreisanalyse Dezember 2023, components of the 28.80 ct average):
# procurement and sales 6.26, grid fee incl. metering 7.01, concession fee 1.66, EEG surcharge 6.354, other levies
# 0.866 (KWKG, §19 StromNEV, offshore, interruptible loads: 15.53 taxes and levies minus the named ones),
# electricity tax 2.05, VAT 19 % (4.60).
DE_HOUSEHOLD = {2016: {"procurement_sales": 0.0626, "grid_fee": 0.0701, "concession": 0.0166, "eeg": 0.06354,
                       "other_levies": 0.00866, "electricity_tax": 0.0205}}  # fmt: skip
# EEG feed-in tariff for rooftop PV up to 10 kWp commissioned from Nov 2015 (municipal and industry rate tables;
# to be checked against the Bundesnetzagentur table and the system's commissioning date), EUR/kWh
DE_FEED_IN = 0.1231
PRICE_FILES = {"fi": ("prices_fi_elering_2015_2017.csv", "Europe/Helsinki"),
               "de": ("prices_de_energycharts_2015_2019.csv", PLANT_TZ)}


def de_tariff(year: int, mean_spot: float) -> Tariff:
    """Dynamic German household tariff whose yearly mean (at the mean spot price) is the BDEW average."""
    c = DE_HOUSEHOLD[year]
    return Tariff(vat=0.19, retail_margin_eur_per_kwh=c["procurement_sales"] - mean_spot,
                  transfer_eur_per_kwh=c["grid_fee"] + c["concession"] + c["eeg"] + c["other_levies"],
                  electricity_tax_eur_per_kwh=c["electricity_tax"])  # fmt: skip


def load_weather(raw_dir: Path) -> pd.DataFrame:
    """DWD Konstanz hourly global radiation (W/m2) and air temperature (C), on 15-min slots in local time."""
    folder = raw_dir / "dwd_konstanz"
    frames = {}
    for sub, column, name in (("st", "FG_LBERG", "ghi"), ("tu", "TT_TU", "temp")):
        path = next((folder / sub).glob("produkt_*.txt"))
        data = pd.read_csv(path, sep=";", skipinitialspace=True, na_values=[-999])
        times = pd.to_datetime(data.MESS_DATUM.astype(str).str[:10], format="%Y%m%d%H")
        series = pd.Series(data[column].to_numpy(dtype=float), index=pd.DatetimeIndex(times).tz_localize("UTC"))
        frames[name] = series * 10000 / 3600 if name == "ghi" else series  # J/cm2 per hour -> mean W/m2
    weather = pd.DataFrame(frames).interpolate(limit=3)
    return weather.resample("15min").interpolate().tz_convert(PLANT_TZ)


@dataclass(frozen=True)
class Home:
    """Prototype assumptions (to be sourced)."""

    battery_kwh: float = 10.0
    battery_kw: float = 5.0
    efficiency: float = 0.95  # each way
    soc_min: float = 0.1
    soc_start: float = 0.5
    hp_max_kw: float = 3.2  # recorded maximum is 3.1 kW
    ev_max_kw: float = 3.7  # single-phase 16 A; recorded maximum is 3.2 kW
    loss_kw_per_k: float = 0.15
    capacity_kwh_per_k: float = 10.0
    set_c: float = 21.0
    comfort_min_c: float = 20.0
    comfort_max_c: float = 22.0
    boost_surplus_kw: float = 1.0  # rules: boost the heat pump above this PV surplus


@dataclass
class Day:
    date: str
    pv: np.ndarray
    fixed: np.ndarray  # household load other than heat pump and EV
    hp: np.ndarray  # recorded heat pump electricity
    ev: np.ndarray  # recorded EV charging
    heat: np.ndarray  # heat delivered by the heat pump (recorded electricity x COP)
    cop: np.ndarray
    sessions: list[tuple[int, int, float]]  # (first slot, end slot, kWh)
    import_price: np.ndarray
    export_price: np.ndarray
    ghi: np.ndarray | None = None  # DWD global radiation, W/m2
    temp: np.ndarray | None = None  # DWD air temperature, C


@dataclass
class Result:
    imports: np.ndarray
    exports: np.ndarray
    hp: np.ndarray
    ev: np.ndarray
    battery: np.ndarray  # + charge, - discharge (kW at the battery terminals, grid side)
    soc: np.ndarray  # 97 values, kWh
    indoor: np.ndarray  # 97 values, C


def load_days(raw_dir: Path, year: int, market: str = "fi", export: str = "spot") -> list[Day]:
    data = pd.read_csv(raw_dir / "opsd_household" / "household_data_15min_singleindex.csv",
                       usecols=lambda c: c == "utc_timestamp" or c.startswith(SITE))  # fmt: skip
    data.index = pd.DatetimeIndex(pd.to_datetime(data.pop("utc_timestamp"), utc=True)).tz_convert(PLANT_TZ)
    kw = (data.diff() * 4).clip(lower=0)
    kw.columns = [c.removeprefix(f"{SITE}_") for c in kw.columns]
    w2h = pd.read_csv(raw_dir / "when2heat_de_2015_2018.csv")
    w2h.index = pd.DatetimeIndex(pd.to_datetime(w2h.pop("utc_timestamp"), utc=True)).tz_convert(PLANT_TZ)
    cop = w2h["DE_COP_ASHP_radiator"].resample("15min").ffill()
    price_file, price_tz = PRICE_FILES[market]
    raw_prices = load_price_csv(raw_dir / price_file, local_tz=price_tz)
    prices = to_daily_slots(raw_prices)
    hours = pd.Series(raw_prices.index.date).value_counts()
    prices = prices[prices.index.isin(hours[hours >= 23].index)]
    yearly = raw_prices[raw_prices.index.year == year]
    tariff = de_tariff(year, float(yearly.mean())) if market == "de" else Tariff()
    weather = load_weather(raw_dir) if (raw_dir / "dwd_konstanz").exists() else None

    days = []
    for date, frame in kw[kw.index.year == year].groupby(kw[kw.index.year == year].index.date):
        if len(frame) != SLOTS_PER_DAY or frame.isna().any().any() or date not in prices.index:
            continue
        day_cop = cop.reindex(frame.index).to_numpy()
        if np.isnan(day_cop).any():
            continue
        consumption = frame["pv"] + frame["grid_import"] - frame["grid_export"]
        ev = frame["ev"].to_numpy()
        sessions, residual = ev_sessions(ev)
        # EV energy outside the detected sessions (trickle charging) stays where it was recorded.
        fixed = np.clip((consumption - frame["heat_pump"]).to_numpy() - ev, 0.0, None) + residual
        spot = prices.loc[date].to_numpy()
        day_weather = weather.reindex(frame.index) if weather is not None else None
        if day_weather is not None and day_weather.isna().any().any():
            day_weather = None
        days.append(Day(
            date=str(date), pv=frame["pv"].to_numpy(), fixed=fixed, hp=frame["heat_pump"].to_numpy(),
            ev=ev - residual, heat=frame["heat_pump"].to_numpy() * day_cop, cop=day_cop, sessions=sessions,
            import_price=tariff.consumer_price(spot),
            export_price=np.full(SLOTS_PER_DAY, DE_FEED_IN) if export == "feedin" else spot,
            ghi=None if day_weather is None else day_weather["ghi"].to_numpy(),
            temp=None if day_weather is None else day_weather["temp"].to_numpy(),
        ))  # fmt: skip
    return days


def ev_sessions(ev: np.ndarray, on_kw: float = 0.5,
                min_kwh: float = 0.5) -> tuple[list[tuple[int, int, float]], np.ndarray]:  # fmt: skip
    """Recorded charging runs -> (first slot, end slot, kWh), and the EV power outside them (kW per slot).

    Runs split by up to 30 min off are merged.
    """
    on = np.flatnonzero(ev > on_kw)
    sessions: list[tuple[int, int, float]] = []
    residual = ev.copy()
    if not on.size:
        return sessions, residual
    groups = np.split(on, np.flatnonzero(np.diff(on) > 2) + 1)
    runs = [(int(g[0]), int(g[-1]), float(ev[g[0] : g[-1] + 1].sum() * SLOT_HOURS)) for g in groups]
    runs = [r for r in runs if r[2] >= min_kwh]
    for n, (start, last, energy) in enumerate(runs):
        # One car: a session's window ends when the next recorded run starts.
        next_start = runs[n + 1][0] if n + 1 < len(runs) else SLOTS_PER_DAY
        end = min(SLOTS_PER_DAY, start + EV_WINDOW_H * 4, next_start)
        sessions.append((start, max(end, last + 1), energy))
        residual[start : last + 1] = 0.0
    return sessions, residual


def settle(day: Day, home: Home, hp: np.ndarray, ev: np.ndarray, battery_on: bool, soc0: float,
           indoor: np.ndarray | None = None) -> Result:  # fmt: skip
    """Grid flows for given heat pump and EV power; the battery (if any) runs in self-consumption mode."""
    soc = np.zeros(SLOTS_PER_DAY + 1)
    soc[0] = soc0
    battery = np.zeros(SLOTS_PER_DAY)
    imports, exports = np.zeros(SLOTS_PER_DAY), np.zeros(SLOTS_PER_DAY)
    for t in range(SLOTS_PER_DAY):
        net = day.fixed[t] + hp[t] + ev[t] - day.pv[t]
        if battery_on and net < 0:
            room = (home.battery_kwh - soc[t]) / (home.efficiency * SLOT_HOURS)
            battery[t] = min(-net, home.battery_kw, room)
            soc[t + 1] = soc[t] + battery[t] * home.efficiency * SLOT_HOURS
        elif battery_on and net > 0:
            available = (soc[t] - home.soc_min * home.battery_kwh) * home.efficiency / SLOT_HOURS
            battery[t] = -min(net, home.battery_kw, max(available, 0.0))
            soc[t + 1] = soc[t] + battery[t] / home.efficiency * SLOT_HOURS
        else:
            soc[t + 1] = soc[t]
        grid = net + battery[t]
        imports[t], exports[t] = max(grid, 0.0), max(-grid, 0.0)
    indoor = np.full(SLOTS_PER_DAY + 1, home.set_c) if indoor is None else indoor
    return Result(imports, exports, hp, ev, battery, soc, indoor)


def rules(day: Day, home: Home, soc0: float, indoor0: float) -> Result:
    """SG Ready-style heat pump boost on PV surplus, evcc-style "min + PV" EV charging, self-consumption battery."""
    hp, ev = np.zeros(SLOTS_PER_DAY), np.zeros(SLOTS_PER_DAY)
    indoor = np.zeros(SLOTS_PER_DAY + 1)
    indoor[0] = indoor0
    left = {i: e for i, (_, _, e) in enumerate(day.sessions)}
    for t in range(SLOTS_PER_DAY):
        surplus = day.pv[t] - day.fixed[t]
        target = home.comfort_max_c if surplus > home.boost_surplus_kw else home.set_c
        needed_heat = (day.heat[t] + home.loss_kw_per_k * (indoor[t] - home.set_c)
                       + home.capacity_kwh_per_k * (target - indoor[t]) / SLOT_HOURS)  # fmt: skip
        hp[t] = float(np.clip(needed_heat / day.cop[t], 0.0, home.hp_max_kw))
        indoor[t + 1] = indoor[t] + SLOT_HOURS * (
            day.cop[t] * hp[t] - day.heat[t] - home.loss_kw_per_k * (indoor[t] - home.set_c)
        ) / home.capacity_kwh_per_k
        surplus -= hp[t]
        for i, (first, end, _) in enumerate(day.sessions):
            if not first <= t < end or left[i] <= 1e-9:
                continue
            must = max(0.0, left[i] / SLOT_HOURS - home.ev_max_kw * (end - t - 1))
            power = min(home.ev_max_kw - ev[t], left[i] / SLOT_HOURS, max(must, surplus))
            ev[t] += power
            left[i] -= power * SLOT_HOURS
            surplus -= power
    return settle(day, home, hp, ev, battery_on=True, soc0=soc0, indoor=indoor)


def optimum(day: Day, home: Home, soc0: float, indoor0: float) -> Result | None:
    """Cheapest day with perfect foresight: battery, heat pump and EV charging scheduled together.

    Starts from the state the previous day left and must end with at least the reference battery charge and
    the set point, so it never borrows from the next day.
    """
    slots, bounds = range(SLOTS_PER_DAY), range(SLOTS_PER_DAY + 1)
    model = pulp.LpProblem("home", pulp.LpMinimize)
    hp = [pulp.LpVariable(f"h{t}", 0, home.hp_max_kw) for t in slots]
    charge = [pulp.LpVariable(f"c{t}", 0, home.battery_kw) for t in slots]
    discharge = [pulp.LpVariable(f"d{t}", 0, home.battery_kw) for t in slots]
    imports = [pulp.LpVariable(f"i{t}", 0) for t in slots]
    exports = [pulp.LpVariable(f"x{t}", 0) for t in slots]
    soc = [pulp.LpVariable(f"s{t}", home.soc_min * home.battery_kwh, home.battery_kwh) for t in bounds]
    indoor = [pulp.LpVariable(f"T{t}", home.comfort_min_c, home.comfort_max_c) for t in bounds]
    ev_vars = {(i, t): pulp.LpVariable(f"e{i}_{t}", 0, home.ev_max_kw)
               for i, (first, end, _) in enumerate(day.sessions) for t in range(first, end)}  # fmt: skip
    ev = [pulp.lpSum(v for (_, s), v in ev_vars.items() if s == t) for t in slots]

    model += pulp.lpSum((day.import_price[t] * imports[t] - day.export_price[t] * exports[t]) * SLOT_HOURS for t in slots)
    model += soc[0] == soc0
    model += soc[-1] >= home.soc_start * home.battery_kwh
    model += indoor[0] == indoor0
    model += indoor[-1] >= home.set_c
    for i, (first, end, energy) in enumerate(day.sessions):
        model += pulp.lpSum(ev_vars[i, t] for t in range(first, end)) * SLOT_HOURS == energy
    for t in slots:
        model += day.fixed[t] + hp[t] + ev[t] + charge[t] - discharge[t] - day.pv[t] == imports[t] - exports[t]
        model += ev[t] <= home.ev_max_kw
        model += soc[t + 1] == soc[t] + SLOT_HOURS * (home.efficiency * charge[t] - discharge[t] / home.efficiency)
        model += home.capacity_kwh_per_k * (indoor[t + 1] - indoor[t]) == SLOT_HOURS * (
            day.cop[t] * hp[t] - day.heat[t] - home.loss_kw_per_k * (indoor[t] - home.set_c)
        )
    if model.solve(pulp.PULP_CBC_CMD(msg=False)) != pulp.LpStatusOptimal:
        return None

    def values(items: list) -> np.ndarray:
        return np.array([pulp.value(v) or 0.0 for v in items], dtype=float)

    return Result(values(imports), values(exports), values(hp), values(ev), values(charge) - values(discharge),
                  values(soc), values(indoor))  # fmt: skip


def run_day(day: Day, home: Home, state: dict[str, tuple[float, float]]) -> dict[str, Result | None]:
    """One day of every strategy, each continuing from the battery charge and indoor temperature it left."""
    results = {
        "recorded": settle(day, home, day.hp, day.ev, battery_on=False, soc0=state["recorded"][0]),
        "battery": settle(day, home, day.hp, day.ev, battery_on=True, soc0=state["battery"][0]),
        "rules": rules(day, home, *state["rules"]),
        "optimum": optimum(day, home, *state["optimum"]),
    }
    for name, result in results.items():
        if result is not None:
            state[name] = (float(result.soc[-1]), float(result.indoor[-1]))
    return results


def metrics(day: Day, result: Result) -> dict[str, float]:
    kwh = SLOT_HOURS
    exported = result.exports.sum() * kwh
    bill = float((day.import_price * result.imports * kwh).sum())
    revenue = float((day.export_price * result.exports * kwh).sum())
    return {
        "cost_eur": bill - revenue, "import_bill_eur": bill, "export_revenue_eur": revenue,
        "ev_kwh": float(result.ev.sum() * kwh), "hp_kwh": float(result.hp.sum() * kwh),
        "import_kwh": float(result.imports.sum() * kwh), "export_kwh": float(exported),
        "pv_kwh": float(day.pv.sum() * kwh), "peak_import_kw": float(result.imports.max()),
        "min_indoor_c": float(result.indoor.min()),
    }  # fmt: skip


def plot_day(day: Day, results: dict[str, Result | None], home: Home, path: Path) -> None:
    hours = np.arange(SLOTS_PER_DAY) * SLOT_HOURS
    edges = np.arange(SLOTS_PER_DAY + 1) * SLOT_HOURS
    shown = [name for name in ("rules", "optimum") if results[name] is not None]
    fig, axes = plt.subplots(len(shown) + 2, 1, figsize=(9, 3 + 2.6 * (len(shown) + 1)), sharex=True)
    for ax, name in zip(axes, shown, strict=False):
        r = results[name]
        ax.stackplot(hours, day.fixed, r.hp, r.ev, np.clip(r.battery, 0, None), step="post", alpha=0.85,
                     labels=["household", "heat pump", "EV", "battery charge"])  # fmt: skip
        ax.step(hours, day.pv, where="post", color="goldenrod", lw=1.5, label="PV")
        ax.step(hours, r.imports, where="post", color="k", lw=1, ls="--", label="grid import")
        ax.set_ylabel("kW")
        ax.set_title(f"{day.date}: {name}", fontsize=9)
        ax.legend(fontsize=7, ncol=3, loc="upper left")
    axes[-2].step(hours, day.import_price * 100, where="post", label="import")
    axes[-2].step(hours, day.export_price * 100, where="post", label="export")
    axes[-2].set_ylabel("c/kWh")
    axes[-2].legend(fontsize=7)
    for name in shown:
        axes[-1].plot(edges, results[name].soc / home.battery_kwh * 100, label=f"battery %, {name}")
    axes[-1].set_ylabel("battery %")
    axes[-1].set_xlabel("hour of day")
    axes[-1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--year", type=int, default=2016)
    parser.add_argument("--plot-days", nargs="*", default=["2016-07-12", "2016-12-07"])
    parser.add_argument("--market", choices=sorted(PRICE_FILES), default="fi")
    parser.add_argument("--export", choices=["spot", "feedin"], default=None, help="default: feedin for de, spot for fi")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "out")
    args = parser.parse_args()
    home = Home()
    export = args.export or ("feedin" if args.market == "de" else "spot")
    days = load_days(args.raw_dir, args.year, args.market, export)
    tag = "" if args.market == "fi" else f"_{args.market}_{export}"
    args.out.mkdir(parents=True, exist_ok=True)

    rows = []
    state = {name: (home.soc_start * home.battery_kwh, home.set_c) for name in STRATEGIES}
    for day in days:
        results = run_day(day, home, state)
        for name, result in results.items():
            if result is not None:
                rows.append({"date": day.date, "strategy": name, **metrics(day, result)})
        if day.date in args.plot_days:
            plot_day(day, results, home, args.out / f"day_{day.date}{tag}.png")
    frame = pd.DataFrame(rows)
    frame.to_csv(args.out / f"days_{args.year}{tag}.csv", index=False)

    solved = frame.groupby("date").strategy.nunique() == len(STRATEGIES)
    frame = frame[frame.date.isin(solved[solved].index)]
    sums = ["cost_eur", "import_bill_eur", "export_revenue_eur", "import_kwh", "export_kwh", "hp_kwh", "ev_kwh", "pv_kwh"]
    total = frame.groupby("strategy")[sums].sum().reindex(STRATEGIES)
    total["self_consumption_pct"] = 100 * (1 - total.export_kwh / total.pv_kwh)
    # Net cost is close to zero (export revenue offsets the bill), so savings are reported in EUR, not %.
    total["saving_vs_recorded_eur"] = total.cost_eur["recorded"] - total.cost_eur
    total["max_peak_import_kw"] = frame.groupby("strategy").peak_import_kw.max().reindex(STRATEGIES)
    total["min_indoor_c"] = frame.groupby("strategy").min_indoor_c.min().reindex(STRATEGIES)
    print(f"{SITE}, {args.year}: {frame.date.nunique()} complete days (of {len(days)} loaded), "
          f"PV {total.pv_kwh.iloc[0]:.0f} kWh")  # fmt: skip
    print(total.drop(columns="pv_kwh").round(1).to_string())
    (args.out / f"summary_{args.year}{tag}.json").write_text(json.dumps(total.round(3).to_dict(orient="index"), indent=1))


if __name__ == "__main__":
    main()
