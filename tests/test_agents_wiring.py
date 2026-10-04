"""Graph wiring with scripted models: tools are really executed, LLM turns are fixed."""

from __future__ import annotations

from hems.agents.multi_agent import run_multi_agent
from hems.agents.oneshot import run_oneshot, scenario_message
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


def test_single_agent_recovers_after_provider_rejects_prose(scenario: Scenario) -> None:
    from .fakes import ProviderRejection

    model = scripted(
        call("read_household_data"),
        ProviderRejection(),  # model answered in prose; provider rejected the turn
        call("ScheduleOutput", assignments=_optimal_assignments(scenario), total_cost_eur=1.0, explanation="ok"),
    )
    run = run_single_agent(scenario, model)
    assert run.recoveries == 1 and run.errors == []
    assert run.tool_calls == 2  # the tool call made before the rejection is kept


def test_single_agent_gives_up_after_max_recoveries(scenario: Scenario) -> None:
    from hems.agents.errors import MAX_RECOVERIES

    from .fakes import ProviderRejection

    model = scripted(*[ProviderRejection() for _ in range(MAX_RECOVERIES + 1)])
    run = run_single_agent(scenario, model)
    assert run.assignments is None and "rejected" in run.errors[0]


def test_pipeline_counts_specialist_recoveries(scenario: Scenario) -> None:
    from .fakes import ProviderRejection

    ids = [a.id for a in scenario.appliances]
    optimal = _optimal_assignments(scenario)
    profiles = [
        {"appliance_id": a.id, "kind": a.kind, "flexible": True, "peak_kw": a.peak_kw, "duration_minutes": 60,
         "earliest_time": "00:00", "deadline_time": "24:00"}
        for a in scenario.appliances
    ]  # fmt: skip
    models = {
        "orchestrator": scripted(call("TaskBrief", appliance_ids=ids, notes=""), "done"),
        "profiler": scripted(call("ProfileOutput", appliances=profiles)),
        "scheduler": scripted(ProviderRejection(), call("ScheduleOutput", assignments=optimal, total_cost_eur=1.0, explanation="x")),
        "resolver": scripted(call("ResolverOutput", assignments=optimal, conflicts_remaining=False, changes="none")),
    }
    run = run_multi_agent(scenario, lambda role: models[role])
    assert run.recoveries == 1 and run.errors == []
    assert run.assignments == {o["appliance_id"]: o["start_time"] for o in optimal}


def test_daily_quota_detection() -> None:
    from hems.agents.errors import daily_quota_exhausted

    assert daily_quota_exhausted(Exception("rate_limit_exceeded ... on tokens per day (TPD): Limit 200000"))
    assert not daily_quota_exhausted(Exception("rate_limit_exceeded ... on tokens per minute (TPM)"))


def test_single_agent_recovers_when_prose_ends_the_loop(scenario: Scenario) -> None:
    # Ollama-style: no provider error, the model just answers in prose and the agent loop stops.
    model = scripted(
        call("read_household_data"),
        "Here is my schedule: everything at noon.",
        call("ScheduleOutput", assignments=_optimal_assignments(scenario), total_cost_eur=1.0, explanation="ok"),
    )
    run = run_single_agent(scenario, model)
    assert run.recoveries == 1 and run.errors == [] and run.assignments


def test_pipeline_sends_missing_appliances_back_to_scheduler(scenario: Scenario) -> None:
    ids = [a.id for a in scenario.appliances]
    optimal = _optimal_assignments(scenario)
    partial = optimal[:-1]  # the Scheduler forgets one appliance
    profiles = [
        {"appliance_id": a.id, "kind": a.kind, "flexible": True, "peak_kw": a.peak_kw, "duration_minutes": 60,
         "earliest_time": "00:00", "deadline_time": "24:00"}
        for a in scenario.appliances
    ]  # fmt: skip
    models = {
        "orchestrator": scripted(call("TaskBrief", appliance_ids=ids, notes=""), "done"),
        "profiler": scripted(call("ProfileOutput", appliances=profiles)),
        "scheduler": scripted(
            call("ScheduleOutput", assignments=partial, total_cost_eur=1.0, explanation="partial"),
            call("ScheduleOutput", assignments=optimal, total_cost_eur=1.0, explanation="complete"),
        ),
        "resolver": scripted(
            call("ResolverOutput", assignments=partial, conflicts_remaining=False, changes="none"),
            call("ResolverOutput", assignments=optimal, conflicts_remaining=False, changes="none"),
        ),
    }
    run = run_multi_agent(scenario, lambda role: models[role])
    assert run.iterations == 2
    assert set(run.assignments) == set(ids)


def test_pipeline_sends_out_of_window_starts_back_to_scheduler(scenario: Scenario) -> None:
    # Reproduces pilot/evaluation failure E03: the Resolver moved an appliance past its deadline.
    ids = [a.id for a in scenario.appliances]
    optimal = _optimal_assignments(scenario)
    late = scenario.appliances[0]
    outside = [dict(o) for o in optimal]
    outside[0]["start_time"] = scenario.slot_to_time(late.latest_start_slot + 1)
    profiles = [
        {"appliance_id": a.id, "kind": a.kind, "flexible": True, "peak_kw": a.peak_kw, "duration_minutes": 60,
         "earliest_time": "00:00", "deadline_time": "24:00"}
        for a in scenario.appliances
    ]  # fmt: skip
    models = {
        "orchestrator": scripted(call("TaskBrief", appliance_ids=ids, notes=""), "done"),
        "profiler": scripted(call("ProfileOutput", appliances=profiles)),
        "scheduler": scripted(
            call("ScheduleOutput", assignments=optimal, total_cost_eur=1.0, explanation="first"),
            call("ScheduleOutput", assignments=optimal, total_cost_eur=1.0, explanation="revised"),
        ),
        "resolver": scripted(
            call("ResolverOutput", assignments=outside, conflicts_remaining=False, changes="moved one"),
            call("ResolverOutput", assignments=optimal, conflicts_remaining=False, changes="none"),
        ),
    }
    run = run_multi_agent(scenario, lambda role: models[role])
    assert run.iterations == 2  # the out-of-window start triggered the feedback round
    parsed = {k: scenario.time_to_slot(v) for k, v in run.assignments.items()}
    assert evaluate(scenario, parsed).feasible


def test_oneshot_answers_without_tools_from_full_data(scenario: Scenario) -> None:
    message = scenario_message(scenario)
    assert len(message.splitlines()) > 96 and "base_kW" in message  # every slot's price and base load
    model = scripted(call("ScheduleOutput", assignments=_optimal_assignments(scenario), total_cost_eur=1.0, explanation="x"))
    run = run_oneshot(scenario, model)
    assert run.errors == [] and run.tool_calls == 0
    parsed = {k: scenario.time_to_slot(v) for k, v in run.assignments.items()}
    assert evaluate(scenario, parsed).feasible


def _one_cheap_hour_scenario() -> Scenario:
    """One dishwasher, price 0.30 EUR/kWh except 0.10 from 01:00 to 02:00: any other start is valid but costly."""
    from datetime import datetime

    from hems.core.models import FlexibleAppliance

    price = [0.30] * 96
    price[4:8] = [0.10] * 4
    return Scenario(
        id="COST", type="C", date="2026-01-01", start_time=datetime(2026, 1, 1), spot_eur_per_kwh=price,
        price_eur_per_kwh=price, base_load_kw=[0.0] * 96, peak_limit_kw=3.5, user_request="dishwasher_1",
        appliances=[FlexibleAppliance(id="dishwasher_1", kind="dishwasher", profile_kw=[1.0] * 4,
                                      earliest_slot=0, deadline_slot=96, default_start_slot=0)],
    )  # fmt: skip


def _cost_models(*starts: str) -> dict:
    a = [{"appliance_id": "dishwasher_1", "start_time": s} for s in starts]
    profile = [{"appliance_id": "dishwasher_1", "kind": "dishwasher", "flexible": True, "peak_kw": 1.0,
                "duration_minutes": 60, "earliest_time": "00:00", "deadline_time": "24:00"}]  # fmt: skip
    return {
        "orchestrator": scripted(call("TaskBrief", appliance_ids=["dishwasher_1"], notes=""), "done"),
        "profiler": scripted(call("ProfileOutput", appliances=profile)),
        "scheduler": scripted(*[call("ScheduleOutput", assignments=[x], total_cost_eur=1.0, explanation="") for x in a]),
        "resolver": scripted(*[call("ResolverOutput", assignments=[x], conflicts_remaining=False, changes="none") for x in a]),
    }


def test_cost_check_sends_a_costly_valid_schedule_back_once() -> None:
    scenario = _one_cheap_hour_scenario()
    models = _cost_models("12:00", "01:00")  # valid but 200 % above the bound, then the cheap hour
    run = run_multi_agent(scenario, lambda role: models[role], cost_check=True)
    assert run.iterations == 2 and run.assignments == {"dishwasher_1": "01:00"}


def test_cost_check_keeps_the_cheapest_valid_schedule() -> None:
    scenario = _one_cheap_hour_scenario()
    models = _cost_models("05:00", "12:00")  # the revision is no cheaper: the first schedule stays
    run = run_multi_agent(scenario, lambda role: models[role], cost_check=True)
    assert run.iterations == 2 and run.assignments == {"dishwasher_1": "05:00"}


def test_without_cost_check_a_valid_schedule_is_final() -> None:
    scenario = _one_cheap_hour_scenario()
    models = _cost_models("12:00", "01:00")
    run = run_multi_agent(scenario, lambda role: models[role])  # the evaluated pipeline ("multi")
    assert run.iterations == 1 and run.assignments == {"dishwasher_1": "12:00"}
