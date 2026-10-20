"""REFIT Electrical Load Measurements (cleaned, Murray et al. 2017) -> appliance cycle profiles.

Expected input: the cleaned per-house CSVs (e.g. ``CLEAN_House1.csv``) with
columns ``Time, Unix, Aggregate, Appliance1..Appliance9, Issues`` in watts at
~8-second resolution.

The appliance-column mapping is transcribed from the APPLIANCE LIST in
CLEAN_READ_ME_081116.txt (identical to MetaData_Tables.xlsx). The cleaned files
already re-align IAM columns where a monitor was moved between appliances, so
no date-range exclusions are applied.

Rows flagged ``Issues == 1`` (sub-meter sum exceeds the aggregate) are, as the
README advises, discarded when deriving the base load.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from hems.core.models import SLOT_MINUTES, SLOTS_PER_DAY, FixedAppliance

# House -> the appliances on IAM columns Appliance1..Appliance9 (README order). None = unknown ("???")
# or nothing recorded. There is no house 14.
HOUSE_APPLIANCES: dict[int, list[str | None]] = {
    1: ["fridge", "freezer_1", "freezer_2", "washer_dryer", "washing_machine", "dishwasher", "computer", "television", "electric_heater"],
    2: ["fridge_freezer", "washing_machine", "dishwasher", "television", "microwave", "toaster", "hifi", "kettle", "overhead_fan"],
    3: ["toaster", "fridge_freezer", "freezer", "tumble_dryer", "dishwasher", "washing_machine", "television", "microwave", "kettle"],
    4: ["fridge", "freezer", "fridge_freezer", "washing_machine_1", "washing_machine_2", "computer", "television", "microwave", "kettle"],
    5: ["fridge_freezer", "tumble_dryer", "washing_machine", "dishwasher", "computer", "television", "microwave", "kettle", "toaster"],
    6: ["freezer", "washing_machine", "dishwasher", "computer_1", "television", "microwave", "kettle", "toaster", "computer_2"],
    7: ["fridge", "freezer_1", "freezer_2", "tumble_dryer", "washing_machine", "dishwasher", "television", "toaster", "kettle"],
    8: ["fridge", "freezer", "washer_dryer", "washing_machine", "toaster", "computer", "television", "microwave", "kettle"],
    9: ["fridge_freezer", "washer_dryer", "washing_machine", "dishwasher", "television", "microwave", "kettle", "hifi", "electric_heater"],
    10: ["blender", "toaster", "chest_freezer", "fridge_freezer", "washing_machine", "dishwasher", "television", "microwave", "food_mixer"],
    11: ["fridge", "fridge_freezer", "washing_machine", "dishwasher", "computer", "microwave", "kettle", "router", "hifi"],
    12: ["fridge_freezer", None, None, "computer", "microwave", "kettle", None, None, None],
    13: ["television", "freezer", "washing_machine", "dishwasher", None, "network_site", "microwave_1", "microwave_2", "kettle"],
    15: ["fridge_freezer", "tumble_dryer", "washing_machine", "dishwasher", "computer", "television", "microwave", "hifi", "toaster"],
    16: ["fridge_freezer_1", "fridge_freezer_2", "electric_heater_1", "electric_heater_2", "washing_machine", "dishwasher", "computer", "television", "dehumidifier"],
    17: ["freezer", "fridge_freezer", "tumble_dryer", "washing_machine", "computer", "television", "microwave", "kettle", "television_2"],
    18: ["fridge", "freezer", "fridge_freezer", "washer_dryer", "washing_machine", "dishwasher", "computer", "television", "microwave"],
    19: ["fridge_freezer", "washing_machine", "television", "microwave", "kettle", "toaster", "bread_maker", "games_console", "hifi"],
    20: ["fridge", "freezer", "tumble_dryer", "washing_machine", "dishwasher", "computer", "television", "microwave", "kettle"],
    21: ["fridge_freezer", "tumble_dryer", "washing_machine", "dishwasher", "food_mixer", "television", "kettle", "vivarium", "pond_pump"],
}

FLEXIBLE_KINDS = ("washing_machine", "dishwasher", "tumble_dryer")
# Shiftable, but not one of the scheduled kinds: a washer-dryer runs wash and dry as one cycle, so it is
# not a tumble-dryer profile. Its load is still removed from the base load.
OTHER_SHIFTABLE_KINDS = ("washer_dryer",)

TYPICAL_KW = {
    "fridge": 0.08, "freezer": 0.08, "chest_freezer": 0.08, "fridge_freezer": 0.1, "computer": 0.15,
    "television": 0.1, "electric_heater": 1.5, "microwave": 1.0, "toaster": 0.9, "kettle": 2.0, "hifi": 0.05,
    "overhead_fan": 0.05, "router": 0.01, "network_site": 0.02, "dehumidifier": 0.3, "blender": 0.3,
    "food_mixer": 0.3, "bread_maker": 0.5, "games_console": 0.1, "vivarium": 0.1, "pond_pump": 0.1,
}  # fmt: skip


def base_kind(name: str) -> str:
    """"washing_machine_2" -> "washing_machine"."""
    head, _, tail = name.rpartition("_")
    return head if tail.isdigit() else name


def _columns(house: int, kinds: tuple[str, ...]) -> dict[str, str]:
    return {
        f"Appliance{i}": base_kind(name)
        for i, name in enumerate(HOUSE_APPLIANCES[house], 1)
        if name and base_kind(name) in kinds
    }


FLEXIBLE_COLUMNS: dict[int, dict[str, str]] = {h: _columns(h, FLEXIBLE_KINDS) for h in HOUSE_APPLIANCES}
OTHER_SHIFTABLE_COLUMNS: dict[int, dict[str, str]] = {h: _columns(h, OTHER_SHIFTABLE_KINDS) for h in HOUSE_APPLIANCES}
# Houses left out of the benchmark, with the reason (report in the thesis, Section 5.1).
EXCLUDED_HOUSES: dict[int, str] = {
    12: "no washing machine, dishwasher or tumble dryer monitored",
    19: (
        "washing-machine IAM never shows a heating phase: 0 of 246 cycles exceed 1.2 kW (15-min mean) "
        "vs 22-70% in other houses; median 0.24 kWh per cycle. Not representative of the heating load "
        "that drives cost and peaks (cold-only use or a mislabelled monitor)"
    ),
}
ALL_HOUSES: tuple[int, ...] = tuple(h for h in HOUSE_APPLIANCES if FLEXIBLE_COLUMNS[h] and h not in EXCLUDED_HOUSES)


# Longest "off" pause merged into one programme. Dishwashers pause for passive drying (~20-30 min, e.g.
# house 2) and are rarely run back to back; washers and dryers are often reloaded within minutes, so a
# long merge window would fuse consecutive loads.
MERGE_GAP_MIN: dict[str, int] = {"dishwasher": 30, "washing_machine": 15, "tumble_dryer": 15}


def house_file(refit_dir: str | Path, house: int) -> Path:
    directory = Path(refit_dir)
    for pattern in (f"CLEAN_House{house}.csv", f"House_{house}.csv", f"*House{house}.csv", f"*House_{house}.csv"):
        matches = sorted(directory.glob(pattern))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"no REFIT CSV for house {house} in {directory}")


def shiftable_columns(house: int) -> list[str]:
    return [*FLEXIBLE_COLUMNS[house], *OTHER_SHIFTABLE_COLUMNS.get(house, {})]


def load_house(refit_dir: str | Path, house: int) -> pd.DataFrame:
    columns = ["Time", "Aggregate", *shiftable_columns(house), "Issues"]
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
    return [profile for _start, profile in timed_cycles(watts, on_w, max_gap_min, min_duration_min, max_duration_min,
                                                         min_energy_kwh)]  # fmt: skip


def timed_cycles(
    watts: pd.Series,
    on_w: float = 20.0,
    max_gap_min: int = 10,
    min_duration_min: int = 20,
    max_duration_min: int = 300,
    min_energy_kwh: float = 0.1,
) -> list[tuple[pd.Timestamp, list[float]]]:
    """The cycles of ``detect_cycles`` with the time each one started (local time of the REFIT recording)."""
    per_min = watts.resample("1min").mean().fillna(0.0)
    on = per_min > on_w
    if not on.any():
        return []
    on_times = per_min.index[on]
    breaks = np.flatnonzero(on_times[1:] - on_times[:-1] > pd.Timedelta(minutes=max_gap_min))
    starts = np.r_[0, breaks + 1]
    ends = np.r_[breaks, len(on_times) - 1]

    cycles: list[tuple[pd.Timestamp, list[float]]] = []
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
            cycles.append((on_times[s], [round(float(p), 3) for p in profile_kw]))
    return cycles


def typical_base_load(house_df: pd.DataFrame, house: int) -> np.ndarray:
    """Median non-shiftable load per 15-min slot of the day (kW): aggregate minus flexible sub-meters."""
    clean = house_df[house_df["Issues"] != 1] if "Issues" in house_df else house_df
    shiftable = clean[shiftable_columns(house)].sum(axis=1)
    base = (clean["Aggregate"] - shiftable).clip(lower=0).resample(f"{SLOT_MINUTES}min").mean().dropna()
    slot_of_day = base.index.hour * 4 + base.index.minute // SLOT_MINUTES
    profile = base.groupby(slot_of_day).median().reindex(range(SLOTS_PER_DAY)).interpolate().bfill().ffill()
    return profile.to_numpy() / 1000


def fixed_appliances(house: int) -> list[FixedAppliance]:
    """Non-shiftable appliances of a house (shown to the Appliance Profiler); their load is in the base load."""
    shiftable = FLEXIBLE_KINDS + OTHER_SHIFTABLE_KINDS
    return [
        FixedAppliance(id=name, kind=base_kind(name), typical_power_kw=TYPICAL_KW.get(base_kind(name), 0.1))
        for name in HOUSE_APPLIANCES[house]
        if name and base_kind(name) not in shiftable
    ]


def inspect(refit_dir: str | Path, houses: tuple[int, ...] = ALL_HOUSES) -> pd.DataFrame:
    rows = []
    for house in houses:
        df = load_house(refit_dir, house)
        for column, kind in FLEXIBLE_COLUMNS[house].items():
            cycles = detect_cycles(df[column], max_gap_min=MERGE_GAP_MIN[kind])
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
