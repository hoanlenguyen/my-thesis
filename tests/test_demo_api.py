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


TWO_PERIODS = [{"start": "06:00", "end": "09:00"}, {"start": "18:00", "end": "22:00"}]


def test_several_periods_keep_every_cycle_inside_one(client: TestClient) -> None:
    body = {**PROFILE, "appliances": [{"kind": "dishwasher", "periods": TWO_PERIODS},
                                      {"kind": "washing_machine", "periods": TWO_PERIODS}]}  # fmt: skip
    out = client.post("/api/plan/tools", json=body).json()
    assert [a["periods"] for a in out["appliances"]] == [[[24, 36], [72, 88]]] * 2
    assert out["emhassSkipped"] == "periods" and not out["emhass"]
    durations = {a["id"]: len(a["profileKw"]) for a in out["appliances"]}
    for r in out["results"]:
        for appliance_id, start in r["starts"].items():
            slot = int(start[:2]) * 4 + int(start[3:]) // 15 if isinstance(start, str) else start
            assert any(p0 <= slot and slot + durations[appliance_id] <= p1 for p0, p1 in ((24, 36), (72, 88))), r["system"]


def test_the_request_names_the_periods(client: TestClient) -> None:
    body = {**PROFILE, "appliances": [{"kind": "dishwasher", "periods": TWO_PERIODS}]}
    scenario, _ = demo_api.build_scenario(demo_api.PlanIn.model_validate(body))
    assert "may run only within 06:00-09:00 or 18:00-22:00" in scenario.user_request


def test_one_period_is_the_old_single_window(client: TestClient) -> None:
    one = {**PROFILE, "appliances": [{"kind": "dishwasher", "periods": [{"start": "08:00", "end": "22:00"}]}]}
    old = {**PROFILE, "appliances": [{"kind": "dishwasher", "ready": "08:00", "finish_by": "22:00"}]}
    a_new, _ = demo_api.build_scenario(demo_api.PlanIn.model_validate(one))
    a_old, _ = demo_api.build_scenario(demo_api.PlanIn.model_validate(old))
    assert a_new.appliances[0].windows is None and a_new.model_dump() == a_old.model_dump()


def test_overlapping_periods_are_merged_and_short_ones_rejected(client: TestClient) -> None:
    merged = {**PROFILE, "appliances": [{"kind": "dishwasher", "periods": [
        {"start": "06:00", "end": "10:00"}, {"start": "09:00", "end": "12:00"}, {"start": "18:00", "end": "22:00"}]}]}  # fmt: skip
    scenario, _ = demo_api.build_scenario(demo_api.PlanIn.model_validate(merged))
    assert scenario.appliances[0].windows == [(24, 48), (72, 88)]
    short = {**PROFILE, "appliances": [{"kind": "dishwasher", "periods": [{"start": "06:00", "end": "06:30"}, TWO_PERIODS[1]]}]}
    response = client.post("/api/plan/tools", json=short)
    assert response.status_code == 422 and "06:00-06:30 is shorter than" in response.json()["detail"]


def test_the_summary_states_the_saving_shown_on_the_page(client: TestClient) -> None:
    """The pipeline's summary gets the page's figures: energy plus the fee above the limit, against no scheduling."""
    body = {**PROFILE, "appliances": [{"kind": "ev_charger", "ready": "18:00", "finish_by": "24:00"},
                                      {"kind": "dishwasher", "ready": "18:00", "finish_by": "24:00"}]}  # fmt: skip
    plan = demo_api.PlanIn.model_validate(body)
    scenario, _ = demo_api.build_scenario(plan)
    out = client.post("/api/plan/tools", json=body).json()
    best = next(r for r in out["results"] if r["system"] == "milp")
    facts = demo_api._summary_costs(scenario, plan.fee_eur_per_kw)
    best_slots = demo_api.optimum_with_fee(scenario, plan.fee_eur_per_kw)
    assert f"Saving: EUR {best['savingEur']:.3f}" in facts(best_slots)
    naive_text = facts({a.id: a.default_start_slot for a in scenario.appliances})
    assert "Saving: EUR 0.000" in naive_text and "plus a fee of EUR" in naive_text  # no scheduling exceeds 3.5 kW


def test_the_recommendation_has_a_fixed_form_built_from_the_scored_schedule(client: TestClient) -> None:
    body = {**PROFILE, "appliances": [{"kind": "dishwasher", "periods": TWO_PERIODS},
                                      {"kind": "washing_machine", "ready": "08:00", "finish_by": "22:00"}]}  # fmt: skip
    scenario, _ = demo_api.build_scenario(demo_api.PlanIn.model_validate(body))
    out = client.post("/api/plan/tools", json=body).json()
    result = next(r for r in out["results"] if r["system"] == "milp") | {"message": "Your appliances are set."}
    rec = demo_api._recommendation(scenario, result)
    assert set(rec) == {"message", "schedules", "cost", "saving", "savingPct", "currency", "currencySymbol", "peakKw",
                        "peakLimitKw", "valid", "date"}  # fmt: skip
    assert rec["message"] == "Your appliances are set." and rec["valid"]
    assert rec["currency"] == "EUR" and rec["currencySymbol"] == "€"
    assert rec["cost"] == result["costEur"] and rec["saving"] == result["savingEur"]
    items = rec["schedules"]
    assert [i["applianceId"] for i in items] == sorted(result["starts"], key=lambda k: (result["starts"][k], k))
    assert sum(i["cost"] for i in items) == pytest.approx(result["energyEur"], abs=1e-3)
    dish = next(i for i in items if i["applianceId"] == "dishwasher_1")
    assert dish["appliance"] == "Dishwasher" and dish["period"] in {"06:00-09:00", "18:00-22:00"}
    assert dish["period"].split("-")[0] <= dish["start"] and dish["end"] <= dish["period"].split("-")[1]
    assert "Recommendation" in client.get("/openapi.json").json()["components"]["schemas"]
