"""Measured appliance cycles of OPSD DE_KN_residential4 (dishwasher, washing machine), for the ReAct gateway's tools.

A cycle is a run of 15-min slots with power above ``ON_KW``, allowing gaps of up to ``GAP_SLOTS`` slots (a washing
machine soaks between phases); cycles shorter than 30 min or below 0.1 kWh are standby noise. The typical cycle
of an appliance is the median cycle by energy among those of the median length; its 15-min power profile is
what the gateway schedules. Writes ``appliances.json``.

    uv run python prototypes/react_gateway/appliance_cycles.py --raw-dir D:/Study/my-thesis/data/raw
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
SITE = "DE_KN_residential4"
APPLIANCES = ("dishwasher", "washing_machine")
ON_KW, GAP_SLOTS, MIN_SLOTS, MIN_KWH = 0.05, 2, 2, 0.1


def cycles(kw: np.ndarray) -> list[np.ndarray]:
    on = np.flatnonzero(kw > ON_KW)
    if not len(on):
        return []
    runs, start, last = [], on[0], on[0]
    for i in on[1:]:
        if i - last > GAP_SLOTS + 1:
            runs.append((start, last + 1))
            start = i
        last = i
    runs.append((start, last + 1))
    out = [kw[a:b] for a, b in runs]
    return [c for c in out if len(c) >= MIN_SLOTS and c.sum() / 4 >= MIN_KWH]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    cols = [f"{SITE}_{a}" for a in APPLIANCES]
    data = pd.read_csv(args.raw_dir / "opsd_household" / "household_data_15min_singleindex.csv",
                       usecols=["utc_timestamp", *cols])  # fmt: skip
    data.index = pd.to_datetime(data.pop("utc_timestamp"), utc=True)
    kw = (data.diff() * 4).clip(lower=0).fillna(0.0)
    report = {}
    for name, col in zip(APPLIANCES, cols, strict=True):
        found = cycles(kw[col].to_numpy())
        lengths = np.array([len(c) for c in found])
        energies = np.array([c.sum() / 4 for c in found])
        typical_len = int(np.median(lengths))
        same = [c for c in found if len(c) == typical_len]
        typical = sorted(same, key=lambda c: c.sum())[len(same) // 2]
        report[name] = {
            "cycles_found": len(found),
            "energy_kwh_median": round(float(np.median(energies)), 2),
            "energy_kwh_p10_p90": [round(float(x), 2) for x in np.percentile(energies, [10, 90])],
            "duration_h_median": typical_len / 4,
            "typical_profile_kw": [round(float(x), 3) for x in typical],  # power per 15-min slot of the typical cycle
            "typical_energy_kwh": round(float(typical.sum() / 4), 2),
        }
        print(name, {k: v for k, v in report[name].items() if k != "typical_profile_kw"}, report[name]["typical_profile_kw"])
    report["source"] = (f"OPSD household data, {SITE}, {kw.index.min():%Y-%m-%d} to {kw.index.max():%Y-%m-%d}; "
                        f"cycle = slots above {ON_KW} kW with gaps up to {GAP_SLOTS} slots")  # fmt: skip
    (HERE / "appliances.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
