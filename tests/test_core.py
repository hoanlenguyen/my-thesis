from __future__ import annotations

import ast
import itertools

import pytest

from hems.core.evaluate import evaluate
from hems.core.models import Scenario
from hems.solvers.milp import solve_milp
from hems.solvers.naive import cheapest_hours_schedule, greedy_schedule, naive_schedule, smart_timer_schedule
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
    for reference in (naive_schedule(scenario), greedy_schedule(scenario), smart_timer_schedule(scenario)):
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


def test_adjust_schedule_auto_mode_resolves_overlap_one_move_at_a_time() -> None:
    scenario = make_scenario("D", seed=2)
    tools = build_tools(scenario)
    greedy = {k: scenario.slot_to_time(v) for k, v in greedy_schedule(scenario).items()}
    assert tools["detect_conflicts"].invoke({"schedule": greedy}).startswith("CONFLICT")

    schedule = dict(greedy)
    for appliance in scenario.appliances[1:]:  # keep the first, move the rest one by one
        reply = tools["adjust_schedule"].invoke({"schedule": schedule, "appliance_id": appliance.id})
        if reply.startswith("No start time"):
            continue
        moved = reply.split("Adjusted schedule: ")[1].split("\n")[0]
        schedule = ast.literal_eval(moved)  # tool echoes a dict literal of the new schedule
    parsed = {k: scenario.time_to_slot(v) for k, v in schedule.items()}
    result = evaluate(scenario, parsed)
    assert result.feasible
    assert result.cost_eur >= evaluate(scenario, solve_milp(scenario).schedule).cost_eur - 1e-9


def test_model_output_failure_is_distinguished_from_provider_errors() -> None:
    from hems.agents.errors import model_output_failure

    class Rejected(Exception):
        body = {"error": {"code": "tool_use_failed", "message": "Tool choice is required"}}

    assert model_output_failure(Rejected("400")) is not None
    assert model_output_failure(ConnectionError("timeout")) is None


def test_household_data_states_measured_base_load(scenario: Scenario) -> None:
    text = build_tools(scenario)["read_household_data"].invoke({})
    assert "Measured base load" in text and "rated power when on" in text


def test_step_budget_parity() -> None:
    from hems.agents.multi_agent import STEP_LIMITS
    from hems.agents.single_agent import RECURSION_LIMIT

    assert sum(STEP_LIMITS.values()) == RECURSION_LIMIT


@pytest.mark.parametrize("scenario_type", list("ABCDEF"))
def test_smart_timer_stays_in_windows_and_matches_greedy_without_conflict(scenario_type: str) -> None:
    scenario = make_scenario(scenario_type, seed=5)
    timer = smart_timer_schedule(scenario)
    assert all(timer[a.id] in a.valid_starts() for a in scenario.appliances)
    greedy = evaluate(scenario, greedy_schedule(scenario))
    if greedy.feasible:  # nothing to coordinate: placing each at its cheapest start is optimal
        assert evaluate(scenario, timer).cost_eur == pytest.approx(greedy.cost_eur)


@pytest.mark.parametrize("scenario_type", list("ABCDEF"))
def test_cheapest_hours_starts_in_window_at_a_cheap_slot(scenario_type: str) -> None:
    scenario = make_scenario(scenario_type, seed=5)
    schedule = cheapest_hours_schedule(scenario)
    for a in scenario.appliances:
        window = list(a.valid_starts())
        assert schedule[a.id] in window
        # every slot before the chosen start is above the blueprint threshold
        threshold = sorted(scenario.price_eur_per_kwh[s] for s in window)[min(-(-a.duration_slots // 4) * 4, len(window) - 1)]
        assert all(scenario.price_eur_per_kwh[s] > threshold for s in window if s < schedule[a.id])


def test_external_record_is_scored_like_other_systems(scenario: Scenario) -> None:
    from hems.run import execute, external_record

    milp = execute(scenario, "milp")
    record = external_record(scenario, "emhass", dict(milp["schedule_slots"]), 0.5, [])
    assert record["key"] == f"emhass|-|{scenario.id}|0"
    assert record["cost_eur"] == pytest.approx(milp["cost_eur"]) and record["feasible"]
    missing = external_record(scenario, "emhass", {a.id: None for a in scenario.appliances}, 0.5, ["solver failed"])
    assert not missing["feasible"] and missing["agent_errors"] == ["solver failed"]


@pytest.mark.parametrize("scenario_type", list("ABCDEF"))
def test_cheapest_hours_hourly_starts_on_full_hours_inside_the_window(scenario_type: str) -> None:
    scenario = make_scenario(scenario_type, seed=5)
    schedule = cheapest_hours_schedule(scenario, resolution="hourly")
    for a in scenario.appliances:
        assert schedule[a.id] in a.valid_starts()
        if any(s % 4 == 0 for s in a.valid_starts()):
            assert schedule[a.id] % 4 == 0
    assert cheapest_hours_schedule(scenario) == cheapest_hours_schedule(scenario, hours=None, resolution="15min")
    with pytest.raises(ValueError):
        cheapest_hours_schedule(scenario, resolution="5min")


def test_system_registry_is_consistent() -> None:
    from hems.run import ALL_SYSTEMS, LLM_SYSTEMS, REFERENCE_SYSTEMS
    from hems.systems import SYSTEMS

    assert set(REFERENCE_SYSTEMS) | set(LLM_SYSTEMS) == set(ALL_SYSTEMS) == set(SYSTEMS)
    assert not set(REFERENCE_SYSTEMS) & set(LLM_SYSTEMS)
    for spec in SYSTEMS.values():
        assert (spec.plan is None) == (spec.kind == "llm") and (spec.agent is None) == (spec.kind != "llm")


def test_tariff_adders_do_not_change_the_comparison_between_schedules(scenario: Scenario) -> None:
    """Constant per-kWh adders and VAT shift every schedule's cost equally (cycle energy is fixed), so the
    optimum, the ranking and savings captured are the same as under spot prices alone (thesis 3.2)."""
    from hems.data.tariff import Tariff

    spot_only = scenario.model_copy(update={"price_eur_per_kwh": list(scenario.spot_eur_per_kwh)})
    consumer = scenario.model_copy(update={"price_eur_per_kwh": list(Tariff().consumer_price(scenario.spot_eur_per_kwh))})
    schedules = [naive_schedule(scenario), greedy_schedule(scenario), smart_timer_schedule(scenario), cheapest_hours_schedule(scenario)]
    for a, b in itertools.combinations(schedules, 2):
        diff_spot = evaluate(spot_only, a).cost_eur - evaluate(spot_only, b).cost_eur
        diff_consumer = evaluate(consumer, a).cost_eur - evaluate(consumer, b).cost_eur
        assert diff_consumer == pytest.approx(diff_spot * (1 + Tariff().vat), abs=1e-12)
