"""The single agent in the harness (hems.agents.harness_agent) with a scripted model: tools really run."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from hems.agents.harness import Checker, profiles
from hems.agents.harness_agent import AGENT_TOOLS, build_harness_agent, run_harness_agent
from hems.agents.multi_agent import SCHEDULER_AGENT_TOOLS
from hems.core.evaluate import evaluate
from hems.core.models import Scenario
from hems.solvers.milp import solve_milp
from hems.tools import build_tools

from .fakes import ScriptedModel, call

SEEN: list[list[Any]] = []  # every conversation the scripted model was given


class Recording(ScriptedModel):
    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any):  # type: ignore[no-untyped-def]
        SEEN.append(list(messages))
        return super()._generate(messages, stop, run_manager, **kwargs)


def _model(*turns: Any, summary: str = "All set.") -> Recording:
    """The agent's turns (a schedule list becomes a ScheduleOutput), then its household message."""
    items = [call("ScheduleOutput", assignments=t, total_cost_eur=1.0, explanation="") if isinstance(t, list) else t
             for t in turns]  # fmt: skip
    SEEN.clear()
    return Recording(messages=iter([*items, AIMessage(content=summary)]))


def _optimal(scenario: Scenario) -> list[dict[str, str]]:
    return [{"appliance_id": k, "start_time": scenario.slot_to_time(v)} for k, v in solve_milp(scenario).schedule.items()]


def _clash(scenario: Scenario) -> list[dict[str, str]]:
    at = scenario.slot_to_time(scenario.appliances[0].earliest_slot + 8)
    clash = [{"appliance_id": a.id, "start_time": at} for a in scenario.appliances]
    assert not evaluate(scenario, {c["appliance_id"]: scenario.time_to_slot(at) for c in clash}).feasible
    return clash


def test_one_agent_two_functions_and_the_same_tools_as_the_scheduler(scenario: Scenario) -> None:
    nodes = set(build_harness_agent(scenario, _model()).get_graph().nodes)
    assert {"profile_data", "agent", "verify_schedule", "explain"} <= nodes
    assert not {"orchestrator_plan", "scheduler"} & nodes
    assert AGENT_TOOLS == SCHEDULER_AGENT_TOOLS


def test_end_to_end_reads_the_request_and_explains_with_the_checked_figures(scenario: Scenario) -> None:
    optimal = _optimal(scenario)
    ids = [a.id for a in scenario.appliances]
    model = _model(call("get_spot_prices"), call("optimize_schedule", appliance_ids=ids), optimal,
                   summary="Your dishwasher runs at night.")  # fmt: skip
    run = run_harness_agent(scenario, model)
    assert run.errors == [] and run.iterations == 1 and run.tool_calls == 3
    assert run.assignments == {o["appliance_id"]: o["start_time"] for o in optimal}
    assert run.explanation == "Your dishwasher runs at night."
    first = str(SEEN[0][-1].content)
    assert scenario.user_request in first and "Appliance profiles" in first  # the agent reads the request itself
    last = SEEN[-1]
    assert "Saving: EUR" in str(last[-1].content) and len(last) > 4  # the message is written with the whole history


def test_feedback_continues_the_same_conversation(scenario: Scenario) -> None:
    optimal = _optimal(scenario)
    run = run_harness_agent(scenario, _model(_clash(scenario), optimal))
    assert run.iterations == 2
    assert run.assignments == {o["appliance_id"]: o["start_time"] for o in optimal}
    second_round = next(m for m in SEEN if "Verification feedback" in str(m[-1].content))
    assert "CONFLICT" in str(second_round[-1].content)
    assert any(scenario.user_request in str(m.content) for m in second_round)  # the first round is still in view


def test_an_appliance_still_missing_after_the_last_round_is_placed(scenario: Scenario) -> None:
    partial = _optimal(scenario)[:-1]
    run = run_harness_agent(scenario, _model(partial, partial))
    assert set(run.assignments) == {a.id for a in scenario.appliances}
    parsed = {k: scenario.time_to_slot(v) for k, v in run.assignments.items()}
    assert evaluate(scenario, parsed).feasible and any("placed missing" in e for e in run.errors)


def test_thoughts_are_recorded_for_the_agent(scenario: Scenario) -> None:
    ids = [a.id for a in scenario.appliances]
    model = _model(call("optimize_schedule", thought="solve the day exactly", appliance_ids=ids), _optimal(scenario))
    run = run_harness_agent(scenario, model, thoughts=True)
    assert run.thoughts == [{"agent": "agent", "tool": "optimize_schedule", "thought": "solve the day exactly"}]


def test_the_harness_check_is_shared(scenario: Scenario) -> None:
    checker = Checker(scenario, build_tools(scenario))
    ids = [p.appliance_id for p in profiles(scenario).appliances if p.flexible]
    optimal = {o["appliance_id"]: o["start_time"] for o in _optimal(scenario)}
    assert checker.problems(optimal, ids) == []
    assert checker.problems({}, ids)[0].startswith("MISSING")
