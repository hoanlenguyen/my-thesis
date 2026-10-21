"""Benchmark v4: v3 plus a third household load, "electrified" (an electric car and a sauna), under the 8 kW limit.

Under the 8 kW power-charge threshold the REFIT laundry and dishwasher loads rarely compete for capacity (2 of the
48 v3 days need coordination). An electric car and an electric sauna are the usual reasons a Finnish house reaches
8 kW, so each heavy-load day of v3 is also scheduled with both added (same day, prices, base load and cycles; ids
"U-VH01-80" -> "U-VE01-80", type "volatile-electrified-realistic"):

- Electric car charge, flexible: a constant 3.7 kW, the single-phase home charge point (230 V x 16 A; charger
  manufacturer data), for 2 h (7.4 kWh, about 37 km at 0.2 kWh/km; Finns travel about 40 km per person and day,
  Traficom HLT 2021). Ready on arrival at 17:00, finished by midnight (the benchmark day ends then); without
  scheduling it charges on arrival and finishes as the sauna starts, so "no scheduling" is a plan the household
  could follow. (A first build with 2 h 15 min overlapped the sauna by one slot, which made the no-scheduling plan
  break the limit on every day; changed on 20 Oct 2026, before any campaign.) An 11 kW three-phase charger alone exceeds 8 kW, so it cannot be scheduled
  under a hard limit.
- Sauna, fixed: a 6.8 kW heater (Harvia Virta HL70, for 5-10 m3) heating at 19:00 for 1 h plus 30 min of bathing
  (ELY Centre: 6 kW heater, 1 h heating, 30-40 min bathing). The household chooses when to bathe, so it is not
  shifted: its power is added to the base load (it counts towards the peak, not the cost, as every fixed load),
  and it is listed as a fixed appliance and stated in the request.

The arrival and sauna times are assumptions (no measured Finnish data); they are the same on every day.
"""

from __future__ import annotations

import json
from pathlib import Path

from hems.core.models import FixedAppliance, FlexibleAppliance, Scenario, load_scenarios
from hems.data.factorial import LIMIT_KW
from hems.data.scenarios import build_request
from hems.data.usage import LIMIT_STEP_KW, USAGE_PATH, with_usage_windows
from hems.solvers.milp import solve_milp

EV_KW = 3.7
EV_SLOTS = 8  # 2 h, 7.4 kWh
EV_READY_SLOT = 68  # 17:00
SAUNA_KW = 6.8
SAUNA_START_SLOT = 76  # 19:00
SAUNA_SLOTS = 6  # 1 h heating + 30 min bathing


def electrified(scenario: Scenario) -> Scenario:
    """The heavy-load scenario with the car charge (flexible) and the sauna (fixed) added."""
    prefix, rest = scenario.id.split("-", 1)  # "U", "VH01-80"
    if rest[1] != "H":
        raise ValueError(f"{scenario.id}: only heavy-load scenarios are electrified")
    regime = scenario.type.split("-")[0]
    base = list(scenario.base_load_kw)
    for t in range(SAUNA_START_SLOT, SAUNA_START_SLOT + SAUNA_SLOTS):
        base[t] = round(base[t] + SAUNA_KW, 3)
    car = FlexibleAppliance(id="ev_charger_1", kind="ev_charger", profile_kw=[EV_KW] * EV_SLOTS,
                            earliest_slot=EV_READY_SLOT, deadline_slot=96, default_start_slot=EV_READY_SLOT)  # fmt: skip
    sauna = FixedAppliance(id="sauna", kind="sauna", typical_power_kw=SAUNA_KW)
    limit = scenario.peak_limit_kw
    notes = f"{scenario.notes} Electrified: car charge 3.7 kW from 17:00, sauna 6.8 kW 19:00-20:30 in the base load."
    while True:
        new = scenario.model_copy(update={
            "id": f"{prefix}-{rest[0]}E{rest[2:]}", "type": f"{regime}-electrified-realistic",
            "base_load_kw": base, "appliances": [*scenario.appliances, car],
            "fixed_appliances": [*scenario.fixed_appliances, sauna], "peak_limit_kw": round(limit, 2), "notes": notes,
        })  # fmt: skip
        if solve_milp(new).status == "Optimal":
            break
        limit += LIMIT_STEP_KW
        notes = f"{notes} Peak limit raised to {limit:.2f} kW for feasibility."
    sauna_time = f"{new.slot_to_time(SAUNA_START_SLOT)}-{new.boundary_to_time(SAUNA_START_SLOT + SAUNA_SLOTS)}"
    new.user_request = f"{build_request(new)}\nThe sauna is heated at {sauna_time} (fixed, not to be moved)."
    return Scenario.model_validate(new.model_dump())


def _write_with_electrified(scenarios: list[Scenario], out_dir: str | Path, info: dict) -> dict:
    """Save ``scenarios`` and the electrified version of each heavy-load one; returns the manifest."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    copied, added, raised = [], [], []
    for scenario in scenarios:
        scenario.save(out / f"{scenario.id}.json")
        copied.append(scenario.id)
        if "raised" in scenario.notes:
            raised.append(scenario.id)
        if scenario.type.split("-")[1] == "heavy":
            new = electrified(scenario)
            new.save(out / f"{new.id}.json")
            added.append(new.id)
            if "raised" in new.notes:
                raised.append(new.id)
    manifest = {
        **info,
        "electrified": {"ev_kw": EV_KW, "ev_slots": EV_SLOTS, "ev_ready": "17:00", "ev_finish_by": "24:00",
                        "sauna_kw": SAUNA_KW, "sauna": "19:00-20:30, fixed (in the base load)"},
        "scenarios": len(copied) + len(added), "light_and_heavy": len(copied), "electrified_scenarios": len(added),
        "peak_limit_raised": raised,
    }  # fmt: skip
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def build_electrified_benchmark(source_dir: str | Path, out_dir: str | Path) -> dict:
    """Every scenario of ``source_dir`` (copied unchanged) plus the electrified version of each heavy-load day."""
    info = {"design": "v3 plus an electrified load on every heavy-load day (hems.data.electrified)",
            "source_set": str(source_dir)}  # fmt: skip
    return _write_with_electrified(load_scenarios(source_dir), out_dir, info)


def build_heldout(source_dir: str | Path, out_dir: str | Path, prefix: str = "Q3",
                  usage_path: str | Path = USAGE_PATH) -> dict:  # fmt: skip
    """The held-out set Q3: the 8 kW scenarios of the Q2 days with the v3 windows (usual run times), plus the
    electrified version of each heavy day, as v4 is built from v2. Ids "Q2-PH01-80" -> "Q3-PH01-80" / "Q3-PE01-80".

    Built on 21 Oct 2026, before any run of the two-agent design on these days (the registered Q2 run used the
    four-agent design, other windows and the 3.5 kW level as well); the Q2 days are in no other benchmark and not in
    the case library.
    """
    usage = json.loads(Path(usage_path).read_text(encoding="utf-8"))
    scenarios = [
        with_usage_windows(s.model_copy(update={"id": f"{prefix}-{s.id.split('-', 1)[1]}"}), usage, id_prefix="")
        for s in load_scenarios(source_dir) if s.peak_limit_kw >= LIMIT_KW
    ]  # fmt: skip
    info = {"design": "held-out: Q2 days, 8 kW, windows from usual run times, plus an electrified load on every "
                      "heavy-load day (hems.data.electrified.build_heldout)",
            "source_set": str(source_dir), "usage_times": str(usage_path), "id_prefix": prefix}  # fmt: skip
    return _write_with_electrified(scenarios, out_dir, info)
