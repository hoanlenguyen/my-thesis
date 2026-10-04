"""Schedule benchmark scenarios with EMHASS running as a service (Docker / Home Assistant add-on), via REST.

This is the documented way a household uses EMHASS: each scenario is sent as runtime parameters to
POST /action/dayahead-optim, and the plan is read back from GET /api/v1/plan. Unlike
tools/emhass_adapter.py (direct call of the optimisation module with an exact MIP gap), the service
keeps its own configuration, so its solver settings are EMHASS's defaults. Only what describes the
household and the day is sent: 15-min time step, prices, base load as the load forecast, no PV, the
appliances as deferrable loads with their windows, and the peak limit as the maximum grid power.

Writes the same JSON as the adapter, so the results are scored with:
    uv run hems import-schedules results/tools/rest_scenarios_profile.json --system emhass_rest \
        --scenarios data/scenarios --out results/tools/scenarios.jsonl

    uv run python tools/emhass_rest.py data/scenarios results/tools/rest_scenarios_profile.json --mode profile
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

STEP_MIN = 15


def _call(url: str, body: dict | None = None, timeout: int = 300) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})  # fmt: skip
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def runtime_params(scenario: dict, mode: str) -> dict:
    apps = scenario["appliances"]
    k = len(apps)
    slots = len(scenario["price_eur_per_kwh"])
    if mode == "profile":  # measured cycle profile, run once; only the start is chosen
        nominal = [[round(p * 1000, 1) for p in a["profile_kw"]] for a in apps]
        semi, single = [False] * k, [False] * k
    else:  # the simple configuration: constant power (the cycle's peak), one uninterrupted block
        nominal = [round(max(a["profile_kw"]) * 1000, 1) for a in apps]
        semi, single = [True] * k, [True] * k
    return {
        "optimization_time_step": STEP_MIN,
        "load_cost_forecast": scenario["price_eur_per_kwh"],
        "prod_price_forecast": [0.0] * slots,
        "pv_power_forecast": [0.0] * slots,
        "load_power_forecast": [round(b * 1000, 1) for b in scenario["base_load_kw"]],
        "number_of_deferrable_loads": k,
        "nominal_power_of_deferrable_loads": nominal,
        "minimum_power_of_deferrable_loads": [0.0] * k,
        "operating_hours_of_each_deferrable_load": [len(a["profile_kw"]) * STEP_MIN / 60 for a in apps],
        "start_timesteps_of_each_deferrable_load": [a["earliest_slot"] for a in apps],
        "end_timesteps_of_each_deferrable_load": [a["deadline_slot"] for a in apps],
        "treat_deferrable_load_as_semi_cont": semi,
        "set_deferrable_load_single_constant": single,
        "set_deferrable_startup_penalty": [0.0] * k,
        "deferrable_load_max_cost": [0.0] * k,
        "set_deferrable_max_startups": [0] * k,
        "is_electric_load": [True] * k,
        "maximum_power_from_grid": scenario["peak_limit_kw"] * 1000,
    }


def starts_from_plan(plan: dict, scenario: dict) -> tuple[dict, str]:
    """First step with power > 0 for each deferrable load in the returned plan."""
    rows = plan.get("plan") or []
    if isinstance(rows, dict):  # column-oriented
        rows = [dict(zip(rows, values)) for values in zip(*rows.values())]
    starts = {}
    for i, a in enumerate(scenario["appliances"]):
        column = f"P_deferrable{i}"
        on = [t for t, row in enumerate(rows) if float(row.get(column) or 0) > 1e-3]
        starts[a["id"]] = on[0] if on else None
    status = str(plan.get("optim_status") or (rows[0].get("optim_status") if rows else plan.get("status", "")))
    if len(rows) != len(scenario["price_eur_per_kwh"]):  # the plan must cover the whole day, step for step
        status = f"plan has {len(rows)} steps, expected {len(scenario['price_eur_per_kwh'])}"
    return starts, status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenarios", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--mode", choices=["profile", "nominal"], default="profile")
    parser.add_argument("--url", default="http://localhost:5000")
    parser.add_argument("--only", nargs="*", help="scenario ids (default: all)")
    parser.add_argument("--show-plan", action="store_true", help="print the first returned plan (debugging)")
    args = parser.parse_args()

    version = _call(f"{args.url}/api/v1/last-run").get("emhass_version", "") or ""
    out = {"emhass_version": version or "service", "mode": args.mode, "via": f"REST {args.url}", "schedules": {}}
    if args.out.exists():  # resume
        out["schedules"] = json.loads(args.out.read_text(encoding="utf-8"))["schedules"]
    for path in sorted(args.scenarios.glob("*.json")):
        if path.name == "manifest.json":
            continue
        scenario = json.loads(path.read_text(encoding="utf-8"))
        if (args.only and scenario["id"] not in args.only) or scenario["id"] in out["schedules"]:
            continue
        started = time.perf_counter()
        _call(f"{args.url}/action/dayahead-optim", runtime_params(scenario, args.mode))
        plan = _call(f"{args.url}/api/v1/plan")
        elapsed = time.perf_counter() - started
        if args.show_plan:
            print(json.dumps(plan)[:3000])
        starts, status = starts_from_plan(plan, scenario)
        out["schedules"][scenario["id"]] = {"starts": starts, "status": status, "solve_s": round(elapsed, 3)}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(out, indent=1), encoding="utf-8")  # after every scenario
        print(scenario["id"], status, f"{elapsed:.1f}s", starts, flush=True)


if __name__ == "__main__":
    main()
