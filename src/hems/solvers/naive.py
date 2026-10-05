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


def cheapest_hours_schedule(scenario: Scenario, hours: int | None = None, resolution: str = "15min") -> Schedule:
    """Home Assistant "Nordpool cheapest hours actions" blueprint (kullarkert), applied to cycle appliances.

    The blueprint sorts the prices inside a user-set time window (inclusive) and takes as threshold
    the price at index cheap_hours * factor (factor 4 for 96 fifteen-minute prices, 1 for 24 hourly
    prices); the device is switched on whenever the current price is at or below it. For a cycle
    appliance the household sets the window to [ready time, latest start that still meets the
    deadline] and cheap_hours to the cycle length rounded up to whole hours (`hours` overrides it),
    and the trigger starts the cycle, which then runs to the end. Each appliance is handled by its
    own automation: there is no peak coordination.

    resolution="hourly" models a household whose price sensor gives 24 hourly prices (the mean of
    the four quarter-hour prices): the cycle can then only start on a full hour. If no full hour
    lies in the window, the fifteen-minute rule is used for that appliance.
    """
    if resolution not in ("15min", "hourly"):
        raise ValueError(f"unknown resolution {resolution!r}")
    prices = scenario.price_eur_per_kwh
    schedule: Schedule = {}
    for a in scenario.appliances:
        cheap_hours = hours if hours is not None else -(-a.duration_slots // 4)  # ceil to whole hours
        window = list(a.valid_starts())
        if resolution == "hourly" and (starts := [s for s in window if s % 4 == 0]):
            hourly = {s: sum(prices[s : s + 4]) / 4 for s in starts}
            ranked = sorted(hourly.values())
            threshold = ranked[min(cheap_hours, len(ranked) - 1)]
            schedule[a.id] = next(s for s in starts if hourly[s] <= threshold)
            continue
        ranked = sorted(prices[s] for s in window)
        threshold = ranked[min(cheap_hours * 4, len(ranked) - 1)]
        schedule[a.id] = next(s for s in window if prices[s] <= threshold)
    return schedule


def cheapest_window_schedule(scenario: Scenario) -> Schedule:
    """Lowest-average consecutive window: Home Assistant Nordpool Planner (dala318/nordpool_planner, static
    planner) and the sequential cheapest-hours mode of shelly-porssisahko (jisotalo).

    Both tools slide a block of `duration` whole hours over hourly prices between a start and an end hour
    and switch the device on for the block with the lowest average price. For a cycle appliance the
    household sets the block to the cycle length rounded up to whole hours and the search span to
    [ready time, deadline]; the cycle starts at the first hour of the block. Blocks must lie on full hours
    within the window, so a cycle shorter than its rounded duration still finishes in time. The price is
    a flat hourly average, not weighted by the cycle's power profile. Each appliance has its own planner:
    there is no peak coordination. If no full-hour block fits, the appliance starts when ready.
    """
    prices = scenario.price_eur_per_kwh
    schedule: Schedule = {}
    for a in scenario.appliances:
        block = -(-a.duration_slots // 4) * 4  # whole hours, in slots
        starts = [s for s in a.valid_starts() if s % 4 == 0 and s + block <= a.deadline_slot]
        if not starts:
            schedule[a.id] = a.default_start_slot
            continue
        schedule[a.id] = min(starts, key=lambda s: (sum(prices[s : s + block]), s))
    return schedule


def has_coordination_conflict(scenario: Scenario) -> bool:
    """True when independently optimal starts overload the household.

    These are the scenarios where multi-appliance coordination is actually
    required; the conflict resolution rate (SQ1) is computed over them.
    """
    return not evaluate(scenario, greedy_schedule(scenario)).feasible
