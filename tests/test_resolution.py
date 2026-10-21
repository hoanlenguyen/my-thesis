"""The 15-minute price analysis by condition (hems.analysis.resolution.condition_summary), on stand-in rows."""

from __future__ import annotations

import pandas as pd
import pytest

from hems.analysis.resolution import condition_summary, thesis_table


def _row(scenario_type: str, naive: float, hourly: float, opt: float) -> dict:
    return {"scenario_id": scenario_type, "scenario_type": scenario_type, "intra_hour_spread_c_kwh": 1.0,
            "naive_eur": naive, "hourly_plan_eur": hourly, "opt_15_eur": opt, "value_15min_eur": hourly - opt}  # fmt: skip


def test_rows_by_pattern_then_load_then_all_weighted_by_cost() -> None:
    rows = pd.DataFrame([
        _row("stable-light-realistic", 1.0, 0.9, 0.8),
        _row("spike-electrified-realistic", 3.0, 2.0, 2.0),
    ])  # fmt: skip
    table = condition_summary(rows)
    assert list(table.scenario_type) == ["Stable prices", "Price spike", "Light load", "Electrified load", "All"]
    everything = table.set_index("scenario_type").loc["All"]
    assert everything.saving_opt_15_pct == pytest.approx((4.0 - 2.8) / 4.0 * 100)  # cost-weighted, not a mean of %
    assert everything.share_of_saving_pct == pytest.approx(0.1 / 1.2 * 100)
    assert everything.scenarios_improved == 1 and everything.scenarios == 2
    latex = thesis_table(table, "Condition", "2 scenarios")
    assert latex.count(r"\midrule") == 3 and "(MILP, 2 scenarios)" in latex  # header, patterns | loads, All
