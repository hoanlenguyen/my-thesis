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

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from hems.agents import prompts
from hems.agents.harness import MAX_ROUNDS, Checker, cost_facts, profile_text, profiles, run_react
from hems.agents.schemas import ProfileOutput, ScheduleOutput, TaskBrief, assignments_to_dict
from hems.agents.types import AgentRun
from hems.core.models import Scenario, Schedule
from hems.tools import OPTIMIZER_TOOLS, RESOLVER_TOOLS, SCHEDULER_TOOLS, build_tools, select, with_thought

# The Scheduler's step budget: the former Scheduler (35) and Conflict Resolver (25) budgets together.
SCHEDULER_STEP_LIMIT = 60
ORCHESTRATOR_RECURSION_LIMIT = 6
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
    checker = Checker(scenario, tools)
    plan_ids = checker.plan_ids  # every cycle in the day's appliance plan
    examples = f"\n\n{retriever(scenario)}" if retriever else ""
    thought_log: list[dict[str, str]] = []  # filled by the wrapped tools; moved into the state after each agent

    def scheduler_tools() -> list:
        listed = select(tools, SCHEDULER_AGENT_TOOLS)
        return [with_thought(t, thought_log) for t in listed] if thoughts else listed

    scheduler_prompt = prompts.SCHEDULER + (prompts.THOUGHT_NOTE if thoughts else "")

    def requested_ids(state: PipelineState) -> list[str]:
        """Appliances the schedule must cover: the Orchestrator's brief plus the flexible profiled ones."""
        ids = list(state["brief"].appliance_ids)
        ids += [p.appliance_id for p in state["profile"].appliances if p.flexible and p.appliance_id not in ids]
        return ids

    # ── Agents and steps ────────────────────────────────────────────────────
    def orchestrator_plan(state: PipelineState, config) -> PipelineState:
        run = run_react(
            models("orchestrator"), [], prompts.ORCHESTRATOR_PLAN, TaskBrief, state["request"],
            "orchestrator", ORCHESTRATOR_RECURSION_LIMIT, config,
        )  # fmt: skip
        brief = run.output
        if brief is None:  # fall back to all appliances rather than abort the run
            brief = TaskBrief(appliance_ids=[a.id for a in scenario.appliances], notes="")
        return {"brief": brief, "rounds": 0, "tool_calls": run.tool_calls, "errors": run.errors, "recoveries": run.recoveries}

    def profile_data(state: PipelineState, config) -> PipelineState:
        """The appliance profiles straight from the household data, without a language model."""
        return {"profile": profiles(scenario)}

    def scheduler(state: PipelineState, config) -> PipelineState:
        message = f"{profile_text(state['profile'])}{examples}"
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
        run = run_react(
            models("scheduler"), scheduler_tools(), scheduler_prompt, ScheduleOutput, message,
            "scheduler", SCHEDULER_STEP_LIMIT, config,
        )  # fmt: skip
        update: PipelineState = {"tool_calls": run.tool_calls, "errors": run.errors, "recoveries": run.recoveries,
                                 "thoughts": [{"agent": "scheduler", **t} for t in thought_log[since:]]}  # fmt: skip
        if run.output is not None:
            update["proposal"] = run.output
        return update

    def verify_schedule(state: PipelineState, config) -> PipelineState:
        """Deterministic check of the Scheduler's schedule; problems go back to the Scheduler while a round is left.
        In the last round, an appliance still missing is placed at its cheapest start that fits under the limit."""
        proposal = state.get("proposal")
        rounds = state["rounds"] + 1
        if proposal is None:  # the Scheduler returned nothing: incomplete by definition, send it back
            return {"feedback": checker.completeness(requested_ids(state), {}) or "MISSING: no schedule was returned.",
                    "rounds": rounds, "errors": ["verification: no schedule to check"]}  # fmt: skip
        schedule, feedback, errors = checker.verify(assignments_to_dict(proposal.assignments), requested_ids(state), rounds)
        return {"checked": schedule, "feedback": feedback, "rounds": rounds, "errors": errors}

    def after_verification(state: PipelineState) -> str:
        if state.get("feedback") and state["rounds"] < MAX_ROUNDS:
            return "scheduler"
        return "review" if human_review else "orchestrator_finalize"

    def review(state: PipelineState) -> PipelineState:
        return {}  # graph is interrupted before this node; the caller resumes after approval

    def orchestrator_finalize(state: PipelineState, config) -> PipelineState:
        final = state.get("checked")
        if final is None:
            return {"errors": ["orchestrator: no schedule produced"]}
        summary = ""
        if summarize:
            check = tools["detect_conflicts"].invoke({"schedule": final})
            facts = f"Request:\n{state['request']}\n\nFinal schedule: {json.dumps(final)}\nPeak-load check: {check}"
            facts += cost_facts(scenario, final, summary_costs)
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
