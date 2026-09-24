"""Analysis pipeline on a runs file built from real reference runs and stand-in agent rows."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

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
