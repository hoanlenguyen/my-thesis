"""tools/emhass_rest.py: request building and plan parsing (offline, no EMHASS service needed)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from hems.core.models import Scenario

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("emhass_rest", ROOT / "tools" / "emhass_rest.py")
emhass_rest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(emhass_rest)


def test_runtime_params_describe_the_scenario(scenario: Scenario) -> None:
    raw = json.loads(scenario.model_dump_json())
    k = len(scenario.appliances)
    profile = emhass_rest.runtime_params(raw, "profile")
    assert profile["optimization_time_step"] == 15 and profile["number_of_deferrable_loads"] == k
    assert profile["maximum_power_from_grid"] == scenario.peak_limit_kw * 1000
    assert len(profile["load_cost_forecast"]) == len(profile["load_power_forecast"]) == 96
    assert profile["start_timesteps_of_each_deferrable_load"] == [a.earliest_slot for a in scenario.appliances]
    assert profile["end_timesteps_of_each_deferrable_load"] == [a.deadline_slot for a in scenario.appliances]
    assert all(isinstance(p, list) for p in profile["nominal_power_of_deferrable_loads"])  # measured profiles
    nominal = emhass_rest.runtime_params(raw, "nominal")
    assert nominal["nominal_power_of_deferrable_loads"] == [round(a.peak_kw * 1000, 1) for a in scenario.appliances]
    assert all(nominal["set_deferrable_load_single_constant"])
    assert not any(key.startswith("lp_solver") for key in profile)  # the service keeps its default solver settings


def test_starts_are_read_from_the_plan(scenario: Scenario) -> None:
    raw = json.loads(scenario.model_dump_json())
    rows = [{"optim_status": "Optimal", **{f"P_deferrable{i}": 0.0 for i in range(len(raw["appliances"]))}} for _ in range(96)]
    rows[40]["P_deferrable0"] = rows[41]["P_deferrable0"] = 1500.0
    starts, status = emhass_rest.starts_from_plan({"plan": rows}, raw)
    assert status == "Optimal" and starts[raw["appliances"][0]["id"]] == 40
    assert all(starts[a["id"]] is None for a in raw["appliances"][1:])
    _, short = emhass_rest.starts_from_plan({"plan": rows[:90]}, raw)
    assert short.startswith("plan has 90 steps")
