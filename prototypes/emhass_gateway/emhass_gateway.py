"""EMHASS as the gateway's optimiser: a demonstration of the two-device deployment (option B, exploratory, 17 Nov 2026).

The Household Assistant is the ReAct agent of ``react_gateway/agent.py`` with its prompt, tools and checker unchanged.
Only the optimiser behind ``plan_schedule`` differs: instead of the thesis MPC (``closed_loop.mpc``) the gateway sends
the checked constraints and the forecasts made at the time of the message to EMHASS's REST API
(``POST /action/naive-mpc-optim``, then ``GET /api/v1/plan``) and reports EMHASS's plan in the same app format.

    gateway (EMHASS container, Raspberry Pi 5 sized)  <-- plans, prices, forecasts --  harness
    companion (Ollama, small model)                   <-- the agent's model calls  --  harness

Mapping (EMHASS 0.18.4, 15-min steps, horizon = the agent's horizon, up to the end of the next day):

- prices: import price as ``load_cost_forecast``, feed-in price as ``prod_price_forecast``; PV forecast as
  ``pv_power_forecast``; base load as ``load_power_forecast`` (W);
- heat pump: an EMHASS thermal load (``def_load_config`` ``thermal_config``, continuous 0-3.2 kW) with the twin's
  house model: EMHASS's room equation T+ = T + heating_rate*dt*P/P_nom - cooling_constant*dt*(T - T_out) equals the
  twin's C*dT = dt*(COP*P - heat demand - loss*(T - set point)) with cooling_constant = loss / C, heating_rate =
  COP * P_nom / C and, as "outdoor" temperature, set point - heat demand / loss. One COP per request (the mean of the
  forecast COP) instead of one per slot is the only approximation. EMHASS treats the comfort band as hard limits, so
  it gets the band clipped to what the heat pump can reach (heating at full power from the indoor temperature now;
  cooling only by switching off); the gateway then checks the predicted temperature against the band the household
  asked for, as with the thesis MPC (whose band is a soft penalty);
- home battery: the twin's 10 kWh / 5 kW battery, efficiencies 0.95, 10-100 %; ``soc_init`` = its charge now and
  ``soc_final`` = the same charge (EMHASS needs an end target; the thesis MPC values the end energy instead);
- each car charge: a deferrable load at the charger's 3.7 kW, continuous power (not semi-continuous), operating
  hours = kWh to add / 3.7, rounded up to 15 min and capped at its window; window = earliest .. departure;
- each appliance run: a deferrable load with the house's measured 15-min power profile (run once, start chosen),
  window = earliest .. deadline.

Until 17 Nov 2026 (first run) the heat pump was a fixed load and the indoor temperature was reported as held within
the requested band, so comfort conflicts were not exposed (DX2). Results are not comparable with the thesis MPC.

    uv run python prototypes/emhass_gateway/emhass_gateway.py --raw-dir D:/Study/my-thesis/data/raw \
        --model gemma4-e4b --plans prototypes/plan_pilot/plans_dev.json --ids DS1 \
        --emhass http://localhost:5001 --ollama http://<companion>:11434
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "react_gateway"))
import agent  # noqa: E402  (react_gateway/agent.py; puts closed_loop, plan_pilot and home_gateway on the path)
from agent import APPLIANCE, Gateway, Home, World, forecasts_for, load_days, now, parse, run_plan, score  # noqa: E402

from hems.core.models import SLOT_HOURS  # noqa: E402

EMHASS_URL = "http://localhost:5001"
GRID_LIMIT_W = 17000  # no peak limit in the gateway thesis; above any load the house can draw


def call(url: str, body: dict | None = None, timeout: int = 300) -> dict:
    req = urllib.request.Request(url, None if body is None else json.dumps(body).encode(),
                                 {"Content-Type": "application/json"}, method="GET" if body is None else "POST")  # fmt: skip
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def watts(values: np.ndarray) -> list[float]:
    return [round(float(v) * 1000, 1) for v in values]


def thermal(f: dict[str, np.ndarray], st, c, home: Home) -> dict:
    """The heat pump as an EMHASS thermal load with the twin's house model (see the module docstring).

    EMHASS's temperature list index t is the temperature at the start of slot t (index 0 = now); the gateway's band
    ``c.low[t]``/``c.high[t]`` holds for the end of slot t, i.e. EMHASS index t + 1."""
    H = len(f["import_price"])
    cop = float(np.mean(f["cop"]))
    t_eff = home.set_c - f["heat"] / home.loss_kw_per_k  # "outdoor" temperature giving the twin's heat loss
    low, high = np.empty(H), np.empty(H)
    low[0], high[0] = min(c.low[0], st.indoor), max(c.high[0], st.indoor)
    low[1:], high[1:] = c.low[:-1], c.high[:-1]
    # what the heat pump can reach: full power from now on (warmest) and switched off (coolest)
    warm, cool = np.empty(H), np.empty(H)
    warm[0] = cool[0] = st.indoor
    for t in range(H - 1):
        warm[t + 1] = warm[t] + SLOT_HOURS * (cop * home.hp_max_kw - home.loss_kw_per_k * (warm[t] - t_eff[t])) / home.capacity_kwh_per_k
        cool[t + 1] = cool[t] - SLOT_HOURS * home.loss_kw_per_k * (cool[t] - t_eff[t]) / home.capacity_kwh_per_k
    low = np.minimum(low, warm - 0.01)
    high = np.maximum(np.maximum(high, cool + 0.01), low)
    return {"heating_rate": round(cop * home.hp_max_kw / home.capacity_kwh_per_k, 5),
            "cooling_constant": round(home.loss_kw_per_k / home.capacity_kwh_per_k, 5),
            "start_temperature": round(float(st.indoor), 3), "sense": "heat",
            "min_temperatures": [round(float(v), 3) for v in low], "max_temperatures": [round(float(v), 3) for v in high],
            "outdoor": [round(float(v), 3) for v in t_eff]}  # fmt: skip


def request(f: dict[str, np.ndarray], st, c, home: Home) -> tuple[dict, list[tuple[str, int]]]:
    """EMHASS runtime parameters for one plan; also the deferrable loads in order ((kind, index)); the heat pump is
    the last one."""
    H = len(f["import_price"])
    loads, nominal, hours, start, end = [], [], [], [], []
    for i, (a, b, _) in enumerate(c.ev):
        need = st.ev_left[i]
        if need <= 0.05 or b <= a:
            continue
        window_h = (b - a) * SLOT_HOURS
        hours.append(min(math.ceil(need / home.ev_max_kw / SLOT_HOURS) * SLOT_HOURS, window_h))
        nominal.append(home.ev_max_kw * 1000)
        start.append(a)
        end.append(b if b < H else 0)  # 0: no end constraint (the end of the horizon)
        loads.append(("ev", i))
    for n, (name, a, b) in enumerate(c.appliances):
        prof = APPLIANCE[name]
        nominal.append(watts(prof))
        hours.append(len(prof) * SLOT_HOURS)
        start.append(a)
        end.append(b if b < H else 0)
        loads.append(("appliance", n))
    hc = thermal(f, st, c, home)
    outdoor = hc.pop("outdoor")
    nominal.append(home.hp_max_kw * 1000)
    hours.append(0)  # a thermal load has no energy target: the comfort band drives it
    start.append(0)
    end.append(0)
    loads.append(("heat_pump", 0))
    k = len(loads)
    body = {
        "prediction_horizon": H, "optimization_time_step": 15, "costfun": "profit",
        "load_cost_forecast": [round(float(p), 5) for p in f["import_price"]],
        "prod_price_forecast": [round(float(p), 5) for p in f["export_price"]],
        "pv_power_forecast": watts(f["pv"]), "set_use_pv": True,
        "load_power_forecast": watts(f["fixed"]),
        "outdoor_temperature_forecast": outdoor,
        "def_load_config": [{} for _ in range(k - 1)] + [{"thermal_config": hc}],
        "set_use_battery": True, "soc_init": round(st.soc / home.battery_kwh, 4),
        "soc_final": round(st.soc / home.battery_kwh, 4),
        "battery_nominal_energy_capacity": home.battery_kwh * 1000,
        "battery_charge_power_max": home.battery_kw * 1000, "battery_discharge_power_max": home.battery_kw * 1000,
        "battery_charge_efficiency": home.efficiency, "battery_discharge_efficiency": home.efficiency,
        "battery_minimum_state_of_charge": home.soc_min, "battery_maximum_state_of_charge": 1.0,
        "maximum_power_from_grid": GRID_LIMIT_W, "maximum_power_to_grid": GRID_LIMIT_W,
        "number_of_deferrable_loads": k,
        "nominal_power_of_deferrable_loads": nominal, "operating_hours_of_each_deferrable_load": hours,
        "start_timesteps_of_each_deferrable_load": start, "end_timesteps_of_each_deferrable_load": end,
        "treat_deferrable_load_as_semi_cont": [False] * k, "set_deferrable_load_single_constant": [False] * k,
        "set_deferrable_startup_penalty": [0.0] * k, "deferrable_load_max_cost": [0.0] * k,
        "set_deferrable_max_startups": [0] * k, "is_electric_load": [True] * k,
    }  # fmt: skip
    return body, loads


def emhass_mpc(f: dict[str, np.ndarray], k: int, st, c, w: World, home: Home, url: str, log: list) -> dict:
    """Same output as ``closed_loop.mpc`` (kW per horizon slot), solved by EMHASS."""
    H = w.horizon
    body, loads = request({key: v[k:] for key, v in f.items()}, st, c, home)
    started = time.perf_counter()
    action = call(f"{url}/action/naive-mpc-optim", body)
    plan = call(f"{url}/api/v1/plan")
    solve_s = time.perf_counter() - started
    rows = plan.get("plan") or []
    if isinstance(rows, dict):
        rows = [dict(zip(rows, values)) for values in zip(*rows.values())]
    status = str(rows[0].get("optim_status")) if rows else str(action)[:200]
    log.append({"solve_s": round(solve_s, 3), "status": status, "steps": len(rows), "deferrable_loads": len(loads),
                "request_bytes": len(json.dumps(body))})  # fmt: skip
    if status != "Optimal" or len(rows) != H - k:
        raise RuntimeError(f"EMHASS returned status {status!r} with {len(rows)} of {H - k} steps")

    def col(name: str) -> np.ndarray:
        out = np.zeros(H)
        out[k:] = [float(r.get(name) or 0.0) / 1000 for r in rows]
        return out

    ev_plan, starts, hp = np.zeros((len(c.ev), H)), {}, np.zeros(H)
    for j, (kind, i) in enumerate(loads):
        power = col(f"P_deferrable{j}")
        if kind == "ev":
            ev_plan[i] = power
        elif kind == "heat_pump":
            hp = power
            temp_col = f"predicted_temp_heater{j}"
        else:
            on = np.flatnonzero(power > 1e-3)
            if len(on):
                starts[i] = int(on[0])
    # EMHASS's temperature at the start of each slot -> the gateway's indoor temperature at the end of each slot
    start_of_slot = np.array([float(r[temp_col]) for r in rows])
    indoor = np.full(H, float(st.indoor))
    indoor[k:] = np.append(start_of_slot[1:], start_of_slot[-1])
    return {"hp": hp, "grid": col("P_grid"), "ev": ev_plan, "starts": starts,
            "battery": -col("P_batt"),  # EMHASS: positive = discharging; the gateway: positive = charging
            "indoor": indoor}  # fmt: skip


def companion_up(timeout: float = 3.0) -> bool:
    """Whether the companion device's Ollama server answers (the gateway checks before handing it a message)."""
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    host = host if host.startswith("http") else f"http://{host}"
    try:
        call(f"{host}/api/version", timeout=int(timeout))
        return True
    except OSError:
        return False


def offline_answer(plan: dict) -> tuple[dict, dict]:
    """The gateway's fallback when the companion device is unreachable: the message is not interpreted, the last
    committed plan and the control layer keep running, and the household app says so."""
    got = {"ev": [], "appliances": [], "away": [], "comfort": [], "commit": False,
           "questions": [{"topic": "other", "text": "(assistant offline)"}]}  # fmt: skip
    app = {"plan": plan["id"], "decision": "offline",
           "message_to_household": "The assistant is not reachable right now, so your message was not read. The home "
                                   "keeps running on the last confirmed plan. Please send the message again later.",
           "schedule": None}  # fmt: skip
    meta = {"latency_s": 0.0, "tool_calls": 0, "tokens_in": 0, "tokens_out": 0, "usd": 0.0, "recoveries": 0,
            "error": "companion offline", "schedule_calls": 0, "actions": [], "model_commit": False}  # fmt: skip
    return got, {**meta, "app": app}


@dataclass
class EmhassGateway(Gateway):
    url: str = EMHASS_URL
    solves: list = field(default_factory=list)

    def schedule(self, got: dict) -> dict:
        """The agent's ``Gateway.schedule`` with EMHASS in place of the thesis MPC."""
        original = agent.mpc
        agent.mpc = lambda f, k, st, c, w, home: emhass_mpc(f, k, st, c, w, home, self.url, self.solves)
        try:
            result = agent.Gateway.schedule(self, got)
        finally:
            agent.mpc = original
        result["optimiser"] = {"name": "EMHASS 0.18.4 (naive-mpc-optim)", **self.solves[-1]}
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("D:/Study/my-thesis/data/raw"))
    parser.add_argument("--model", default="gemma4-e4b")
    parser.add_argument("--plans", type=Path, default=ROOT / "plan_pilot" / "plans_dev.json")
    parser.add_argument("--ids", nargs="*", help="only these plans")
    parser.add_argument("--emhass", default=EMHASS_URL, help="the gateway's EMHASS service")
    parser.add_argument("--ollama", default=None, help="the companion device's Ollama server (default: OLLAMA_HOST)")
    parser.add_argument("--out", type=Path, default=HERE / "out" / "results.jsonl")
    args = parser.parse_args()
    if args.ollama:
        os.environ["OLLAMA_HOST"] = args.ollama  # read by the Ollama client behind ChatOllama
    version = call(f"{args.emhass}/api/v1/last-run").get("emhass_version", "?")
    print(f"gateway: EMHASS {version} at {args.emhass}; companion: Ollama at {os.environ.get('OLLAMA_HOST', 'localhost:11434')}")
    home = Home()
    all_days = load_days(args.raw_dir, 2016, "de", "feedin")
    fcs = forecasts_for(all_days, "weather")
    days = {d.date: d for d in all_days}
    data = json.loads(args.plans.read_text(encoding="utf-8"))
    appliances = json.loads((ROOT / "react_gateway" / "appliances.json").read_text(encoding="utf-8"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as out:
        for plan in data["plans"]:
            if args.ids and plan["id"] not in args.ids:
                continue
            t0 = parse(now(plan))
            d0, d1 = t0.date().isoformat(), (t0.date() + timedelta(days=1)).isoformat()
            w = World(t0, t0.hour * 4 + t0.minute // 15, (days[d0], days[d1]), (fcs[d0], fcs[d1]))
            gw = EmhassGateway(plan, data["household"], w, home, appliances, url=args.emhass)
            got, meta = run_plan(args.model, gw) if companion_up() else offline_answer(plan)
            app = meta.pop("app")
            app["optimiser"] = "EMHASS"
            app["emhass_solves"] = gw.solves
            row = {"model": args.model, "id": plan["id"], "plans_file": args.plans.name, "optimiser": "emhass",
                   **score(plan, got, data["household"]), **meta, "emhass_solves": gw.solves, "output": got}  # fmt: skip
            out.write(json.dumps(row) + "\n")
            out.flush()
            app_path = args.out.parent / "app" / args.model / f"{plan['id']}.json"
            app_path.parent.mkdir(parents=True, exist_ok=True)
            app_path.write_text(json.dumps(app, indent=1, default=str), encoding="utf-8")
            solve = sum(s["solve_s"] for s in gw.solves)
            print(f"{plan['id']}: {app['decision']:7s} (key {plan['key'].get('decision', 'commit')}) "
                  f"{meta['latency_s']:6.1f} s total, EMHASS {len(gw.solves)} solve(s) {solve:.2f} s, "
                  f"{meta['tool_calls']} tool calls" + (f" ERROR {meta['error']}" if meta["error"] else ""), flush=True)  # fmt: skip


if __name__ == "__main__":
    main()
