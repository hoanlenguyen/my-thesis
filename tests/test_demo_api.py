"""Demo API: a profile entered in the browser becomes a scenario and is scheduled by the real systems."""

from __future__ import annotations

import numpy as np
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from hems import demo_api  # noqa: E402


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    prices = 0.05 + 0.04 * np.sin(np.linspace(0, 2 * np.pi, 96))  # synthetic day, no network
    monkeypatch.setattr(demo_api, "day_prices", lambda _day: prices)
    monkeypatch.setattr(demo_api, "_emhass", lambda _scenario: None)
    return TestClient(demo_api.app)


PROFILE = {
    "date": "2026-01-15", "housing": "house", "peak_limit_kw": 3.5,
    "appliances": [
        {"kind": "washing_machine", "ready": "08:00", "finish_by": "22:00"},
        {"kind": "tumble_dryer", "ready": "08:00", "finish_by": "24:00"},
        {"kind": "dishwasher", "ready": "18:00", "finish_by": "24:00"},
    ],
}  # fmt: skip


def test_catalog_lists_measured_and_constant_appliances(client: TestClient) -> None:
    items = {a["kind"]: a for a in client.get("/api/catalog").json()["appliances"]}
    assert items["washing_machine"]["measured"] and not items["ev_charger"]["measured"]
    assert items["ev_charger"]["peakKw"] == 7.0 and items["ev_charger"]["durationMin"] == 240


def test_tools_schedule_the_profile_and_report_savings(client: TestClient) -> None:
    out = client.post("/api/plan/tools", json=PROFILE).json()
    assert len(out["appliances"]) == 3 and len(out["priceEurPerKwh"]) == 96
    assert out["baseLoad"]["source"] == "refit"
    results = {r["system"]: r for r in out["results"]}
    assert set(results) == {"naive", "milp", "timer", "cheapest_hours", "cheapest_window"}
    assert results["milp"]["feasible"] and results["milp"]["savingPct"] >= results["timer"]["savingPct"] - 1e-9
    assert results["naive"]["savingEur"] == 0
    assert set(results["milp"]["starts"]) == {a["id"] for a in out["appliances"]}
    for r in out["results"]:  # cost = energy + fee, and the optimum is never beaten
        assert abs(r["costEur"] - r["energyEur"] - r["feeEur"]) < 1e-3
        assert r["costEur"] >= results["milp"]["costEur"] - 1e-6


def test_exceeding_the_limit_is_allowed_and_charged(client: TestClient) -> None:
    ev = {**PROFILE, "appliances": [{"kind": "ev_charger", "ready": "18:00", "finish_by": "24:00"}]}
    out = client.post("/api/plan/tools", json=ev).json()
    best = next(r for r in out["results"] if r["system"] == "milp")
    assert best["feasible"] and best["overKw"] > 3 and best["feeEur"] == pytest.approx(1.97 * best["overKw"], abs=0.01)


def test_the_optimum_trades_the_fee_against_energy(client: TestClient) -> None:
    free = client.post("/api/plan/tools", json={**PROFILE, "fee_eur_per_kw": 0}).json()
    dear = client.post("/api/plan/tools", json={**PROFILE, "fee_eur_per_kw": 100}).json()
    best = lambda out: next(r for r in out["results"] if r["system"] == "milp")  # noqa: E731
    assert best(free)["energyEur"] <= best(dear)["energyEur"] + 1e-9  # no fee: cheapest energy, any peak
    assert best(dear)["overKw"] == 0  # a high fee keeps the schedule under the limit when that is possible


def test_profile_errors_are_explained(client: TestClient) -> None:
    short = {**PROFILE, "appliances": [{"kind": "washing_machine", "ready": "08:00", "finish_by": "08:30"}]}
    assert "shorter than" in client.post("/api/plan/tools", json=short).json()["detail"]


def test_a_measured_cycle_keeps_its_shape_at_a_new_runtime_and_power() -> None:
    measured = demo_api.typical_cycles()["washing_machine"]
    assert demo_api.cycle_for("washing_machine", None, None) == measured  # defaults: the exact REFIT cycle
    longer = demo_api.cycle_for("washing_machine", 2.0, len(measured) * 15 * 2)
    assert len(longer) == 2 * len(measured)
    assert max(longer) == pytest.approx(2.0, abs=1e-3)
    assert np.argmax(longer) // 2 == pytest.approx(np.argmax(measured), abs=1)  # the peak stays in the same phase


def test_a_constant_appliance_uses_the_entered_runtime_and_power(client: TestClient) -> None:
    sauna = {**PROFILE, "appliances": [{"kind": "sauna", "ready": "16:00", "finish_by": "22:00", "power_kw": 9, "duration_min": 90}]}
    out = client.post("/api/plan/tools", json=sauna).json()
    profile = out["appliances"][0]["profileKw"]
    assert profile == [9.0] * 6


def test_runtime_and_power_are_validated(client: TestClient) -> None:
    bad = {**PROFILE, "appliances": [{"kind": "dishwasher", "ready": "08:00", "finish_by": "22:00", "power_kw": 0}]}
    assert client.post("/api/plan/tools", json=bad).status_code == 422
