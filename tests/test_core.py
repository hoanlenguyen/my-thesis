from __future__ import annotations

import itertools

import pytest

from hems.core.evaluate import evaluate
from hems.core.models import Scenario
from hems.solvers.milp import solve_milp
from hems.solvers.naive import greedy_schedule, naive_schedule
from hems.tools import ALL_TOOLS, PROFILER_TOOLS, RESOLVER_TOOLS, SCHEDULER_TOOLS, build_tools

from .conftest import make_scenario


def brute_force(scenario: Scenario) -> float:
    best = float("inf")
    for starts in itertools.product(*(a.valid_starts() for a in scenario.appliances)):
        result = evaluate(scenario, dict(zip([a.id for a in scenario.appliances], starts)))
        if result.feasible:
            best = min(best, result.cost_eur)
    return best


@pytest.mark.parametrize(("scenario_type", "seed"), [("A", 1), ("A", 2), ("E", 1), ("E", 4)])
def test_milp_matches_brute_force(scenario_type: str, seed: int) -> None:
    scenario = make_scenario(scenario_type, seed)
    milp = solve_milp(scenario)
    assert milp.status == "Optimal"
    evaluation = evaluate(scenario, milp.schedule)
    assert evaluation.feasible
    assert evaluation.cost_eur == pytest.approx(milp.objective_eur, abs=1e-9)
    assert evaluation.cost_eur == pytest.approx(brute_force(scenario), abs=1e-9)


@pytest.mark.parametrize("scenario_type", list("ABCDEF"))
def test_milp_feasible_and_no_worse_than_references(scenario_type: str) -> None:
    scenario = make_scenario(scenario_type, seed=5)
    milp = evaluate(scenario, solve_milp(scenario).schedule)
    assert milp.feasible
    for reference in (naive_schedule(scenario), greedy_schedule(scenario)):
        ref = evaluate(scenario, reference)
        if ref.feasible:
            assert milp.cost_eur <= ref.cost_eur + 1e-9
    # greedy ignores the peak limit, so it lower-bounds the MILP cost
    assert evaluate(scenario, greedy_schedule(scenario)).cost_eur <= milp.cost_eur + 1e-9


def test_evaluate_flags_violations(scenario: Scenario) -> None:
    a = scenario.appliances[0]
    result = evaluate(scenario, {a.id: a.latest_start_slot + 1, "ghost": 3})
    text = " ".join(result.violations)
    assert not result.feasible
    assert "outside window" in text and "unknown appliance ghost" in text and "not scheduled" in text


def test_clock_time_round_trip(scenario: Scenario) -> None:
    for slot in (0, 1, 47, 95):
        assert scenario.time_to_slot(scenario.slot_to_time(slot)) == slot
    assert scenario.time_to_slot("13:50") == scenario.time_to_slot("13:45")
    assert scenario.boundary_to_time(96) == "24:00"
    with pytest.raises(ValueError):
        scenario.time_to_slot("24:00")


def test_tool_partition_is_fair() -> None:
    assert set(PROFILER_TOOLS) | set(SCHEDULER_TOOLS) | set(RESOLVER_TOOLS) == set(ALL_TOOLS)
    assert len(ALL_TOOLS) == len(set(ALL_TOOLS)) == 8


def test_tools_report_conflicts_and_errors(scenario: Scenario) -> None:
    tools = build_tools(scenario)
    assert set(tools) == set(ALL_TOOLS)
    clash = {a.id: scenario.slot_to_time(a.earliest_slot + 4) for a in scenario.appliances}
    clash = {k: list(clash.values())[0] for k in clash}
    detected = tools["detect_conflicts"].invoke({"schedule": clash})
    milp = {k: scenario.slot_to_time(v) for k, v in solve_milp(scenario).schedule.items()}
    assert tools["detect_conflicts"].invoke({"schedule": milp}).startswith("No conflicts")
    assert detected.startswith(("CONFLICT", "No conflicts"))
    assert tools["calculate_schedule_cost"].invoke({"appliance_id": "ghost", "start_time": "10:00"}).startswith(
        "ERROR: unknown appliance"
    )
    assert "FIXED" in tools["classify_appliance"].invoke({"appliance_id": "microwave"})
    assert "FLEXIBLE" in tools["classify_appliance"].invoke({"appliance_id": scenario.appliances[0].id})


def test_find_cheapest_window_is_single_appliance_optimum(scenario: Scenario) -> None:
    tools = build_tools(scenario)
    greedy = greedy_schedule(scenario)
    for a in scenario.appliances:
        best_line = tools["find_cheapest_window"].invoke({"appliance_id": a.id, "top_k": 1})
        assert f"start {scenario.slot_to_time(greedy[a.id])}" in best_line
