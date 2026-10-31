"""Exploratory OPSD/CoSSMic scenarios (not part of the thesis evaluation): working days of DE_KN_industrial3.

OPSD "Household data" 2020-04-15 (Open Power System Data, CC BY 4.0; CoSSMic project, ISC Konstanz) holds
cumulative kWh meter readings of small businesses and homes in Konstanz. Site DE_KN_industrial3 (a small
business) meters grid import, five machines, compressor, cooling, ventilation, an EV charger, PV and a
dishwasher. Its 15-min readings are differenced to kW in ``industrial3_kw_15min.csv`` (see README).

For a sample of working days (Mon-Fri, ``--days`` spread evenly over the record, each with a machine_1 run,
at least two flexible runs and no missing data):

- flexible: every run of the devices in ``FLEXIBLE`` (cycles detected as for REFIT, at least 0.5 kWh).
  Machines and the dishwasher may move within the day shift 06:00-22:00; the EV may charge from its recorded
  start (the car is not there before) until 22:00. "No scheduling" is the recorded start;
- base load: grid import minus those runs, per 15-min slot (PV is already netted in grid import);
- peak limit: the day's recorded 15-min grid peak, rounded up to 0.5 kW, so a schedule may not raise it;
- prices: Nord Pool FI day-ahead prices of the same date with the thesis consumer tariff (for comparability
  with the HIPE prototype); clock times are read as Finnish local times.

Assumptions: runs are independent jobs; nothing is known about real deadlines or job order.

    uv run python prototypes/opsd/build_scenarios.py --raw-dir D:/Study/my-thesis/data/raw
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

from hems.core.models import SLOT_HOURS, SLOT_MINUTES, SLOTS_PER_DAY, FixedAppliance, FlexibleAppliance, Scenario
from hems.data.prices import LOCAL_TZ, load_price_csv, to_daily_slots
from hems.data.refit import timed_cycles
from hems.data.tariff import Tariff

FLEXIBLE = {"machine_1": 2000, "machine_4": 300, "machine_5": 500, "ev": 500, "dishwasher": 300}  # on-threshold, W
FIXED = ("compressor", "cooling_aggregate", "cooling_pumps", "ventilation", "machine_2", "machine_3", "refrigerator")
SHIFT = (24, 88)  # 06:00-22:00
MIN_KWH = 0.5
LIMIT_STEP_KW = 0.5
PLANT_TZ = "Europe/Berlin"


def load_site(raw_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(raw_dir / "opsd_household" / "industrial3_kw_15min.csv", index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    return df


def runs(site: pd.DataFrame) -> dict[str, list[tuple[pd.Timestamp, list[float]]]]:
    """Runs of each flexible device, with local start times."""
    found = {}
    for device, on_w in FLEXIBLE.items():
        watts = (site[device].fillna(0) * 1000).resample("1min").ffill()
        cycles = timed_cycles(watts, on_w=on_w, max_gap_min=15, min_duration_min=15, max_duration_min=16 * 60,
                              min_energy_kwh=MIN_KWH)  # fmt: skip
        found[device] = [(start.tz_convert(PLANT_TZ), profile) for start, profile in cycles]
    return found


def scenario_for(day: pd.Timestamp, site: pd.DataFrame, day_runs: list[tuple[str, int, list[float]]],
                 spot: np.ndarray) -> Scenario:  # fmt: skip
    local = site.tz_convert(PLANT_TZ)
    recorded = local[(local.index >= day) & (local.index < day + pd.Timedelta(days=1))]
    appliances, counts = [], {}
    for device, slot, profile in day_runs:
        counts[device] = counts.get(device, 0) + 1
        profile = profile[: SLOTS_PER_DAY - slot]
        earliest = slot if device == "ev" else min(SHIFT[0], slot)
        appliances.append(FlexibleAppliance(
            id=f"{device}_{counts[device]}", kind="industrial_machine" if device != "ev" else "ev_charger",
            profile_kw=profile, earliest_slot=earliest, deadline_slot=max(SHIFT[1], slot + len(profile)),
            default_start_slot=slot,
        ))  # fmt: skip
    naive = np.zeros(SLOTS_PER_DAY)
    for a in appliances:
        naive[a.default_start_slot : a.default_start_slot + a.duration_slots] += a.profile_kw
    grid = recorded["grid_import"].to_numpy()
    base = np.clip(grid - naive, 0.0, None)
    limit = math.ceil((base + naive).max() / LIMIT_STEP_KW) * LIMIT_STEP_KW
    fixed = [FixedAppliance(id=d, kind="industrial_machine", typical_power_kw=round(float(site[d].quantile(0.99)), 1))
             for d in FIXED]  # fmt: skip
    scenario = Scenario(
        id=f"OPSD-I3-{day:%y%m%d}", type="opsd-industrial", date=f"{day:%Y-%m-%d}",
        start_time=pd.Timestamp(day.date(), tz=LOCAL_TZ).to_pydatetime(),
        spot_eur_per_kwh=[round(float(p), 5) for p in spot],
        price_eur_per_kwh=[round(float(p), 5) for p in Tariff().consumer_price(spot)],
        base_load_kw=[round(float(b), 3) for b in base], peak_limit_kw=limit, appliances=appliances,
        fixed_appliances=fixed, user_request="",
        notes=f"OPSD DE_KN_industrial3 {day:%a %d %b %Y}; flexible = runs of {', '.join(FLEXIBLE)}; shift window "
              f"06:00-22:00 (EV from arrival); limit = recorded 15-min grid peak {(base + naive).max():.1f} kW "
              f"rounded up; FI prices of the same date.",
    )  # fmt: skip
    items = [f"- {a.id}: ready from {scenario.slot_to_time(a.earliest_slot)}, must finish by "
             f"{scenario.boundary_to_time(a.deadline_slot)}" for a in appliances]  # fmt: skip
    scenario.user_request = (
        f"Our site buys electricity at the spot price. Please schedule these machine runs and the car charge for "
        f"{scenario.date} so that the electricity cost is as low as possible, without exceeding the site peak "
        f"limit:\n" + "\n".join(items)
    )
    return scenario


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--prices", default="prices_fi_elering_2015_2017.csv")
    parser.add_argument("--days", type=int, default=12)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "scenarios")
    args = parser.parse_args()
    site = load_site(args.raw_dir)
    raw_prices = load_price_csv(args.raw_dir / args.prices)
    prices = to_daily_slots(raw_prices)
    hours = pd.Series(raw_prices.index.date).value_counts()
    prices = prices[prices.index.isin(hours[hours >= 23].index)]  # gaps would be forward-filled into flat days
    by_day: dict[pd.Timestamp, list[tuple[str, int, list[float]]]] = {}
    for device, found in runs(site).items():
        for start, profile in found:
            day = start.normalize()
            by_day.setdefault(day, []).append((device, start.hour * 4 + start.minute // SLOT_MINUTES, profile))
    local = site.tz_convert(PLANT_TZ)
    eligible = []
    for day, day_runs in sorted(by_day.items()):
        recorded = local[(local.index >= day) & (local.index < day + pd.Timedelta(days=1))]
        if (day.dayofweek < 5 and len(recorded) == SLOTS_PER_DAY and not recorded["grid_import"].isna().any()
                and any(d == "machine_1" for d, _, _ in day_runs) and len(day_runs) >= 2
                and day.date() in prices.index):  # fmt: skip
            eligible.append(day)
    chosen = [eligible[round(i * (len(eligible) - 1) / (args.days - 1))] for i in range(args.days)]
    print(f"{len(eligible)} eligible working days; using {len(chosen)}")
    args.out.mkdir(parents=True, exist_ok=True)
    for day in chosen:
        scenario = scenario_for(day, site, sorted(by_day[day], key=lambda r: (r[0], r[1])),
                                prices.loc[day.date()].to_numpy())  # fmt: skip
        scenario.save(args.out / f"{scenario.id}.json")
        energy = sum(a.energy_kwh for a in scenario.appliances)
        print(f"{scenario.id}: {len(scenario.appliances)} runs, {energy:.0f} kWh flexible of "
              f"{sum(scenario.base_load_kw) * SLOT_HOURS + energy:.0f} kWh, limit {scenario.peak_limit_kw} kW, "
              f"spot {min(scenario.spot_eur_per_kwh) * 100:.1f}-{max(scenario.spot_eur_per_kwh) * 100:.1f} c/kWh")  # fmt: skip


if __name__ == "__main__":
    main()
