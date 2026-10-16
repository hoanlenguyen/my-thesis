"""iHomeLab RAPT dataset (Huber et al., 2020): appliance cycles and the Swiss scenario set.

Uses the same detector and thresholds as the REFIT pipeline (`refit.detect_cycles`),
so cycles from the two datasets are directly comparable. RAPT is sampled at five
minutes, so each five-minute mean is held for its five minutes before the detector
resamples to one minute.

The Swiss set keeps the design of the held-out set Q2 (regime x load x limit, the
same price days and the same Finnish tariff) and replaces only the household data:
cycles and base loads come from RAPT houses A, D and E instead of REFIT.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from hems.core.models import SLOT_MINUTES, SLOTS_PER_DAY, FixedAppliance, load_scenarios
from hems.data import prices as price_data
from hems.data.factorial import CODES, compose_cell
from hems.data.refit import MERGE_GAP_MIN, detect_cycles
from hems.data.tariff import Tariff

# House -> {appliance kind: column}. Only houses with a metered dishwasher, washing machine or
# tumble dryer are listed (B and C meter none of them).
RAPT_COLUMNS: dict[str, dict[str, str]] = {
    "A": {"dishwasher": "A_dishwasher_power", "washing_machine": "A_washing_machine_power"},
    "D": {"dishwasher": "D_dishwasher_power", "washing_machine": "D_washing_machine_power"},
    "E": {
        "dishwasher": "E_dishwasher_power",
        "washing_machine": "E_washing_machine_power",
        "tumble_dryer": "E_tumble_dryer_power",
    },
}
# Metered appliances left out of the cycle pool, with the reason (report in the thesis).
EXCLUDED_APPLIANCES: dict[tuple[str, str], str] = {
    ("D", "tumble_dryer"): (
        "monitor reads about 80 W while on and never exceeds 1 kW (median cycle 0.24 kWh, median peak 0.21 kW): "
        "a standby or auxiliary load, not a heating phase. Its draw stays in the base load"
    ),
}
# Non-shiftable loads shown to the Appliance Profiler; their consumption is in the base load.
FIXED_COLUMNS: dict[str, dict[str, str]] = {
    "A": {"heat_pump": "A_hp_power", "sauna": "A_sauna_power", "stove": "A_stove_power"},
    "D": {"heat_pump": "D_hp_power", "audio_wlan": "D_audio_wlan_og_power", "rainwater_pump": "D_rainwater_power"},
    "E": {
        "dehumidifier": "E_dehumidifier_power",
        "gas_heating_pump": "E_gasheating_pump_power",
        "solar_heating_pump": "E_solarheating_pump_power",
    },
}
HOUSES: tuple[str, ...] = tuple(RAPT_COLUMNS)
ON_W = 20.0


def load_house(rapt_dir: str | Path, house: str) -> pd.DataFrame:
    return pd.read_hdf(Path(rapt_dir) / "data" / f"df{house}_300s.hdf").sort_index()


def _to_one_minute(watts: pd.Series) -> pd.Series:
    """Hold each five-minute mean for its five minutes; gaps stay NaN (read as off)."""
    watts = watts[~watts.index.duplicated(keep="first")]
    minutes = pd.date_range(watts.index.min(), watts.index.max(), freq="1min")
    return watts.reindex(minutes, method="ffill", limit=4)


def extract(rapt_dir: str | Path) -> dict[str, dict[str, list[list[float]]]]:
    out: dict[str, dict[str, list[list[float]]]] = {}
    for house, kinds in RAPT_COLUMNS.items():
        df = load_house(rapt_dir, house)
        out[house] = {
            kind: detect_cycles(_to_one_minute(df[column]), max_gap_min=MERGE_GAP_MIN[kind])
            for kind, column in kinds.items()
        }
    return out


def typical_base_load(df: pd.DataFrame, house: str) -> np.ndarray:
    """Median non-shiftable load per 15-min slot of the day (kW): total minus the pooled appliances.

    Rows where the total or a pooled appliance is missing are dropped, so a metering gap is not read
    as an appliance that was off (which would inflate the base load).
    """
    shiftable = list(RAPT_COLUMNS[house].values())
    clean = df[[f"{house}_total_cons_power", *shiftable]].dropna()
    base = (clean[f"{house}_total_cons_power"] - clean[shiftable].sum(axis=1)).clip(lower=0)
    base = base.resample(f"{SLOT_MINUTES}min").mean().dropna()
    slot_of_day = base.index.hour * 4 + base.index.minute // SLOT_MINUTES
    profile = base.groupby(slot_of_day).median().reindex(range(SLOTS_PER_DAY)).interpolate().bfill().ffill()
    return profile.to_numpy() / 1000


def fixed_appliances(df: pd.DataFrame, house: str) -> list[FixedAppliance]:
    """Fixed loads with a typical power taken from the house's own readings while on."""
    out = []
    for kind, column in FIXED_COLUMNS[house].items():
        on = df[column][df[column] > ON_W]
        typical = round(float(on.median()) / 1000, 2) if len(on) else 0.1
        out.append(FixedAppliance(id=kind, kind=kind, typical_power_kw=typical))
    return out


def load_household_data(rapt_dir: str | Path) -> tuple[dict, dict, dict, dict]:
    """Cycle pool by kind (one group per metered appliance), base load, fixed appliances, cycle counts."""
    pool: dict[str, list[list[list[float]]]] = {"washing_machine": [], "dishwasher": [], "tumble_dryer": []}
    base_loads: dict[str, np.ndarray] = {}
    fixed: dict[str, list[FixedAppliance]] = {}
    counts: dict[str, int] = {}
    cycles = extract(rapt_dir)
    for house in HOUSES:
        df = load_house(rapt_dir, house)
        base_loads[house] = typical_base_load(df, house)
        fixed[house] = fixed_appliances(df, house)
        for kind, found in cycles[house].items():
            if found:
                pool[kind].append(found)
            counts[f"house{house}/{kind}"] = len(found)
    return pool, base_loads, fixed, counts


def build_swiss_factorial(
    rapt_dir: str | Path,
    price_csv: str | Path,
    out_dir: str | Path,
    reference_manifest: str | Path,
    *,
    seed: int = 2030,
    id_prefix: str = "CH-",
    tariff: Tariff = Tariff(),
) -> dict:
    """Rebuild a factorial set on RAPT households, using the price days of ``reference_manifest``.

    Reusing the reference days (e.g. Q2) keeps the price patterns identical, so a difference to the
    reference set is attributable to the household data alone.
    """
    reference = json.loads(Path(reference_manifest).read_text(encoding="utf-8"))
    rng = np.random.default_rng(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    pool, base_loads, fixed, counts = load_household_data(rapt_dir)
    days = price_data.to_daily_slots(price_data.load_price_csv(price_csv))

    written: list[str] = []
    base_houses = [str(h) for h in rng.permutation(HOUSES)]
    n = 0
    for cell, iso_days in reference["days"].items():
        regime, load = cell.split("-")
        for i, iso in enumerate(iso_days, 1):
            house = base_houses[n % len(base_houses)]
            n += 1
            day = date.fromisoformat(iso)
            for scenario in compose_cell(
                f"{id_prefix}{CODES[regime]}{CODES[load]}{i:02d}", regime, load, day, days.loc[day].to_numpy(),
                base_loads[house], pool, fixed[house], rng, tariff, house,  # type: ignore[arg-type]
            ):  # fmt: skip
                scenario.notes = scenario.notes.replace("REFIT house", "RAPT house")
                scenario.save(out / f"{scenario.id}.json")
                written.append(scenario.id)

    manifest = {
        "design": "factorial on RAPT households: same price days, loads and limits as the reference set",
        "reference_set": str(reference_manifest), "seed": seed, "limits_kw": reference["limits_kw"],
        "tariff": tariff.__dict__, "houses": list(HOUSES), "excluded_appliances": {
            f"{h}/{k}": r for (h, k), r in EXCLUDED_APPLIANCES.items()
        },
        "profile_sources": {k: len(v) for k, v in pool.items()}, "cycles_detected": counts,
        "price_csv": str(price_csv), "days": reference["days"], "scenarios": written,
    }  # fmt: skip
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def summarise(rapt_dir: str | Path, cycles: dict[str, dict[str, list[list[float]]]]) -> pd.DataFrame:
    rows = []
    for house, kinds in RAPT_COLUMNS.items():
        df = load_house(rapt_dir, house)
        for kind, column in kinds.items():
            s = df[column]
            profiles = cycles[house][kind]
            dur = np.array([len(p) * SLOT_MINUTES for p in profiles], dtype=float)
            kwh = np.array([sum(p) * SLOT_MINUTES / 60 for p in profiles], dtype=float)
            peak = np.array([max(p) for p in profiles], dtype=float)
            days = max((s.index.max() - s.index.min()).days, 1)
            rows.append(
                {
                    "house": house, "appliance": kind, "days": days,
                    "nan_%": round(float(s.isna().mean()) * 100, 1),
                    "active_%": round(float((s > ON_W).mean()) * 100, 2),
                    "cycles": len(profiles), "cycles/week": round(len(profiles) / days * 7, 1),
                    "median_min": float(np.median(dur)) if len(dur) else np.nan,
                    "median_kwh": round(float(np.median(kwh)), 2) if len(kwh) else np.nan,
                    "median_peak_kw": round(float(np.median(peak)), 2) if len(peak) else np.nan,
                }
            )  # fmt: skip
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("cycles", help="extract cycles and write cycles_15min.json + cycle_summary.csv")
    p.add_argument("--rapt", default="data/rapt")
    p = sub.add_parser("build", help="build the Swiss factorial scenario set")
    p.add_argument("--rapt", default="data/rapt")
    p.add_argument("--prices", default="data/raw/prices_fi_elering.csv")
    p.add_argument("--reference", default="data/scenarios_q2/manifest.json")
    p.add_argument("--out", default="data/scenarios_rapt")
    p.add_argument("--seed", type=int, default=2030)
    args = parser.parse_args()

    root = Path(args.rapt)
    if args.cmd == "cycles":
        found = extract(root)
        table = summarise(root, found)
        pd.set_option("display.width", 200)
        print(table.to_string(index=False))
        print("\nTotals by appliance:\n" + table.groupby("appliance")["cycles"].sum().to_string())
        (root / "cycles_15min.json").write_text(json.dumps(found))
        table.to_csv(root / "cycle_summary.csv", index=False)
    else:
        manifest = build_swiss_factorial(root, args.prices, args.out, args.reference, seed=args.seed)
        scenarios = load_scenarios(args.out)
        print(f"{len(manifest['scenarios'])} scenarios written to {args.out}")
        print("profile sources:", manifest["profile_sources"])
        print("cycles:", manifest["cycles_detected"])
        raised = [s.id for s in scenarios if "raised" in s.notes]
        print(f"peak limit raised for feasibility in {len(raised)} scenarios: {raised[:10]}")
