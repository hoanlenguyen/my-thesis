"""Reference schedules that need no reasoning."""

from __future__ import annotations

from hems.core.evaluate import appliance_cost, evaluate
from hems.core.models import Scenario, Schedule


def naive_schedule(scenario: Scenario) -> Schedule:
    """No scheduling: every appliance starts at the user's default time."""
    return {a.id: a.default_start_slot for a in scenario.appliances}


def greedy_schedule(scenario: Scenario) -> Schedule:
    """Each appliance at its individually cheapest start, ignoring the peak limit."""
    return {a.id: min(a.valid_starts(), key=lambda s: appliance_cost(scenario, a, s)) for a in scenario.appliances}


def has_coordination_conflict(scenario: Scenario) -> bool:
    """True when independently optimal starts overload the household.

    These are the scenarios where multi-appliance coordination is actually
    required; the conflict resolution rate (SQ1) is computed over them.
    """
    return not evaluate(scenario, greedy_schedule(scenario)).feasible
