"""Energy per event on a household device, from the edge kit's power log (edge kit, 22 Nov 2026).

Reads a device's output folder (``run_device.sh``): ``events.jsonl`` (phase windows), ``power.jsonl`` (the plug's
readings, ``power_log.py``), the edge benchmark's rows (``<device>_<model>.jsonl``) and the one-device test's plans
(``plans_<run>.jsonl``), each plan with its wall-clock start and end. Without a power log, ``manual.json`` holds
meter readings taken by hand (README.md, "Manual readings").

- idle power without the model (``idle_no_model``) and with it loaded (``idle_model``); their difference is the extra
  idle power of keeping the model in memory on the gateway;
- energy per plan above idle: the power integrated over the plan's window minus the baseline power times its length.
  The baseline is ``idle_model`` for the benchmark and the window just before the plans with the probe running and
  the model loaded (``probe_idle_<run>``) for the one-device test;
- the time per plan (mean and 95th percentile, H5).

It ends with the ``year_balance.py`` command for this device. The registered event is a Household Assistant plan,
so ``--wh-per-plan`` is the one-device test's unprioritised plan; a Configurator call is a single structured exchange
of a similar size to a benchmark plan, so ``--wh-per-config`` uses the benchmark's mean (stated as an estimate).

    uv run python prototypes/edge_kit/edge_energy.py --dir prototypes/edge_kit/out/pi5-16gb
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def phases(events: list[dict]) -> dict[str, tuple[float, float]]:
    starts, out = {}, {}
    for e in events:
        if e["event"] == "start":
            starts[e["phase"]] = e["t"]
        elif e["event"] == "end" and e["phase"] in starts:
            out[e["phase"]] = (starts[e["phase"]], e["t"])
    return out


class Power:
    def __init__(self, rows: list[dict]) -> None:
        rows = sorted(rows, key=lambda r: r["t"])
        self.t = np.array([r["t"] for r in rows], dtype=float)
        self.w = np.array([r["w"] for r in rows], dtype=float)

    def mean(self, a: float, b: float) -> float | None:
        m = (self.t >= a) & (self.t < b)  # half-open, so a reading at a boundary counts in one phase only
        return float(self.w[m].mean()) if m.sum() >= 3 else None

    def wh(self, a: float, b: float) -> float | None:
        """Energy over [a, b), Wh: the readings in the window, integrated (trapezoid), edges held."""
        m = (self.t >= a) & (self.t < b)
        if m.sum() < 2:
            return None
        t = np.concatenate([[a], self.t[m], [b]])
        w = np.concatenate([[self.w[m][0]], self.w[m], [self.w[m][-1]]])
        return float(np.sum((w[1:] + w[:-1]) / 2 * np.diff(t)) / 3600)


def per_plan(plans: list[dict], power: Power | None, base_w: float | None, manual_load_w: float | None) -> dict:
    secs = [p["ended_at"] - p["started_at"] for p in plans if "started_at" in p and "ended_at" in p]
    out = {"plans": len(secs), "mean_s": round(float(np.mean(secs)), 1) if secs else None,
           "p95_s": round(float(np.percentile(secs, 95)), 1) if secs else None}  # fmt: skip
    above = []
    for p in plans:
        if "started_at" not in p or base_w is None:
            continue
        length = p["ended_at"] - p["started_at"]
        total = power.wh(p["started_at"], p["ended_at"]) if power else \
            (manual_load_w * length / 3600 if manual_load_w is not None else None)
        if total is not None:
            above.append(total - base_w * length / 3600)
    out["wh_above_idle_mean"] = round(float(np.mean(above)), 3) if above else None
    out["wh_above_idle_per_plan"] = [round(x, 3) for x in above]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--model", default="gemma4-e4b")
    args = parser.parse_args()
    d = args.dir
    device = d.name
    win = phases(load(d / "events.jsonl"))
    rows = load(d / "power.jsonl")
    power = Power(rows) if rows else None
    manual = json.loads((d / "manual.json").read_text()) if (d / "manual.json").exists() else {}
    if power is None and not manual:
        raise SystemExit(f"no power.jsonl or manual.json in {d}")

    def phase_w(name: str) -> float | None:
        if power is not None and name in win:
            return power.mean(*win[name])
        return manual.get(f"{name}_w")

    idle_no, idle_model = phase_w("idle_no_model"), phase_w("idle_model")
    report = {"device": device, "source": "power log" if power is not None else "manual readings",
              "idle_no_model_w": idle_no, "idle_model_w": idle_model,
              "extra_idle_w": round(idle_model - idle_no, 2) if idle_no is not None and idle_model is not None else None,
              "bench": per_plan(load(d / f"{device}_{args.model}.jsonl"), power, idle_model, manual.get("bench_w"))}  # fmt: skip
    for run in ("unprioritised", "prioritised"):
        report[f"onedevice_{run}"] = per_plan(load(d / f"plans_{run}.jsonl"), power, phase_w(f"probe_idle_{run}"),
                                              manual.get(f"onedevice_{run}_w"))  # fmt: skip
        report[f"onedevice_{run}"]["baseline_w"] = phase_w(f"probe_idle_{run}")
    (d / "energy.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items()}, indent=1, default=str))
    plan_wh = report["onedevice_unprioritised"]["wh_above_idle_mean"]
    config_wh = report["bench"]["wh_above_idle_mean"]
    if None not in (plan_wh, config_wh, report["extra_idle_w"], idle_model):
        print(f"\nyear balance for {device} (wh-per-config estimated from the benchmark's structured call):\n"
              f"  uv run python prototypes/heldout/year_balance.py --runs prototypes/heldout/out/year_2016.jsonl "
              f"--device {device} --wh-per-plan {plan_wh} --wh-per-config {config_wh} "
              f"--extra-idle-w {report['extra_idle_w']} --device-idle-w {round(idle_model, 2)}")  # fmt: skip
    else:
        print("\nnot enough readings for the year balance (see the fields that are null)")


if __name__ == "__main__":
    main()
