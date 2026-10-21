"""Confirmatory tests on the held-out set Q3 (docs/preregistration_q3.md).

Do not change this file after that registration is committed: the confirmatory result is
whatever these functions return on the Q3 run files.

    uv run python -m hems.analysis.confirm_q3      # prints the table, writes results/confirmation_q3/tests.csv
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from hems.analysis import metrics, stats
from hems.analysis.confirm import holm

MODEL = "gpt-6-luna"
ALPHA = 0.05
MARGIN_PP = 1.0  # equivalence margin on the per-scenario saving, percentage points of the naive cost
RUN_FILES = ("results/confirmation_q3.jsonl", "results/tools/scenarios_q3.jsonl")
OUT = Path("results/confirmation_q3/tests.csv")
ZERO = 1e-9  # differences below this are ties (both systems at the same cost)

LATENCY_LIMIT_S = 60.0  # design objectives of Section 4.1: a recommendation within 60 s and under $0.10
COST_LIMIT_USD = 0.10

# The pipeline is the two-agent design (iteration 14); the single agent in the harness is reported without hypotheses.
PIPELINE, ONESHOT = (MODEL, "multi_duo"), (MODEL, "oneshot")
EMHASS, WINDOW, HOURS = ("-", "emhass_rest"), ("-", "cheapest_window"), ("-", "cheapest_hours")
ELECTRIFIED = "electrified"  # the household load in the scenario type "<pattern>-<load>-realistic"


def _paired(means: pd.DataFrame, a: tuple[str, str], b: tuple[str, str], value: str) -> tuple[pd.Series, pd.Series]:
    wide = means.pivot_table(index="scenario_id", columns=["model", "system"], values=value)
    return wide[a], wide[b]


def _p(value: float) -> float:
    """A test that cannot be computed (e.g. every difference zero) counts as p = 1: no effect shown."""
    return 1.0 if value is None or np.isnan(value) else float(value)


def _wilcoxon_row(sq: str, label: str, means: pd.DataFrame, a, b, value: str, higher: bool) -> dict:
    x, y = _paired(means, a, b, value)
    w = stats.wilcoxon_paired(x, y)
    diff = float((x - y).mean())
    return {"sq": sq, "hypothesis": label, "n": w["n"], "p": _p(w["p"]), "effect": w["r"], "estimate": diff,
            "direction_ok": diff > 0 if higher else diff < 0}  # fmt: skip


def _bound_row(sq: str, label: str, means: pd.DataFrame, system: tuple[str, str], value: str, limit: float) -> dict:
    """Mean per-scenario value below a fixed limit: one-sided one-sample t test (upper 95 % bound < limit)."""
    x = means[(means.model == system[0]) & (means.system == system[1])][value].dropna()
    t = scipy_stats.ttest_1samp(x, limit, alternative="less")
    upper = float(x.mean() + scipy_stats.t.ppf(0.95, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x)))
    return {"sq": sq, "hypothesis": label, "n": len(x), "p": _p(t.pvalue), "effect": np.nan,
            "estimate": float(x.mean()), "direction_ok": True, "ci90": f"upper 95 % bound {upper:.4f}"}  # fmt: skip


def _tost_row(means: pd.DataFrame) -> dict:
    """H2c: the pipeline saves as much as EMHASS within +/- MARGIN_PP (paired t TOST, 90 % CI inside the margin).

    If every paired difference is zero (both at the same cost on every scenario) the CI is [0, 0], inside the
    margin, and equivalence holds (p = 0); the t test itself is undefined then.
    """
    x, y = _paired(means, PIPELINE, EMHASS, "saving_pct")
    diff = (x - y).dropna()
    label = f"H2c pipeline = emhass_rest within +/-{MARGIN_PP} pp (saving)"
    if (diff.abs() < ZERO).all():
        return {"sq": "SQ2", "hypothesis": label, "n": len(diff), "p": 0.0, "effect": np.nan, "estimate": 0.0,
                "direction_ok": True, "ci90": "[0.000, 0.000] (all differences zero)"}  # fmt: skip
    t = stats.tost_paired(x, y, MARGIN_PP)
    return {"sq": "SQ2", "hypothesis": label, "n": t["n"], "p": _p(t["p_tost_t"]), "effect": np.nan,
            "estimate": t["mean_diff"], "direction_ok": True,
            "ci90": f"[{t['ci90_low']:.3f}, {t['ci90_high']:.3f}]"}  # fmt: skip


def _load_row(label: str, means: pd.DataFrame, rule: tuple[str, str]) -> dict:
    """H2d/H2e: the pipeline's saving advantage over a rule is larger on electrified days than on the others.

    Mann-Whitney U, two-sided, on the per-scenario differences (pipeline minus rule) of the 24 electrified against
    the 48 light and heavy scenarios. Effect: rank-biserial correlation, positive when the electrified differences
    are larger. Estimate: mean difference on electrified days minus that on the others.
    """
    x, y = _paired(means, PIPELINE, rule, "saving_pct")
    advantage = (x - y).dropna()
    load = means.drop_duplicates("scenario_id").set_index("scenario_id").scenario_type.str.split("-").str[1]
    electrified = advantage[load.reindex(advantage.index) == ELECTRIFIED]
    others = advantage[load.reindex(advantage.index) != ELECTRIFIED]
    u = scipy_stats.mannwhitneyu(electrified, others, alternative="two-sided")
    estimate = float(electrified.mean() - others.mean())
    return {"sq": "SQ2", "hypothesis": label, "n": f"{len(electrified)} vs {len(others)}", "p": _p(u.pvalue),
            "effect": 2 * float(u.statistic) / (len(electrified) * len(others)) - 1, "estimate": estimate,
            "direction_ok": estimate > 0}  # fmt: skip


def confirmatory_tests(means: pd.DataFrame) -> pd.DataFrame:
    """One row per registered test; `supported` requires Holm-adjusted p < ALPHA (within SQ1, within SQ2) and the
    predicted direction. `estimate` is the mean paired difference (first minus second system), the mean for a bound
    test, or the difference of mean advantages for H2d/H2e.
    """
    rows = [
        # SQ1 (value and cost): against a language model that answers without tools, and the cost per run.
        _wilcoxon_row("SQ1", "H1a pipeline > oneshot (saving)", means, PIPELINE, ONESHOT, "saving_pct", True),
        _wilcoxon_row("SQ1", "H1b pipeline > oneshot (validity rate)", means, PIPELINE, ONESHOT, "feasible_rate", True),
        _bound_row("SQ1", f"H1c pipeline latency < {LATENCY_LIMIT_S:.0f} s", means, PIPELINE, "latency_s", LATENCY_LIMIT_S),
        _bound_row("SQ1", f"H1c pipeline API cost < ${COST_LIMIT_USD:.2f}", means, PIPELINE, "cost_usd", COST_LIMIT_USD),
        # SQ2 (conditions): against the tools households deploy, over all price patterns and loads ...
        _wilcoxon_row("SQ2", "H2a pipeline > cheapest_window (saving)", means, PIPELINE, WINDOW, "saving_pct", True),
        _wilcoxon_row("SQ2", "H2b pipeline > cheapest_hours (saving)", means, PIPELINE, HOURS, "saving_pct", True),
        _tost_row(means),
        # ... and whether the advantage over the rules grows with the electrified load.
        _load_row("H2d advantage over cheapest_hours larger on electrified days", means, HOURS),
        _load_row("H2e advantage over cheapest_window larger on electrified days", means, WINDOW),
    ]
    result = pd.DataFrame(rows)
    result["p_holm"] = np.nan
    for sq, group in result.groupby("sq"):
        result.loc[group.index, "p_holm"] = holm(group.p.tolist())
    result["supported"] = (result.p_holm < ALPHA) & result.direction_ok
    return result


def run(paths: tuple[str, ...] = RUN_FILES) -> pd.DataFrame:
    runs = metrics.load_runs(list(paths))
    means = metrics.per_scenario(metrics.scored_runs(runs[runs.model.isin(["-", MODEL])]))
    return confirmatory_tests(means)


if __name__ == "__main__":
    table = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT, index=False)
    with pd.option_context("display.width", 200, "display.max_columns", None, "display.max_colwidth", 70):
        print(table)
