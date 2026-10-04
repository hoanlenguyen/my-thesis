"""Typical appliance use of the 18 benchmark households, from the raw REFIT recordings, for the demo.

For every monitored appliance of a house (scheduled and fixed), the share of recorded days on which it
was on during each hour of the day (UK local time of the recording, 2013-2015), its typical power when
on, and its mean energy per day. Rows flagged in REFIT's Issues column are dropped. Written to
demo/public/data/households.json. Reads ~6.5 GB of CSV; takes several minutes.

    uv run python tools/export_household_profiles.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from hems.data.refit import ALL_HOUSES, FLEXIBLE_KINDS, HOUSE_APPLIANCES, OTHER_SHIFTABLE_KINDS, base_kind, house_file

ROOT = Path(__file__).resolve().parents[1]
REFIT = ROOT / "data" / "raw" / "refit"
OUT = ROOT / "demo" / "public" / "data" / "households.json"
MIN_ON_W = 15.0  # below this an appliance counts as off (standby)
MIN_ON_MINUTES = 2  # minutes on within an hour for that hour to count as "used"
MIN_DAY_COVERAGE = 20 * 60  # minutes of data a day needs to count


def profile_house(house: int) -> dict:
    names = {f"Appliance{i}": n for i, n in enumerate(HOUSE_APPLIANCES[house], 1) if n}
    df = pd.read_csv(house_file(REFIT, house), usecols=["Time", *names, "Issues"], parse_dates=["Time"], index_col="Time")
    df = df[df.Issues.fillna(0) == 0].drop(columns="Issues").astype("float32")
    minute = df.resample("1min").mean()  # mean power per minute (W)
    covered = minute.notna().all(axis=1)
    minute = minute[covered]
    days_minutes = minute.groupby(minute.index.date).size()
    good_days = set(days_minutes[days_minutes >= MIN_DAY_COVERAGE].index)
    minute = minute[np.isin(minute.index.date, list(good_days))]
    n_days = len(good_days)

    appliances = []
    for column, name in names.items():
        power = minute[column]
        threshold = max(MIN_ON_W, 0.1 * float(power.quantile(0.99)))
        on = power > threshold
        per_hour = on.groupby([on.index.date, on.index.hour]).sum()  # minutes on per (day, hour)
        used = (per_hour >= MIN_ON_MINUTES).groupby(level=1).sum() / n_days
        hourly = [round(float(used.get(h, 0.0)), 3) for h in range(24)]
        kind = base_kind(name)
        appliances.append({
            "name": name, "kind": kind,
            "shiftable": kind in FLEXIBLE_KINDS or kind in OTHER_SHIFTABLE_KINDS,
            "scheduled": kind in FLEXIBLE_KINDS,
            "ratedKw": round(float(power[on].median()) / 1000, 3) if on.any() else 0.0,
            "kwhPerDay": round(float(power.sum()) / 60 / 1000 / n_days, 3),
            "daysUsedShare": round(float((on.groupby(on.index.date).sum() >= MIN_ON_MINUTES).mean()), 3),
            "hourly": hourly,
        })  # fmt: skip
    dates = sorted(good_days)
    return {"house": house, "firstDay": str(dates[0]), "lastDay": str(dates[-1]), "days": n_days, "appliances": appliances}


def main() -> None:
    households = []
    for house in ALL_HOUSES:
        p = profile_house(house)
        households.append(p)
        print(f"house {house}: {p['days']} days, {len(p['appliances'])} appliances", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(households, indent=1), encoding="utf-8")
    print(f"written to {OUT}")


if __name__ == "__main__":
    main()
