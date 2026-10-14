"""Hierarchical ReAct multi-agent pipeline (LangGraph).

    orchestrator_plan -> profiler -> scheduler -> resolver --(conflict, missing appliance or start
                                                     |          outside window; budget left)--> scheduler
                                                     +--> [human review] -> orchestrator_finalize -> END

Each specialist is a ReAct agent with only its own tools. The fixed edge order
matches Chapter 4.2; the only branch is the Orchestrator's verification gate after
the resolver, which re-runs detect_conflicts, checks that every requested appliance
has a start time inside its user window, and sends any problems back to the scheduler.
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
    Assignment,
    ProfileOutput,
    ResolverOutput,
    ScheduleOutput,
    TaskBrief,
    assignments_to_dict,
)
from hems.agents.types import AgentRun
from hems.core.evaluate import PEAK_TOLERANCE_KW, appliance_cost, evaluate, total_load
from hems.core.models import FlexibleAppliance, Scenario, Schedule
from hems.tools import OPTIMIZER_TOOLS, PROFILER_TOOLS, RESOLVER_TOOLS, SCHEDULER_TOOLS, build_tools, select

# Step budget split by workload; the total equals the single agent's RECURSION_LIMIT (75).
STEP_LIMITS = {"profiler": 15, "scheduler": 35, "resolver": 25}
ORCHESTRATOR_RECURSION_LIMIT = 6
MAX_RESOLVE_ITERATIONS = 2
# Design iteration 6 (system "multi_v3", off by default): a valid schedule that costs more than this much
# above the cost of every appliance at its individually cheapest start (a lower bound that ignores the
# peak limit) is sent back once for a cheaper staggering; the cheapest valid schedule seen is kept.
COST_TOLERANCE = 0.03
# Design iteration 7 ("multi_rag", "multi_rag_opt"): ``retriever`` returns worked examples of similar solved
# days (hems.rag) for the Scheduler's and the Resolver's messages; ``optimizer`` gives the Scheduler the
# optimize_schedule tool and its prompt. Both off by default, so "multi" is unchanged.
# Design iteration 8 (``complete_missing``, final Multi-Agent Pipeline only): on a missing-appliance retry the
# Scheduler is told every appliance of the day's plan, and if one is still missing after the last feedback
# round, the verification step places it at its cheapest start that keeps the load within the limit, with
# the other start times unchanged. The language model rarely drops an appliance (2 of 288 exploratory runs).
# Design iteration 9 (``lean``, system "multi_lean"): the response time is almost entirely sequential model calls
# (tools take < 0.5 s of ~20 s). The Profiler gets the household data and classifications in its message and answers
# in one call; the Scheduler returns the solver's result without re-costing it; the Resolver runs only when the
# proposal fails the verification step; the summary is given the schedule's cost and its saving.

ModelFactory = Callable[[str], BaseChatModel]
"""Role name ("orchestrator" | "profiler" | "scheduler" | "resolver") -> chat model."""


class PipelineState(TypedDict, total=False):
    request: str
    brief: TaskBrief
    profile: ProfileOutput
    proposal: ScheduleOutput
    resolution: ResolverOutput
    conflict_feedback: str
    iterations: int
    final: dict[str, str]
    summary: str
    best: dict[str, str]  # cost check only: cheapest valid schedule so far
    best_cost: float
    tool_calls: Annotated[int, operator.add]
    recoveries: Annotated[int, operator.add]
    errors: Annotated[list[str], operator.add]


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
    scenario: Scenario, models: ModelFactory, *, human_review: bool = False, summarize: bool = True, cost_check: bool = False,
    retriever: Callable[[Scenario], str] | None = None, optimizer: bool = False, complete_missing: bool = False,
    lean: bool = False, parallel_start: bool = False, summary_costs: Callable[[Schedule], str] | None = None,
):  # fmt: skip
    """``parallel_start`` (demo only, with ``lean``; not evaluated): the Profiler starts at the same time as the
    Orchestrator's planning step instead of waiting for its brief, since it already receives the household data.

    ``summary_costs`` (demo only, with ``lean``; not evaluated): replaces the cost lines given to the summary, so
    that it states the cost the demo page shows (energy plus a fee for exceeding the limit) instead of the energy
    cost alone."""
    if parallel_start and not lean:
        raise ValueError("parallel_start requires lean")
    tools = build_tools(scenario)
    plan_ids = [a.id for a in scenario.appliances]  # every cycle in the day's appliance plan

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
    examples = f"\n\n{retriever(scenario)}" if retriever else ""
    scheduler_tools = SCHEDULER_TOOLS + (OPTIMIZER_TOOLS if optimizer else ())
    scheduler_prompt = prompts.SCHEDULER_OPT if optimizer else prompts.SCHEDULER
    if lean:
        scheduler_prompt = prompts.SCHEDULER_LEAN

    def verification_problems(state: PipelineState, final: dict[str, str]) -> list[str]:
        """The Orchestrator's verification gate: peak-load conflicts, completeness and user time windows."""
        conflicts = tools["detect_conflicts"].invoke({"schedule": final})
        problems = [conflicts] if conflicts.startswith(("CONFLICT", "ERROR")) else []
        if missing := completeness_feedback(state, final):
            problems.append(missing)
        if outside := window_feedback(final):
            problems.append(outside)
        return problems

    def orchestrator_plan(state: PipelineState, config) -> PipelineState:
        brief, calls, errors, recoveries = _run_agent(
            models("orchestrator"), [], prompts.ORCHESTRATOR_PLAN, TaskBrief, state["request"],
            "orchestrator", ORCHESTRATOR_RECURSION_LIMIT, config,
        )  # fmt: skip
        if brief is None:  # fall back to all appliances rather than abort the run
            brief = TaskBrief(appliance_ids=[a.id for a in scenario.appliances], notes="")
        return {"brief": brief, "iterations": 0, "tool_calls": calls, "errors": errors, "recoveries": recoveries}

    def profiler(state: PipelineState, config) -> PipelineState:
        # The original request travels in the shared state alongside the Orchestrator's brief, so an
        # appliance omitted from the brief is not silently lost at this hand-off (observed in the pilot).
        brief = state.get("brief")  # not yet available when the Profiler starts in parallel
        handoff = f"Orchestrator brief: appliances {', '.join(brief.appliance_ids)}; notes: {brief.notes or 'none'}.\n" if brief else ""
        message = f"User request:\n{state['request']}\n\n{handoff}Profile every appliance the user's request asks to schedule."
        profiler_tools, profiler_prompt = select(tools, PROFILER_TOOLS), prompts.PROFILER
        if lean:  # the deterministic reads are done here, not in separate model turns
            classes = "\n".join(
                tools["classify_appliance"].invoke({"appliance_id": i})
                for i in [a.id for a in scenario.appliances] + [f.id for f in scenario.fixed_appliances]
            )
            message += (
                f"\n\nHousehold data (read_household_data):\n{tools['read_household_data'].invoke({})}"
                f"\n\nClassification (classify_appliance):\n{classes}"
            )
            profiler_tools, profiler_prompt = [], prompts.PROFILER_LEAN
        profile, calls, errors, recoveries = _run_agent(
            models("profiler"), profiler_tools, profiler_prompt, ProfileOutput, message,
            "profiler", STEP_LIMITS["profiler"], config,
        )  # fmt: skip
        return {"profile": profile or ProfileOutput(appliances=[]), "tool_calls": calls, "errors": errors, "recoveries": recoveries}

    def scheduler(state: PipelineState, config) -> PipelineState:
        flexible = [p.model_dump() for p in state["profile"].appliances if p.flexible]
        message = f"Appliance profiles:\n{json.dumps(flexible, indent=1)}{examples}"
        if state.get("conflict_feedback"):
            previous = assignments_to_dict(state["resolution"].assignments) if state.get("resolution") else {}
            message += (
                f"\n\nYour previous schedule after conflict resolution: {json.dumps(previous)}\n"
                f"Verification feedback: {state['conflict_feedback']}\n"
                "Propose a revised schedule that gives every requested appliance a start time."
            )
            if complete_missing and "MISSING" in state["conflict_feedback"]:
                message += f"\nThe day's plan has these appliances; schedule all of them: {', '.join(plan_ids)}."
        proposal, calls, errors, recoveries = _run_agent(
            models("scheduler"), select(tools, scheduler_tools), scheduler_prompt, ScheduleOutput, message,
            "scheduler", STEP_LIMITS["scheduler"], config,
        )  # fmt: skip
        update: PipelineState = {"tool_calls": calls, "errors": errors, "recoveries": recoveries}
        if proposal is not None:
            update["proposal"] = proposal
        return update

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

    def cost_feedback(state: PipelineState, final: dict[str, str]) -> tuple[float, str]:
        """Cost of a valid schedule and, if it is well above the unconstrained lower bound, feedback."""
        schedule = {k: scenario.time_to_slot(v) for k, v in final.items()}
        cost = evaluate(scenario, schedule).cost_eur
        wanted = {i for i in requested_ids(state)} & {a.id for a in scenario.appliances}
        bound = sum(
            min(appliance_cost(scenario, a, s) for s in a.valid_starts()) for a in scenario.appliances if a.id in wanted
        )
        if bound <= 0 or cost <= bound * (1 + COST_TOLERANCE) + 1e-9:
            return cost, ""
        return cost, (
            f"COST: this valid schedule costs EUR {cost:.3f}, {(cost / bound - 1) * 100:.1f} % above EUR {bound:.3f}, the cost "
            "with every appliance at its individually cheapest start (which ignores the peak limit and may be unreachable). "
            "Look for a cheaper staggering that still respects the peak limit and every window: compare moving each of the "
            "overlapping appliances, not only the first one, and keep the arrangement with the lowest total cost. The current "
            "schedule is kept if no cheaper valid one is found."
        )

    def resolver(state: PipelineState, config) -> PipelineState:
        proposal = state.get("proposal")
        if proposal is None:  # the Scheduler returned nothing: incomplete by definition, send it back
            return {
                "conflict_feedback": completeness_feedback(state, {}) or "MISSING: no schedule was returned.",
                "iterations": state["iterations"] + 1,
                "errors": ["resolver: no proposal to resolve"],
            }
        if lean and not verification_problems(state, assignments_to_dict(proposal.assignments)):
            # The proposal already passes the verification gate: nothing for the Resolver to resolve.
            return {
                "resolution": ResolverOutput(
                    assignments=proposal.assignments, conflicts_remaining=False,
                    changes="none (the proposal passed the verification step)",
                ),
                "iterations": state["iterations"] + 1,
                "conflict_feedback": "",
            }  # fmt: skip
        windows = {p.appliance_id: f"{p.earliest_time}-{p.deadline_time}" for p in state["profile"].appliances}
        for a in scenario.appliances:  # several allowed periods (demo only): the true periods, not the span
            if a.windows is not None and a.id in windows:
                windows[a.id] = periods_text(a)
        message = (
            f"Proposed schedule: {json.dumps(assignments_to_dict(proposal.assignments))}\n"
            f"User windows (earliest start - finish by): {json.dumps(windows)}{examples}"
        )
        resolution, calls, errors, recoveries = _run_agent(
            models("resolver"), select(tools, RESOLVER_TOOLS), prompts.RESOLVER, ResolverOutput, message,
            "resolver", STEP_LIMITS["resolver"], config,
        )  # fmt: skip
        if resolution is None:  # keep the unresolved proposal so the run still yields a schedule
            resolution = ResolverOutput(assignments=proposal.assignments, conflicts_remaining=True, changes="resolver failed")
        # Orchestrator's verification gate: peak-load conflicts, completeness and user time windows.
        final = assignments_to_dict(resolution.assignments)
        conflicts = tools["detect_conflicts"].invoke({"schedule": final})
        problems = [conflicts] if conflicts.startswith(("CONFLICT", "ERROR")) else []
        if missing := completeness_feedback(state, final):
            problems.append(missing)
        if outside := window_feedback(final):
            problems.append(outside)
        last_round = state["iterations"] + 1 >= MAX_RESOLVE_ITERATIONS
        if complete_missing and last_round and any(i not in final for i in plan_ids):
            final, placed = place_missing(final)
            resolution = ResolverOutput(
                assignments=[Assignment(appliance_id=k, start_time=v) for k, v in final.items()],
                conflicts_remaining=resolution.conflicts_remaining, changes=f"{resolution.changes}; verification placed {placed}",
            )  # fmt: skip
            errors = [*errors, f"verification: placed missing {', '.join(placed)} automatically"]
            conflicts = tools["detect_conflicts"].invoke({"schedule": final})
            problems = [conflicts] if conflicts.startswith(("CONFLICT", "ERROR")) else []
            if outside := window_feedback(final):
                problems.append(outside)
        update: PipelineState = {
            "resolution": resolution,
            "iterations": state["iterations"] + 1,
            "tool_calls": calls,
            "errors": errors,
            "recoveries": recoveries,
        }
        if cost_check and not problems:  # valid: remember the cheapest, ask for a cheaper one once
            cost, feedback = cost_feedback(state, final)
            if state.get("best_cost") is None or cost < state["best_cost"]:
                update["best"], update["best_cost"] = final, cost
            if feedback and state["iterations"] + 1 < MAX_RESOLVE_ITERATIONS:
                problems.append(feedback)
        update["conflict_feedback"] = " ".join(problems)
        return update

    def after_resolver(state: PipelineState) -> str:
        if state.get("conflict_feedback") and state["iterations"] < MAX_RESOLVE_ITERATIONS:
            return "scheduler"
        return "review" if human_review else "orchestrator_finalize"

    def review(state: PipelineState) -> PipelineState:
        return {}  # graph is interrupted before this node; the caller resumes after approval

    def cost_facts(final: dict[str, str]) -> str:
        """Cost of the final schedule and of starting every appliance when ready, for the summary (iteration 9)."""
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
        resolution = state.get("resolution")
        if resolution is None:
            return {"errors": ["orchestrator: no schedule produced"]}
        final = assignments_to_dict(resolution.assignments)
        if cost_check and state.get("best"):  # the cheapest valid schedule, not necessarily the last one
            final = state["best"]
        summary = ""
        if summarize:
            check = tools["detect_conflicts"].invoke({"schedule": final})
            facts = f"Request:\n{state['request']}\n\nFinal schedule: {json.dumps(final)}\nPeak-load check: {check}"
            if lean:
                facts += cost_facts(final)
            reply = models("orchestrator").invoke(
                [SystemMessage(prompts.ORCHESTRATOR_SUMMARY_LEAN if lean else prompts.ORCHESTRATOR_SUMMARY), HumanMessage(facts)],
                config=config,
            )
            summary = reply.text if hasattr(reply, "text") else str(reply.content)
        return {"final": final, "summary": summary}

    graph = StateGraph(PipelineState)
    graph.add_node("orchestrator_plan", orchestrator_plan)
    graph.add_node("profiler", profiler)
    graph.add_node("scheduler", scheduler)
    graph.add_node("resolver", resolver)
    graph.add_node("orchestrator_finalize", orchestrator_finalize)
    graph.add_edge(START, "orchestrator_plan")
    if parallel_start:  # both start at once; the Scheduler waits for both
        graph.add_edge(START, "profiler")
        graph.add_edge(["orchestrator_plan", "profiler"], "scheduler")
    else:
        graph.add_edge("orchestrator_plan", "profiler")
        graph.add_edge("profiler", "scheduler")
    graph.add_edge("scheduler", "resolver")
    targets = ["scheduler", "orchestrator_finalize"]
    if human_review:
        graph.add_node("review", review)
        graph.add_edge("review", "orchestrator_finalize")
        targets.append("review")
    graph.add_conditional_edges("resolver", after_resolver, targets)
    graph.add_edge("orchestrator_finalize", END)

    if human_review:
        return graph.compile(checkpointer=InMemorySaver(), interrupt_before=["review"])
    return graph.compile()


def run_multi_agent(
    scenario: Scenario, models: ModelFactory, config: dict[str, Any] | None = None, summarize: bool = True,
    cost_check: bool = False, retriever: Callable[[Scenario], str] | None = None, optimizer: bool = False,
    complete_missing: bool = False, lean: bool = False,
) -> AgentRun:  # fmt: skip
    pipeline = build_pipeline(
        scenario, models, summarize=summarize, cost_check=cost_check, retriever=retriever, optimizer=optimizer,
        complete_missing=complete_missing, lean=lean,
    )  # fmt: skip
    state: PipelineState = pipeline.invoke({"request": scenario.user_request}, config={"recursion_limit": 50, **(config or {})})
    return AgentRun(
        assignments=state.get("final"),
        explanation=state.get("summary", ""),
        errors=state.get("errors", []),
        tool_calls=state.get("tool_calls", 0),
        recoveries=state.get("recoveries", 0),
        iterations=state.get("iterations", 0),
    )
