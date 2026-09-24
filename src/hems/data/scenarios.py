"""Scenario composition and price-day selection for the 48-scenario benchmark.

Six types x 8 instances (Table 5.1 of the thesis). Types differ in the price
regime of the selected day and in the appliance set / time windows. Types C-F
need up to five loads while REFIT gives three flexible appliance kinds, so a
day may contain repeated cycles of one kind (e.g. two washing loads).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

import numpy as np
import pandas as pd

from hems.core.models import SLOTS_PER_DAY, FixedAppliance, FlexibleAppliance, Scenario, ScenarioType
from hems.data.tariff import Tariff
from hems.solvers.milp import solve_milp

INSTANCES_PER_TYPE = 8
LABELS = {"washing_machine": "washing machine", "dishwasher": "dishwasher", "tumble_dryer": "tumble dryer"}


@dataclass(frozen=True)
class TypeSpec:
    appliances: tuple[str, ...]  # kinds; C draws 3-5 of these
    window: str  # "normal" | "overlap" | "tight" | "flexible"
    variable_count: bool = False


TYPE_SPECS: dict[str, TypeSpec] = {
    "A": TypeSpec(("dishwasher", "washing_machine"), "normal"),
    "B": TypeSpec(("dishwasher", "washing_machine", "tumble_dryer"), "normal"),
    "C": TypeSpec(("washing_machine", "tumble_dryer", "dishwasher", "washing_machine", "tumble_dryer"), "normal", True),
    "D": TypeSpec(("washing_machine", "washing_machine", "tumble_dryer", "tumble_dryer", "dishwasher"), "overlap"),
    "E": TypeSpec(("dishwasher", "washing_machine", "tumble_dryer"), "tight"),
    "F": TypeSpec(("washing_machine", "tumble_dryer", "dishwasher", "washing_machine"), "flexible"),
}

H = 4  # slots per hour


def _window(kind_duration: int, style: str, rng: np.random.Generator, shared: tuple[int, int] | None) -> tuple[int, int]:
    if style == "overlap" and shared:
        return shared
    if style == "tight":
        earliest = int(rng.integers(6 * H, 16 * H + 1))
        return earliest, min(SLOTS_PER_DAY, earliest + kind_duration + int(rng.integers(2 * H, 4 * H + 1)))
    if style == "flexible":
        earliest = int(rng.integers(0, 4 * H + 1))
        return earliest, SLOTS_PER_DAY
    earliest = int(rng.integers(6 * H, 12 * H + 1))  # normal
    return earliest, min(SLOTS_PER_DAY, earliest + int(rng.integers(8 * H, 14 * H + 1)))


def compose_scenario(
    *,
    scenario_id: str,
    scenario_type: ScenarioType,
    day: date,
    spot_eur_per_kwh: np.ndarray,
    base_load_kw: np.ndarray,
    profile_pool: dict[str, list[list[float]]],
    fixed_appliances: list[FixedAppliance],
    rng: np.random.Generator,
    tariff: Tariff = Tariff(),
    peak_limit_kw: float = 4.0,
    synthetic: bool = False,
) -> Scenario:
    spec = TYPE_SPECS[scenario_type]
    kinds = list(spec.appliances)
    if spec.variable_count:
        kinds = list(rng.permutation(kinds)[: int(rng.integers(3, 6))])

    shared = None
    if spec.window == "overlap":
        earliest = int(rng.integers(8 * H, 10 * H + 1))
        shared = (earliest, int(rng.integers(22 * H, SLOTS_PER_DAY + 1)))

    appliances: list[FlexibleAppliance] = []
    counts: dict[str, int] = {}
    for kind in kinds:
        counts[kind] = counts.get(kind, 0) + 1
        pool = profile_pool[kind]
        profile = [round(float(p), 3) for p in pool[int(rng.integers(len(pool)))]]
        earliest, deadline = _window(len(profile), spec.window, rng, shared)
        appliances.append(
            FlexibleAppliance(
                id=f"{kind}_{counts[kind]}",
                kind=kind,  # type: ignore[arg-type]
                profile_kw=profile,
                earliest_slot=earliest,
                deadline_slot=deadline,
                default_start_slot=earliest,
            )
        )

    # The limit must admit every appliance on its own; raise it until the MILP is feasible.
    limit = max(peak_limit_kw, float(np.max(base_load_kw)) + max(a.peak_kw for a in appliances) + 0.2)
    notes = ""
    while True:
        scenario = Scenario(
            id=scenario_id,
            type=scenario_type,
            date=day.isoformat(),
            start_time=datetime.combine(day, time(0, 0)),
            spot_eur_per_kwh=[round(float(p), 5) for p in spot_eur_per_kwh],
            price_eur_per_kwh=[round(float(p), 5) for p in tariff.consumer_price(spot_eur_per_kwh)],
            base_load_kw=[round(float(b), 3) for b in base_load_kw],
            peak_limit_kw=round(limit, 2),
            appliances=appliances,
            fixed_appliances=fixed_appliances,
            user_request="",
            synthetic=synthetic,
            notes=notes,
        )
        if solve_milp(scenario).status == "Optimal":
            break
        limit += 0.5
        notes = f"peak limit raised to {limit:.2f} kW for feasibility"

    scenario.user_request = build_request(scenario)
    return scenario


def build_request(scenario: Scenario) -> str:
    items = [
        f"- {LABELS[a.kind]} ({a.id}): ready from {scenario.slot_to_time(a.earliest_slot)}, "
        f"must finish by {scenario.boundary_to_time(a.deadline_slot)}"
        for a in scenario.appliances
    ]
    return (
        f"I'm on a spot-price electricity contract. Please schedule these appliance cycles for {scenario.date} "
        f"so that my electricity cost is as low as possible, without exceeding my household peak load limit:\n"
        + "\n".join(items)
    )


# ── Price-day selection (real data) ────────────────────────────────────────────


def daily_stats(days: pd.DataFrame) -> pd.DataFrame:
    """``days``: index = date, 96 columns of spot EUR/kWh. Returns per-day volatility statistics."""
    values = days.to_numpy()
    return pd.DataFrame(
        {
            "mean": values.mean(axis=1),
            "std": values.std(axis=1),
            "max": values.max(axis=1),
            "min": values.min(axis=1),
            "n_negative": (values < 0).sum(axis=1),
            "month": [d.month for d in days.index],
        },
        index=days.index,
    )


def select_days(
    days: pd.DataFrame,
    rng: np.random.Generator,
    crisis: tuple[str, str] = ("2022-12-01", "2022-12-31"),
    min_negative_slots: int = 8,
) -> dict[str, list[date]]:
    """Pick INSTANCES_PER_TYPE days per scenario type; A and B draw disjoint stable days."""
    stats = daily_stats(days)
    normal = stats[(stats.n_negative == 0) & ~stats.index.isin(pd.date_range(*crisis).date)]
    q = normal["std"].quantile

    pools: dict[str, pd.Index] = {
        "stable": normal.index[normal["std"] <= q(0.25)],
        "C": normal.index[(normal["std"] >= q(0.40)) & (normal["std"] <= q(0.60))],
        "D": normal.index[normal.month.isin([12, 1, 2]) & (normal["std"] >= q(0.85))],
        "E": stats.loc[stats.index.isin(pd.date_range(*crisis).date)].sort_values("max", ascending=False).index[
            : 2 * INSTANCES_PER_TYPE
        ],
        "F": stats.index[stats.n_negative >= min_negative_slots],
    }

    def draw(pool: pd.Index, k: int, name: str) -> list[date]:
        if len(pool) < k:
            raise ValueError(f"only {len(pool)} candidate days for {name}, need {k}")
        return sorted(rng.choice(np.asarray(pool, dtype=object), size=k, replace=False).tolist())

    stable = draw(pools["stable"], 2 * INSTANCES_PER_TYPE, "A/B")
    rng.shuffle(stable)
    return {
        "A": sorted(stable[:INSTANCES_PER_TYPE]),
        "B": sorted(stable[INSTANCES_PER_TYPE:]),
        "C": draw(pools["C"], INSTANCES_PER_TYPE, "C"),
        "D": draw(pools["D"], INSTANCES_PER_TYPE, "D"),
        "E": draw(pools["E"], INSTANCES_PER_TYPE, "E"),
        "F": draw(pools["F"], INSTANCES_PER_TYPE, "F"),
    }
