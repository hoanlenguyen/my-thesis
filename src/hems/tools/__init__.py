"""Deterministic scheduling tools, bound to one scenario.

Fairness rule: the single-agent baseline receives exactly the union of the
tools given to the three specialist agents. No tool solves the whole problem:
``find_cheapest_window`` looks at one appliance and ignores the peak limit, so
coordinating appliances is left to the agents under test.

Exception (design iteration 7, system "multi_rag_opt" only): ``optimize_schedule``
solves the whole problem with the MILP. In that arm the agents formulate the call,
check its result and explain it; the solver does the search.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

import numpy as np
from langchain_core.tools import BaseTool, tool

from hems.core.evaluate import appliance_cost, evaluate, total_load
from hems.core.models import Scenario, Schedule

# The extra kinds only occur in the demo, where the household gives each of them a time window.
SHIFTABLE_KINDS = {"washing_machine", "dishwasher", "tumble_dryer", "ev_charger", "sauna", "hot_tub", "electric_oven"}

PROFILER_TOOLS = ("read_household_data", "classify_appliance")
SCHEDULER_TOOLS = ("get_spot_prices", "calculate_schedule_cost", "find_cheapest_window")
RESOLVER_TOOLS = ("sum_load", "detect_conflicts", "adjust_schedule")
ALL_TOOLS = PROFILER_TOOLS + SCHEDULER_TOOLS + RESOLVER_TOOLS
OPTIMIZER_TOOLS = ("optimize_schedule",)  # not in ALL_TOOLS: only the optimiser arm receives it


def _ranges(scenario: Scenario, slots: list[int]) -> str:
    """[40, 41, 42, 50] -> "10:00-10:45, 12:30-12:45" (end = end of last slot)."""
    if not slots:
        return "none"
    parts, start, prev = [], slots[0], slots[0]
    for s in slots[1:] + [None]:
        if s is not None and s == prev + 1:
            prev = s
            continue
        parts.append(f"{scenario.slot_to_time(start)}-{scenario.boundary_to_time(prev + 1)}")
        if s is not None:
            start = prev = s
    return ", ".join(parts)


def _guard(fn: Callable[..., str]) -> Callable[..., str]:
    """Return errors to the agent as text instead of crashing the run."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return fn(*args, **kwargs)
        except (KeyError, ValueError, TypeError) as exc:
            return f"ERROR: {exc}"

    return wrapper


def build_tools(scenario: Scenario) -> dict[str, BaseTool]:
    sc = scenario

    def parse_schedule(schedule: dict[str, str]) -> Schedule:
        parsed: Schedule = {}
        for appliance_id, clock in schedule.items():
            sc.appliance(appliance_id)  # raises ValueError for unknown ids
            parsed[appliance_id] = sc.time_to_slot(clock)
        return parsed

    def describe_window(appliance_id: str) -> str:
        a = sc.appliance(appliance_id)
        if a.windows is not None:  # several allowed periods (demo only)
            periods = " or ".join(f"{sc.slot_to_time(s)}-{sc.boundary_to_time(e)}" for s, e in a.windows)
            return f"may run only within {periods}; the cycle must start and finish inside one of these periods"
        return f"ready from {sc.slot_to_time(a.earliest_slot)}, must finish by {sc.boundary_to_time(a.deadline_slot)}"

    # ── Appliance Profiler ───────────────────────────────────────────────────
    @_guard
    def read_household_data() -> str:
        """Read the household's appliance inventory: power draw, cycle length and user time windows."""
        base = sc.base_load_kw
        lines = [
            f"Household peak load limit: {sc.peak_limit_kw:.2f} kW for the total load, i.e. the measured base load "
            f"plus the scheduled appliances.",
            f"Measured base load (all fixed appliances together): {min(base):.2f}-{max(base):.2f} kW over the day "
            f"(mean {sum(base) / len(base):.2f} kW); sum_load and detect_conflicts already include it.",
            "Fixed appliances below show their rated power when switched on; they do not run continuously and "
            "their actual use is already part of the measured base load.",
        ]
        for a in sc.appliances:
            lines.append(
                f"- {a.id}: kind={a.kind}, cycle {a.duration_slots * 15} min, energy {a.energy_kwh:.2f} kWh, "
                f"peak {a.peak_kw:.2f} kW, user window: {describe_window(a.id)}"
            )
        for f in sc.fixed_appliances:
            lines.append(f"- {f.id}: kind={f.kind}, rated power when on {f.typical_power_kw:.2f} kW, no user window")
        return "\n".join(lines)

    @_guard
    def classify_appliance(appliance_id: str) -> str:
        """Classify one appliance as flexible (shiftable in time) or fixed."""
        for f in sc.fixed_appliances:
            if f.id == appliance_id:
                return f"{appliance_id}: FIXED - {f.kind} runs on demand or continuously and cannot be shifted."
        a = sc.appliance(appliance_id)
        if a.kind in SHIFTABLE_KINDS:
            return (
                f"{appliance_id}: FLEXIBLE - {a.kind} runs a {a.duration_slots * 15}-min cycle that can start any "
                f"time in its window ({describe_window(appliance_id)})."
            )
        return f"{appliance_id}: FIXED - {a.kind} is not a shiftable cycle load."

    # ── Price-Aware Scheduler ────────────────────────────────────────────────
    @_guard
    def get_spot_prices(from_time: str = "", to_time: str = "") -> str:
        """Get the electricity price for every 15-min slot (consumer price in c/kWh, incl. taxes and transfer).

        Optionally restrict to from_time..to_time ("HH:MM", end exclusive)."""
        first = sc.time_to_slot(from_time) if from_time else 0
        last = sc.time_to_slot(to_time) if to_time else len(sc.price_eur_per_kwh)
        if last <= first:
            last = len(sc.price_eur_per_kwh)
        rows = [f"{sc.slot_to_time(t)} {sc.price_eur_per_kwh[t] * 100:.2f}" for t in range(first, last)]
        return "time c/kWh\n" + "\n".join(rows)

    @_guard
    def calculate_schedule_cost(appliance_id: str, start_time: str) -> str:
        """Cost of running one appliance cycle starting at start_time ("HH:MM")."""
        a = sc.appliance(appliance_id)
        start = sc.time_to_slot(start_time)
        cost = appliance_cost(sc, a, start)
        ok = start in a.valid_starts()
        return (
            f"{appliance_id} {sc.slot_to_time(start)}-{sc.boundary_to_time(start + a.duration_slots)}: "
            f"cost EUR {cost:.4f}; {'within' if ok else 'OUTSIDE'} user window ({describe_window(appliance_id)})"
        )

    @_guard
    def find_cheapest_window(appliance_id: str, top_k: int = 3) -> str:
        """Cheapest start times for ONE appliance within its user window.

        Considers price only; ignores other appliances and the household peak limit."""
        a = sc.appliance(appliance_id)
        ranked = sorted(a.valid_starts(), key=lambda s: appliance_cost(sc, a, s))[: max(1, min(top_k, 10))]
        return "\n".join(
            f"{i}. start {sc.slot_to_time(s)} end {sc.boundary_to_time(s + a.duration_slots)} "
            f"cost EUR {appliance_cost(sc, a, s):.4f}"
            for i, s in enumerate(ranked, 1)
        )

    # ── Conflict Resolver ────────────────────────────────────────────────────
    @_guard
    def sum_load(schedule: dict[str, str]) -> str:
        """Total household load (base load + scheduled appliances) for a schedule {appliance_id: "HH:MM"}."""
        load = total_load(sc, parse_schedule(schedule))
        top = np.argsort(load)[::-1][:5]
        peaks = ", ".join(f"{sc.slot_to_time(int(t))} {load[t]:.2f} kW" for t in top)
        return f"Max load {load.max():.2f} kW (limit {sc.peak_limit_kw:.2f} kW). Highest slots: {peaks}"

    @_guard
    def detect_conflicts(schedule: dict[str, str]) -> str:
        """Find time slots where the schedule {appliance_id: "HH:MM"} exceeds the household peak limit."""
        parsed = parse_schedule(schedule)
        load = total_load(sc, parsed)
        over = [int(t) for t in np.flatnonzero(load > sc.peak_limit_kw + 1e-6)]
        if not over:
            return f"No conflicts: max load {load.max():.2f} kW <= limit {sc.peak_limit_kw:.2f} kW."
        running = sorted(
            {
                a.id
                for a in sc.appliances
                if a.id in parsed and any(parsed[a.id] <= t < parsed[a.id] + a.duration_slots for t in over)
            }
        )
        return (
            f"CONFLICT: load exceeds {sc.peak_limit_kw:.2f} kW during {_ranges(sc, over)} "
            f"(max {load.max():.2f} kW). Appliances running then: {', '.join(running)}."
        )

    @_guard
    def adjust_schedule(schedule: dict[str, str], appliance_id: str, new_start_time: str = "") -> str:
        """Move ONE appliance and report the cost change and remaining conflicts.

        With new_start_time "HH:MM" the appliance is moved there. Leave new_start_time empty to move it
        to its cheapest start within its window at which it causes no overload, with all other
        appliances where they are (alternatives are listed)."""
        parsed = parse_schedule(schedule)
        a = sc.appliance(appliance_id)
        before = evaluate(sc, parsed)
        alternatives = ""
        if new_start_time:
            parsed[appliance_id] = sc.time_to_slot(new_start_time)
        else:
            # A start is free if the load stays within the limit while THIS appliance runs; overloads
            # among the other (not yet moved) appliances are left for their own moves.
            others = total_load(sc, {k: v for k, v in parsed.items() if k != appliance_id})
            limit = sc.peak_limit_kw + 1e-6
            free = sorted(
                (
                    s
                    for s in a.valid_starts()
                    if all(others[s + i] + p <= limit for i, p in enumerate(a.profile_kw))
                ),
                key=lambda s: appliance_cost(sc, a, s),
            )
            if not free:
                return (
                    f"No start time for {appliance_id} within its window keeps the load under the limit while the other "
                    f"appliances stay fixed. Move another appliance first. Schedule unchanged: {schedule}"
                )
            parsed[appliance_id] = free[0]
            alternatives = "\nOther conflict-free options: " + (
                ", ".join(f"{sc.slot_to_time(s)} (EUR {appliance_cost(sc, a, s):.4f})" for s in free[1:4]) or "none"
            )
        after = evaluate(sc, parsed)
        window_ok = parsed[appliance_id] in a.valid_starts()
        new = {k: sc.slot_to_time(v) for k, v in parsed.items()}
        status = "no conflicts" if not after.overloaded_slots else f"still overloaded during {_ranges(sc, after.overloaded_slots)}"
        return (
            f"Adjusted schedule: {new}\n"
            f"Cost EUR {after.cost_eur:.4f} (change {after.cost_eur - before.cost_eur:+.4f}); "
            f"{appliance_id} {'within' if window_ok else 'OUTSIDE'} its window; {status}.{alternatives}"
        )

    # ── Optimiser (multi_rag_opt only) ───────────────────────────────────────
    @_guard
    def optimize_schedule(appliance_ids: list[str]) -> str:
        """Solve the scheduling problem exactly for the given appliances with an optimisation solver (MILP).

        Respects every user window and the household peak limit (with the base load) and minimises the
        total cost. Returns the start time per appliance, the cost and the maximum load."""
        from hems.solvers.milp import solve_milp

        wanted = [sc.appliance(i) for i in dict.fromkeys(appliance_ids)]  # raises ValueError for unknown ids
        if not wanted:
            return "ERROR: give at least one appliance id"
        result = solve_milp(sc.model_copy(update={"appliances": wanted}))
        if result.status != "Optimal":
            return f"Solver status {result.status}: no schedule within the windows and the peak limit was found."
        plan = {k: sc.slot_to_time(v) for k, v in result.schedule.items()}
        after = evaluate(sc, result.schedule)
        return (
            f"Optimal schedule: {plan}\nTotal cost EUR {after.cost_eur:.4f}; max load {total_load(sc, result.schedule).max():.2f} kW "
            f"(limit {sc.peak_limit_kw:.2f} kW)."
        )

    fns = [
        read_household_data,
        classify_appliance,
        get_spot_prices,
        calculate_schedule_cost,
        find_cheapest_window,
        sum_load,
        detect_conflicts,
        adjust_schedule,
        optimize_schedule,
    ]
    return {fn.__name__: tool(fn) for fn in fns}


def select(tools: dict[str, BaseTool], names: tuple[str, ...]) -> list[BaseTool]:
    return [tools[n] for n in names]
