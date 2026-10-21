"""The registered tests on Q3 (hems.analysis.confirm_q3), on stand-in per-scenario means (no run files)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from hems.analysis import confirm_q3 as q3

LOADS = ["light"] * 24 + ["heavy"] * 24 + ["electrified"] * 24


def _means(*, rule_gap_electrified: float, rule_gap_other: float, pipeline_offset: np.ndarray | float = 0.0,
           same_rules: bool = False, seed: int = 1) -> pd.DataFrame:  # fmt: skip
    rng = np.random.default_rng(seed)
    n = len(LOADS)
    best = rng.uniform(10, 25, n)
    gap = np.array([rule_gap_electrified if load == "electrified" else rule_gap_other for load in LOADS])
    rule = best if same_rules else best - gap * rng.uniform(0.5, 1.5, n)
    systems = {  # (model, system) -> (saving_pct, validity rate, latency_s, cost_usd)
        q3.EMHASS: (best, 1.0, 1, 0),
        q3.PIPELINE: (best + pipeline_offset, 1.0, 8, 0.0004),
        q3.WINDOW: (rule, 0.8, 0, 0),
        q3.HOURS: (rule - (0 if same_rules else 1), 0.6, 0, 0),
        q3.ONESHOT: (rng.uniform(0, 8, n), 0.0, 2, 0.0002),
    }
    return pd.DataFrame([
        {"model": m, "system": s, "scenario_id": f"Q3-X{i:02d}-80", "scenario_type": f"spike-{LOADS[i]}-realistic",
         "saving_pct": v[0][i], "feasible_rate": min(1.0, v[1] + (0.67 if s == "oneshot" and i % 3 == 0 else 0)),
         "latency_s": v[2] + rng.uniform(0, 1), "cost_usd": v[3] * rng.uniform(0.9, 1.1)}
        for (m, s), v in systems.items() for i in range(n)
    ])  # fmt: skip


def test_nine_tests_in_two_families_all_supported_when_the_pipeline_matches_emhass_exactly() -> None:
    result = q3.confirmatory_tests(_means(rule_gap_electrified=10, rule_gap_other=2))
    assert len(result) == 9 and list(result.sq).count("SQ1") == 4 and list(result.sq).count("SQ2") == 5
    h2c = result[result.hypothesis.str.startswith("H2c")].iloc[0]
    assert h2c.p == 0.0 and "all differences zero" in h2c.ci90  # identical savings: equivalence by the CI [0, 0]
    assert result.supported.all(), result[["hypothesis", "p_holm", "direction_ok"]]


def test_equivalence_uses_the_t_tost_when_the_differences_vary() -> None:
    offset = np.random.default_rng(5).normal(0, 0.2, len(LOADS))
    h2c = q3.confirmatory_tests(_means(rule_gap_electrified=10, rule_gap_other=2, pipeline_offset=offset))
    h2c = h2c[h2c.hypothesis.str.startswith("H2c")].iloc[0]
    assert h2c.supported and h2c.ci90.startswith("[-") and "zero" not in h2c.ci90


def test_no_difference_from_the_rules_is_not_supported() -> None:
    result = q3.confirmatory_tests(_means(rule_gap_electrified=0, rule_gap_other=0, same_rules=True))
    result = result.set_index("hypothesis")
    h2a = result.loc["H2a pipeline > cheapest_window (saving)"]
    assert h2a.p == 1.0 and not h2a.supported  # all ties: the Wilcoxon test is undefined and counts as p = 1
    assert not result.loc["H2e advantage over cheapest_window larger on electrified days"].supported


def test_a_smaller_advantage_on_electrified_days_is_not_supported() -> None:
    result = q3.confirmatory_tests(_means(rule_gap_electrified=1, rule_gap_other=8)).set_index("hypothesis")
    for label in ("H2d advantage over cheapest_hours larger on electrified days",
                  "H2e advantage over cheapest_window larger on electrified days"):  # fmt: skip
        row = result.loc[label]
        assert row.estimate < 0 and row.effect < 0 and not row.direction_ok and not row.supported
    assert result.loc["H2a pipeline > cheapest_window (saving)"].supported  # the overall advantage still holds
