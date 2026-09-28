"""Single-agent ReAct baseline: one agent, all eight tools, one context window."""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError

from hems.agents import prompts
from hems.agents.errors import MAX_RECOVERIES, invoke_with_recovery, model_output_failure
from hems.agents.schemas import ScheduleOutput, assignments_to_dict
from hems.agents.types import AgentRun
from hems.core.models import Scenario
from hems.tools import ALL_TOOLS, build_tools, select

# Same total step budget as the three specialists combined (3 x 25).
RECURSION_LIMIT = 75


def run_single_agent(scenario: Scenario, model: BaseChatModel, config: dict[str, Any] | None = None) -> AgentRun:
    agent = create_agent(
        model,
        tools=select(build_tools(scenario), ALL_TOOLS),
        system_prompt=prompts.SINGLE_AGENT,
        response_format=ToolStrategy(ScheduleOutput),
        checkpointer=InMemorySaver(),  # lets a rejected turn be retried from the last good state
        name="single_agent",
    )
    try:
        result, recoveries = invoke_with_recovery(
            agent, scenario.user_request, "ScheduleOutput", config or {}, RECURSION_LIMIT
        )
    except GraphRecursionError:
        return AgentRun(assignments=None, errors=["single_agent: step limit reached"])
    except Exception as exc:  # provider errors propagate; persistent model-output failures = failed run
        if (reason := model_output_failure(exc)) is None:
            raise
        return AgentRun(assignments=None, errors=[f"single_agent: {reason}"], recoveries=MAX_RECOVERIES)

    output: ScheduleOutput | None = result.get("structured_response")
    tool_calls = sum(len(getattr(m, "tool_calls", []) or []) for m in result["messages"])
    if output is None:
        return AgentRun(
            assignments=None, errors=["single_agent: no structured schedule returned"],
            tool_calls=tool_calls, recoveries=recoveries,
        )  # fmt: skip
    return AgentRun(
        assignments=assignments_to_dict(output.assignments),
        explanation=output.explanation,
        tool_calls=tool_calls,
        recoveries=recoveries,
    )
