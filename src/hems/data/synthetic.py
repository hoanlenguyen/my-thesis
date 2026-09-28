"""Synthetic scenarios for development, tests and pipeline pilots.

These are NOT the thesis benchmark: every generated scenario is flagged
``synthetic=True`` and prefixed ``SYN-``. The benchmark is built from REFIT
profiles and Nord Pool FI prices by ``hems scenarios build``.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np

from hems.core.models import SLOTS_PER_DAY, FixedAppliance, Scenario
from hems.data.scenarios import INSTANCES_PER_TYPE, TYPE_SPECS, compose_scenario

# Stylised 15-min cycle shapes (kW): heating phases dominate the peak.
CYCLES: dict[str, list[list[float]]] = {
    "washing_machine": [
        [2.0, 2.0, 0.3, 0.2, 0.2, 0.5, 0.3, 0.1],
        [2.1, 1.6, 0.2, 0.2, 0.4, 0.4],
    ],
    "dishwasher": [
        [1.9, 1.9, 0.1, 0.1, 1.8, 0.2, 0.1],
        [2.0, 1.2, 0.1, 1.9, 0.1],
    ],
    "tumble_dryer": [
        [2.3, 2.3, 2.3, 2.3, 2.3, 2.3, 1.0],
        [2.2, 2.2, 2.2, 2.2, 0.8],
    ],
}

PROFILE_POOL: dict[str, list[list[list[float]]]] = {kind: [cycles] for kind, cycles in CYCLES.items()}  # one "household"

FIXED = [
    FixedAppliance(id="fridge_freezer", kind="fridge_freezer", typical_power_kw=0.08),
    FixedAppliance(id="microwave", kind="microwave", typical_power_kw=1.0),
    FixedAppliance(id="television", kind="television", typical_power_kw=0.1),
]


def synthetic_spot(scenario_type: str, rng: np.random.Generator) -> np.ndarray:
    hours = np.arange(SLOTS_PER_DAY) / 4
    morning = np.exp(-((hours - 8) ** 2) / 4)
    evening = np.exp(-((hours - 18.5) ** 2) / 5)
    amplitude = {"A": 0.01, "B": 0.01, "C": 0.04, "D": 0.12, "E": 0.25, "F": 0.03}[scenario_type]
    base = {"A": 0.04, "B": 0.04, "C": 0.07, "D": 0.12, "E": 0.20, "F": 0.02}[scenario_type]
    spot = base + amplitude * (morning + 1.3 * evening) + rng.normal(0, amplitude / 8, SLOTS_PER_DAY)
    if scenario_type == "E":
        spike = int(rng.integers(16 * 4, 19 * 4))
        spot[spike : spike + 8] += 0.6
    if scenario_type == "F":
        midday = np.exp(-((hours - 13) ** 2) / 6)
        spot -= 0.05 * midday
    return spot


def synthetic_base_load(rng: np.random.Generator) -> np.ndarray:
    hours = np.arange(SLOTS_PER_DAY) / 4
    return 0.25 + 0.3 * np.exp(-((hours - 19) ** 2) / 6) + rng.uniform(0, 0.05, SLOTS_PER_DAY)


def generate(out_dir: str | Path, per_type: int = INSTANCES_PER_TYPE, seed: int = 7, peak_limit_kw: float = 4.0) -> list[Scenario]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    scenarios = []
    for scenario_type in TYPE_SPECS:
        for i in range(1, per_type + 1):
            scenario = compose_scenario(
                scenario_id=f"SYN-{scenario_type}{i:02d}",
                scenario_type=scenario_type,  # type: ignore[arg-type]
                day=date(2026, 1, 1) + timedelta(days=len(scenarios)),
                spot_eur_per_kwh=synthetic_spot(scenario_type, rng),
                base_load_kw=synthetic_base_load(rng),
                profile_pool=PROFILE_POOL,
                fixed_appliances=FIXED,
                rng=rng,
                peak_limit_kw=peak_limit_kw,
                synthetic=True,
            )
            scenario.save(out / f"{scenario.id}.json")
            scenarios.append(scenario)
    return scenarios
