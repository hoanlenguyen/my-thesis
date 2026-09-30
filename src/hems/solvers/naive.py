"""Reference schedules that need no reasoning."""

from __future__ import annotations

from hems.core.evaluate import PEAK_TOLERANCE_KW, appliance_cost, evaluate, total_load
from hems.core.models import Scenario, Schedule


def naive_schedule(scenario: Scenario) -> Schedule:
    """No scheduling: every appliance starts at the user's default time."""
    return {a.id: a.default_start_slot for a in scenario.appliances}


def greedy_schedule(scenario: Scenario) -> Schedule:
    """Each appliance at its individually cheapest start, ignoring the peak limit."""
    return {a.id: min(a.valid_starts(), key=lambda s: appliance_cost(scenario, a, s)) for a in scenario.appliances}


def smart_timer_schedule(scenario: Scenario) -> Schedule:
    """Rule-based "smart timer", as in commercial smart plugs and home energy apps.

    Appliances are placed one at a time, the most energy-intensive first; each takes its cheapest
    start at which the load (base load plus the appliances already placed) stays within the peak
    limit. If no such start exists, it takes its cheapest start and the schedule is infeasible.
    No search over combinations: the result can miss the optimum when moving an earlier appliance
    would have been cheaper.
    """
    limit = scenario.peak_limit_kw + PEAK_TOLERANCE_KW
    schedule: Schedule = {}
    for a in sorted(scenario.appliances, key=lambda a: (-a.energy_kwh, a.id)):
        load = total_load(scenario, schedule)
        by_cost = sorted(a.valid_starts(), key=lambda s: appliance_cost(scenario, a, s))
        fits = [s for s in by_cost if all(load[s + i] + p <= limit for i, p in enumerate(a.profile_kw))]
        schedule[a.id] = (fits or by_cost)[0]
    return schedule


def has_coordination_conflict(scenario: Scenario) -> bool:
    """True when independently optimal starts overload the household.

    These are the scenarios where multi-appliance coordination is actually
    required; the conflict resolution rate (SQ1) is computed over them.
    """
    return not evaluate(scenario, greedy_schedule(scenario)).feasible
