"""Turn results/runs.jsonl into the metrics of Chapter 5.

Scoring conventions (state these in Chapter 3):
* An infeasible agent schedule (window or peak violation, or no schedule) is
  scored at the naive-baseline cost: the household would fall back to running
  appliances at their default times. Feasibility is reported separately.
* optimality gap % = (scored cost - MILP cost) / MILP cost * 100.
* savings captured = (naive - scored) / (naive - MILP): the share of the
  achievable saving obtained; robust even where costs approach zero.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from hems.core.models import Scenario
from hems.solvers.naive import has_coordination_conflict

AGENT_SYSTEMS = ("single", "multi", "multi_v3", "multi_rag", "multi_rag_opt", "multi_lean")
BASELINE_SYSTEMS = ("timer", "oneshot", "emhass", "emhass_nominal", "cheapest_hours", "cheapest_hours_hourly", "cheapest_window", "emhass_rest", "emhass_rest_nominal")  # incl. real HEMS tools
SCORED_SYSTEMS = (*AGENT_SYSTEMS, *BASELINE_SYSTEMS)


def load_runs(paths: str | Path | list[str | Path]) -> pd.DataFrame:
    """Records from one or more run files; a key present in several files is kept once (first file wins)."""
    from hems.run import read_records  # tolerant of a line cut off by a hard shutdown

    paths = [paths] if isinstance(paths, (str, Path)) else paths
    runs = pd.DataFrame([r for p in paths for r in read_records(Path(p))])
    return runs.drop_duplicates("key").reset_index(drop=True) if not runs.empty else runs


def scored_runs(runs: pd.DataFrame) -> pd.DataFrame:
    """Agent runs joined with their scenario's MILP and naive references."""
    ref = runs[runs.system.isin(["milp", "naive"])].pivot_table(index="scenario_id", columns="system", values="cost_eur")
    ref.columns = [f"{c}_cost" for c in ref.columns]
    ref = ref.reset_index()
    ref.columns.name = None
    agents = runs[runs.system.isin(SCORED_SYSTEMS)].merge(ref, on="scenario_id", how="inner")
    agents["scored_cost"] = np.where(agents.feasible, agents.cost_eur, agents.naive_cost)
    agents["gap_pct"] = (agents.scored_cost - agents.milp_cost) / agents.milp_cost * 100
    # Primary metric from Amendment 2: saving against no scheduling, which needs no optimum as reference.
    agents["saving_eur"] = agents.naive_cost - agents.scored_cost
    agents["saving_pct"] = agents.saving_eur / agents.naive_cost * 100
    achievable = agents.naive_cost - agents.milp_cost
    agents["savings_captured"] = np.where(achievable > 1e-9, (agents.naive_cost - agents.scored_cost) / achievable, np.nan)
    return agents


def per_scenario(scored: pd.DataFrame) -> pd.DataFrame:
    """Mean over repeated runs: one row per (model, system, scenario) — the unit of the paired test."""
    return (
        scored.groupby(["model", "system", "scenario_id", "scenario_type"])
        .agg(
            gap_pct=("gap_pct", "mean"),
            saving_pct=("saving_pct", "mean"),
            saving_eur=("saving_eur", "mean"),
            savings_captured=("savings_captured", "mean"),
            feasible_rate=("feasible", "mean"),
            gap_sd=("gap_pct", "std"),
            latency_s=("latency_s", "mean"),
            tokens=("tokens_in", "mean"),
            tokens_out=("tokens_out", "mean"),
            cost_usd=("cost_usd", "mean"),
            tool_calls=("tool_calls", "mean"),
        )
        .reset_index()
        .assign(tokens_total=lambda df: df.tokens + df.tokens_out)
    )


def summary_by_type(scenario_means: pd.DataFrame) -> pd.DataFrame:
    table = scenario_means.pivot_table(index="scenario_type", columns=["model", "system"], values="gap_pct", aggfunc="mean")
    overall = scenario_means.pivot_table(columns=["model", "system"], values="gap_pct", aggfunc="mean")
    overall.index = ["All"]
    return pd.concat([table, overall])


def pooled_savings_captured(scored: pd.DataFrame) -> pd.DataFrame:
    """Share of the achievable saving captured, pooled over all runs of a (model, system).

    (sum naive - sum scored cost) / (sum naive - sum MILP). Preferred to the mean of the per-run
    ratio, which explodes on days where the naive schedule is already almost optimal (an achievable
    saving of a fraction of a cent turns a one-cent overshoot into -3000 %).
    """
    grouped = scored.groupby(["model", "system"])
    return grouped.apply(
        lambda g: pd.Series({
            "savings_captured_pooled": (g.naive_cost.sum() - g.scored_cost.sum()) / (g.naive_cost.sum() - g.milp_cost.sum()),
            "saving_pct_pooled": (g.naive_cost.sum() - g.scored_cost.sum()) / g.naive_cost.sum() * 100,
            "saving_eur_total": g.naive_cost.sum() - g.scored_cost.sum(),
            "runs": len(g),
        }),
        include_groups=False,
    ).reset_index()  # fmt: skip


def feasible_only_gaps(scored: pd.DataFrame) -> pd.DataFrame:
    """Robustness check of the naive-cost convention: gaps over feasible runs only, next to the scored gaps."""
    return (
        scored.groupby(["model", "system"])
        .apply(
            lambda g: pd.Series({
                "feasible_runs": int(g.feasible.sum()),
                "runs": len(g),
                "gap_scored_mean": g.gap_pct.mean(),
                "gap_feasible_mean": g[g.feasible].gap_pct.mean(),
                "gap_feasible_median": g[g.feasible].gap_pct.median(),
            }),
            include_groups=False,
        )
        .reset_index()
    )  # fmt: skip


def efficiency(scored: pd.DataFrame) -> pd.DataFrame:
    return (
        scored.groupby(["model", "system"])
        .agg(
            feasible_rate=("feasible", "mean"),
            mean_gap_pct=("gap_pct", "mean"),
            median_latency_s=("latency_s", "median"),
            mean_tokens=("tokens_in", "mean"),
            mean_tokens_out=("tokens_out", "mean"),
            mean_cost_usd=("cost_usd", "mean"),
            total_cost_usd=("cost_usd", "sum"),
            mean_tool_calls=("tool_calls", "mean"),
        )
        .reset_index()
    )


def conflict_resolution_rate(scored: pd.DataFrame, scenarios: dict[str, Scenario]) -> pd.DataFrame:
    """SQ1: share of runs ending conflict-free (feasible) among scenarios that require coordination."""
    conflict_ids = {sid for sid, sc in scenarios.items() if has_coordination_conflict(sc)}
    subset = scored[scored.scenario_id.isin(conflict_ids)]
    rate = subset.groupby(["model", "system"]).feasible.agg(["mean", "count"]).reset_index()
    rate.columns = ["model", "system", "resolution_rate", "runs"]
    rate["conflict_scenarios"] = len(conflict_ids)
    return rate


def per_appliance(scored: pd.DataFrame, naive: pd.DataFrame, scenarios: dict[str, Scenario]) -> pd.DataFrame:
    """SQ2: saving per appliance cycle vs the naive start, with the cycle's characteristics."""
    naive_costs = naive.set_index("scenario_id").per_appliance_cost_eur.to_dict()
    rows = []
    for rec in scored[scored.feasible].itertuples():
        scenario = scenarios[rec.scenario_id]
        for a in scenario.appliances:
            cost = rec.per_appliance_cost_eur.get(a.id)
            if cost is None:
                continue
            rows.append(
                {
                    "model": rec.model,
                    "system": rec.system,
                    "scenario_id": rec.scenario_id,
                    "scenario_type": rec.scenario_type,
                    "kind": a.kind,
                    "saving_eur": naive_costs[rec.scenario_id][a.id] - cost,
                    "duration_min": a.duration_slots * 15,
                    "peak_kw": a.peak_kw,
                    "energy_kwh": a.energy_kwh,
                    "window_h": (a.deadline_slot - a.earliest_slot) / 4,
                }
            )
    return pd.DataFrame(rows)
