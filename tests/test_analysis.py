"""Analysis pipeline on a runs file built from real reference runs and stand-in agent rows."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from hems.analysis import metrics, stats
from hems.analysis.report import write_report
from hems.data.synthetic import generate
from hems.run import execute, run_batch, completed_keys


def test_wilcoxon_detects_consistent_improvement() -> None:
    rng = np.random.default_rng(0)
    single = pd.Series(rng.uniform(5, 15, 48))
    multi = single - rng.uniform(1, 3, 48)
    result = stats.wilcoxon_paired(multi, single)
    assert result["n"] == 48 and result["p"] < 1e-6 and result["r"] > 0.5 and result["median_diff"] < 0


def test_tost_concludes_equivalence_only_inside_the_margin() -> None:
    rng = np.random.default_rng(1)
    single = pd.Series(rng.uniform(0, 10, 48))
    close = stats.tost_paired(single + rng.normal(0, 0.3, 48), single, margin=1.0)
    assert close["equivalent"] and close["ci90_low"] > -1 and close["ci90_high"] < 1
    shifted = stats.tost_paired(single + 2 + rng.normal(0, 0.3, 48), single, margin=1.0)
    assert not shifted["equivalent"] and shifted["p_tost_t"] > 0.5


def test_latex_number_format() -> None:
    from hems.analysis.report import _fmt

    assert [_fmt(v) for v in (0.0, -0.0, 10.0, 0.5, 1e-4, float("nan"))] == ["0", "0", "10", "0.5", "0.0001", "--"]


def test_holm_adjustment() -> None:
    from hems.analysis.confirm import holm

    assert np.allclose(holm([0.01, 0.04, 0.03]), [0.03, 0.06, 0.06])
    assert holm([0.5]) == [0.5]


def test_q2_confirmatory_tests_on_stand_in_means() -> None:
    from hems.analysis import confirm_q2 as q2

    rng = np.random.default_rng(1)
    n = 48
    emhass = rng.uniform(10, 40, n)
    systems = {  # (model, system) -> (saving_pct, validity rate, latency_s, cost_usd)
        q2.EMHASS: (emhass, 1.0, 1, 0),
        q2.PIPELINE: (emhass + rng.normal(0, 0.1, n), 1.0, 17, 0.003),
        q2.WINDOW: (emhass - rng.uniform(5, 20, n), 0.6, 0, 0),
        q2.HOURS: (emhass - rng.uniform(5, 20, n), 0.6, 0, 0),
        q2.ONESHOT: (rng.uniform(0, 5, n), 0.0, 2, 0.0005),
    }
    rows = [
        {"model": m, "system": s, "scenario_id": f"S{i:02d}", "saving_pct": v[0][i],
         "feasible_rate": min(1.0, v[1] + (0.67 if s == "oneshot" and i % 3 == 0 else 0)),
         "latency_s": v[2] + rng.uniform(0, 1), "cost_usd": v[3] * rng.uniform(0.9, 1.1)}
        for (m, s), v in systems.items() for i in range(n)
    ]  # fmt: skip
    result = q2.confirmatory_tests(pd.DataFrame(rows))
    assert len(result) == 7 and set(result.sq) == {"SQ1", "SQ2"}
    assert result.supported.all()


def test_report_end_to_end(tmp_path) -> None:
    scenarios = generate(tmp_path / "scen", per_type=2, seed=3)
    runs_path = tmp_path / "runs.jsonl"
    run_batch(scenarios, ["milp", "naive"], [], 0, runs_path)
    assert len(completed_keys(runs_path)) == 2 * len(scenarios)

    # stand-in agents: "multi" reproduces the MILP schedule, "single" the naive one
    with runs_path.open("a", encoding="utf-8") as fh:
        for scenario in scenarios:
            for system, source in (("multi", "milp"), ("single", "naive")):
                for run in (1, 2):
                    record = execute(scenario, source)
                    record.update(system=system, model="gpt-4o-mini", run=run, key=f"{system}|gpt-4o-mini|{scenario.id}|{run}")
                    fh.write(json.dumps(record) + "\n")

    results = write_report(runs_path, {s.id: s for s in scenarios}, tmp_path / "out")
    scored = metrics.scored_runs(metrics.load_runs(runs_path))
    multi = scored[scored.system == "multi"]
    assert np.allclose(multi.gap_pct, 0)
    single = scored[scored.system == "single"]
    assert (single.gap_pct >= 0).all()  # infeasible naive runs are scored at naive cost
    assert (tmp_path / "out" / "tables" / "wilcoxon.tex").exists()
    assert (tmp_path / "out" / "figures" / "gap_by_type.pdf").exists()
    overall = results["wilcoxon"].query("scope == 'all'").iloc[0]
    assert overall["median_diff"] < 0
    assert set(results["conflict_resolution"].system) == {"single", "multi"}
    assert list(results["equivalence"].margin) == list(stats.EQUIVALENCE_MARGINS)
    assert set(results["efficiency_tests"].metric) == set(stats.EFFICIENCY_METRICS)


def test_pooled_savings_captured_is_robust_to_a_near_zero_achievable_saving() -> None:
    scored = pd.DataFrame({
        "model": ["-"] * 2, "system": ["x"] * 2,
        "naive_cost": [1.00, 0.5001], "milp_cost": [0.80, 0.5000], "scored_cost": [0.80, 0.5101],
    })  # fmt: skip
    pooled = metrics.pooled_savings_captured(scored).savings_captured_pooled.iloc[0]
    assert pooled == pytest.approx((1.5001 - 1.3101) / (1.5001 - 1.3000))  # ~0.95, not dragged to -50
