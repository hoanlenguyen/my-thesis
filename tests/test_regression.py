"""Recorded thesis results must stay reproducible after refactors.

Recomputes the deterministic systems on the real benchmarks and compares them with the records
in results/ (skipped where those files or the EMHASS environment are absent). The language-model
systems cannot be recomputed; their records are covered by the wiring tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hems.core.models import load_scenarios
from hems.run import execute, read_records
from hems.solvers.emhass import emhass_python

ROOT = Path(__file__).resolve().parents[1]
RESULT_FILES = [
    "results/runs.jsonl",
    "results/baselines.jsonl",
    "results/confirmation.jsonl",
    "results/tools/scenarios.jsonl",
    "results/tools/scenarios_15min.jsonl",
]
RULES = ("naive", "timer", "cheapest_hours")


def _scenarios() -> dict:
    found = {}
    for folder in ("data/scenarios", "data/scenarios_15min"):
        if (ROOT / folder).exists():
            found |= {s.id: s for s in load_scenarios(ROOT / folder)}
    return found


def _records(systems: tuple[str, ...]) -> list[dict]:
    rows = [r for f in RESULT_FILES for r in read_records(ROOT / f) if r["system"] in systems]
    if not rows:
        pytest.skip("no recorded results in results/")
    return rows


def _same(record: dict, fresh: dict) -> None:
    assert fresh["schedule_slots"] == record["schedule_slots"], record["key"]
    assert fresh["cost_eur"] == pytest.approx(record["cost_eur"], abs=1e-12), record["key"]
    assert fresh["feasible"] == record["feasible"], record["key"]
    assert fresh["violations"] == record["violations"], record["key"]


def test_rule_based_records_are_reproduced_exactly() -> None:
    scenarios = _scenarios()
    for record in _records(RULES):
        _same(record, execute(scenarios[record["scenario_id"]], record["system"]))


def test_milp_optimum_is_reproduced() -> None:
    scenarios = _scenarios()
    for record in _records(("milp",)):  # ties may pick another optimal schedule: compare the optimum
        fresh = execute(scenarios[record["scenario_id"]], "milp")
        assert fresh["cost_eur"] == pytest.approx(record["cost_eur"], abs=1e-9) and fresh["feasible"], record["key"]


@pytest.mark.skipif(not emhass_python().exists(), reason="EMHASS environment .venv-emhass not installed")
@pytest.mark.parametrize("system", ["emhass", "emhass_nominal"])
def test_emhass_through_the_runner_matches_the_imported_records(system: str) -> None:
    scenarios = _scenarios()
    records = {r["scenario_id"]: r for r in _records((system,))}
    for scenario_id in ("D01", "Q-E03"):  # one per benchmark: each call starts EMHASS (a few seconds)
        if scenario_id in records:
            fresh = execute(scenarios[scenario_id], system)
            _same(records[scenario_id], fresh)
            assert fresh["tool_config"] == ("profile" if system == "emhass" else "nominal")
