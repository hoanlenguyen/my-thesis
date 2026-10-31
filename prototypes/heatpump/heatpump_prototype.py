"""Prototype (exploratory, not part of the thesis evaluation): one Finnish heat-pump and EV house-day.

Combines, for the 24 hours from noon of ``--date`` to noon of the next day (most car charging runs overnight):

- a REFIT household's base load and appliance cycles (UK, 2013-2015), from a REFIT day with the same month and
  weekday (appliance use depends little on the weather);
- an air-to-water heat pump driven by When2Heat Finland (Ruhnau & Muessel, 2023, CC BY 4.0: hourly heat demand
  profiles and COP) of the same real day;
- a measured residential EV charging session from Norway (Sorensen et al., 2024, CC BY 4.0: plug-in and plug-out
  time, energy charged, and the user's estimated charging power), plugged in on the same real date. Its clock
  times are read as local Finnish times;
- Nord Pool FI day-ahead prices of the same real day, so that cold days and high prices stay together.

The heat pump serves two stores, sharing a capped electric power; heat it cannot deliver comes from a
resistance backup heater (COP 1):

- space heating: a one-node (1R1C) house model. When2Heat's demand is the heat that holds the set point; any
  other indoor temperature changes the loss by H * (T - set point), and the house's heat capacity C lets the
  temperature move within a comfort band;
- domestic hot water (DHW): a tank whose stored heat stays between its minimum and maximum temperature.

The car must receive the session's energy between plug-in and plug-out (or the end of the horizon); its charger
can run at any power up to the user's charging power. Two plans are compared:

- thermostat: hold the set point, reheat the tank below its switch-on level, charge at full power from plug-in;
- optimum: an LP that minimises the cost of heating and charging within the comfort band, the tank limits, the
  charging window and the peak limit, ending the horizon with the house at the set point and the tank as full
  as the thermostat leaves it.

Houses with an electric heater sub-meter (1, 9, 16) are refused, so that heating is not counted twice. The
house parameters below are assumptions for the prototype and still need a cited Finnish source.

    uv run python prototypes/heatpump/heatpump_prototype.py --raw-dir D:/Study/my-thesis/data/raw --house 2 --date 2021-02-10

Data in ``--raw-dir``: refit/, when2heat.csv (the first run extracts the Finnish columns into when2heat_fi.csv),
ev_norway/Dataset1_charging_reports.csv and Dataset2_user_predictions.csv (zenodo.org/records/12730566), and
the FI price files (``hems prices --source elering --start 2018-01-01 --end 2022-01-01`` for 2018-2021).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pulp

from hems.core.models import SLOT_HOURS, SLOT_MINUTES, SLOTS_PER_DAY
from hems.data.prices import LOCAL_TZ, load_price_csv
from hems.data.refit import FLEXIBLE_COLUMNS, HOUSE_APPLIANCES, load_house, timed_cycles, typical_base_load
from hems.data.tariff import Tariff

WATER_KWH_PER_L_K = 4.186 / 3600
START_HOUR = 12
SLOT = pd.Timedelta(minutes=SLOT_MINUTES)


@dataclass(frozen=True)
class House:
    """Prototype assumptions (to be sourced): a Finnish detached house with an air-to-water heat pump."""

    space_heat_kwh_year: float = 15000.0
    dhw_heat_kwh_year: float = 4000.0
    hp_max_electric_kw: float = 3.0  # shared by space heating and DHW
    sink: str = "radiator"  # When2Heat space-heating sink: radiator or floor
    loss_kw_per_k: float = 0.15  # H: heat loss coefficient of the building
    capacity_kwh_per_k: float = 10.0  # C: heat capacity of the building (time constant C/H = 67 h)
    set_c: float = 21.0
    comfort_min_c: float = 20.0
    comfort_max_c: float = 22.0
    tank_litres: float = 250.0
    tank_min_c: float = 45.0
    tank_max_c: float = 65.0
    tank_switch_on_c: float = 55.0  # thermostat hysteresis
    tank_start_c: float = 55.0
    tank_loss_kw: float = 0.05
    peak_limit_kw: float = 8.0

    def tank_kwh(self, celsius: float) -> float:
        """Stored heat above the minimum temperature."""
        return self.tank_litres * WATER_KWH_PER_L_K * (celsius - self.tank_min_c)


@dataclass(frozen=True)
class EvSession:
    session_id: str
    user_id: str
    plugin: pd.Timestamp
    plugout: pd.Timestamp
    power_kw: float
    first_slot: int  # first slot the car is plugged in for in full
    end_slot: int  # boundary by which charging must be done
    energy_kwh: float  # recorded energy, capped at what the window allows


@dataclass
class Plan:
    space_hp: np.ndarray  # kW electric per slot
    backup: np.ndarray
    dhw_hp: np.ndarray
    ev: np.ndarray
    indoor_c: np.ndarray  # 97 values, at slot boundaries
    tank_kwh: np.ndarray

    def controllable(self) -> np.ndarray:
        return self.space_hp + self.backup + self.dhw_hp + self.ev


def horizon(day: date) -> pd.DatetimeIndex:
    """The 96 slot starts from noon of ``day`` (local time; tz-aware, so DST changes are handled)."""
    return pd.date_range(pd.Timestamp(day, tz=LOCAL_TZ) + pd.Timedelta(hours=START_HOUR), periods=SLOTS_PER_DAY,
                         freq=SLOT)  # fmt: skip


def on_grid(series: pd.Series, grid: pd.DatetimeIndex) -> np.ndarray:
    """Step-hold a time series (hourly or finer) onto the slot grid."""
    values = series.reindex(series.index.union(grid)).ffill().reindex(grid)
    if values.isna().any():
        raise SystemExit(f"{series.name}: no data for part of {grid[0]} .. {grid[-1]}")
    return values.to_numpy(dtype=float)


def when2heat_fi(raw_dir: Path) -> pd.DataFrame:
    """Finnish When2Heat columns, indexed by local time (cached as when2heat_fi.csv)."""
    cache = raw_dir / "when2heat_fi.csv"
    if not cache.exists():
        source = raw_dir / "when2heat.csv"
        with source.open() as f:
            sep = ";" if ";" in f.readline() else ","
        columns = pd.read_csv(source, sep=sep, nrows=0).columns
        wanted = ["utc_timestamp", *(c for c in columns if c.startswith("FI_"))]
        pd.read_csv(source, sep=sep, usecols=wanted, decimal="," if sep == ";" else ".").to_csv(cache, index=False)
    frame = pd.read_csv(cache)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("utc_timestamp"), utc=True)).tz_convert(LOCAL_TZ)
    return frame


def heat_day(w2h: pd.DataFrame, grid: pd.DatetimeIndex, house: House) -> dict[str, np.ndarray]:
    """Per-slot kW of heat to hold the set point and to cover hot water use, and the heat pump's COPs."""
    # Profiles are MW per TWh of annual demand, so kW = profile * annual kWh / 1e6.
    return {
        "space_heat": on_grid(w2h["FI_heat_profile_space_SFH"], grid) * house.space_heat_kwh_year / 1e6,
        "dhw_heat": on_grid(w2h["FI_heat_profile_water_SFH"], grid) * house.dhw_heat_kwh_year / 1e6,
        "cop_space": on_grid(w2h[f"FI_COP_ASHP_{house.sink}"], grid),
        "cop_dhw": on_grid(w2h["FI_COP_ASHP_water"], grid),
    }


def refit_day(raw_dir: Path, house_id: int, day: date) -> tuple[np.ndarray, np.ndarray, str]:
    """Base load and recorded appliance cycles over noon-to-noon of a REFIT day with the same month and weekday."""
    if any(name and name.startswith("electric_heater") for name in HOUSE_APPLIANCES[house_id]):
        raise SystemExit(f"house {house_id} has an electric heater sub-meter; heating would be counted twice")
    df = load_house(raw_dir / "refit", house_id)
    typical = typical_base_load(df, house_id)
    base = np.roll(typical, -START_HOUR * 4)  # slot 0 = noon
    candidates = sorted({d for d in df.index.date if d.month == day.month and d.weekday() == day.weekday()})
    for candidate in candidates:
        start = pd.Timestamp(candidate) + pd.Timedelta(hours=START_HOUR)
        recorded = df[start : start + pd.Timedelta(days=1)]
        appliances = np.zeros(SLOTS_PER_DAY)
        for column in FLEXIBLE_COLUMNS[house_id]:
            for cycle_start, profile in timed_cycles(recorded[column]):
                slot = int((cycle_start - start) / SLOT)
                n = min(len(profile), SLOTS_PER_DAY - slot)
                appliances[slot : slot + n] += profile[:n]
        if appliances.any():
            return base, appliances, f"{candidate} 12:00"
    return base, np.zeros(SLOTS_PER_DAY), "none"


def ev_session(raw_dir: Path, grid: pd.DatetimeIndex, session_id: str | None, min_kwh: float) -> EvSession | None:
    """A Norwegian session plugged in during the horizon's afternoon or evening (or the one named)."""
    folder = raw_dir / "ev_norway"
    reports = pd.read_csv(folder / "Dataset1_charging_reports.csv", sep=";", decimal=",")
    users = pd.read_csv(folder / "Dataset2_user_predictions.csv", sep=";", decimal=",").set_index("user_id")
    for column in ("plugin_time", "plugout_time"):
        reports[column] = pd.to_datetime(reports[column]).dt.tz_localize(LOCAL_TZ, ambiguous="NaT",
                                                                            nonexistent="NaT")  # fmt: skip
    reports = reports.dropna(subset=["plugin_time", "plugout_time"]).join(users, on="user_id")
    if session_id:
        chosen = reports[reports.session_id == session_id]
    else:
        evening = (reports.plugin_time >= grid[0]) & (reports.plugin_time < grid[0] + pd.Timedelta(hours=12))
        chosen = reports[evening & (reports.energy_session >= min_kwh)].dropna(subset=["charging_power"])
        chosen = chosen.sort_values("plugin_time")
    if chosen.empty:
        return None
    row = chosen.iloc[0]
    end = grid[-1] + SLOT
    first = int(np.ceil((row.plugin_time - grid[0]) / SLOT))
    last = int(np.floor((min(row.plugout_time, end) - grid[0]) / SLOT))
    if not 0 <= first < last <= SLOTS_PER_DAY:
        raise SystemExit(f"session {row.session_id} is not plugged in during {grid[0]} .. {end}")
    energy = min(float(row.energy_session), row.charging_power * (last - first) * SLOT_HOURS)
    return EvSession(row.session_id, row.user_id, row.plugin_time, row.plugout_time, float(row.charging_power),
                     first, last, energy)  # fmt: skip


def thermostat(heat: dict[str, np.ndarray], house: House, ev: EvSession | None) -> Plan:
    """Hold the set point, reheat the tank below the switch-on level until full, charge at full power from plug-in."""
    space_hp = np.minimum(heat["space_heat"] / heat["cop_space"], house.hp_max_electric_kw)
    backup = np.clip(heat["space_heat"] - space_hp * heat["cop_space"], 0.0, None)
    full, on_level = house.tank_kwh(house.tank_max_c), house.tank_kwh(house.tank_switch_on_c)
    stored, heating = house.tank_kwh(house.tank_start_c), False
    dhw, tank = np.zeros(SLOTS_PER_DAY), np.zeros(SLOTS_PER_DAY + 1)
    tank[0] = stored
    for t in range(SLOTS_PER_DAY):
        heating = stored < on_level or (heating and stored < full)
        if heating:
            room = house.hp_max_electric_kw - space_hp[t]
            dhw[t] = min(room, (full - stored) / (heat["cop_dhw"][t] * SLOT_HOURS))
        stored = max(stored + SLOT_HOURS * (heat["cop_dhw"][t] * dhw[t] - heat["dhw_heat"][t] - house.tank_loss_kw), 0)
        tank[t + 1] = stored
    charge = np.zeros(SLOTS_PER_DAY)
    if ev:
        left = ev.energy_kwh
        for t in range(ev.first_slot, ev.end_slot):
            charge[t] = min(ev.power_kw, left / SLOT_HOURS)
            left -= charge[t] * SLOT_HOURS
    return Plan(space_hp, backup, dhw, charge, np.full(SLOTS_PER_DAY + 1, house.set_c), tank)


def optimum(heat: dict[str, np.ndarray], fixed: np.ndarray, price: np.ndarray, house: House, ev: EvSession | None,
            tank_end_kwh: float) -> Plan | None:  # fmt: skip
    """Cheapest heating and charging within the comfort band, the tank limits, the charging window and the peak limit."""
    slots, bounds = range(SLOTS_PER_DAY), range(SLOTS_PER_DAY + 1)
    model = pulp.LpProblem("house", pulp.LpMinimize)
    space = [pulp.LpVariable(f"s{t}", 0) for t in slots]
    backup = [pulp.LpVariable(f"b{t}", 0) for t in slots]
    dhw = [pulp.LpVariable(f"w{t}", 0) for t in slots]
    plugged = range(ev.first_slot, ev.end_slot) if ev else range(0)
    charge = [pulp.LpVariable(f"c{t}", 0, ev.power_kw if t in plugged else 0) for t in slots]
    indoor = [pulp.LpVariable(f"T{t}", house.comfort_min_c, house.comfort_max_c) for t in bounds]
    tank = [pulp.LpVariable(f"e{t}", 0, house.tank_kwh(house.tank_max_c)) for t in bounds]

    model += pulp.lpSum(price[t] * (space[t] + backup[t] + dhw[t] + charge[t]) * SLOT_HOURS for t in slots)
    if ev:
        model += pulp.lpSum(charge[t] * SLOT_HOURS for t in plugged) == ev.energy_kwh
    model += indoor[0] == house.set_c
    model += indoor[-1] >= house.set_c
    model += tank[0] == house.tank_kwh(house.tank_start_c)
    model += tank[-1] >= max(house.tank_kwh(house.tank_start_c), tank_end_kwh)
    for t in slots:
        loss = heat["space_heat"][t] + house.loss_kw_per_k * (indoor[t] - house.set_c)
        model += house.capacity_kwh_per_k * (indoor[t + 1] - indoor[t]) == SLOT_HOURS * (
            heat["cop_space"][t] * space[t] + backup[t] - loss
        )
        model += tank[t + 1] == tank[t] + SLOT_HOURS * (
            heat["cop_dhw"][t] * dhw[t] - heat["dhw_heat"][t] - house.tank_loss_kw
        )
        model += space[t] + dhw[t] <= house.hp_max_electric_kw
        model += fixed[t] + space[t] + backup[t] + dhw[t] + charge[t] <= house.peak_limit_kw
    if model.solve(pulp.PULP_CBC_CMD(msg=False)) != pulp.LpStatusOptimal:
        return None

    def values(variables: list) -> np.ndarray:
        return np.array([pulp.value(v) or 0.0 for v in variables], dtype=float)

    return Plan(values(space), values(backup), values(dhw), values(charge), values(indoor), values(tank))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--house", type=int, default=2)
    parser.add_argument("--date", type=date.fromisoformat, default=date(2021, 2, 10), help="noon of this day to noon of the next")
    parser.add_argument("--ev-session", help="a session_id of the Norwegian data (default: the first plugged in after noon)")
    parser.add_argument("--ev-min-kwh", type=float, default=5.0, help="skip shorter sessions when choosing one")
    parser.add_argument("--no-ev", action="store_true")
    parser.add_argument("--prices", nargs="+", default=["prices_fi_elering_2018_2021.csv", "prices_fi_entsoe.csv"])
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "out")
    args = parser.parse_args()
    house = House()
    grid = horizon(args.date)

    heat = heat_day(when2heat_fi(args.raw_dir), grid, house)
    base, appliances, refit_from = refit_day(args.raw_dir, args.house, args.date)
    ev = None if args.no_ev else ev_session(args.raw_dir, grid, args.ev_session, args.ev_min_kwh)
    fixed = base + appliances
    prices = pd.concat([load_price_csv(args.raw_dir / name) for name in args.prices]).sort_index()
    spot = on_grid(prices[~prices.index.duplicated()].rename("price"), grid)
    price = Tariff().consumer_price(spot)

    plans = {"thermostat": thermostat(heat, house, ev)}
    best = optimum(heat, fixed, price, house, ev, tank_end_kwh=plans["thermostat"].tank_kwh[-1])
    if best is None:
        print("optimum: infeasible (peak limit, heat pump capacity, tank or charging window cannot cover the day)")
    else:
        plans["optimum"] = best

    def kwh(series: np.ndarray) -> float:
        return float(series.sum() * SLOT_HOURS)

    def clock(slot: int) -> str:
        return grid[slot].strftime("%H:%M") if slot < SLOTS_PER_DAY else "12:00"

    print(f"house {args.house}, {grid[0]:%Y-%m-%d %H:%M} + 24 h (REFIT from {refit_from}), limit {house.peak_limit_kw} kW")
    print(f"  heat to hold {house.set_c:g} C: {kwh(heat['space_heat']):.1f} kWh (mean COP {heat['cop_space'].mean():.2f}); "
          f"hot water {kwh(heat['dhw_heat']):.1f} kWh; spot {spot.min() * 100:.1f}-{spot.max() * 100:.1f} c/kWh")  # fmt: skip
    if ev:
        print(f"  EV {ev.session_id} ({ev.user_id}, {ev.power_kw:.1f} kW): plugged {ev.plugin:%d.%m %H:%M} to {ev.plugout:%d.%m %H:%M}, "
              f"{ev.energy_kwh:.1f} kWh between {clock(ev.first_slot)} and {clock(ev.end_slot)}")  # fmt: skip
    else:
        print("  no EV session")
    for name, plan in plans.items():
        total = fixed + plan.controllable()
        over = int((total > house.peak_limit_kw + 1e-6).sum())
        print(f"  {name:10s}: {kwh(plan.controllable() * price):6.2f} EUR for space {kwh(plan.space_hp):5.1f} + "
              f"backup {kwh(plan.backup):4.1f} + hot water {kwh(plan.dhw_hp):4.1f} + EV {kwh(plan.ev):4.1f} kWh;"
              f" peak {total.max():.2f} kW{f' ({over} slots over the limit)' if over else ''}; "
              f"indoor {plan.indoor_c.min():.1f}-{plan.indoor_c.max():.1f} C")  # fmt: skip

    hours = np.arange(SLOTS_PER_DAY) * SLOT_HOURS
    edges = np.arange(SLOTS_PER_DAY + 1) * SLOT_HOURS
    fig, axes = plt.subplots(4, 1, figsize=(9, 11), sharex=True, gridspec_kw={"height_ratios": [3, 1.2, 1.3, 1.3]})
    ax_load, ax_price, ax_indoor, ax_tank = axes
    shown_name = "optimum" if "optimum" in plans else "thermostat"
    shown = plans[shown_name]
    stack = [base, appliances, shown.ev, shown.space_hp, shown.backup, shown.dhw_hp]
    labels = ["base load (REFIT)", "appliances (REFIT)", "EV charging (Norway)", "heat pump, space",
              "backup heater", "heat pump, hot water"]  # fmt: skip
    ax_load.stackplot(hours, *stack, labels=labels, step="post", alpha=0.85)
    ax_load.step(hours, fixed + plans["thermostat"].controllable(), where="post", color="k", ls="--", lw=1,
                 label="total, thermostat")  # fmt: skip
    ax_load.axhline(house.peak_limit_kw, color="red", lw=1, label=f"{house.peak_limit_kw:g} kW limit")
    if ev:
        ax_load.axvspan(ev.first_slot * SLOT_HOURS, ev.end_slot * SLOT_HOURS, color="tab:green", alpha=0.07,
                        label="EV plugged in")  # fmt: skip
    ax_load.set_ylabel("kW")
    ax_load.legend(loc="upper left", fontsize=7, ncol=2)
    ax_load.set_title(f"House {args.house}, {grid[0]:%Y-%m-%d} 12:00 + 24 h: {shown_name} (stacked) vs thermostat (dashed)")
    ax_price.step(hours, price * 100, where="post", color="tab:purple")
    ax_price.set_ylabel("c/kWh")
    for name, plan in plans.items():
        ax_indoor.plot(edges, plan.indoor_c, label=name)
        ax_tank.plot(edges, plan.tank_kwh, label=name)
    ax_indoor.axhspan(house.comfort_min_c, house.comfort_max_c, color="grey", alpha=0.15)
    ax_indoor.set_ylabel("indoor C")
    ax_indoor.legend(fontsize=8)
    ax_tank.axhline(house.tank_kwh(house.tank_max_c), color="grey", lw=0.8, ls=":")
    ax_tank.set_ylabel("tank kWh")
    ticks = np.arange(0, 25, 3)
    ax_tank.set_xticks(ticks, [f"{(START_HOUR + h) % 24:02d}:00" for h in ticks])
    ax_tank.set_xlabel("local time (noon to noon)")
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"heatpump_h{args.house}_{args.date}{'' if ev else '_noev'}.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    print(f"  plot: {path}")


if __name__ == "__main__":
    main()
