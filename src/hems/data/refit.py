"""REFIT Electrical Load Measurements (cleaned, Murray et al. 2017) -> appliance cycle profiles.

Expected input: the cleaned per-house CSVs (e.g. ``CLEAN_House1.csv``) with
columns ``Time, Unix, Aggregate, Appliance1..Appliance9, Issues`` in watts at
~8-second resolution.

The appliance-column mapping below follows the REFIT README; VERIFY it against
the README that ships with your download before building the benchmark
(``hems refit-inspect`` prints per-column cycle statistics to help).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from hems.core.models import SLOT_MINUTES, SLOTS_PER_DAY, FixedAppliance

# house -> {column: flexible kind}
FLEXIBLE_COLUMNS: dict[int, dict[str, str]] = {
    1: {"Appliance4": "tumble_dryer", "Appliance5": "washing_machine", "Appliance6": "dishwasher"},
    2: {"Appliance2": "washing_machine", "Appliance3": "dishwasher"},
    3: {"Appliance4": "tumble_dryer", "Appliance5": "dishwasher", "Appliance6": "washing_machine"},
}

# house -> non-shiftable appliances (id, typical kW) shown to the Appliance Profiler
FIXED_APPLIANCES: dict[int, list[tuple[str, float]]] = {
    1: [("fridge", 0.08), ("chest_freezer", 0.08), ("upright_freezer", 0.08), ("computer", 0.15), ("television", 0.1), ("electric_heater", 1.5)],
    2: [("fridge_freezer", 0.1), ("television", 0.1), ("microwave", 1.0), ("toaster", 0.9), ("hifi", 0.05), ("kettle", 2.0), ("overhead_fan", 0.05)],
    3: [("toaster", 0.9), ("fridge_freezer", 0.1), ("freezer", 0.08), ("television", 0.1), ("microwave", 1.0), ("kettle", 2.0)],
}


def house_file(refit_dir: str | Path, house: int) -> Path:
    directory = Path(refit_dir)
    for pattern in (f"CLEAN_House{house}.csv", f"House_{house}.csv", f"*House{house}.csv", f"*House_{house}.csv"):
        matches = sorted(directory.glob(pattern))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"no REFIT CSV for house {house} in {directory}")


def load_house(refit_dir: str | Path, house: int) -> pd.DataFrame:
    columns = ["Time", "Aggregate", *FLEXIBLE_COLUMNS[house]]
    df = pd.read_csv(house_file(refit_dir, house), usecols=columns, parse_dates=["Time"], index_col="Time")
    return df.astype("float32").sort_index()


def detect_cycles(
    watts: pd.Series,
    on_w: float = 20.0,
    max_gap_min: int = 10,
    min_duration_min: int = 20,
    max_duration_min: int = 300,
    min_energy_kwh: float = 0.1,
) -> list[list[float]]:
    """Split an appliance's power series into cycles; each returned as a 15-min mean-kW profile.

    Short "off" gaps inside a programme (e.g. soaking) are merged so one wash is one cycle.
    """
    per_min = watts.resample("1min").mean().fillna(0.0)
    on = per_min > on_w
    if not on.any():
        return []
    on_times = per_min.index[on]
    breaks = np.flatnonzero(on_times[1:] - on_times[:-1] > pd.Timedelta(minutes=max_gap_min))
    starts = np.r_[0, breaks + 1]
    ends = np.r_[breaks, len(on_times) - 1]

    cycles: list[list[float]] = []
    for s, e in zip(starts, ends):
        segment = per_min[on_times[s] : on_times[e]]
        duration = len(segment)
        if not (min_duration_min <= duration <= max_duration_min):
            continue
        n_slots = int(np.ceil(duration / SLOT_MINUTES))
        padded = np.zeros(n_slots * SLOT_MINUTES)
        padded[:duration] = segment.to_numpy()
        profile_kw = padded.reshape(n_slots, SLOT_MINUTES).mean(axis=1) / 1000
        if profile_kw.sum() * SLOT_MINUTES / 60 >= min_energy_kwh:
            cycles.append([round(float(p), 3) for p in profile_kw])
    return cycles


def typical_base_load(house_df: pd.DataFrame, house: int) -> np.ndarray:
    """Median non-shiftable load per 15-min slot of the day (kW): aggregate minus flexible sub-meters."""
    flexible = house_df[list(FLEXIBLE_COLUMNS[house])].sum(axis=1)
    base = (house_df["Aggregate"] - flexible).clip(lower=0).resample(f"{SLOT_MINUTES}min").mean().dropna()
    slot_of_day = base.index.hour * 4 + base.index.minute // SLOT_MINUTES
    profile = base.groupby(slot_of_day).median().reindex(range(SLOTS_PER_DAY)).interpolate().bfill().ffill()
    return profile.to_numpy() / 1000


def fixed_appliances(house: int) -> list[FixedAppliance]:
    return [FixedAppliance(id=name, kind=name, typical_power_kw=kw) for name, kw in FIXED_APPLIANCES[house]]


def inspect(refit_dir: str | Path, houses: tuple[int, ...] = (1, 2, 3)) -> pd.DataFrame:
    rows = []
    for house in houses:
        df = load_house(refit_dir, house)
        for column, kind in FLEXIBLE_COLUMNS[house].items():
            cycles = detect_cycles(df[column])
            durations = [len(c) * SLOT_MINUTES for c in cycles]
            rows.append(
                {
                    "house": house,
                    "column": column,
                    "mapped_kind": kind,
                    "cycles": len(cycles),
                    "median_duration_min": float(np.median(durations)) if durations else np.nan,
                    "median_peak_kw": float(np.median([max(c) for c in cycles])) if cycles else np.nan,
                    "median_energy_kwh": float(np.median([sum(c) / 4 for c in cycles])) if cycles else np.nan,
                }
            )
    return pd.DataFrame(rows)
