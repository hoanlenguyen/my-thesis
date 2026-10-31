"""Exploratory HIPE scenarios (not part of the thesis evaluation): one per working day of the HIPE sample week.

HIPE (Bischof et al., 2018, CC BY 4.0) metered ten machines and the main terminal of a German power-electronics
plant. Its one-week sample (23-29 Oct 2017) is reduced to 1-minute mean active power per machine in
``week_1min.csv`` (see README). For each working day (Mon-Fri):

- flexible: every run of the batch machines in ``FLEXIBLE`` (cycles detected as for REFIT, at least 1 kWh),
  which may move within the day shift 06:00-22:00; "no scheduling" is the recorded start;
- base load: the main terminal minus those machines, per 15-min slot of that day (it counts towards the peak);
- peak limit: the day's recorded 15-min peak, rounded up to 0.5 kW, so a schedule may not raise the plant's
  peak (as under a power charge) and the recorded plan stays valid;
- prices: Nord Pool FI day-ahead prices of the same date, with the thesis consumer tariff; HIPE's clock times
  are read as Finnish local times.

Assumptions: the machines are treated as independent jobs, although the soldering oven belongs to a production
line and the two vacuum pumps run together; nothing is known about the plant's real order deadlines.

    uv run python prototypes/hipe/build_scenarios.py --raw-dir D:/Study/my-thesis/data/raw
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

FLEXIBLE = ("HighTemperatureOven", "SolderingOven", "VacuumPump1", "VacuumPump2")
SHIFT = (24, 88)  # 06:00-22:00
MIN_KWH = 1.0
LIMIT_STEP_KW = 0.5


def load_week(raw_dir: Path) -> pd.DataFrame:
    """1-minute kW per machine, indexed by naive local (plant) time."""
    df = pd.read_csv(raw_dir / "hipe" / "week_1min.csv", index_col=0)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("Europe/Berlin").tz_localize(None)
    return df.clip(lower=0)


def scenario_for(day: pd.Timestamp, week: pd.DataFrame, spot: np.ndarray) -> Scenario:
    recorded = week[day : day + pd.Timedelta(days=1) - pd.Timedelta(minutes=1)]
    slots = recorded.resample(f"{SLOT_MINUTES}min").mean().reindex(
        pd.date_range(day, periods=SLOTS_PER_DAY, freq=f"{SLOT_MINUTES}min")).fillna(0.0)  # fmt: skip
    appliances: list[FlexibleAppliance] = []
    for machine in FLEXIBLE:
        cycles = timed_cycles(recorded[machine] * 1000, on_w=100, max_gap_min=10, min_duration_min=15,
                              max_duration_min=SLOTS_PER_DAY * SLOT_MINUTES, min_energy_kwh=MIN_KWH)  # fmt: skip
        for n, (start, profile) in enumerate(cycles, 1):
            slot = start.hour * 4 + start.minute // SLOT_MINUTES
            profile = profile[: SLOTS_PER_DAY - slot]
            appliances.append(FlexibleAppliance(
                id=f"{machine}_{n}", kind="industrial_machine", profile_kw=profile,
                earliest_slot=min(SHIFT[0], slot), deadline_slot=max(SHIFT[1], slot + len(profile)),
                default_start_slot=slot,
            ))  # fmt: skip
    naive = np.zeros(SLOTS_PER_DAY)
    for a in appliances:
        naive[a.default_start_slot : a.default_start_slot + a.duration_slots] += a.profile_kw
    base = np.clip(slots["MainTerminal"].to_numpy() - naive, 0.0, None)
    limit = math.ceil((base + naive).max() / LIMIT_STEP_KW) * LIMIT_STEP_KW
    fixed = [FixedAppliance(id=m, kind="industrial_machine", typical_power_kw=round(float(week[m].max()), 2))
             for m in week.columns if m not in FLEXIBLE and m != "MainTerminal"]  # fmt: skip
    scenario = Scenario(
        id=f"HIPE-{day:%m%d}", type="hipe-industrial", date=f"{day:%Y-%m-%d}",
        start_time=pd.Timestamp(day, tz=LOCAL_TZ).to_pydatetime(),
        spot_eur_per_kwh=[round(float(p), 5) for p in spot],
        price_eur_per_kwh=[round(float(p), 5) for p in Tariff().consumer_price(spot)],
        base_load_kw=[round(float(b), 3) for b in base], peak_limit_kw=limit, appliances=appliances,
        fixed_appliances=fixed, user_request="",
        notes=f"HIPE plant {day:%a %d %b %Y}; flexible = runs of {', '.join(FLEXIBLE)}; shift window 06:00-22:00; "
              f"limit = recorded 15-min peak {(base + naive).max():.1f} kW rounded up; FI prices of the same date.",
    )  # fmt: skip
    items = [f"- {a.id}: ready from {scenario.slot_to_time(a.earliest_slot)}, must finish by "
             f"{scenario.boundary_to_time(a.deadline_slot)}" for a in appliances]  # fmt: skip
    scenario.user_request = (
        f"Our plant buys electricity at the spot price. Please schedule these machine runs for {scenario.date} so "
        f"that the electricity cost is as low as possible, without exceeding the site peak limit:\n" + "\n".join(items)
    )
    return scenario


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--prices", default="prices_fi_elering_2017_10.csv")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "scenarios")
    args = parser.parse_args()
    week = load_week(args.raw_dir)
    prices = to_daily_slots(load_price_csv(args.raw_dir / args.prices))
    args.out.mkdir(parents=True, exist_ok=True)
    for day in pd.date_range(week.index[0].normalize(), periods=5, freq="D"):  # Mon 23 - Fri 27 Oct 2017
        scenario = scenario_for(day, week, prices.loc[day.date()].to_numpy())
        scenario.save(args.out / f"{scenario.id}.json")
        energy = sum(a.energy_kwh for a in scenario.appliances)
        print(f"{scenario.id}: {len(scenario.appliances)} runs, {energy:.1f} kWh flexible of "
              f"{sum(scenario.base_load_kw) * SLOT_HOURS + energy:.0f} kWh, limit {scenario.peak_limit_kw} kW, "
              f"spot {min(scenario.spot_eur_per_kwh) * 100:.1f}-{max(scenario.spot_eur_per_kwh) * 100:.1f} c/kWh")  # fmt: skip


if __name__ == "__main__":
    main()
