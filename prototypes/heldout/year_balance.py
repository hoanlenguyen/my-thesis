"""Year simulation, energy balance (H5, SQ3; draft, 22 Nov 2026): the HEMS's yearly saving against the energy and
cost of running the small model on the household's hardware.

The year itself is simulated by the Configurator's weekly simulation (``configurator_pilot/configurator.py``) over
``DE_KN_residential4`` 2016, every system with the hourly MPC and the same control layer, the car's requirements as
the household states them at each plug-in (as if the Household Assistant read them correctly):

    uv run python prototypes/configurator_pilot/configurator.py --raw-dir D:/Study/my-thesis/data/raw \
        --start 2016-01-18 --weeks 49 --models gemma4-e4b gpt-6-luna --out prototypes/heldout/out/year_2016.jsonl --resume

(49 weeks, 18 Jan to 24 Dec 2016: the first two weeks of the data are the first week's history, and the data end
on 31 Dec. The year contains the Configurator's held-out weeks, so it runs only after the registration commit.)

This script adds the energy balance. Per system: the adjusted cost and grid import over the simulated days, scaled
to 365 days, and the saving against the rules. Per hardware set-up, the model's energy per year:

- ``gateway``: the model runs on the gateway, which is on anyway; it costs the energy of each event above idle plus
  the extra idle power of keeping the model loaded (``--extra-idle-w``);
- ``companion``: the model runs on a second device that is on only for it; it costs that device's whole idle power
  (``--device-idle-w``) plus the energy of each event.

H5 weighs the saving over rules. Most of that saving is the MPC's, so the report also gives what the model adds
over the expert-tuned MPC, which a household could reach by entering exact parameters, net of the model's energy.

Events per year: one Household Assistant plan per day (``--plans-per-day``, an assumption stated with the result)
and one Configurator call per week. Energy per event comes from the edge-board runs (measured at the wall, above
idle); it is priced at the year's mean import price of the household's tariff.

    uv run python prototypes/heldout/year_balance.py --runs prototypes/heldout/out/year_2016.jsonl \
        --device "Raspberry Pi 5" --wh-per-plan 2.5 --wh-per-config 1.0 --extra-idle-w 0.5 --device-idle-w 4.0
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "home_gateway"))
from twin import load_days  # noqa: E402

HOURS_PER_YEAR = 8760


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, required=True, help="configurator.py output over the year")
    parser.add_argument("--raw-dir", type=Path, default=Path("D:/Study/my-thesis/data/raw"))
    parser.add_argument("--system", default="agent:gemma4-e4b", help="the HEMS whose saving is weighed")
    parser.add_argument("--device", required=True, help="name of the device the energy figures come from")
    parser.add_argument("--wh-per-plan", type=float, required=True, help="Household Assistant, Wh above idle")
    parser.add_argument("--wh-per-config", type=float, required=True, help="Configurator call, Wh above idle")
    parser.add_argument("--extra-idle-w", type=float, required=True, help="gateway set-up: idle W of the loaded model")
    parser.add_argument("--device-idle-w", type=float, required=True, help="companion set-up: the device's idle W")
    parser.add_argument("--plans-per-day", type=float, default=1.0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.runs.read_text(encoding="utf-8").splitlines() if line.strip()]
    weeks = sorted({r["week"] for r in rows if r["system"] == "optimum"})  # complete weeks only
    rows = [r for r in rows if r["week"] in weeks]
    days_simulated = 7 * len(weeks)
    scale = 365 / days_simulated
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        t = totals[r["system"]]
        t["adjusted_cost_eur"] += r["adjusted_cost_eur"]
        for k in ("import_kwh", "export_kwh", "usd", "latency_s"):
            if r.get(k) is not None:
                t[k] += r[k]
    if "rules" not in totals or args.system not in totals:
        raise SystemExit(f"need 'rules' and '{args.system}' in {args.runs}")
    days = load_days(args.raw_dir, 2016, "de", "feedin")
    price = float(np.mean([d.import_price.mean() for d in days]))  # EUR/kWh, the household's tariff
    rules = totals["rules"]
    systems = {}
    for name, t in sorted(totals.items()):
        systems[name] = {
            "cost_eur_per_year": round(t["adjusted_cost_eur"] * scale, 2),
            "saving_vs_rules_eur_per_year": round((rules["adjusted_cost_eur"] - t["adjusted_cost_eur"]) * scale, 2),
            "import_kwh_per_year": round(t["import_kwh"] * scale, 1) if "import_kwh" in t else None,
            "import_saving_vs_rules_kwh_per_year": round((rules["import_kwh"] - t["import_kwh"]) * scale, 1)
            if "import_kwh" in t and "import_kwh" in rules else None,
            "model_usd_per_year": round(t["usd"] * scale, 3) if "usd" in t else None,
        }  # fmt: skip
    plans, configs = args.plans_per_day * 365, 52
    events_kwh = (plans * args.wh_per_plan + configs * args.wh_per_config) / 1000
    setups = {
        "gateway": events_kwh + args.extra_idle_w * HOURS_PER_YEAR / 1000,
        "companion": events_kwh + args.device_idle_w * HOURS_PER_YEAR / 1000,
    }
    saving = systems[args.system]["saving_vs_rules_eur_per_year"]
    # H5 weighs the saving over rules; most of it is the MPC's, so what the model adds over the expert-tuned MPC
    # (the household entering exact parameters) is reported beside it
    added = (round((totals["tuned"]["adjusted_cost_eur"] - totals[args.system]["adjusted_cost_eur"]) * scale, 2)
             if "tuned" in totals else None)  # fmt: skip
    balance = {name: {"model_kwh_per_year": round(kwh, 2), "model_eur_per_year": round(kwh * price, 2),
                      "net_saving_vs_rules_eur_per_year": round(saving - kwh * price, 2),
                      "saving_exceeds_model_cost": saving > kwh * price,
                      "net_vs_expert_mpc_eur_per_year": round(added - kwh * price, 2) if added is not None else None}
               for name, kwh in setups.items()}  # fmt: skip
    report = {"runs": args.runs.name, "weeks": len(weeks), "days_simulated": days_simulated, "scaled_to_days": 365,
              "import_price_eur_kwh": round(price, 4), "system": args.system, "device": args.device,
              "assumptions": {"plans_per_year": plans, "configurations_per_year": configs,
                              "wh_per_plan": args.wh_per_plan, "wh_per_config": args.wh_per_config,
                              "extra_idle_w": args.extra_idle_w, "device_idle_w": args.device_idle_w},
              "saving_over_expert_mpc_eur_per_year": added, "systems": systems, "balance": balance}  # fmt: skip
    out = args.out or args.runs.with_name(f"{args.runs.stem}_balance_{args.device.replace(' ', '_').lower()}.json")
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"{len(weeks)} weeks ({days_simulated} days) scaled to a year; import price {price:.3f} EUR/kWh\n")
    print(f"{'system':20s} {'EUR/yr':>9s} {'saving vs rules':>16s} {'import kWh/yr':>14s}")
    for name, s in systems.items():
        print(f"{name:20s} {s['cost_eur_per_year']:9.2f} {s['saving_vs_rules_eur_per_year']:16.2f} "
              f"{s['import_kwh_per_year'] if s['import_kwh_per_year'] is not None else float('nan'):14.1f}")  # fmt: skip
    print(f"\n{args.system} on {args.device}: saving {saving:.2f} EUR/yr over rules, {added} EUR/yr over the "
          f"expert MPC")  # fmt: skip
    for name, b in balance.items():
        print(f"  {name:10s} {b['model_kwh_per_year']:7.2f} kWh/yr = {b['model_eur_per_year']:6.2f} EUR/yr -> net "
              f"{b['net_saving_vs_rules_eur_per_year']:7.2f} EUR/yr over rules, "
              f"{b['net_vs_expert_mpc_eur_per_year']} over the expert MPC")  # fmt: skip
    print(f"-> {out}")


if __name__ == "__main__":
    main()
