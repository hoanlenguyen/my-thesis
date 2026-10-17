"""One ReAct agent inside the agent harness (LangGraph): the single-agent counterpart of the two-agent pipeline.

    profile_data -> agent -> verify_schedule --(problem found and a round left: feedback in the same conversation)
                      ^                       |
                      +-----------------------+
                                              +--> explain (the same agent writes the household message) -> END

The agent has the Scheduler agent's tools (prices with a cache, the optimiser, cost and load tools) and gets the same
context, retrieved examples and checks from the harness (``hems.agents.harness``). What the two-agent pipeline splits
over an Orchestrator and a Scheduler, this agent does in one conversation: it reads the household's request itself,
plans, fixes what the check reports with its whole history in view, and finally explains the schedule. Built in
October 2026 for the comparison of one agent with two (exploratory; systems "single_harness" and
"single_harness_thoughts").
"""

from __future__ import annotations

import json
import operator
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from hems.agents import prompts
from hems.agents.harness import MAX_ROUNDS, Checker, cost_facts, profile_text, profiles, run_react
from hems.agents.multi_agent import ORCHESTRATOR_RECURSION_LIMIT, SCHEDULER_AGENT_TOOLS, SCHEDULER_STEP_LIMIT
from hems.agents.schemas import ProfileOutput, ScheduleOutput, assignments_to_dict
from hems.agents.types import AgentRun
from hems.core.models import Scenario, Schedule
from hems.tools import build_tools, select, with_thought

# Step budget per round: the Scheduler agent's and the Orchestrator agent's budgets together.
AGENT_STEP_LIMIT = SCHEDULER_STEP_LIMIT + ORCHESTRATOR_RECURSION_LIMIT
AGENT_TOOLS = SCHEDULER_AGENT_TOOLS  # the same tools as the two-agent pipeline's Scheduler agent


class HarnessState(TypedDict, total=False):
    request: str
    profile: ProfileOutput
    messages: list[BaseMessage]  # the agent's conversation, continued in a feedback round and for the message
    proposal: ScheduleOutput
    checked: dict[str, str]
    feedback: str
    rounds: int
    final: dict[str, str]
    summary: str
    tool_calls: Annotated[int, operator.add]
    recoveries: Annotated[int, operator.add]
    errors: Annotated[list[str], operator.add]
    thoughts: Annotated[list[dict[str, str]], operator.add]


def build_harness_agent(
    scenario: Scenario, model: BaseChatModel, *, retriever: Callable[[Scenario], str] | None = None,
    thoughts: bool = False, summarize: bool = True, summary_costs: Callable[[Schedule], str] | None = None,
    message_instruction: str = prompts.HARNESS_MESSAGE,
):  # fmt: skip
    """The single agent for one household-day. Arguments as in ``multi_agent.build_pipeline``;
    ``message_instruction`` (demo only; not evaluated) replaces the request for the household message."""
    tools = build_tools(scenario)
    checker = Checker(scenario, tools)
    examples = f"\n\n{retriever(scenario)}" if retriever else ""
    thought_log: list[dict[str, str]] = []
    system_prompt = prompts.HARNESS_AGENT + (prompts.THOUGHT_NOTE if thoughts else "")

    def agent_tools() -> list:
        listed = select(tools, AGENT_TOOLS)
        return [with_thought(t, thought_log) for t in listed] if thoughts else listed

    def required(state: HarnessState) -> list[str]:
        return [p.appliance_id for p in state["profile"].appliances if p.flexible]

    def profile_data(state: HarnessState, config) -> HarnessState:
        """The appliance profiles straight from the household data, without a language model."""
        return {"profile": profiles(scenario), "rounds": 0}

    def agent(state: HarnessState, config) -> HarnessState:
        if state.get("feedback") and state.get("messages"):  # feedback round: continue the same conversation
            note = (
                f"Verification feedback: {state['feedback']}\n"
                f"Your schedule after the check: {json.dumps(state.get('checked') or {})}\n"
                "Propose a revised schedule that gives every requested appliance a start time."
            )
            if "MISSING" in state["feedback"]:
                note += f"\nThe day's plan has these appliances; schedule all of them: {', '.join(checker.plan_ids)}."
            message: str | list[BaseMessage] = [*state["messages"], HumanMessage(note)]
        else:
            message = f"{state['request']}\n\n{profile_text(state['profile'])}{examples}"
        since = len(thought_log)
        run = run_react(model, agent_tools(), system_prompt, ScheduleOutput, message, "agent", AGENT_STEP_LIMIT, config)
        update: HarnessState = {"tool_calls": run.tool_calls, "errors": run.errors, "recoveries": run.recoveries,
                                "thoughts": [{"agent": "agent", **t} for t in thought_log[since:]]}  # fmt: skip
        if run.messages:
            update["messages"] = run.messages
        if run.output is not None:
            update["proposal"] = run.output
        return update

    def verify_schedule(state: HarnessState, config) -> HarnessState:
        """The harness's check, as in the two-agent pipeline."""
        proposal = state.get("proposal")
        rounds = state["rounds"] + 1
        if proposal is None:
            return {"feedback": checker.completeness(required(state), {}) or "MISSING: no schedule was returned.",
                    "rounds": rounds, "errors": ["verification: no schedule to check"]}  # fmt: skip
        schedule, feedback, errors = checker.verify(assignments_to_dict(proposal.assignments), required(state), rounds)
        return {"checked": schedule, "feedback": feedback, "rounds": rounds, "errors": errors}

    def after_verification(state: HarnessState) -> str:
        return "agent" if state.get("feedback") and state["rounds"] < MAX_ROUNDS else "explain"

    def explain(state: HarnessState, config) -> HarnessState:
        """The same agent, with its whole conversation, writes the household message from the checked figures."""
        final = state.get("checked")
        if final is None:
            return {"errors": ["agent: no schedule produced"]}
        summary = ""
        if summarize:
            check = tools["detect_conflicts"].invoke({"schedule": final})
            facts = (f"Your schedule after the automatic check: {json.dumps(final)}\nPeak-load check: {check}"
                     f"{cost_facts(scenario, final, summary_costs)}\n\n{message_instruction}")  # fmt: skip
            reply = model.invoke([SystemMessage(system_prompt), *state.get("messages", []), HumanMessage(facts)], config=config)
            summary = reply.text if hasattr(reply, "text") else str(reply.content)
        return {"final": final, "summary": summary}

    graph = StateGraph(HarnessState)
    graph.add_node("profile_data", profile_data)
    graph.add_node("agent", agent)
    graph.add_node("verify_schedule", verify_schedule)
    graph.add_node("explain", explain)
    graph.add_edge(START, "profile_data")
    graph.add_edge("profile_data", "agent")
    graph.add_edge("agent", "verify_schedule")
    graph.add_conditional_edges("verify_schedule", after_verification, ["agent", "explain"])
    graph.add_edge("explain", END)
    return graph.compile()


def run_harness_agent(
    scenario: Scenario, model: BaseChatModel, config: dict[str, Any] | None = None, summarize: bool = True,
    retriever: Callable[[Scenario], str] | None = None, thoughts: bool = False,
) -> AgentRun:  # fmt: skip
    graph = build_harness_agent(scenario, model, retriever=retriever, thoughts=thoughts, summarize=summarize)
    state: HarnessState = graph.invoke({"request": scenario.user_request}, config={"recursion_limit": 50, **(config or {})})
    return AgentRun(
        assignments=state.get("final"),
        explanation=state.get("summary", ""),
        errors=state.get("errors", []),
        tool_calls=state.get("tool_calls", 0),
        recoveries=state.get("recoveries", 0),
        iterations=state.get("rounds", 0),
        thoughts=state.get("thoughts", []),
    )
