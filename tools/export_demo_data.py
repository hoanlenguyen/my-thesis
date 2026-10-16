"""Export recorded benchmark results as static JSON for the demo app (demo/public/data).

The demo only replays what the evaluation recorded; it runs no system itself.

    uv run python tools/export_demo_data.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from hems.analysis import metrics
from hems.core.models import load_scenarios

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo" / "public" / "data"

BENCHMARKS = {  # first = default view in the demo
    "q2": {
        "label": "Held-out benchmark Q2 (confirmatory)",
        "scenarios": "data/scenarios_q2",
        "runs": ["results/confirmation_q2.jsonl", "results/tools/scenarios_q2.jsonl"],
    },
    "v2": {
        "label": "Factorial benchmark (exploratory)",
        "scenarios": "data/scenarios_v2",
        "runs": ["results/main_v2.jsonl", "results/tools/scenarios_v2.jsonl"],
    },
    # Design iterations 9 and 10: the three pipelines interleaved in one campaign (same API conditions), with the
    # deterministic systems and EMHASS of the exploratory set as references. A dict entry keeps only the listed
    # systems of that file.
    "iter10": {
        "label": "Design iterations: 4 vs 2 agents (exploratory)",
        "scenarios": "data/scenarios_v2",
        "runs": ["results/iteration10.jsonl",
                 {"path": "results/main_v2.jsonl", "systems": ["milp", "naive", "timer", "cheapest_window",
                                                               "cheapest_hours", "cheapest_hours_hourly"]},
                 "results/tools/scenarios_v2.jsonl"],
    },
}
SYSTEMS = {  # order = display order; multi_rag and multi are design iterations (v2 only)
    "multi_rag_opt": "Multi-Agent Pipeline",
    "multi_duo": "Design iteration 10: two agents",
    "multi_lean": "Design iteration 9: lean, four agents",
    "multi_rag": "Design iteration: retrieval, no optimiser",
    "multi": "Design iteration: no retrieval, no optimiser",
    "oneshot": "LLM without tools",
    "emhass_rest": "EMHASS, profiles",
    "emhass_rest_nominal": "EMHASS, nominal power",
    "cheapest_window": "Cheapest window (HA Nordpool Planner)",
    "cheapest_hours": "Cheapest hours (HA blueprint, 15 min)",
    "cheapest_hours_hourly": "Cheapest hours (HA blueprint, hourly)",
    "timer": "Smart timer (own heuristic)",
    "milp": "MILP optimum",
    "naive": "No scheduling",
}
MODELS = ("-", "gpt-4o-mini")


def _factors(scenario_type: str) -> dict:
    """Scenario type "pattern-load-limit", e.g. "spike-heavy-strict"."""
    pattern, load, limit = scenario_type.split("-")
    return {"pattern": pattern, "load": load, "limit": limit}


def _num(x, nd=4):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def export(key: str, spec: dict) -> dict:
    scenarios = {s.id: s for s in load_scenarios(ROOT / spec["scenarios"])}
    parts = []
    for entry in spec["runs"]:  # a file, or {"path": file, "systems": [...]} to keep only some of its systems
        path, keep = (entry["path"], entry["systems"]) if isinstance(entry, dict) else (entry, None)
        part = metrics.load_runs([ROOT / path])
        parts.append(part[part.system.isin(keep)] if keep else part)
    runs = pd.concat(parts).drop_duplicates("key").reset_index(drop=True)  # first file wins, as in load_runs
    runs = runs[runs.system.isin(SYSTEMS) & runs.model.isin(MODELS)]
    scored = metrics.scored_runs(runs)
    ref = runs[runs.system.isin(["milp", "naive"])].pivot_table(index="scenario_id", columns="system", values="cost_eur")

    summary = []
    for (model, system), g in scored.groupby(["model", "system"]):
        pooled = (g.naive_cost.sum() - g.scored_cost.sum()) / (g.naive_cost.sum() - g.milp_cost.sum())
        summary.append({
            "system": system, "label": SYSTEMS[system], "model": model, "runs": len(g),
            "feasible": int(g.feasible.sum()), "gapMean": _num(g.gap_pct.mean(), 3),
            # pooled over runs, as in the thesis tables (metrics.pooled_savings_captured)
            "savingPct": _num((g.naive_cost.sum() - g.scored_cost.sum()) / g.naive_cost.sum() * 100, 3),
            "savingsCaptured": _num(pooled, 4), "latencyMean": _num(g.latency_s.mean(), 2),
            "usdPerRun": _num(g.cost_usd.mean(), 6), "tokensIn": _num(g.tokens_in.mean(), 0),
        })  # fmt: skip
    summary.sort(key=lambda r: (list(SYSTEMS).index(r["system"]), r["model"]))

    # Saving by condition (SQ2): pooled over the runs of the scenarios with that factor level,
    # each factor averaged over the other two, as in the thesis table tab:q2-conditions.
    factors = {sid: _factors(sc.type) for sid, sc in scenarios.items()}
    by_condition = []
    for factor in ("pattern", "load", "limit"):
        for level in sorted({f[factor] for f in factors.values()}):
            ids = [sid for sid, f in factors.items() if f[factor] == level]
            g_ref = ref.loc[ids]
            row = {"factor": factor, "level": level, "scenarios": len(ids),
                   "optimumPct": _num((g_ref.naive.sum() - g_ref.milp.sum()) / g_ref.naive.sum() * 100, 3),
                   "systems": {}}  # fmt: skip
            for (model, system), g in scored[scored.scenario_id.isin(ids)].groupby(["model", "system"]):
                row["systems"][f"{system}|{model}"] = {
                    "savingPct": _num((g.naive_cost.sum() - g.scored_cost.sum()) / g.naive_cost.sum() * 100, 3),
                    "validShare": _num(g.feasible.mean(), 3),
                }
            by_condition.append(row)

    folder = OUT / key
    folder.mkdir(parents=True, exist_ok=True)
    index = []
    for sid, sc in sorted(scenarios.items()):
        rows = runs[runs.scenario_id == sid]
        results = []
        for _, r in rows.iterrows():
            results.append({
                "system": r.system, "label": SYSTEMS[r.system], "model": r.model, "run": int(r.run),
                "starts": {k: int(v) for k, v in (r.schedule_slots or {}).items()},
                "costEur": _num(r.cost_eur), "feasible": bool(r.feasible),
                "violations": list(r.violations or []), "latencyS": _num(r.latency_s, 2),
                "tokensIn": int(r.tokens_in or 0), "tokensOut": int(r.tokens_out or 0),
                "usd": _num(r.cost_usd, 6), "message": r.explanation or "",
            })  # fmt: skip
        results.sort(key=lambda r: (list(SYSTEMS).index(r["system"]), r["model"], r["run"]))
        naive, milp = float(ref.loc[sid, "naive"]), float(ref.loc[sid, "milp"])
        naive_feasible = bool(rows[rows.system == "naive"].feasible.iloc[0])
        house = int(m.group(1)) if (m := re.search(r"house (\d+)", sc.notes, re.I)) else None
        detail = {
            "id": sid, "type": sc.type, **_factors(sc.type), "date": sc.date, "peakLimitKw": sc.peak_limit_kw, "house": house,
            "fixedAppliances": [{"id": f.id, "kind": f.kind, "ratedKw": f.typical_power_kw} for f in sc.fixed_appliances],
            "priceCents": [round(p * 100, 3) for p in sc.price_eur_per_kwh],
            "spotCents": [round(p * 100, 3) for p in sc.spot_eur_per_kwh],
            "baseLoadKw": [round(b, 3) for b in sc.base_load_kw],
            "appliances": [
                {"id": a.id, "kind": a.kind, "profileKw": [round(p, 3) for p in a.profile_kw],
                 "earliest": a.earliest_slot, "deadline": a.deadline_slot, "energyKwh": round(a.energy_kwh, 3)}
                for a in sc.appliances
            ],
            "plan": sc.user_request,
            "naiveCost": round(naive, 4), "milpCost": round(milp, 4), "naiveFeasible": naive_feasible,
            "results": results,
        }  # fmt: skip
        (folder / f"{sid}.json").write_text(json.dumps(detail), encoding="utf-8")
        index.append({"id": sid, "type": sc.type, **_factors(sc.type), "peakLimitKw": sc.peak_limit_kw,
                      "date": sc.date, "appliances": len(sc.appliances), "house": house,
                      "naiveCost": round(naive, 4), "milpCost": round(milp, 4), "naiveFeasible": naive_feasible,
                      "achievableSaving": round(naive - milp, 4)})  # fmt: skip
    return {"id": key, "label": spec["label"], "summary": summary, "byCondition": by_condition, "scenarios": index}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    benchmarks = [export(k, v) for k, v in BENCHMARKS.items()]
    (OUT / "benchmarks.json").write_text(json.dumps(benchmarks, indent=1), encoding="utf-8")
    for b in benchmarks:
        print(f"{b['id']}: {len(b['scenarios'])} scenarios, {len(b['summary'])} system/model rows")


if __name__ == "__main__":
    main()
