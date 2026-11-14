"""Optimiser time on a gateway device (SQ4): runs the closed-loop pilot's hourly MPC for the 11 commit plans with
the answer key's constraints and records how long each MILP solve takes. Run it on the device itself (it needs
the repository, ``uv`` and the OPSD, DWD, When2Heat and price files in ``--raw-dir``).

    uv run python prototypes/edge_bench/mpc_time.py --device pi5-16gb --raw-dir data/raw
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "closed_loop"))
import closed_loop  # noqa: E402
from closed_loop import World, constraints, forecasts_for, load_days, now, parse, run  # noqa: E402
from twin import Home  # noqa: E402

HERE = Path(__file__).parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device", required=True)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    times: list[float] = []
    solve = closed_loop.mpc

    def timed(*a, **k):
        started = time.perf_counter()
        out = solve(*a, **k)
        times.append(time.perf_counter() - started)
        return out

    closed_loop.mpc = timed
    home = Home()
    all_days = load_days(args.raw_dir, 2016, "de", "feedin")
    fcs = forecasts_for(all_days, "weather")
    days = {d.date: d for d in all_days}
    data = json.loads((ROOT / "plan_pilot" / "plans.json").read_text(encoding="utf-8"))
    for plan in (p for p in data["plans"] if p["key"].get("decision") == "commit"):
        t0 = parse(now(plan))
        d0, d1 = t0.date().isoformat(), (t0.date() + timedelta(days=1)).isoformat()
        if d0 not in days or d1 not in days:
            continue
        w = World(t0, t0.hour * 4 + t0.minute // 15, (days[d0], days[d1]), (fcs[d0], fcs[d1]))
        key = constraints(plan, plan["key"], t0, w.horizon, home, data["household"]["car_battery_kwh"])
        run(w, home, key, (0, max([b for _, b, _ in key.ev], default=w.horizon)))
        print(f"{plan['id']}: {len(times)} solves so far", flush=True)
    ordered = sorted(times)
    summary = {"device": args.device, "host_os": platform.platform(), "solves": len(times),
               "mean_s": round(sum(times) / len(times), 3), "p95_s": round(ordered[int(0.95 * (len(ordered) - 1))], 3),
               "max_s": round(ordered[-1], 3)}  # fmt: skip
    out = HERE / "out" / f"{args.device}_mpc.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
