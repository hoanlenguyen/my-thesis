"""Windows from the households' usual run times (hems.data.usage), with made-up usage times (no raw REFIT data)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from hems.core.evaluate import evaluate
from hems.core.models import load_scenarios
from hems.data import refit
from hems.data.usage import MIN_SLACK_SLOTS, usage_times, window, with_usage_windows
from hems.solvers.milp import solve_milp

USAGE = usage_times({
    1: {"washing_machine": [600, 630, 660, 720, 780], "dishwasher": [1140, 1170, 1200, 1230]},
    2: {"washing_machine": [480, 540, 600], "tumble_dryer": [840, 900, 960]},
})  # fmt: skip


def test_detect_cycles_is_unchanged_by_the_start_times() -> None:
    minutes = pd.date_range("2014-01-01 10:00", periods=600, freq="1min")
    watts = pd.Series(0.0, index=minutes)
    watts.iloc[30:120] = 1500.0  # one 90-minute cycle starting at 10:30
    watts.iloc[300:345] = 800.0  # one 45-minute cycle starting at 15:00
    timed = refit.timed_cycles(watts)
    assert refit.detect_cycles(watts) == [profile for _start, profile in timed]
    assert [t.strftime("%H:%M") for t, _p in timed] == ["10:30", "15:00"]


def test_the_percentiles_and_the_fallback_over_households() -> None:
    assert USAGE["houses"]["1"]["washing_machine"] == {"cycles": 5, "p25_min": 630, "p50_min": 660, "p75_min": 720}
    assert USAGE["pooled"]["washing_machine"]["houses"] == 2  # both households own one
    assert "dishwasher" not in USAGE["houses"]["2"] and USAGE["pooled"]["dishwasher"]["houses"] == 1


def test_window_rule() -> None:
    earliest, deadline, source = window(USAGE, 1, "washing_machine", duration_slots=6)
    assert (earliest, source) == (630 // 15, "house 1")  # ready at the 25th percentile (10:30)
    assert deadline == max(720 // 15 + 6, earliest + 6 + MIN_SLACK_SLOTS)  # p75 start + cycle, at least 2 h of slack
    _e, _d, fallback = window(USAGE, 2, "dishwasher", duration_slots=6)
    assert fallback == "all households"  # house 2 owns no dishwasher
    late_e, late_d, _s = window({"houses": {"9": {"dishwasher": {"p25_min": 1410, "p75_min": 1425}}}, "pooled": {}},
                                9, "dishwasher", duration_slots=8)  # fmt: skip
    assert late_d == 96 and late_d - late_e >= 8 + MIN_SLACK_SLOTS  # a late habit: ready earlier, never past midnight


def test_a_factorial_scenario_gets_the_household_windows_and_stays_solvable() -> None:
    scenario = next(s for s in load_scenarios("data/scenarios_v2") if "REFIT house 1." in s.notes)
    new = with_usage_windows(scenario, USAGE)
    assert new.id == f"U-{scenario.id}" and new.date == scenario.date and new.price_eur_per_kwh == scenario.price_eur_per_kwh
    assert [a.profile_kw for a in new.appliances] == [a.profile_kw for a in scenario.appliances]  # same cycles
    for a in new.appliances:
        assert (a.earliest_slot, a.deadline_slot) == window(USAGE, 1, a.kind, a.duration_slots)[:2]
        assert a.default_start_slot == a.earliest_slot  # no scheduling = start when ready, as before
    assert solve_milp(new).status == "Optimal"
    assert evaluate(new, solve_milp(new).schedule).feasible
    first = new.appliances[0]
    assert f"ready from {new.slot_to_time(first.earliest_slot)}" in new.user_request  # the request states the new window
    assert new.peak_limit_kw >= scenario.peak_limit_kw and np.isfinite(new.peak_limit_kw)
