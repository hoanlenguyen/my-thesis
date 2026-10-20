"""Factorial benchmark design: price regime x household load, under the 8 kW peak limit.

Each factor varies on its own, so an effect can be attributed to it:
  regime (4)  stable, volatile, spike, negative: how the day's prices behave
  load   (2)  light: dishwasher + washing machine with separate daytime windows;
              heavy: two washes, two dryings and a dishwasher sharing one window
The peak limit is 8 kW, the threshold of the Energy Authority's regulation on distribution fees (2 Feb 2026):
a household's power charge starts when its 60-minute average power exceeds 8 kW. The benchmark treats it as a
hard limit in every 15-minute slot, which is stricter than the charge.
Every regime x load cell gets its own price days.

Until 20 Oct 2026 the limit was a third factor with a second, stylised level of 3.5 kW (ids ending in -35, type
"<regime>-<load>-strict"); it had no source and was dropped. The sets built before then (data/scenarios_v2, the
registered data/scenarios_q2) still hold both levels and stay as recorded (git a01bb6a builds them).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from hems.core.models import Scenario, load_scenarios
from hems.data import prices as price_data
from hems.data import refit
from hems.data.build import load_household_data
from hems.data.scenarios import TypeSpec, compose_scenario, daily_stats
from hems.data.tariff import Tariff

REGIMES = ("stable", "volatile", "spike", "negative")
LOADS: dict[str, TypeSpec] = {
    "light": TypeSpec(("dishwasher", "washing_machine"), "normal"),
    "heavy": TypeSpec(("washing_machine", "washing_machine", "tumble_dryer", "tumble_dryer", "dishwasher"), "overlap"),
}
LIMIT_KW = 8.0  # Energy Authority power-charge threshold; ids end in -80, types in -realistic as before
CODES = {"stable": "S", "volatile": "V", "spike": "P", "negative": "N", "light": "L", "heavy": "H"}
MIN_NEGATIVE_SLOTS = 4  # at least one hour below zero


def select_regime_days(
    days: pd.DataFrame, rng: np.random.Generator, per_cell: int, exclude: set[date] | None = None,
    allow_fewer: bool = False,
) -> dict[tuple[str, str], list[date]]:  # fmt: skip
    """``per_cell`` days for every (regime, load) cell; no day is used twice.

    negative: at least one hour below zero. spike: the highest daily maxima among days without negative
    prices. volatile: the top 15 % by standard deviation among the remaining days without negative prices.
    stable: the bottom 25 % by standard deviation. Drawn in that order, so the rarer regimes come first.
    """
    if exclude:
        days = days[[d not in exclude for d in days.index]]
    stats = daily_stats(days)
    positive = stats[stats.n_negative == 0]
    q = positive["std"].quantile
    need = per_cell * len(LOADS)
    pools = {
        "negative": stats.index[stats.n_negative >= MIN_NEGATIVE_SLOTS],
        "spike": positive.sort_values("max", ascending=False).index[: 2 * need],
        "volatile": positive.index[positive["std"] >= q(0.85)],
        "stable": positive.index[positive["std"] <= q(0.25)],
    }
    used: set[date] = set()
    chosen: dict[tuple[str, str], list[date]] = {}
    for regime in ("negative", "spike", "volatile", "stable"):
        available = [d for d in pools[regime] if d not in used]
        k = min(need, len(available)) if allow_fewer else need
        if len(available) < k:
            raise ValueError(f"only {len(available)} candidate days for {regime}, need {k}")
        picked = list(rng.choice(np.asarray(available, dtype=object), size=k, replace=False))
        used.update(picked)
        half = len(picked) // 2
        chosen[regime, "light"], chosen[regime, "heavy"] = sorted(picked[:half]), sorted(picked[half:])
    return chosen


def compose_cell(
    scenario_id: str, regime: str, load: str, day: date, spot: np.ndarray, base_load: np.ndarray,
    pool: dict, fixed: list, rng: np.random.Generator, tariff: Tariff, house: int,
) -> list[Scenario]:  # fmt: skip
    """The day's scenario under the 8 kW limit (id ends in -80; the same draws as the earlier two-level design)."""
    scenario = compose_scenario(
        scenario_id=f"{scenario_id}-80", scenario_type=f"{regime}-{load}-realistic", day=day, spot_eur_per_kwh=spot,
        base_load_kw=base_load, profile_pool=pool, fixed_appliances=fixed, rng=rng, tariff=tariff,
        peak_limit_kw=LIMIT_KW, spec=LOADS[load],
    )  # fmt: skip
    scenario.notes = f"REFIT house {house}. {scenario.notes}".strip()
    return [scenario]


def build_factorial(
    refit_dir: str | Path,
    price_csv: str | Path,
    out_dir: str | Path,
    *,
    per_cell: int = 6,
    seed: int = 2028,
    id_prefix: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    exclude_dirs: tuple[str | Path, ...] = (),
    houses: tuple[int, ...] = refit.ALL_HOUSES,
    tariff: Tariff = Tariff(),
    local_tz: str = price_data.LOCAL_TZ,
    price_scale: float = 1.0,
    allow_fewer: bool = False,
) -> dict:
    """``local_tz``, ``price_scale`` and ``allow_fewer`` serve the UK appendix set: GB prices in GBP on London
    time, converted to EUR, with no negative-price days (that pattern then gets no scenarios)."""
    rng = np.random.default_rng(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    excluded = {date.fromisoformat(s.date) for d in exclude_dirs for s in load_scenarios(d)}
    pool, base_loads, cycle_counts = load_household_data(refit_dir, houses)
    days = price_data.to_daily_slots(price_data.load_price_csv(price_csv, local_tz=local_tz, scale=price_scale))
    days = days[[(date_from is None or d >= date_from) and (date_to is None or d <= date_to) for d in days.index]]
    chosen = select_regime_days(days, rng, per_cell, excluded, allow_fewer=allow_fewer)

    written: list[str] = []
    base_houses = list(rng.permutation(houses))
    n = 0
    for (regime, load), cell_days in chosen.items():
        for i, day in enumerate(cell_days, 1):
            house = int(base_houses[n % len(base_houses)])
            n += 1
            for scenario in compose_cell(
                f"{id_prefix}{CODES[regime]}{CODES[load]}{i:02d}", regime, load, day, days.loc[day].to_numpy(),
                base_loads[house], pool, refit.fixed_appliances(house), rng, tariff, house,
            ):  # fmt: skip
                scenario.save(out / f"{scenario.id}.json")
                written.append(scenario.id)
    manifest = {
        "design": "factorial: regime x load, 8 kW limit (hems.data.factorial)",
        "seed": seed, "per_cell": per_cell, "limit_kw": LIMIT_KW, "tariff": tariff.__dict__,
        "houses": list(houses), "price_csv": str(price_csv), "price_days_available": len(days),
        "price_period": [days.index.min().isoformat(), days.index.max().isoformat()],
        "price_resolution_min": price_data.native_resolution_minutes(price_csv, date_from),
        "local_tz": local_tz, "price_scale": price_scale,
        "excluded_sets": [str(d) for d in exclude_dirs], "excluded_days": len(excluded),
        "profile_sources": {k: len(v) for k, v in pool.items()}, "cycles_detected": cycle_counts,
        "days": {f"{r}-{lo}": [d.isoformat() for d in ds] for (r, lo), ds in chosen.items()},
        "scenarios": written,
    }  # fmt: skip
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest
