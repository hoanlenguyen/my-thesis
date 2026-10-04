"""Schedule benchmark scenarios with EMHASS (Energy Management for Home Assistant).

Runs in the separate environment .venv-emhass (EMHASS pins numpy<2.3 and other packages that
conflict with the thesis environment), so it reads the scenario JSON directly instead of
importing hems. It writes one start slot per appliance; scoring is done in the thesis
environment with `hems import-schedules`, by the same evaluate() as every other system.

Two configurations:
  profile  - each appliance as an EMHASS sequence load: its measured 15-min power profile,
             run once, contiguously; only the start is chosen.
  nominal  - the common simple configuration: constant nominal power (the cycle's peak)
             for the cycle's duration, semi-continuous, one start.

Both use the scenario's price, base load (as the non-deferrable load forecast), per-appliance
window [earliest_slot, deadline_slot) and the household peak limit as maximum_power_from_grid.
No PV, no battery. 15-minute time step, 96-step horizon.

    .venv-emhass/Scripts/python.exe tools/emhass_adapter.py data/scenarios results/emhass_profile.json --mode profile
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import pathlib
import sys
import time
from importlib.metadata import version

import numpy as np
import pandas as pd
from emhass import utils
from emhass.optimization import Optimization

SLOTS = 96
STEP_MIN = 15


def _base_params(logger: logging.Logger) -> tuple[dict, dict]:
    root = pathlib.Path(utils.__file__).parent
    emhass_conf = {
        "root_path": root,
        "data_path": pathlib.Path("."),
        "associations_path": root / "data" / "associations.csv",
        "defaults_path": root / "data" / "config_defaults.json",
    }
    config = json.loads(emhass_conf["defaults_path"].read_text())
    return emhass_conf, config


def schedule(scenario: dict, mode: str, logger: logging.Logger) -> dict:
    emhass_conf, config = _base_params(logger)
    apps = scenario["appliances"]
    k = len(apps)
    if mode == "profile":
        nominal = [[p * 1000 for p in a["profile_kw"]] for a in apps]
        hours = [len(a["profile_kw"]) * STEP_MIN / 60 for a in apps]
        semi, single = [False] * k, [False] * k
    else:
        nominal = [max(a["profile_kw"]) * 1000 for a in apps]
        hours = [len(a["profile_kw"]) * STEP_MIN / 60 for a in apps]
        semi, single = [True] * k, [True] * k
    config.update({
        "optimization_time_step": STEP_MIN,
        "costfun": "cost",
        "number_of_deferrable_loads": k,
        "nominal_power_of_deferrable_loads": nominal,
        "minimum_power_of_deferrable_loads": [0.0] * k,
        "operating_hours_of_each_deferrable_load": hours,
        "start_timesteps_of_each_deferrable_load": [a["earliest_slot"] for a in apps],
        "end_timesteps_of_each_deferrable_load": [a["deadline_slot"] for a in apps],
        "treat_deferrable_load_as_semi_cont": semi,
        "set_deferrable_load_single_constant": single,
        "set_deferrable_startup_penalty": [0.0] * k,
        "deferrable_load_max_cost": [0.0] * k,
        "set_deferrable_max_startups": [0] * k,
        "cost_forecast_per_deferrable_load": [None] * k,
        "is_electric_load": [True] * k,
        "deferrable_load_groups": [],
        "maximum_power_from_grid": scenario["peak_limit_kw"] * 1000,
        "set_use_pv": False,
        "set_use_battery": False,
        "lp_solver_timeout": 120,
        "lp_solver_mip_rel_gap": 0.0,
    })  # fmt: skip
    params = asyncio.run(utils.build_params(emhass_conf, {}, config, logger))
    retrieve_hass_conf, optim_conf, plant_conf = utils.get_yaml_parse(params, logger)

    index = pd.date_range(pd.Timestamp(scenario["start_time"]), periods=SLOTS, freq=f"{STEP_MIN}min")
    price = np.asarray(scenario["price_eur_per_kwh"], dtype=float)
    base_w = np.asarray(scenario["base_load_kw"], dtype=float) * 1000
    data = pd.DataFrame({"unit_load_cost": price, "unit_prod_price": np.zeros(SLOTS)}, index=index)

    opt = Optimization(
        retrieve_hass_conf, optim_conf, plant_conf, "unit_load_cost", "unit_prod_price", "cost",
        emhass_conf, logger, num_timesteps=SLOTS,
    )  # fmt: skip
    started = time.perf_counter()
    result = opt.perform_optimization(
        data, np.zeros(SLOTS), base_w, price, np.zeros(SLOTS),
        def_start_timestep=[a["earliest_slot"] for a in apps],
        def_end_timestep=[a["deadline_slot"] for a in apps],
    )  # fmt: skip
    elapsed = time.perf_counter() - started

    starts: dict[str, int | None] = {}
    for i, a in enumerate(apps):
        power = result[f"P_deferrable{i}"].to_numpy()
        on = np.flatnonzero(power > 1e-3)
        starts[a["id"]] = int(on[0]) if len(on) else None
    return {"starts": starts, "status": str(getattr(opt, "optim_status", "")), "solve_s": round(elapsed, 3)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenarios", type=pathlib.Path, nargs="?")
    parser.add_argument("out", type=pathlib.Path, nargs="?")
    parser.add_argument("--mode", choices=["profile", "nominal"], default="profile")
    parser.add_argument("--only", nargs="*", help="scenario ids (default: all)")
    parser.add_argument("--stdin", action="store_true",
                        help="read ONE scenario JSON from stdin, write the result as the last stdout line "
                             "(used by hems.solvers.emhass)")  # fmt: skip
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)  # to stderr, so stdout stays machine-readable
    logger = logging.getLogger("emhass_adapter")
    if args.stdin:
        scenario = json.loads(sys.stdin.read())
        res = schedule(scenario, args.mode, logger)
        print(json.dumps({"emhass_version": version("emhass"), "mode": args.mode, **res}), flush=True)
        return
    if args.scenarios is None or args.out is None:
        parser.error("scenarios and out are required unless --stdin is given")
    out = {"emhass_version": version("emhass"), "mode": args.mode, "schedules": {}}
    for path in sorted(args.scenarios.glob("*.json")):
        if path.name == "manifest.json":
            continue
        scenario = json.loads(path.read_text(encoding="utf-8"))
        if args.only and scenario["id"] not in args.only:
            continue
        res = schedule(scenario, args.mode, logger)
        out["schedules"][scenario["id"]] = res
        print(scenario["id"], res["status"], res["solve_s"], "s", res["starts"], flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
