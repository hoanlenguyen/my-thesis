"""MILP ground truth (PuLP + CBC).

Binary x[a, s] = 1 iff appliance a starts in slot s. Choosing a start slot
(rather than per-slot on/off) makes every cycle non-interruptible by
construction. Constraints: one start per appliance within its window, and
total load <= peak limit in every slot. Objective: minimise consumer cost.
"""

from __future__ import annotations

from dataclasses import dataclass

import pulp

from hems.core.evaluate import appliance_cost
from hems.core.models import SLOTS_PER_DAY, Scenario, Schedule


@dataclass
class MilpResult:
    status: str
    schedule: Schedule
    objective_eur: float | None


def solve_milp(scenario: Scenario, time_limit_s: int = 60) -> MilpResult:
    prob = pulp.LpProblem(f"hems_{scenario.id}", pulp.LpMinimize)

    x: dict[tuple[str, int], pulp.LpVariable] = {
        (a.id, s): prob.add_variable(f"x_{i}_{s}", cat="Binary")
        for i, a in enumerate(scenario.appliances)
        for s in a.valid_starts()
    }

    prob += pulp.lpSum(appliance_cost(scenario, a, s) * x[a.id, s] for a in scenario.appliances for s in a.valid_starts())

    for a in scenario.appliances:
        prob += pulp.lpSum(x[a.id, s] for s in a.valid_starts()) == 1, f"one_start_{a.id}"

    for t in range(SLOTS_PER_DAY):
        terms = [
            a.profile_kw[t - s] * x[a.id, s]
            for a in scenario.appliances
            for s in a.valid_starts()
            if 0 <= t - s < a.duration_slots
        ]
        if terms:
            prob += pulp.lpSum(terms) <= scenario.peak_limit_kw - scenario.base_load_kw[t], f"peak_{t}"

    prob.solve(pulp.COIN_CMD(msg=False, timeLimit=time_limit_s))
    status = pulp.LpStatus[prob.status]
    if status != "Optimal":
        return MilpResult(status=status, schedule={}, objective_eur=None)

    schedule = {a.id: next(s for s in a.valid_starts() if x[a.id, s].value() > 0.5) for a in scenario.appliances}
    return MilpResult(status=status, schedule=schedule, objective_eur=float(pulp.value(prob.objective)))
