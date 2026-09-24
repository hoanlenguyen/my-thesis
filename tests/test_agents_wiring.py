"""Graph wiring with scripted models: tools are really executed, LLM turns are fixed."""

from __future__ import annotations

from hems.agents.multi_agent import run_multi_agent
from hems.agents.single_agent import run_single_agent
from hems.core.evaluate import evaluate
from hems.core.models import Scenario
from hems.solvers.milp import solve_milp

from .fakes import call, scripted


def _optimal_assignments(scenario: Scenario) -> list[dict[str, str]]:
    schedule = solve_milp(scenario).schedule
    return [{"appliance_id": k, "start_time": scenario.slot_to_time(v)} for k, v in schedule.items()]


def test_single_agent_returns_schedule(scenario: Scenario) -> None:
    first = scenario.appliances[0].id
    model = scripted(
        call("read_household_data"),
        call("find_cheapest_window", appliance_id=first),
        call("ScheduleOutput", assignments=_optimal_assignments(scenario), total_cost_eur=1.0, explanation="cheap"),
    )
    run = run_single_agent(scenario, model)
    assert run.errors == []
    assert run.tool_calls == 3
    parsed = {k: scenario.time_to_slot(v) for k, v in run.assignments.items()}
    assert evaluate(scenario, parsed).feasible


def test_multi_agent_pipeline_end_to_end(scenario: Scenario) -> None:
    ids = [a.id for a in scenario.appliances]
    optimal = _optimal_assignments(scenario)
    profiles = [
        {
            "appliance_id": a.id,
            "kind": a.kind,
            "flexible": True,
            "peak_kw": a.peak_kw,
            "duration_minutes": a.duration_slots * 15,
            "earliest_time": scenario.slot_to_time(a.earliest_slot),
            "deadline_time": scenario.boundary_to_time(a.deadline_slot),
        }
        for a in scenario.appliances
    ]
    models = {
        "orchestrator": scripted(call("TaskBrief", appliance_ids=ids, notes=""), "All set: cheapest conflict-free times."),
        "profiler": scripted(call("read_household_data"), call("ProfileOutput", appliances=profiles)),
        "scheduler": scripted(
            call("find_cheapest_window", appliance_id=ids[0]),
            call("ScheduleOutput", assignments=optimal, total_cost_eur=1.0, explanation="cheapest"),
        ),
        "resolver": scripted(
            call("detect_conflicts", schedule={o["appliance_id"]: o["start_time"] for o in optimal}),
            call("ResolverOutput", assignments=optimal, conflicts_remaining=False, changes="none"),
        ),
    }
    run = run_multi_agent(scenario, lambda role: models[role])
    assert run.errors == []
    assert run.iterations == 1  # MILP schedule is conflict-free: no loop back
    assert run.explanation.startswith("All set")
    parsed = {k: scenario.time_to_slot(v) for k, v in run.assignments.items()}
    assert evaluate(scenario, parsed).cost_eur == evaluate(scenario, solve_milp(scenario).schedule).cost_eur


def test_multi_agent_loops_back_on_conflict(scenario: Scenario) -> None:
    ids = [a.id for a in scenario.appliances]
    clash = [{"appliance_id": i, "start_time": scenario.slot_to_time(scenario.appliances[0].earliest_slot + 8)} for i in ids]
    optimal = _optimal_assignments(scenario)
    profiles = [
        {"appliance_id": a.id, "kind": a.kind, "flexible": True, "peak_kw": a.peak_kw, "duration_minutes": 60,
         "earliest_time": "00:00", "deadline_time": "24:00"}
        for a in scenario.appliances
    ]  # fmt: skip
    models = {
        "orchestrator": scripted(call("TaskBrief", appliance_ids=ids, notes=""), "done"),
        "profiler": scripted(call("ProfileOutput", appliances=profiles)),
        "scheduler": scripted(
            call("ScheduleOutput", assignments=clash, total_cost_eur=1.0, explanation="first try"),
            call("ScheduleOutput", assignments=optimal, total_cost_eur=1.0, explanation="revised"),
        ),
        "resolver": scripted(
            call("ResolverOutput", assignments=clash, conflicts_remaining=True, changes="could not fix"),
            call("ResolverOutput", assignments=optimal, conflicts_remaining=False, changes="none"),
        ),
    }
    run = run_multi_agent(scenario, lambda role: models[role])
    assert run.iterations == 2
    parsed = {k: scenario.time_to_slot(v) for k, v in run.assignments.items()}
    assert evaluate(scenario, parsed).feasible
