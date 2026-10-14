"""The single scoring function every system is evaluated with.

Cost is the consumer cost of the *flexible* appliance energy only; the base
load costs the same under every schedule, so including it would only dilute
differences between systems. The base load does count towards the peak limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from hems.core.models import SLOT_HOURS, SLOTS_PER_DAY, FlexibleAppliance, Scenario, Schedule

PEAK_TOLERANCE_KW = 1e-6


def appliance_load(appliance: FlexibleAppliance, start: int) -> np.ndarray:
    load = np.zeros(SLOTS_PER_DAY)
    end = min(start + appliance.duration_slots, SLOTS_PER_DAY)
    load[start:end] = appliance.profile_kw[: end - start]
    return load


def appliance_cost(scenario: Scenario, appliance: FlexibleAppliance, start: int) -> float:
    prices = np.asarray(scenario.price_eur_per_kwh)
    return float(appliance_load(appliance, start) @ prices * SLOT_HOURS)


def total_load(scenario: Scenario, schedule: Schedule) -> np.ndarray:
    load = np.asarray(scenario.base_load_kw, dtype=float).copy()
    for appliance in scenario.appliances:
        if appliance.id in schedule:
            load += appliance_load(appliance, schedule[appliance.id])
    return load


@dataclass
class Evaluation:
    cost_eur: float
    per_appliance_cost_eur: dict[str, float]
    feasible: bool
    violations: list[str] = field(default_factory=list)
    peak_kw: float = 0.0
    overloaded_slots: list[int] = field(default_factory=list)


def evaluate(scenario: Scenario, schedule: Schedule) -> Evaluation:
    violations: list[str] = []
    known = {a.id for a in scenario.appliances}
    for extra in sorted(set(schedule) - known):
        violations.append(f"unknown appliance {extra}")

    per_appliance: dict[str, float] = {}
    for appliance in scenario.appliances:
        start = schedule.get(appliance.id)
        if start is None:
            violations.append(f"{appliance.id}: not scheduled")
            continue
        if start not in appliance.valid_starts() and appliance.windows is not None:  # several periods (demo)
            periods = " or ".join(f"{scenario.slot_to_time(s)}-{scenario.boundary_to_time(e)}" for s, e in appliance.windows)
            violations.append(f"{appliance.id}: start {scenario.slot_to_time(start)} outside the periods {periods}")
        elif start not in appliance.valid_starts():
            violations.append(
                f"{appliance.id}: start {scenario.slot_to_time(start)} outside window "
                f"{scenario.slot_to_time(appliance.earliest_slot)}-{scenario.slot_to_time(appliance.latest_start_slot)}"
            )
        per_appliance[appliance.id] = appliance_cost(scenario, appliance, start)

    valid = {k: v for k, v in schedule.items() if k in known}
    load = total_load(scenario, valid)
    overloaded = [int(t) for t in np.flatnonzero(load > scenario.peak_limit_kw + PEAK_TOLERANCE_KW)]
    if overloaded:
        violations.append(
            f"peak limit {scenario.peak_limit_kw:.2f} kW exceeded in {len(overloaded)} slot(s), max {load.max():.2f} kW"
        )

    return Evaluation(
        cost_eur=float(sum(per_appliance.values())),
        per_appliance_cost_eur=per_appliance,
        feasible=not violations,
        violations=violations,
        peak_kw=float(load.max()),
        overloaded_slots=overloaded,
    )
