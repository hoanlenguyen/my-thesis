"""The agent harness: the deterministic code around the language model agents, shared by every agent design.

It prepares the agent's context (``profiles``), runs a ReAct agent with recovery (``run_react``), checks every
schedule against the household data (``Checker``), places an appliance the agent left out (``Checker.place_missing``)
and states the figures of the final schedule for the household message (``cost_facts``). The two-agent pipeline
(``multi_agent``) and the single agent (``harness_agent``) use exactly this code, so they differ only in how the
language model work is split.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel

from hems.agents.errors import MAX_RECOVERIES, invoke_with_recovery, model_output_failure
from hems.agents.schemas import ApplianceProfile, ProfileOutput
from hems.core.evaluate import PEAK_TOLERANCE_KW, appliance_cost, total_load
from hems.core.models import SLOT_MINUTES, FlexibleAppliance, Scenario, Schedule
from hems.tools import SHIFTABLE_KINDS

MAX_ROUNDS = 2  # verification rounds: a problem found in the first round is sent back to the agent once


# ── Context ──────────────────────────────────────────────────────────────────
def profiles(scenario: Scenario) -> ProfileOutput:
    """The appliance profiles straight from the household data, without a language model."""
    return ProfileOutput(appliances=[
        ApplianceProfile(
            appliance_id=a.id, kind=a.kind, flexible=a.kind in SHIFTABLE_KINDS, peak_kw=round(a.peak_kw, 2),
            duration_minutes=a.duration_slots * SLOT_MINUTES, earliest_time=scenario.slot_to_time(a.earliest_slot),
            deadline_time=scenario.boundary_to_time(a.deadline_slot),
            periods=[f"{scenario.slot_to_time(s)}-{scenario.boundary_to_time(e)}" for s, e in a.window_periods()]
            if len(a.window_periods()) > 1 else None,
        )
        for a in scenario.appliances
    ])  # fmt: skip


def profile_text(profile: ProfileOutput) -> str:
    """The flexible appliances' profiles as the agent reads them (``periods`` only where there are several)."""
    flexible = [p.model_dump(exclude_none=True) for p in profile.appliances if p.flexible]
    return f"Appliance profiles:\n{json.dumps(flexible, indent=1)}"


# ── Running an agent ─────────────────────────────────────────────────────────
@dataclass
class ReactResult:
    output: BaseModel | None
    tool_calls: int
    errors: list[str]
    recoveries: int
    messages: list[BaseMessage] = field(default_factory=list)  # the whole conversation, to continue it later


def run_react(
    model: BaseChatModel, tools: list, system_prompt: str, schema: type[BaseModel], message: str | list[BaseMessage],
    name: str, limit: int, config: dict[str, Any] | None,
) -> ReactResult:  # fmt: skip
    """One ReAct agent until it returns ``schema``; ``message`` may be a conversation to continue."""
    agent = create_agent(
        model, tools=tools, system_prompt=system_prompt, response_format=ToolStrategy(schema),
        checkpointer=InMemorySaver(),  # lets a rejected turn be retried from the last good state
        name=name,
    )  # fmt: skip
    try:
        result, recoveries = invoke_with_recovery(agent, message, schema.__name__, config or {}, limit)
    except GraphRecursionError:
        return ReactResult(None, 0, [f"{name}: step limit reached"], 0)
    except Exception as exc:  # provider errors propagate; persistent model-output failures = failed step
        if (reason := model_output_failure(exc)) is None:
            raise
        return ReactResult(None, 0, [f"{name}: {reason}"], MAX_RECOVERIES)
    given = 1 if isinstance(message, str) else len(message)
    messages = result["messages"]
    calls = sum(len(getattr(m, "tool_calls", []) or []) for m in messages[given:])
    output = result.get("structured_response")
    return ReactResult(output, calls, [] if output is not None else [f"{name}: no structured output"], recoveries, messages)


# ── Checking a schedule ──────────────────────────────────────────────────────
class Checker:
    """Deterministic checks of a schedule against the household data, as the tools see it."""

    def __init__(self, scenario: Scenario, tools: dict[str, Any]) -> None:
        self.scenario = scenario
        self.tools = tools
        self.plan_ids = [a.id for a in scenario.appliances]  # every cycle in the day's appliance plan

    def periods_text(self, appliance: FlexibleAppliance) -> str:
        """Allowed periods of an appliance with several of them (demo only), e.g. "06:00-09:00 or 18:00-22:00"."""
        sc = self.scenario
        return " or ".join(f"{sc.slot_to_time(s)}-{sc.boundary_to_time(e)}" for s, e in appliance.window_periods())

    def completeness(self, required: list[str], scheduled: dict[str, str]) -> str:
        missing = [i for i in required if i not in scheduled]
        return f"MISSING: no start time for {', '.join(missing)}." if missing else ""

    def windows(self, scheduled: dict[str, str]) -> str:
        """Start times outside the user window."""
        sc = self.scenario
        problems = []
        for appliance_id, clock in scheduled.items():
            try:
                appliance = sc.appliance(appliance_id)
                start = sc.time_to_slot(clock)
            except (ValueError, AttributeError):
                problems.append(f"{appliance_id} at {clock!r} is not a valid appliance and start time")
                continue
            if start not in appliance.valid_starts() and appliance.windows is not None:  # several periods (demo)
                problems.append(
                    f"{appliance_id} starts {sc.slot_to_time(start)} but must start and finish inside one of "
                    f"{self.periods_text(appliance)}"
                )
            elif start not in appliance.valid_starts():
                problems.append(
                    f"{appliance_id} starts {sc.slot_to_time(start)} but must start between "
                    f"{sc.slot_to_time(appliance.earliest_slot)} and {sc.slot_to_time(appliance.latest_start_slot)} "
                    f"to finish by {sc.boundary_to_time(appliance.deadline_slot)}"
                )
        return f"OUTSIDE WINDOW: {'; '.join(problems)}." if problems else ""

    def conflicts(self, schedule: dict[str, str]) -> list[str]:
        result = self.tools["detect_conflicts"].invoke({"schedule": schedule})
        return [result] if result.startswith(("CONFLICT", "ERROR")) else []

    def problems(self, schedule: dict[str, str], required: list[str]) -> list[str]:
        """Peak-load conflicts, completeness and user time windows of a schedule."""
        problems = self.conflicts(schedule)
        if missing := self.completeness(required, schedule):
            problems.append(missing)
        if outside := self.windows(schedule):
            problems.append(outside)
        return problems

    def verify(self, schedule: dict[str, str], required: list[str], rounds: int) -> tuple[dict[str, str], str, list[str]]:
        """Check a schedule in round ``rounds`` (1-based): (schedule, feedback, errors). In the last round, an
        appliance still missing is placed at its cheapest start that fits under the limit."""
        problems = self.problems(schedule, required)
        errors: list[str] = []
        if problems and rounds >= MAX_ROUNDS and any(i not in schedule for i in self.plan_ids):
            schedule, placed = self.place_missing(schedule)
            errors.append(f"verification: placed missing {', '.join(placed)} automatically")
            problems = self.conflicts(schedule)
            if outside := self.windows(schedule):
                problems.append(outside)
        return schedule, " ".join(problems), errors

    def place_missing(self, final: dict[str, str]) -> tuple[dict[str, str], list[str]]:
        """Give each appliance of the plan without a valid start its cheapest start that keeps the load within the
        limit, leaving the other start times unchanged (most energy first; cheapest start if none fits)."""
        sc = self.scenario
        schedule = {}
        for appliance_id, clock in final.items():
            try:
                if appliance_id in self.plan_ids:
                    schedule[appliance_id] = sc.time_to_slot(clock)
            except (ValueError, AttributeError):
                continue
        missing = sorted((a for a in sc.appliances if a.id not in schedule), key=lambda a: (-a.energy_kwh, a.id))
        limit = sc.peak_limit_kw + PEAK_TOLERANCE_KW
        for a in missing:
            load = total_load(sc, schedule)
            by_cost = sorted(a.valid_starts(), key=lambda s: appliance_cost(sc, a, s))
            fits = [s for s in by_cost if all(load[s + i] + p <= limit for i, p in enumerate(a.profile_kw))]
            schedule[a.id] = (fits or by_cost)[0]
        return {k: sc.slot_to_time(v) for k, v in schedule.items()}, [a.id for a in missing]


# ── Figures for the household message ───────────────────────────────────────
def cost_facts(scenario: Scenario, final: dict[str, str], summary_costs: Callable[[Schedule], str] | None = None) -> str:
    """Cost of the final schedule and of starting every appliance when ready. ``summary_costs`` (demo) replaces the
    lines with the cost the demo page shows (energy plus a fee for exceeding the limit)."""
    plan_ids = {a.id for a in scenario.appliances}
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
