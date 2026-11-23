"""The gateway's background work on a shared device (one-device test, 18 Nov 2026).

Every ``--every`` seconds it times (1) one EMHASS re-plan, a fixed 96-slot problem with the home battery, a car charge
and the heat pump as a thermal load, standing in for the hourly MPC, and (2) a fixed CPU workload standing in for one
15-minute control step. Each sample is one JSON line with its wall-clock time, so the samples can be matched to the
windows in which the language model on the same cores was answering a plan.

    python prototypes/emhass_gateway/probe.py --emhass http://emhass:5000 --out /out/probe.jsonl
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import time
import urllib.request
from pathlib import Path

H = 96


@contextlib.contextmanager
def emhass_lock():
    """Hold the EMHASS lock shared with the assistant (``EMHASS_LOCK``, a file on a volume both containers mount).

    EMHASS's ``GET /api/v1/plan`` returns the latest solve, so a solve and its read must not interleave with another
    client's; on a real gateway one harness makes both calls (19 Nov 2026). Yields the seconds spent waiting.
    """
    path = os.environ.get("EMHASS_LOCK")
    started = time.perf_counter()
    if not path:
        yield 0.0
        return
    import fcntl

    with open(path, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield time.perf_counter() - started
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def replan_body() -> dict:
    price = [round(0.28 + 0.08 * math.sin(2 * math.pi * t / 96), 4) for t in range(H)]
    pv = [round(max(0.0, 4000 * math.sin(math.pi * (t - 28) / 48)) if 28 <= t <= 76 else 0.0, 1) for t in range(H)]
    return {
        "prediction_horizon": H, "optimization_time_step": 15, "costfun": "profit",
        "load_cost_forecast": price, "prod_price_forecast": [0.123] * H,
        "pv_power_forecast": pv, "load_power_forecast": [450.0] * H, "set_use_pv": True,
        "set_use_battery": True, "soc_init": 0.5, "soc_final": 0.5,
        "battery_nominal_energy_capacity": 10000, "battery_charge_power_max": 5000, "battery_discharge_power_max": 5000,
        "battery_charge_efficiency": 0.95, "battery_discharge_efficiency": 0.95,
        "battery_minimum_state_of_charge": 0.1, "battery_maximum_state_of_charge": 1.0,
        "maximum_power_from_grid": 17000, "maximum_power_to_grid": 17000,
        "outdoor_temperature_forecast": [1.0] * H,
        "number_of_deferrable_loads": 2,
        "nominal_power_of_deferrable_loads": [3700.0, 3200.0],
        "operating_hours_of_each_deferrable_load": [3.0, 0],
        "start_timesteps_of_each_deferrable_load": [0, 0], "end_timesteps_of_each_deferrable_load": [30, 0],
        "treat_deferrable_load_as_semi_cont": [False, False], "set_deferrable_load_single_constant": [False, False],
        "set_deferrable_startup_penalty": [0.0, 0.0], "deferrable_load_max_cost": [0.0, 0.0],
        "set_deferrable_max_startups": [0, 0], "is_electric_load": [True, True],
        "def_load_config": [{}, {"thermal_config": {"heating_rate": 0.96, "cooling_constant": 0.015,
                                                    "start_temperature": 21.0, "sense": "heat",
                                                    "min_temperatures": [20.0] * H, "max_temperatures": [22.0] * H}}],
    }  # fmt: skip


def call(url: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(url, None if body is None else json.dumps(body).encode(),
                                 {"Content-Type": "application/json"}, method="GET" if body is None else "POST")  # fmt: skip
    with urllib.request.urlopen(req, timeout=600) as resp:
        text = resp.read().decode()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def control_step() -> float:
    """A fixed CPU workload (about 0.1 s on an idle laptop core), timed."""
    started = time.perf_counter()
    acc = 0.0
    for i in range(1, 400_000):
        acc += math.sqrt(i) % 7
    return time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--emhass", default="http://emhass:5000")
    parser.add_argument("--every", type=float, default=15.0, help="seconds between samples")
    parser.add_argument("--out", type=Path, default=Path("/out/probe.jsonl"))
    args = parser.parse_args()
    body = replan_body()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    while True:
        t0 = time.time()
        with emhass_lock() as wait_s:  # the harness's solve and read must not interleave with the assistant's
            started = time.perf_counter()
            try:
                call(f"{args.emhass}/action/naive-mpc-optim", body)
                rows = call(f"{args.emhass}/api/v1/plan").get("plan") or [{}]
                status = str(rows[0].get("optim_status"))
                if len(rows) != H:
                    status = f"{status}, {len(rows)} of {H} steps"
            except OSError as exc:
                status = f"error: {exc}"[:120]
            solve_s = time.perf_counter() - started
        sample = {"t": round(t0, 2), "replan_s": round(solve_s, 3), "lock_wait_s": round(wait_s, 3), "status": status,
                  "control_step_s": round(control_step(), 4)}  # fmt: skip
        with args.out.open("a", encoding="utf-8") as out:
            out.write(json.dumps(sample) + "\n")
        time.sleep(max(0.0, args.every - (time.time() - t0)))


if __name__ == "__main__":
    main()
