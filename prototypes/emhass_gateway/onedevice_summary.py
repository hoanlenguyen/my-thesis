"""Summary of the one-device test: plan answers, and the gateway's background work with the model idle vs answering.

    uv run python prototypes/emhass_gateway/onedevice_summary.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent / "out" / "onedevice"  # runs before 20 Nov 2026: OUT / "archive" (see its README)

# Probe samples to leave out (local time): the model was answering a plan whose answer was lost, so the samples are
# neither "idle" nor matched to a plan window, or a LaTeX compile on the laptop loaded the shared cores.
EXCLUDE = {
    "prioritised": [
        ("2026-11-19 12:11:50", "2026-11-19 12:12:15"),  # compile
        ("2026-11-19 13:23:00", "2026-11-19 14:19:35"),  # DS2, first attempt (EMHASS read race, 19 Nov), restart
        ("2026-11-19 14:30:51", "2026-11-19 14:32:14"),  # compiles
        ("2026-11-19 20:15:00", "2026-11-19 22:21:00"),  # DS4, first attempt, lost when the laptop stopped
    ],
}


def excluded(run: str, t: float) -> bool:
    from datetime import datetime

    return any(datetime.fromisoformat(a).timestamp() <= t <= datetime.fromisoformat(b).timestamp()
               for a, b in EXCLUDE.get(run, []))  # fmt: skip


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def stats(values: list[float]) -> str:
    if not values:
        return "n=0"
    v = np.array(values)
    return f"n={len(v):3d} median {np.median(v):6.2f}  p95 {np.percentile(v, 95):6.2f}  max {v.max():6.2f}"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=OUT, help="results folder (edge kit: prototypes/edge_kit/out/<device>)")
    out = parser.parse_args().dir
    for run in ("unprioritised", "prioritised"):
        plans_path, probe_path = out / f"plans_{run}.jsonl", out / f"probe_{run}.jsonl"
        if not plans_path.exists() or not probe_path.exists():
            print(f"{run}: no results")
            continue
        plans, probe = load(plans_path), load(probe_path)
        dropped = sum(excluded(run, s["t"]) for s in probe)
        probe = [s for s in probe if not excluded(run, s["t"])]
        windows = [(p["started_at"], p["ended_at"]) for p in plans if "started_at" in p]
        busy = [s for s in probe if any(a <= s["t"] <= b for a, b in windows)]
        idle = [s for s in probe if s not in busy]
        print(f"=== {run}")
        print(f"plans: {len(plans)}, decisions right {sum(bool(p.get('decision_ok')) for p in plans)}, "
              f"failed {sum(p.get('error') is not None for p in plans)}; probe samples left out: {dropped}")
        print(f"  seconds per plan      {stats([p['latency_s'] for p in plans])}")
        solves = [s['solve_s'] for p in plans for s in p.get('emhass_solves', [])]
        print(f"  plan's EMHASS solve s {stats(solves)}")
        for name, group in (("model idle", idle), ("model answering", busy)):
            ok = [s for s in group if s["status"] == "Optimal"]
            print(f"  {name:16s} re-plan s {stats([s['replan_s'] for s in ok])}  "
                  f"(not optimal: {len(group) - len(ok)})")
            print(f"  {name:16s} control s {stats([s['control_step_s'] for s in group])}")


if __name__ == "__main__":
    main()
