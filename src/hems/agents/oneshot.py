"""No-tools LLM baseline: one structured answer from the full scenario data, no ReAct loop.

It receives the same information the agents can obtain through their tools (household data,
the price of every slot and, since it cannot call sum_load, the base load of every slot), so
the comparison with the agents isolates the value of tool use and step-by-step reasoning.
"""

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
from hems.tools import build_tools

# Only the structured answer (plus recovery nudges) is needed; no tool steps.
RECURSION_LIMIT = 6


def scenario_message(scenario: Scenario) -> str:
    household = build_tools(scenario)["read_household_data"].invoke({})
    rows = [
        f"{scenario.slot_to_time(t)} {price * 100:.2f} {base:.2f}"
        for t, (price, base) in enumerate(zip(scenario.price_eur_per_kwh, scenario.base_load_kw))
    ]
    return (
        f"{scenario.user_request}\n\nHousehold data:\n{household}\n\n"
        "Price (consumer price, c/kWh) and measured base load (kW) per 15-minute slot:\n"
        "time c/kWh base_kW\n" + "\n".join(rows)
    )


def run_oneshot(scenario: Scenario, model: BaseChatModel, config: dict[str, Any] | None = None) -> AgentRun:
    agent = create_agent(
        model, tools=[], system_prompt=prompts.ONESHOT, response_format=ToolStrategy(ScheduleOutput),
        checkpointer=InMemorySaver(), name="oneshot",
    )  # fmt: skip
    try:
        result, recoveries = invoke_with_recovery(agent, scenario_message(scenario), "ScheduleOutput", config or {}, RECURSION_LIMIT)
    except GraphRecursionError:
        return AgentRun(assignments=None, errors=["oneshot: step limit reached"])
    except Exception as exc:  # provider errors propagate; persistent model-output failures = failed run
        if (reason := model_output_failure(exc)) is None:
            raise
        return AgentRun(assignments=None, errors=[f"oneshot: {reason}"], recoveries=MAX_RECOVERIES)
    output: ScheduleOutput | None = result.get("structured_response")
    if output is None:
        return AgentRun(assignments=None, errors=["oneshot: no structured schedule returned"], recoveries=recoveries)
    return AgentRun(assignments=assignments_to_dict(output.assignments), explanation=output.explanation, recoveries=recoveries)
