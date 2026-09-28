"""Build the frozen 48-scenario benchmark from REFIT + Nord Pool FI data."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np

from hems.data import prices as price_data
from hems.data import refit
from hems.data.scenarios import compose_scenario, select_days
from hems.data.tariff import Tariff


def build_benchmark(
    refit_dir: str | Path,
    price_csv: str | Path,
    out_dir: str | Path,
    *,
    seed: int = 2026,
    peak_limit_kw: float = 3.5,
    houses: tuple[int, ...] = refit.ALL_HOUSES,
    price_kwargs: dict | None = None,
    tariff: Tariff = Tariff(),
    date_from: date | None = None,
    date_to: date | None = None,
    crisis: tuple[str, str] | None = ("2022-12-01", "2022-12-31"),
    id_prefix: str = "",
) -> dict:
    rng = np.random.default_rng(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # kind -> one group of cycles per monitored appliance, so heavy-use households don't dominate sampling
    pool: dict[str, list[list[list[float]]]] = {"washing_machine": [], "dishwasher": [], "tumble_dryer": []}
    base_loads, cycle_counts = {}, {}
    for house in houses:
        df = refit.load_house(refit_dir, house)
        base_loads[house] = refit.typical_base_load(df, house)
        for column, kind in refit.FLEXIBLE_COLUMNS[house].items():
            cycles = refit.detect_cycles(df[column], max_gap_min=refit.MERGE_GAP_MIN[kind])
            if cycles:
                pool[kind].append(cycles)
            cycle_counts[f"house{house}/{column}/{kind}"] = len(cycles)
    empty = [k for k, v in pool.items() if not v]
    if empty:
        raise ValueError(f"no REFIT cycles detected for {empty}; check the column mapping")

    days = price_data.to_daily_slots(price_data.load_price_csv(price_csv, **(price_kwargs or {})))
    days = days[[(date_from is None or d >= date_from) and (date_to is None or d <= date_to) for d in days.index]]
    chosen = select_days(days, rng, crisis=crisis)

    written = []
    base_houses = list(rng.permutation(houses))
    for scenario_type, type_days in chosen.items():
        for i, day in enumerate(type_days, 1):
            house = int(base_houses[len(written) % len(base_houses)])
            scenario = compose_scenario(
                scenario_id=f"{id_prefix}{scenario_type}{i:02d}",
                scenario_type=scenario_type,  # type: ignore[arg-type]
                day=day,
                spot_eur_per_kwh=days.loc[day].to_numpy(),
                base_load_kw=base_loads[house],
                profile_pool=pool,
                fixed_appliances=refit.fixed_appliances(house),
                rng=rng,
                tariff=tariff,
                peak_limit_kw=peak_limit_kw,
            )
            scenario.notes = f"REFIT house {house}. {scenario.notes}".strip()
            scenario.save(out / f"{scenario.id}.json")
            written.append(scenario.id)

    manifest = {
        "seed": seed,
        "peak_limit_kw": peak_limit_kw,
        "tariff": tariff.__dict__,
        "refit_dir": str(refit_dir),
        "houses": list(houses),
        "excluded_houses": {h: r for h, r in refit.EXCLUDED_HOUSES.items() if h not in houses},
        "profile_sources": {k: len(v) for k, v in pool.items()},
        "price_csv": str(price_csv),
        "price_days_available": len(days),
        "price_period": [days.index.min().isoformat(), days.index.max().isoformat()],
        "price_resolution_min": price_data.native_resolution_minutes(price_csv, date_from, **(price_kwargs or {})),
        "type_e_days": f"crisis {crisis[0]}..{crisis[1]}" if crisis else "16 highest-peak days of the period",
        "cycles_detected": cycle_counts,
        "days": {t: [d.isoformat() for d in ds] for t, ds in chosen.items()},
        "scenarios": written,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest
