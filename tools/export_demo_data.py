"""Export recorded benchmark results as static JSON for the demo app (demo/public/data).

The demo only replays what the evaluation recorded; it runs no system itself.

    uv run python tools/export_demo_data.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from hems.analysis import metrics
from hems.core.models import load_scenarios

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo" / "public" / "data"

BENCHMARKS = {
    "main": {
        "label": "Main benchmark (hourly prices, 2022-2026)",
        "scenarios": "data/scenarios",
        "runs": ["results/runs.jsonl", "results/baselines.jsonl", "results/tools/scenarios.jsonl"],
    },
    "q": {
        "label": "Held-out benchmark (15-minute prices, Oct 2025 - Sep 2026)",
        "scenarios": "data/scenarios_15min",
        "runs": ["results/confirmation.jsonl", "results/tools/scenarios_15min.jsonl"],
    },
}
SYSTEMS = {  # order = display order
    "multi": "Multi-agent pipeline",
    "single": "Single agent",
    "timer": "Smart timer",
    "emhass_rest": "EMHASS, profiles",
    "emhass_rest_nominal": "EMHASS, nominal power",
    "cheapest_hours": "Cheapest hours (HA)",
    "oneshot": "LLM without tools",
    "milp": "MILP optimum",
    "naive": "No scheduling",
}
MODELS = ("-", "gpt-4o-mini", "gpt-oss-20b")


def _num(x, nd=4):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def export(key: str, spec: dict) -> dict:
    scenarios = {s.id: s for s in load_scenarios(ROOT / spec["scenarios"])}
    runs = metrics.load_runs([ROOT / p for p in spec["runs"]])
    runs = runs[runs.system.isin(SYSTEMS) & runs.model.isin(MODELS)]
    scored = metrics.scored_runs(runs)
    ref = runs[runs.system.isin(["milp", "naive"])].pivot_table(index="scenario_id", columns="system", values="cost_eur")

    summary = []
    for (model, system), g in scored.groupby(["model", "system"]):
        pooled = (g.naive_cost.sum() - g.scored_cost.sum()) / (g.naive_cost.sum() - g.milp_cost.sum())
        summary.append({
            "system": system, "label": SYSTEMS[system], "model": model, "runs": len(g),
            "feasible": int(g.feasible.sum()), "gapMean": _num(g.gap_pct.mean(), 3),
            "savingsCaptured": _num(pooled, 4), "latencyMean": _num(g.latency_s.mean(), 2),
            "usdPerRun": _num(g.cost_usd.mean(), 6), "tokensIn": _num(g.tokens_in.mean(), 0),
        })  # fmt: skip
    summary.sort(key=lambda r: (list(SYSTEMS).index(r["system"]), r["model"]))

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
        house = int(m.group(1)) if (m := re.search(r"house (\d+)", sc.notes, re.I)) else None
        detail = {
            "id": sid, "type": sc.type, "date": sc.date, "peakLimitKw": sc.peak_limit_kw, "house": house,
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
            "naiveCost": round(naive, 4), "milpCost": round(milp, 4),
            "results": results,
        }  # fmt: skip
        (folder / f"{sid}.json").write_text(json.dumps(detail), encoding="utf-8")
        index.append({"id": sid, "type": sc.type, "date": sc.date, "appliances": len(sc.appliances), "house": house,
                      "naiveCost": round(naive, 4), "milpCost": round(milp, 4),
                      "achievableSaving": round(naive - milp, 4)})  # fmt: skip
    return {"id": key, "label": spec["label"], "summary": summary, "scenarios": index}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    benchmarks = [export(k, v) for k, v in BENCHMARKS.items()]
    (OUT / "benchmarks.json").write_text(json.dumps(benchmarks, indent=1), encoding="utf-8")
    for b in benchmarks:
        print(f"{b['id']}: {len(b['scenarios'])} scenarios, {len(b['summary'])} system/model rows")


if __name__ == "__main__":
    main()
