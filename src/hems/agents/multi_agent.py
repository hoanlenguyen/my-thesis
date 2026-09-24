"""Hierarchical ReAct multi-agent pipeline (LangGraph).

    orchestrator_plan -> profiler -> scheduler -> resolver --(conflicts & budget left)--> scheduler
                                                     |
                                                     +--> [human review] -> orchestrator_finalize -> END

Each specialist is a ReAct agent with only its own tools. The fixed edge order
matches Chapter 4.2; the only branch is the verification gate after the
resolver, which re-runs detect_conflicts and sends feedback to the scheduler.
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
from hems.agents.schemas import (
    ProfileOutput,
    ResolverOutput,
    ScheduleOutput,
    TaskBrief,
    assignments_to_dict,
)
from hems.agents.types import AgentRun
from hems.core.models import Scenario
from hems.tools import PROFILER_TOOLS, RESOLVER_TOOLS, SCHEDULER_TOOLS, build_tools, select

SPECIALIST_RECURSION_LIMIT = 25
ORCHESTRATOR_RECURSION_LIMIT = 6
MAX_RESOLVE_ITERATIONS = 2

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
    tool_calls: Annotated[int, operator.add]
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
) -> tuple[BaseModel | None, int, list[str]]:
    agent = create_agent(model, tools=tools, system_prompt=system_prompt, response_format=ToolStrategy(schema), name=name)
    try:
        result = agent.invoke({"messages": [HumanMessage(message)]}, config={**(config or {}), "recursion_limit": limit})
    except GraphRecursionError:
        return None, 0, [f"{name}: step limit reached"]
    calls = sum(len(getattr(m, "tool_calls", []) or []) for m in result["messages"])
    output = result.get("structured_response")
    return output, calls, ([] if output is not None else [f"{name}: no structured output"])


def build_pipeline(scenario: Scenario, models: ModelFactory, *, human_review: bool = False, summarize: bool = True):
    tools = build_tools(scenario)

    def orchestrator_plan(state: PipelineState, config) -> PipelineState:
        brief, calls, errors = _run_agent(
            models("orchestrator"), [], prompts.ORCHESTRATOR_PLAN, TaskBrief, state["request"],
            "orchestrator", ORCHESTRATOR_RECURSION_LIMIT, config,
        )  # fmt: skip
        if brief is None:  # fall back to all appliances rather than abort the run
            brief = TaskBrief(appliance_ids=[a.id for a in scenario.appliances], notes="")
        return {"brief": brief, "iterations": 0, "tool_calls": calls, "errors": errors}

    def profiler(state: PipelineState, config) -> PipelineState:
        brief = state["brief"]
        message = f"Profile these requested appliances: {', '.join(brief.appliance_ids)}.\nUser notes: {brief.notes or 'none'}"
        profile, calls, errors = _run_agent(
            models("profiler"), select(tools, PROFILER_TOOLS), prompts.PROFILER, ProfileOutput, message,
            "profiler", SPECIALIST_RECURSION_LIMIT, config,
        )  # fmt: skip
        return {"profile": profile or ProfileOutput(appliances=[]), "tool_calls": calls, "errors": errors}

    def scheduler(state: PipelineState, config) -> PipelineState:
        flexible = [p.model_dump() for p in state["profile"].appliances if p.flexible]
        message = f"Appliance profiles:\n{json.dumps(flexible, indent=1)}"
        if state.get("conflict_feedback"):
            previous = assignments_to_dict(state["resolution"].assignments)
            message += (
                f"\n\nYour previous schedule after conflict resolution: {json.dumps(previous)}\n"
                f"Conflict feedback: {state['conflict_feedback']}\nPropose a revised schedule."
            )
        proposal, calls, errors = _run_agent(
            models("scheduler"), select(tools, SCHEDULER_TOOLS), prompts.SCHEDULER, ScheduleOutput, message,
            "scheduler", SPECIALIST_RECURSION_LIMIT, config,
        )  # fmt: skip
        update: PipelineState = {"tool_calls": calls, "errors": errors}
        if proposal is not None:
            update["proposal"] = proposal
        return update

    def resolver(state: PipelineState, config) -> PipelineState:
        proposal = state.get("proposal")
        if proposal is None:
            return {"errors": ["resolver: no proposal to resolve"]}
        windows = {p.appliance_id: f"{p.earliest_time}-{p.deadline_time}" for p in state["profile"].appliances}
        message = (
            f"Proposed schedule: {json.dumps(assignments_to_dict(proposal.assignments))}\n"
            f"User windows (earliest start - finish by): {json.dumps(windows)}"
        )
        resolution, calls, errors = _run_agent(
            models("resolver"), select(tools, RESOLVER_TOOLS), prompts.RESOLVER, ResolverOutput, message,
            "resolver", SPECIALIST_RECURSION_LIMIT, config,
        )  # fmt: skip
        if resolution is None:  # keep the unresolved proposal so the run still yields a schedule
            resolution = ResolverOutput(assignments=proposal.assignments, conflicts_remaining=True, changes="resolver failed")
        feedback = tools["detect_conflicts"].invoke({"schedule": assignments_to_dict(resolution.assignments)})
        return {
            "resolution": resolution,
            "conflict_feedback": feedback if feedback.startswith(("CONFLICT", "ERROR")) else "",
            "iterations": state["iterations"] + 1,
            "tool_calls": calls,
            "errors": errors,
        }

    def after_resolver(state: PipelineState) -> str:
        if state.get("conflict_feedback") and state["iterations"] < MAX_RESOLVE_ITERATIONS:
            return "scheduler"
        return "review" if human_review else "orchestrator_finalize"

    def review(state: PipelineState) -> PipelineState:
        return {}  # graph is interrupted before this node; the caller resumes after approval

    def orchestrator_finalize(state: PipelineState, config) -> PipelineState:
        resolution = state.get("resolution")
        if resolution is None:
            return {"errors": ["orchestrator: no schedule produced"]}
        final = assignments_to_dict(resolution.assignments)
        summary = ""
        if summarize:
            reply = models("orchestrator").invoke(
                [SystemMessage(prompts.ORCHESTRATOR_SUMMARY), HumanMessage(f"Request:\n{state['request']}\n\nFinal schedule: {json.dumps(final)}")],
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


def run_multi_agent(scenario: Scenario, models: ModelFactory, config: dict[str, Any] | None = None, summarize: bool = True) -> AgentRun:
    pipeline = build_pipeline(scenario, models, summarize=summarize)
    state: PipelineState = pipeline.invoke({"request": scenario.user_request}, config={"recursion_limit": 50, **(config or {})})
    return AgentRun(
        assignments=state.get("final"),
        explanation=state.get("summary", ""),
        errors=state.get("errors", []),
        tool_calls=state.get("tool_calls", 0),
        iterations=state.get("iterations", 0),
    )
