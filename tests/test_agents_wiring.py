"""Graph wiring with scripted models: tools are really executed, LLM turns are fixed."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from hems.agents.multi_agent import build_pipeline, run_multi_agent
from hems.agents.oneshot import run_oneshot, scenario_message
from hems.agents.single_agent import run_single_agent
from hems.core.evaluate import evaluate
from hems.core.models import Scenario
from hems.solvers.milp import solve_milp

from .fakes import ScriptedModel, call, scripted


def _optimal_assignments(scenario: Scenario) -> list[dict[str, str]]:
    schedule = solve_milp(scenario).schedule
    return [{"appliance_id": k, "start_time": scenario.slot_to_time(v)} for k, v in schedule.items()]


# ── Baselines ────────────────────────────────────────────────────────────────
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


def test_oneshot_answers_without_tools_from_full_data(scenario: Scenario) -> None:
    message = scenario_message(scenario)
    assert len(message.splitlines()) > 96 and "base_kW" in message  # every slot's price and base load
    model = scripted(call("ScheduleOutput", assignments=_optimal_assignments(scenario), total_cost_eur=1.0, explanation="x"))
    run = run_oneshot(scenario, model)
    assert run.errors == [] and run.tool_calls == 0
    parsed = {k: scenario.time_to_slot(v) for k, v in run.assignments.items()}
    assert evaluate(scenario, parsed).feasible


# ── The pipeline: Orchestrator agent, profile_data, Scheduler agent, verify_schedule ──
SEEN: list[str] = []


class _Recording(ScriptedModel):
    """Scripted model that also records the text of the last message it receives."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[no-untyped-def]
        SEEN.append(str(messages[-1].content))
        return super()._generate(messages, stop, run_manager, **kwargs)


def _models(scenario: Scenario, *turns, summary: str = "done") -> dict:  # type: ignore[no-untyped-def]
    """The two agents: the Orchestrator plans and summarises; the Scheduler replays ``turns`` (a schedule list
    becomes a ScheduleOutput; anything else is passed on as a scripted turn)."""
    ids = [a.id for a in scenario.appliances]
    scheduler_turns = [
        call("ScheduleOutput", assignments=t, total_cost_eur=1.0, explanation="") if isinstance(t, list) else t
        for t in turns
    ]  # fmt: skip
    return {
        "orchestrator": _Recording(messages=iter([call("TaskBrief", appliance_ids=ids, notes=""), AIMessage(content=summary)])),
        "scheduler": _Recording(messages=iter(scheduler_turns)),
    }


def _clash(scenario: Scenario) -> list[dict[str, str]]:
    clash = [{"appliance_id": a.id, "start_time": scenario.slot_to_time(scenario.appliances[0].earliest_slot + 8)}
             for a in scenario.appliances]  # fmt: skip
    assert not evaluate(scenario, {c["appliance_id"]: scenario.time_to_slot(c["start_time"]) for c in clash}).feasible
    return clash


def test_pipeline_has_two_agents_and_two_functions(scenario: Scenario) -> None:
    nodes = set(build_pipeline(scenario, lambda _role: scripted()).get_graph().nodes)
    assert {"orchestrator_plan", "profile_data", "scheduler", "verify_schedule", "orchestrator_finalize"} <= nodes
    assert not {"profiler", "resolver"} & nodes


def test_pipeline_end_to_end_with_a_verified_schedule(scenario: Scenario) -> None:
    SEEN.clear()
    optimal = _optimal_assignments(scenario)
    models = _models(scenario, call("find_cheapest_window", appliance_id=scenario.appliances[0].id), optimal,
                     summary="All set: cheapest conflict-free times.")  # fmt: skip
    run = run_multi_agent(scenario, lambda role: models[role])  # only the two agents are ever asked for a model
    assert run.errors == [] and run.iterations == 1  # the schedule passed the verification step: no loop back
    assert run.explanation.startswith("All set")
    assert run.assignments == {o["appliance_id"]: o["start_time"] for o in optimal}
    scheduler_message = SEEN[1]  # the Orchestrator's brief, then the Scheduler's first message
    for a in scenario.appliances:  # profile_data built the profiles from the household data
        assert a.id in scheduler_message and f'"duration_minutes": {a.duration_slots * 15}' in scheduler_message
    assert "Saving: EUR" in SEEN[-1]  # the summary is given the cost and the saving


def test_a_conflicting_schedule_goes_back_to_the_scheduler(scenario: Scenario) -> None:
    SEEN.clear()
    optimal = _optimal_assignments(scenario)
    models = _models(scenario, _clash(scenario), optimal)
    run = run_multi_agent(scenario, lambda role: models[role])
    assert run.iterations == 2
    assert run.assignments == {o["appliance_id"]: o["start_time"] for o in optimal}
    assert any("Verification feedback" in m and "CONFLICT" in m for m in SEEN)  # the Scheduler got the problem


def test_pipeline_counts_recoveries(scenario: Scenario) -> None:
    from .fakes import ProviderRejection

    optimal = _optimal_assignments(scenario)
    models = _models(scenario, ProviderRejection(), optimal)
    run = run_multi_agent(scenario, lambda role: models[role])
    assert run.recoveries == 1 and run.errors == []
    assert run.assignments == {o["appliance_id"]: o["start_time"] for o in optimal}


def test_a_missing_appliance_goes_back_to_the_scheduler(scenario: Scenario) -> None:
    SEEN.clear()
    optimal = _optimal_assignments(scenario)
    models = _models(scenario, optimal[:-1], optimal)  # the Scheduler forgets one appliance, then corrects it
    run = run_multi_agent(scenario, lambda role: models[role])
    assert run.iterations == 2 and set(run.assignments) == {a.id for a in scenario.appliances}
    assert any("MISSING" in m and "schedule all of them" in m for m in SEEN)


def test_an_appliance_still_missing_after_the_last_round_is_placed(scenario: Scenario) -> None:
    partial = _optimal_assignments(scenario)[:-1]
    models = _models(scenario, partial, partial)
    run = run_multi_agent(scenario, lambda role: models[role])
    assert set(run.assignments) == {a.id for a in scenario.appliances}
    kept = {p["appliance_id"]: p["start_time"] for p in partial}
    assert all(run.assignments[k] == v for k, v in kept.items())  # the Scheduler's other start times are unchanged
    parsed = {k: scenario.time_to_slot(v) for k, v in run.assignments.items()}
    assert evaluate(scenario, parsed).feasible
    assert any("placed missing" in e for e in run.errors)


def test_an_out_of_window_start_goes_back_to_the_scheduler(scenario: Scenario) -> None:
    optimal = _optimal_assignments(scenario)
    outside = [dict(o) for o in optimal]
    outside[0]["start_time"] = scenario.slot_to_time(scenario.appliances[0].latest_start_slot + 1)
    models = _models(scenario, outside, optimal)
    run = run_multi_agent(scenario, lambda role: models[role])
    assert run.iterations == 2  # the out-of-window start triggered the feedback round
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


def test_a_valid_schedule_is_final_even_if_costly() -> None:
    scenario = _one_cheap_hour_scenario()
    costly = [{"appliance_id": "dishwasher_1", "start_time": "12:00"}]
    models = _models(scenario, costly)
    run = run_multi_agent(scenario, lambda role: models[role])
    assert run.iterations == 1 and run.assignments == {"dishwasher_1": "12:00"}  # the check is validity, not cost


def test_parallel_start_profiles_while_the_orchestrator_plans_and_gives_the_same_schedule(scenario: Scenario) -> None:
    optimal = _optimal_assignments(scenario)
    models = _models(scenario, optimal)
    pipeline = build_pipeline(scenario, lambda role: models[role], parallel_start=True)
    assert {"orchestrator_plan", "profile_data"} <= {e.target for e in pipeline.get_graph().edges if e.source == "__start__"}
    state = pipeline.invoke({"request": scenario.user_request})
    assert state["final"] == {o["appliance_id"]: o["start_time"] for o in optimal}
    assert state["rounds"] == 1 and state["errors"] == []


# ── Explicit Thoughts (design iteration 11) ─────────────────────────────────
def test_with_thought_requires_a_thought_and_leaves_the_tool_unchanged(scenario: Scenario) -> None:
    from pydantic import ValidationError

    from hems.tools import build_tools, with_thought

    tools, log = build_tools(scenario), []
    wrapped = with_thought(tools["calculate_schedule_cost"], log)
    assert list(wrapped.args_schema.model_fields)[0] == "thought"  # written first, before the arguments
    a = scenario.appliances[0]
    args = {"appliance_id": a.id, "start_time": scenario.slot_to_time(a.earliest_slot)}
    assert wrapped.invoke({"thought": "check the cost at the ready time", **args}) == tools["calculate_schedule_cost"].invoke(args)
    assert log == [{"tool": "calculate_schedule_cost", "thought": "check the cost at the ready time"}]
    with pytest.raises(ValidationError):
        wrapped.invoke(args)  # no Thought, no Action


def test_the_schedulers_thoughts_are_recorded(scenario: Scenario) -> None:
    optimal = _optimal_assignments(scenario)
    ids = [a.id for a in scenario.appliances]
    models = _models(scenario, call("optimize_schedule", thought="solve the whole day exactly", appliance_ids=ids), optimal)
    run = run_multi_agent(scenario, lambda role: models[role], thoughts=True)
    assert run.assignments == {o["appliance_id"]: o["start_time"] for o in optimal}
    assert run.thoughts == [{"agent": "scheduler", "tool": "optimize_schedule", "thought": "solve the whole day exactly"}]


def test_without_thoughts_tools_take_no_thought(scenario: Scenario) -> None:
    optimal = _optimal_assignments(scenario)
    run = run_multi_agent(scenario, lambda role: _models(scenario, optimal)[role])
    assert run.thoughts == []


# ── Inputs of the Scheduler agent ───────────────────────────────────────────
def test_several_allowed_periods_reach_the_scheduler_and_one_window_stays_as_before(scenario: Scenario) -> None:
    from hems.core.models import FlexibleAppliance

    SEEN.clear()
    washer = FlexibleAppliance(id="washing_machine_1", kind="washing_machine", profile_kw=[1.5] * 4, earliest_slot=24,
                               deadline_slot=88, default_start_slot=24, windows=[(24, 36), (72, 88)])  # fmt: skip
    two = _one_cheap_hour_scenario().model_copy(update={"appliances": [washer], "user_request": "washing_machine_1"})
    run_multi_agent(two, lambda role: _models(two, [{"appliance_id": "washing_machine_1", "start_time": "18:00"}])[role])
    assert '"periods"' in SEEN[1] and '"06:00-09:00"' in SEEN[1] and '"18:00-22:00"' in SEEN[1]
    SEEN.clear()
    run_multi_agent(scenario, lambda role: _models(scenario, _optimal_assignments(scenario))[role])
    assert "periods" not in SEEN[1]  # one window per appliance (the benchmarks): the message is unchanged


def test_spot_prices_are_cached_within_a_run(scenario: Scenario) -> None:
    from hems.tools import build_tools

    prices = build_tools(scenario)["get_spot_prices"]
    first = prices.invoke({})
    assert first.startswith("Whole day, hourly mean") and len(first.splitlines()) == 4  # brief, not 96 rows
    assert prices.invoke({}) == "(cached) " + first
    assert not build_tools(scenario)["get_spot_prices"].invoke({}).startswith("(cached)")  # a new run starts empty


def test_the_day_summary_is_brief_and_the_15_min_detail_stays_available(scenario: Scenario) -> None:
    import numpy as np

    from hems.tools import build_tools

    prices = build_tools(scenario)["get_spot_prices"]
    summary = prices.invoke({})
    cents = np.asarray(scenario.price_eur_per_kwh) * 100
    cheapest = scenario.slot_to_time(int(np.argmin(cents)))
    assert f"Cheapest 15-min slots: {cheapest} {cents.min():.2f}" in summary
    assert summary.count("|") == 23  # 24 hourly means
    detail = prices.invoke({"from_time": "18:00", "to_time": "19:00"})
    assert detail.startswith("time c/kWh") and len(detail.splitlines()) == 5  # four 15-min slots
