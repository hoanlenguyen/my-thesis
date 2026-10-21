"""Benchmark v4 (hems.data.electrified): a car charge and a fixed sauna added to the heavy-load days of v3."""

from __future__ import annotations

import pytest

from hems.core.evaluate import evaluate
from hems.core.models import load_scenarios
from hems.data.electrified import EV_KW, EV_SLOTS, SAUNA_KW, SAUNA_SLOTS, SAUNA_START_SLOT, electrified
from hems.solvers.milp import solve_milp

V3 = {s.id: s for s in load_scenarios("data/scenarios_v3")}


def test_the_electrified_day_keeps_the_heavy_day_and_adds_the_car_and_the_sauna() -> None:
    heavy = V3["U-VH01-80"]
    new = electrified(heavy)
    assert (new.id, new.type) == ("U-VE01-80", "volatile-electrified-realistic")
    assert new.date == heavy.date and new.price_eur_per_kwh == heavy.price_eur_per_kwh and new.peak_limit_kw == 8.0
    assert new.appliances[:-1] == heavy.appliances
    car = new.appliances[-1]
    assert (car.kind, car.peak_kw, car.duration_slots) == ("ev_charger", EV_KW, EV_SLOTS)
    assert (new.slot_to_time(car.earliest_slot), car.deadline_slot, car.default_start_slot) == ("17:00", 96, 68)
    sauna = range(SAUNA_START_SLOT, SAUNA_START_SLOT + SAUNA_SLOTS)
    for t in range(96):  # the sauna is a fixed load: in the base load at 19:00-20:30 only
        extra = SAUNA_KW if t in sauna else 0.0
        assert new.base_load_kw[t] == pytest.approx(heavy.base_load_kw[t] + extra, abs=1e-6)
    assert new.fixed_appliances[-1].kind == "sauna"
    assert "electric car charging (ev_charger_1): ready from 17:00, must finish by 24:00" in new.user_request
    assert "sauna is heated at 19:00-20:30 (fixed" in new.user_request


def test_the_car_must_avoid_the_sauna_and_the_day_stays_solvable() -> None:
    new = electrified(V3["U-VH01-80"])
    car = new.appliance("ev_charger_1")
    assert car.default_start_slot + car.duration_slots == SAUNA_START_SLOT  # charging on arrival ends as the sauna starts
    during_sauna = {**{a.id: a.default_start_slot for a in new.appliances}, "ev_charger_1": SAUNA_START_SLOT}
    assert not evaluate(new, during_sauna).feasible  # 3.7 kW on top of the 6.8 kW sauna exceeds 8 kW
    best = solve_milp(new)
    assert best.status == "Optimal" and evaluate(new, best.schedule).feasible
    start = best.schedule["ev_charger_1"]
    assert start + EV_SLOTS <= SAUNA_START_SLOT or start >= SAUNA_START_SLOT + SAUNA_SLOTS


def test_only_heavy_days_are_electrified() -> None:
    with pytest.raises(ValueError, match="only heavy-load"):
        electrified(V3["U-VL01-80"])


def test_the_held_out_set_q3_is_built_from_the_q2_days_like_v4_from_v2() -> None:
    import json

    from hems.data.usage import USAGE_PATH, with_usage_windows

    q3 = {s.id: s for s in load_scenarios("data/scenarios_q3")}
    q2 = {s.id: s for s in load_scenarios("data/scenarios_q2") if s.id.endswith("-80")}
    assert len(q3) == 72 and sum("-electrified-" in s.type for s in q3.values()) == 24
    usage = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
    for source_id in list(q2)[:4]:  # "Q2-NH01-80" -> "Q3-NH01-80": same day, prices and cycles, the v3 windows
        source = q2[source_id]
        new = q3[f"Q3-{source_id.split('-', 1)[1]}"]
        assert new.date == source.date and new.price_eur_per_kwh == source.price_eur_per_kwh
        assert new == with_usage_windows(source.model_copy(update={"id": new.id}), usage, id_prefix="")
    others = {s.date for d in ("data/scenarios", "data/scenarios_15min", "data/scenarios_v4") for s in load_scenarios(d)}
    assert not {s.date for s in q3.values()} & others  # held out: no day of any other benchmark


def test_benchmark_v4_holds_v3_and_one_electrified_day_per_heavy_day() -> None:
    v4 = {s.id: s for s in load_scenarios("data/scenarios_v4")}
    assert len(v4) == 72 and all(v4[i] == s for i, s in V3.items())  # v3 unchanged, so its results carry over
    heavy = [i for i in V3 if i[3] == "H"]  # "U-VH01-80" -> "U-VE01-80"
    assert sorted(i for i in v4 if i not in V3) == sorted(f"{i[:3]}E{i[4:]}" for i in heavy)
    assert all(v4[f"{i[:3]}E{i[4:]}"] == electrified(V3[i]) for i in heavy[:3])
