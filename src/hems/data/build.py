"""Build the frozen 48-scenario benchmark from REFIT + Nord Pool FI data."""

from __future__ import annotations

import json
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
    peak_limit_kw: float = 4.0,
    houses: tuple[int, ...] = (1, 2, 3),
    price_kwargs: dict | None = None,
    tariff: Tariff = Tariff(),
) -> dict:
    rng = np.random.default_rng(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    pool: dict[str, list[list[float]]] = {"washing_machine": [], "dishwasher": [], "tumble_dryer": []}
    base_loads, cycle_counts = {}, {}
    for house in houses:
        df = refit.load_house(refit_dir, house)
        base_loads[house] = refit.typical_base_load(df, house)
        for column, kind in refit.FLEXIBLE_COLUMNS[house].items():
            cycles = refit.detect_cycles(df[column])
            pool[kind] += cycles
            cycle_counts[f"house{house}/{column}/{kind}"] = len(cycles)
    empty = [k for k, v in pool.items() if not v]
    if empty:
        raise ValueError(f"no REFIT cycles detected for {empty}; check the column mapping")

    days = price_data.to_daily_slots(price_data.load_price_csv(price_csv, **(price_kwargs or {})))
    chosen = select_days(days, rng)

    written = []
    for scenario_type, type_days in chosen.items():
        for i, day in enumerate(type_days, 1):
            house = houses[(i - 1) % len(houses)]
            scenario = compose_scenario(
                scenario_id=f"{scenario_type}{i:02d}",
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
        "price_csv": str(price_csv),
        "price_days_available": len(days),
        "cycles_detected": cycle_counts,
        "days": {t: [d.isoformat() for d in ds] for t, ds in chosen.items()},
        "scenarios": written,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest
