"""Hierarchical ReAct multi-agent pipeline (LangGraph): two language model agents and two deterministic steps.

    orchestrator_plan -> profile_data -> scheduler -> verify_schedule --(conflict, missing appliance or start
                                             ^                               |    outside its window; a round left)
                                             +-------------------------------+
                                                                             +--> [human review] -> orchestrator_finalize

Agents (ReAct, language model): the Orchestrator reads the household's request and briefs the Scheduler, then
explains the final schedule; the Price-Aware Scheduler plans the start times with its tools, including the
optimiser, and fixes any problem the verification step reports. Deterministic steps (no language model):
``profile_data`` builds the appliance profiles from the household data, and ``verify_schedule`` checks the peak
limit, completeness and every start window and returns problems to the Scheduler.

History: the evaluated designs up to design iteration 9 had two more agents, an Appliance Profiler and a Conflict
Resolver (results in results/*.jsonl). In the evaluation their work turned out deterministic (profiling) or
unnecessary (the verification step sent a schedule back in 0 of 289 held-out runs), so design iteration 10 replaced
them by the deterministic steps above, and their code was removed on 16 October 2026. This module is the pipeline
of design iteration 10 (system "multi_duo"); ``thoughts=True`` is design iteration 11 ("multi_duo_thoughts").
"""

from __future__ import annotations

import json
import operator
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from hems.agents import prompts
from hems.agents.errors import MAX_RECOVERIES, invoke_with_recovery, model_output_failure
from hems.agents.schemas import (
    ApplianceProfile,
    Assignment,
    ProfileOutput,
    ScheduleOutput,
    TaskBrief,
    assignments_to_dict,
)
from hems.agents.types import AgentRun
from hems.core.evaluate import PEAK_TOLERANCE_KW, appliance_cost, total_load
from hems.core.models import SLOT_MINUTES, FlexibleAppliance, Scenario, Schedule
from hems.tools import (
    OPTIMIZER_TOOLS,
    RESOLVER_TOOLS,
    SCHEDULER_TOOLS,
    SHIFTABLE_KINDS,
    build_tools,
    select,
    with_thought,
)

# The Scheduler's step budget: the former Scheduler (35) and Conflict Resolver (25) budgets together.
SCHEDULER_STEP_LIMIT = 60
ORCHESTRATOR_RECURSION_LIMIT = 6
MAX_ROUNDS = 2  # verification rounds: a problem found in the first round is sent back to the Scheduler once
# The Scheduler's tools: price-aware scheduling, the optimiser, and the conflict tools to fix reported problems.
SCHEDULER_AGENT_TOOLS = SCHEDULER_TOOLS + OPTIMIZER_TOOLS + RESOLVER_TOOLS

ModelFactory = Callable[[str], BaseChatModel]
"""Role name ("orchestrator" | "scheduler") -> chat model."""


class PipelineState(TypedDict, total=False):
    request: str
    brief: TaskBrief
    profile: ProfileOutput
    proposal: ScheduleOutput  # the Scheduler's latest schedule
    checked: dict[str, str]  # the schedule after the verification step (missing appliances placed in the last round)
    feedback: str  # problems the verification step returns to the Scheduler ("" when the schedule passed)
    rounds: int
    final: dict[str, str]
    summary: str
    tool_calls: Annotated[int, operator.add]
    recoveries: Annotated[int, operator.add]
    errors: Annotated[list[str], operator.add]
    thoughts: Annotated[list[dict[str, str]], operator.add]  # explicit Thoughts (iteration 11): agent, tool, thought


def _run_agent(
    model: BaseChatModel,
    tools: list,
    system_prompt: str,
    schema: type[BaseModel],
    message: str,
    name: str,
    limit: int,
    config: dict[str, Any] | None,
) -> tuple[BaseModel | None, int, list[str], int]:
    agent = create_agent(
        model, tools=tools, system_prompt=system_prompt, response_format=ToolStrategy(schema),
        checkpointer=InMemorySaver(),  # lets a rejected turn be retried from the last good state
        name=name,
    )  # fmt: skip
    try:
        result, recoveries = invoke_with_recovery(agent, message, schema.__name__, config or {}, limit)
    except GraphRecursionError:
        return None, 0, [f"{name}: step limit reached"], 0
    except Exception as exc:  # provider errors propagate; persistent model-output failures = failed step
        if (reason := model_output_failure(exc)) is None:
            raise
        return None, 0, [f"{name}: {reason}"], MAX_RECOVERIES
    calls = sum(len(getattr(m, "tool_calls", []) or []) for m in result["messages"])
    output = result.get("structured_response")
    return output, calls, ([] if output is not None else [f"{name}: no structured output"]), recoveries


def build_pipeline(
    scenario: Scenario, models: ModelFactory, *, retriever: Callable[[Scenario], str] | None = None,
    thoughts: bool = False, human_review: bool = False, summarize: bool = True, parallel_start: bool = False,
    summary_costs: Callable[[Schedule], str] | None = None,
):  # fmt: skip
    """The two-agent pipeline for one household-day.

    ``retriever`` returns worked examples of similar solved days (hems.rag) for the Scheduler's message.
    ``thoughts`` (design iteration 11): every tool the Scheduler may call requires a written Thought, recorded per agent.
    ``human_review``: the graph stops before the summary so a person can approve the schedule (``hems demo --review``).
    ``parallel_start`` (demo only; not evaluated): the household data are profiled while the Orchestrator plans.
    ``summary_costs`` (demo only; not evaluated): replaces the cost lines given to the summary, so that it states the
    cost the demo page shows (energy plus a fee for exceeding the limit) instead of the energy cost alone."""
    tools = build_tools(scenario)
    plan_ids = [a.id for a in scenario.appliances]  # every cycle in the day's appliance plan
    examples = f"\n\n{retriever(scenario)}" if retriever else ""
    thought_log: list[dict[str, str]] = []  # filled by the wrapped tools; moved into the state after each agent

    def scheduler_tools() -> list:
        listed = select(tools, SCHEDULER_AGENT_TOOLS)
        return [with_thought(t, thought_log) for t in listed] if thoughts else listed

    scheduler_prompt = prompts.SCHEDULER + (prompts.THOUGHT_NOTE if thoughts else "")

    def periods_text(appliance: FlexibleAppliance) -> str:
        """Allowed periods of an appliance with several of them (demo only), e.g. "06:00-09:00 or 18:00-22:00"."""
        return " or ".join(f"{scenario.slot_to_time(s)}-{scenario.boundary_to_time(e)}" for s, e in appliance.window_periods())

    def place_missing(final: dict[str, str]) -> tuple[dict[str, str], list[str]]:
        """Give each appliance of the plan without a valid start its cheapest start that keeps the load within the
        limit, leaving the other start times unchanged (most energy first; cheapest start if none fits)."""
        schedule = {}
        for appliance_id, clock in final.items():
            try:
                if appliance_id in plan_ids:
                    schedule[appliance_id] = scenario.time_to_slot(clock)
            except (ValueError, AttributeError):
                continue
        missing = sorted(
            (a for a in scenario.appliances if a.id not in schedule), key=lambda a: (-a.energy_kwh, a.id)
        )  # fmt: skip
        limit = scenario.peak_limit_kw + PEAK_TOLERANCE_KW
        for a in missing:
            load = total_load(scenario, schedule)
            by_cost = sorted(a.valid_starts(), key=lambda s: appliance_cost(scenario, a, s))
            fits = [s for s in by_cost if all(load[s + i] + p <= limit for i, p in enumerate(a.profile_kw))]
            schedule[a.id] = (fits or by_cost)[0]
        return {k: scenario.slot_to_time(v) for k, v in schedule.items()}, [a.id for a in missing]

    def requested_ids(state: PipelineState) -> list[str]:
        """Appliances the schedule must cover: the Orchestrator's brief plus the flexible profiled ones."""
        ids = list(state["brief"].appliance_ids)
        ids += [p.appliance_id for p in state["profile"].appliances if p.flexible and p.appliance_id not in ids]
        return ids

    def completeness_feedback(state: PipelineState, scheduled: dict[str, str]) -> str:
        missing = [i for i in requested_ids(state) if i not in scheduled]
        return f"MISSING: no start time for {', '.join(missing)}." if missing else ""

    def window_feedback(scheduled: dict[str, str]) -> str:
        """Start times outside the user window (checked against the household data, as the tools do)."""
        problems = []
        for appliance_id, clock in scheduled.items():
            try:
                appliance = scenario.appliance(appliance_id)
                start = scenario.time_to_slot(clock)
            except (ValueError, AttributeError):
                problems.append(f"{appliance_id} at {clock!r} is not a valid appliance and start time")
                continue
            if start not in appliance.valid_starts() and appliance.windows is not None:  # several periods (demo)
                problems.append(
                    f"{appliance_id} starts {scenario.slot_to_time(start)} but must start and finish inside one of "
                    f"{periods_text(appliance)}"
                )
            elif start not in appliance.valid_starts():
                problems.append(
                    f"{appliance_id} starts {scenario.slot_to_time(start)} but must start between "
                    f"{scenario.slot_to_time(appliance.earliest_slot)} and "
                    f"{scenario.slot_to_time(appliance.latest_start_slot)} to finish by "
                    f"{scenario.boundary_to_time(appliance.deadline_slot)}"
                )
        return f"OUTSIDE WINDOW: {'; '.join(problems)}." if problems else ""

    def problems_of(state: PipelineState, schedule: dict[str, str]) -> list[str]:
        """Peak-load conflicts, completeness and user time windows of a schedule."""
        conflicts = tools["detect_conflicts"].invoke({"schedule": schedule})
        problems = [conflicts] if conflicts.startswith(("CONFLICT", "ERROR")) else []
        if missing := completeness_feedback(state, schedule):
            problems.append(missing)
        if outside := window_feedback(schedule):
            problems.append(outside)
        return problems

    # ── Agents and steps ────────────────────────────────────────────────────
    def orchestrator_plan(state: PipelineState, config) -> PipelineState:
        brief, calls, errors, recoveries = _run_agent(
            models("orchestrator"), [], prompts.ORCHESTRATOR_PLAN, TaskBrief, state["request"],
            "orchestrator", ORCHESTRATOR_RECURSION_LIMIT, config,
        )  # fmt: skip
        if brief is None:  # fall back to all appliances rather than abort the run
            brief = TaskBrief(appliance_ids=[a.id for a in scenario.appliances], notes="")
        return {"brief": brief, "rounds": 0, "tool_calls": calls, "errors": errors, "recoveries": recoveries}

    def profile_data(state: PipelineState, config) -> PipelineState:
        """The appliance profiles straight from the household data, without a language model."""
        profiles = [
            ApplianceProfile(
                appliance_id=a.id, kind=a.kind, flexible=a.kind in SHIFTABLE_KINDS, peak_kw=round(a.peak_kw, 2),
                duration_minutes=a.duration_slots * SLOT_MINUTES, earliest_time=scenario.slot_to_time(a.earliest_slot),
                deadline_time=scenario.boundary_to_time(a.deadline_slot),
            )
            for a in scenario.appliances
        ]  # fmt: skip
        return {"profile": ProfileOutput(appliances=profiles)}

    def scheduler(state: PipelineState, config) -> PipelineState:
        flexible = [p.model_dump() for p in state["profile"].appliances if p.flexible]
        message = f"Appliance profiles:\n{json.dumps(flexible, indent=1)}{examples}"
        if state.get("feedback"):
            previous = state.get("checked") or {}
            message += (
                f"\n\nYour previous schedule after conflict resolution: {json.dumps(previous)}\n"
                f"Verification feedback: {state['feedback']}\n"
                "Propose a revised schedule that gives every requested appliance a start time."
            )
            if "MISSING" in state["feedback"]:
                message += f"\nThe day's plan has these appliances; schedule all of them: {', '.join(plan_ids)}."
        since = len(thought_log)
        proposal, calls, errors, recoveries = _run_agent(
            models("scheduler"), scheduler_tools(), scheduler_prompt, ScheduleOutput, message,
            "scheduler", SCHEDULER_STEP_LIMIT, config,
        )  # fmt: skip
        update: PipelineState = {"tool_calls": calls, "errors": errors, "recoveries": recoveries,
                                 "thoughts": [{"agent": "scheduler", **t} for t in thought_log[since:]]}  # fmt: skip
        if proposal is not None:
            update["proposal"] = proposal
        return update

    def verify_schedule(state: PipelineState, config) -> PipelineState:
        """Deterministic check of the Scheduler's schedule; problems go back to the Scheduler while a round is left.
        In the last round, an appliance still missing is placed at its cheapest start that fits under the limit."""
        proposal = state.get("proposal")
        rounds = state["rounds"] + 1
        if proposal is None:  # the Scheduler returned nothing: incomplete by definition, send it back
            return {"feedback": completeness_feedback(state, {}) or "MISSING: no schedule was returned.",
                    "rounds": rounds, "errors": ["verification: no schedule to check"]}  # fmt: skip
        schedule = assignments_to_dict(proposal.assignments)
        problems = problems_of(state, schedule)
        errors: list[str] = []
        if problems and rounds >= MAX_ROUNDS and any(i not in schedule for i in plan_ids):
            schedule, placed = place_missing(schedule)
            errors.append(f"verification: placed missing {', '.join(placed)} automatically")
            conflicts = tools["detect_conflicts"].invoke({"schedule": schedule})
            problems = [conflicts] if conflicts.startswith(("CONFLICT", "ERROR")) else []
            if outside := window_feedback(schedule):
                problems.append(outside)
        return {"checked": schedule, "feedback": " ".join(problems), "rounds": rounds, "errors": errors}

    def after_verification(state: PipelineState) -> str:
        if state.get("feedback") and state["rounds"] < MAX_ROUNDS:
            return "scheduler"
        return "review" if human_review else "orchestrator_finalize"

    def review(state: PipelineState) -> PipelineState:
        return {}  # graph is interrupted before this node; the caller resumes after approval

    def cost_facts(final: dict[str, str]) -> str:
        """Cost of the final schedule and of starting every appliance when ready, for the summary."""
        try:
            schedule = {k: scenario.time_to_slot(v) for k, v in final.items()}
        except (ValueError, AttributeError):
            return ""
        if summary_costs is not None:
            return summary_costs({k: s for k, s in schedule.items() if k in plan_ids})
        cost = sum(appliance_cost(scenario, scenario.appliance(k), s) for k, s in schedule.items() if k in plan_ids)
        ready = sum(appliance_cost(scenario, a, a.earliest_slot) for a in scenario.appliances if a.id in schedule)
        saving = ready - cost
        share = f" ({saving / ready * 100:.0f} %)" if ready > 0 else ""
        return (
            f"\nCost of the scheduled cycles: EUR {cost:.3f}. Cost if every appliance started as soon as it is ready: "
            f"EUR {ready:.3f}. Saving: EUR {saving:.3f}{share}."
        )

    def orchestrator_finalize(state: PipelineState, config) -> PipelineState:
        final = state.get("checked")
        if final is None:
            return {"errors": ["orchestrator: no schedule produced"]}
        summary = ""
        if summarize:
            check = tools["detect_conflicts"].invoke({"schedule": final})
            facts = f"Request:\n{state['request']}\n\nFinal schedule: {json.dumps(final)}\nPeak-load check: {check}"
            facts += cost_facts(final)
            reply = models("orchestrator").invoke(
                [SystemMessage(prompts.ORCHESTRATOR_SUMMARY), HumanMessage(facts)], config=config
            )
            summary = reply.text if hasattr(reply, "text") else str(reply.content)
        return {"final": final, "summary": summary}

    graph = StateGraph(PipelineState)
    graph.add_node("orchestrator_plan", orchestrator_plan)
    graph.add_node("profile_data", profile_data)
    graph.add_node("scheduler", scheduler)
    graph.add_node("verify_schedule", verify_schedule)
    graph.add_node("orchestrator_finalize", orchestrator_finalize)
    graph.add_edge(START, "orchestrator_plan")
    if parallel_start:  # both start at once; the Scheduler waits for both
        graph.add_edge(START, "profile_data")
        graph.add_edge(["orchestrator_plan", "profile_data"], "scheduler")
    else:
        graph.add_edge("orchestrator_plan", "profile_data")
        graph.add_edge("profile_data", "scheduler")
    graph.add_edge("scheduler", "verify_schedule")
    targets = ["scheduler", "orchestrator_finalize"]
    if human_review:
        graph.add_node("review", review)
        graph.add_edge("review", "orchestrator_finalize")
        targets.append("review")
    graph.add_conditional_edges("verify_schedule", after_verification, targets)
    graph.add_edge("orchestrator_finalize", END)

    if human_review:
        return graph.compile(checkpointer=InMemorySaver(), interrupt_before=["review"])
    return graph.compile()


def run_multi_agent(
    scenario: Scenario, models: ModelFactory, config: dict[str, Any] | None = None, summarize: bool = True,
    retriever: Callable[[Scenario], str] | None = None, thoughts: bool = False,
) -> AgentRun:  # fmt: skip
    pipeline = build_pipeline(scenario, models, retriever=retriever, thoughts=thoughts, summarize=summarize)
    state: PipelineState = pipeline.invoke({"request": scenario.user_request}, config={"recursion_limit": 50, **(config or {})})
    return AgentRun(
        assignments=state.get("final"),
        explanation=state.get("summary", ""),
        errors=state.get("errors", []),
        tool_calls=state.get("tool_calls", 0),
        recoveries=state.get("recoveries", 0),
        iterations=state.get("rounds", 0),
        thoughts=state.get("thoughts", []),
    )
