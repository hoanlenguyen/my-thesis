"""Several allowed periods per appliance (demo "Try it" view), e.g. 06:00-09:00 and 18:00-22:00.

A cycle must start and finish inside one period. Without periods every system behaves exactly as before
(tests/test_regression.py); these tests cover the multi-period case.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hems.core.evaluate import evaluate
from hems.core.models import FlexibleAppliance, Scenario
from hems.solvers.milp import solve_milp
from hems.solvers.naive import cheapest_hours_schedule, cheapest_window_schedule, naive_schedule, smart_timer_schedule
from hems.tools import build_tools

from .conftest import make_scenario

MORNING = (24, 36)  # 06:00-09:00
EVENING = (72, 88)  # 18:00-22:00


def with_periods(scenario: Scenario, periods: list[tuple[int, int]], cheap_gap: bool = True) -> Scenario:
    """The scenario with its first appliance limited to ``periods``; the gap between them is made the
    cheapest time of the day, so a system that ignored the periods would start there."""
    a = scenario.appliances[0]
    fields = a.model_dump() | {"earliest_slot": periods[0][0], "deadline_slot": periods[-1][1],
                               "default_start_slot": periods[0][0], "windows": periods}  # fmt: skip
    first = FlexibleAppliance(**fields)
    prices = list(scenario.price_eur_per_kwh)
    if cheap_gap:
        for t in range(periods[0][1], periods[-1][0]):
            prices[t] = 0.0
    return Scenario.model_validate(scenario.model_dump() | {"appliances": [first.model_dump(), *[x.model_dump() for x in scenario.appliances[1:]]],
                                                              "price_eur_per_kwh": prices})  # fmt: skip


@pytest.fixture
def two_periods() -> Scenario:
    sc = make_scenario("B", seed=3)
    d = sc.appliances[0].duration_slots
    return with_periods(sc, [(MORNING[0], max(MORNING[1], MORNING[0] + d)), (EVENING[0], max(EVENING[1], EVENING[0] + d + 2))])


def test_valid_starts_are_the_union_of_the_periods(two_periods: Scenario) -> None:
    a = two_periods.appliances[0]
    (s0, e0), (s1, e1) = a.windows  # type: ignore[misc]
    d = a.duration_slots
    assert list(a.valid_starts()) == [*range(s0, e0 - d + 1), *range(s1, e1 - d + 1)]
    assert all(s not in a.valid_starts() for s in range(e0 - d + 1, s1))  # a cycle may not span the gap
    assert a.window_periods() == [(s0, e0), (s1, e1)]


def test_single_window_is_unchanged_and_not_serialised() -> None:
    a = make_scenario("B", seed=3).appliances[0]
    assert a.windows is None and a.valid_starts() == range(a.earliest_slot, a.latest_start_slot + 1)
    assert a.window_periods() == [(a.earliest_slot, a.deadline_slot)]
    assert "windows" not in a.model_dump() and "windows" not in a.model_dump_json()


def test_periods_are_validated(two_periods: Scenario) -> None:
    fields = two_periods.appliances[0].model_dump()
    assert fields["windows"] is not None  # serialised when set
    with pytest.raises(ValidationError, match="must not overlap"):
        FlexibleAppliance(**fields | {"windows": [(24, 60), (50, 88)]})
    with pytest.raises(ValidationError, match="span the periods"):
        FlexibleAppliance(**fields | {"earliest_slot": 0})
    with pytest.raises(ValidationError, match="shorter than the cycle"):
        FlexibleAppliance(**fields | {"windows": [(24, 25), (87, 88)], "earliest_slot": 24, "deadline_slot": 88,
                                      "default_start_slot": 24})  # fmt: skip


def test_a_start_in_the_gap_is_a_violation(two_periods: Scenario) -> None:
    a = two_periods.appliances[0]
    gap_start = a.windows[0][1]  # type: ignore[index]
    schedule = naive_schedule(two_periods) | {a.id: gap_start}
    result = evaluate(two_periods, schedule)
    assert not result.feasible and any("outside the periods" in v for v in result.violations)


@pytest.mark.parametrize("system", [solve_milp, smart_timer_schedule, cheapest_hours_schedule, cheapest_window_schedule,
                                    naive_schedule])  # fmt: skip
def test_every_system_keeps_the_cycle_inside_one_period(two_periods: Scenario, system) -> None:  # type: ignore[no-untyped-def]
    out = system(two_periods)
    schedule = out.schedule if hasattr(out, "schedule") else out
    a = two_periods.appliances[0]
    start = schedule[a.id]
    assert any(p0 <= start and start + a.duration_slots <= p1 for p0, p1 in a.windows)  # type: ignore[union-attr]


def test_cheapest_window_block_fits_inside_one_period(two_periods: Scenario) -> None:
    a = two_periods.appliances[0]
    start = cheapest_window_schedule(two_periods)[a.id]
    block = -(-a.duration_slots // 4) * 4
    assert start % 4 == 0 and any(p0 <= start and start + block <= p1 for p0, p1 in a.windows)  # type: ignore[union-attr]


def test_tools_describe_the_periods_and_flag_the_gap(two_periods: Scenario) -> None:
    tools = build_tools(two_periods)
    a = two_periods.appliances[0]
    data = tools["read_household_data"].invoke({})
    assert "may run only within 06:00-09:" in data and " or 18:00-" in data
    gap = two_periods.slot_to_time(a.windows[0][1])  # type: ignore[index]
    assert "OUTSIDE user window" in tools["calculate_schedule_cost"].invoke({"appliance_id": a.id, "start_time": gap})
    others = make_scenario("B", seed=3)  # appliances without periods keep the original text
    assert "ready from" in build_tools(others)["read_household_data"].invoke({})
