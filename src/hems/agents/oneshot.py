"""No-tools LLM baseline: one structured answer from the full scenario data, no ReAct loop.

It receives the same information the agents can obtain through their tools (each appliance's cycle, energy and peak
power, the peak limit, the price of every slot and, since it cannot call sum_load, the base load of every slot), so
the comparison with the agents isolates the value of tool use and step-by-step reasoning.

Design iteration 14 (19 Oct 2026): it answers with the agents' FinalSchedule (start times only; the cost estimate and
explanation of ScheduleOutput were never scored), the price and base-load table has one row per hour with its four
15-minute values (the same values, about 40 % fewer tokens), and the household text leaves out what does not apply to
a system without tools (tool names, fixed appliances, the windows already stated in the request).
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
from hems.agents.schemas import FinalSchedule, assignments_to_dict
from hems.agents.types import AgentRun
from hems.core.models import Scenario

# Only the structured answer (plus recovery nudges) is needed; no tool steps. 3 since 20 Oct 2026 (6 before): a model that
# writes its schedule as text and then sends empty replies reaches the nudge after fewer wasted calls.
RECURSION_LIMIT = 3


def scenario_message(scenario: Scenario) -> str:
    appliances = "\n".join(
        f"- {a.id}: {a.kind}, cycle {a.duration_slots * 15} min, energy {a.energy_kwh:.2f} kWh, peak {a.peak_kw:.2f} kW"
        for a in scenario.appliances
    )
    rows = []
    for hour in range(len(scenario.price_eur_per_kwh) // 4):
        slots = range(4 * hour, 4 * hour + 4)
        prices = " ".join(f"{scenario.price_eur_per_kwh[t] * 100:.2f}" for t in slots)
        bases = " ".join(f"{scenario.base_load_kw[t]:.2f}" for t in slots)
        rows.append(f"{hour:02d} | {prices} | {bases}")
    return (
        f"{scenario.user_request}\n\n"
        f"Household peak load limit: {scenario.peak_limit_kw:.2f} kW for the total load (base load plus the appliances).\n"
        f"Appliances:\n{appliances}\n\n"
        "Price (consumer price, c/kWh) and measured base load (kW), one row per hour; the four values of each are the "
        "15-minute slots starting at :00, :15, :30 and :45:\n"
        "hour | price :00 :15 :30 :45 | base load :00 :15 :30 :45\n" + "\n".join(rows)
    )


def run_oneshot(scenario: Scenario, model: BaseChatModel, config: dict[str, Any] | None = None) -> AgentRun:
    agent = create_agent(
        model, tools=[], system_prompt=prompts.ONESHOT, response_format=ToolStrategy(FinalSchedule),
        checkpointer=InMemorySaver(), name="oneshot",
    )  # fmt: skip
    try:
        result, recoveries = invoke_with_recovery(agent, scenario_message(scenario), "FinalSchedule", config or {}, RECURSION_LIMIT)
    except GraphRecursionError:
        return AgentRun(assignments=None, errors=["oneshot: step limit reached"], recoveries=MAX_RECOVERIES)
    except Exception as exc:  # provider errors propagate; persistent model-output failures = failed run
        if (reason := model_output_failure(exc)) is None:
            raise
        return AgentRun(assignments=None, errors=[f"oneshot: {reason}"], recoveries=MAX_RECOVERIES)
    output: FinalSchedule | None = result.get("structured_response")
    if output is None:
        return AgentRun(assignments=None, errors=["oneshot: no structured schedule returned"], recoveries=recoveries)
    return AgentRun(assignments=assignments_to_dict(output.assignments), recoveries=recoveries)
