"""Registry of every scheduling system compared in the thesis.

Each system turns a Scenario into a schedule; all are scored by the same core.evaluate.evaluate.
  reference - deterministic rules and the MILP optimum, computed in this code base
  external  - real home energy management tools run outside it (EMHASS, in its own environment)
  llm       - systems that call a language model (the agent designs and the no-tools baseline)
Deterministic systems (reference, external) run once per scenario with model "-".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Literal

from hems.agents.harness_agent import run_harness_agent
from hems.agents.multi_agent import run_multi_agent
from hems.agents.oneshot import run_oneshot
from hems.agents.single_agent import run_single_agent
from hems.agents.types import AgentRun
from hems.core.models import Scenario, Schedule
from hems.solvers.emhass import emhass_schedule
from hems.solvers.milp import solve_milp
from hems.solvers.naive import cheapest_hours_schedule, cheapest_window_schedule, naive_schedule, smart_timer_schedule

Kind = Literal["reference", "external", "llm"]


@dataclass
class Planned:
    """Output of a deterministic system."""

    schedule: Schedule
    problems: list[str] = field(default_factory=list)  # make the run infeasible (e.g. solver not optimal)
    errors: list[str] = field(default_factory=list)  # reported, like agent errors
    latency_s: float | None = None  # time reported by the tool itself; None = measured wall clock
    info: dict[str, Any] = field(default_factory=dict)  # extra record fields (e.g. tool version)


@dataclass(frozen=True)
class System:
    name: str
    kind: Kind
    description: str
    plan: Callable[[Scenario], Planned] | None = None  # reference / external
    agent: Callable[[Scenario, Any, dict, bool], AgentRun] | None = None  # llm: (scenario, model, config, summarize)


def _milp(scenario: Scenario) -> Planned:
    result = solve_milp(scenario)
    return Planned(result.schedule, [] if result.status == "Optimal" else [f"MILP status {result.status}"])


def _rule(fn: Callable[[Scenario], Schedule]) -> Callable[[Scenario], Planned]:
    return lambda scenario: Planned(fn(scenario))


def _emhass(mode: str) -> Callable[[Scenario], Planned]:
    def plan(scenario: Scenario) -> Planned:
        r = emhass_schedule(scenario, mode)
        return Planned(r.schedule, errors=r.errors, latency_s=r.solve_s, info=r.info)

    return plan


def _retriever() -> Callable[[Scenario], str]:
    from hems.rag import default_retriever  # loads data/rag/cases.jsonl on first use only

    return default_retriever()


SYSTEMS: dict[str, System] = {
    s.name: s
    for s in (
        System("milp", "reference", "MILP optimum (PuLP/CBC)", plan=_milp),
        System("naive", "reference", "every appliance starts when ready", plan=_rule(naive_schedule)),
        System("timer", "reference", "smart timer: own peak-aware heuristic written for this study (not a deployed product)", plan=_rule(smart_timer_schedule)),
        System("cheapest_hours", "reference", "HA Nord Pool cheapest-hours blueprint, 15-min prices",
               plan=_rule(cheapest_hours_schedule)),  # fmt: skip
        System("cheapest_hours_hourly", "reference",
               "HA cheapest-hours blueprint with hourly prices",
               plan=_rule(partial(cheapest_hours_schedule, resolution="hourly"))),  # fmt: skip
        System("cheapest_window", "reference",
               "lowest-average hour block: HA Nordpool Planner",
               plan=_rule(cheapest_window_schedule)),  # fmt: skip
        System("emhass", "external", "EMHASS with measured power profiles", plan=_emhass("profile")),
        System("emhass_nominal", "external", "EMHASS with constant nominal power", plan=_emhass("nominal")),
        System("single", "llm", "single ReAct agent, all tools",
               agent=lambda sc, model, config, summarize: run_single_agent(sc, model, config)),  # fmt: skip
        # The Multi-Agent Pipeline: two agents (Orchestrator, Scheduler) and two deterministic steps. The four-agent
        # designs evaluated earlier ("multi", "multi_v3", "multi_rag", "multi_rag_opt", "multi_lean") were removed on
        # 16 October 2026; their recorded runs stay in results/ and are still read by the analysis.
        System("multi_duo", "llm",
               "Multi-Agent Pipeline: Orchestrator and Scheduler; profiling and verification without a model (design iteration 10)",
               agent=lambda sc, model, config, summarize: run_multi_agent(sc, lambda _role: model, config, summarize=summarize, retriever=_retriever())),  # fmt: skip
        System("multi_duo_thoughts", "llm",
               "Multi-Agent Pipeline with an explicit Thought in every tool call (design iteration 11)",
               agent=lambda sc, model, config, summarize: run_multi_agent(sc, lambda _role: model, config, summarize=summarize, retriever=_retriever(), thoughts=True)),  # fmt: skip
        # One agent inside the same harness (same tools, context, checks; exploratory, October 2026)
        System("single_harness", "llm",
               "One agent in the harness: the Scheduler agent's tools, the same profiling and verification, writes its own message",
               agent=lambda sc, model, config, summarize: run_harness_agent(sc, model, config, summarize=summarize, retriever=_retriever())),  # fmt: skip
        System("single_harness_thoughts", "llm",
               "One agent in the harness with an explicit Thought in every tool call",
               agent=lambda sc, model, config, summarize: run_harness_agent(sc, model, config, summarize=summarize, retriever=_retriever(), thoughts=True)),  # fmt: skip
        System("oneshot", "llm", "language model without tools",
               agent=lambda sc, model, config, summarize: run_oneshot(sc, model, config)),  # fmt: skip
    )
}


def names(*kinds: Kind) -> tuple[str, ...]:
    return tuple(n for n, s in SYSTEMS.items() if s.kind in kinds)
