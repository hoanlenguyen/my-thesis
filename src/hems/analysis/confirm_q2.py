"""Confirmatory tests on the held-out set Q2 (docs/preregistration_q2.md).

Do not change this file after that registration is committed: the confirmatory result is
whatever these functions return on the Q2 run files.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from hems.analysis import metrics, stats
from hems.analysis.confirm import holm

MODEL = "gpt-4o-mini"
ALPHA = 0.05
MARGIN_PP = 1.0  # equivalence margin on the per-scenario saving, percentage points of the naive cost
RUN_FILES = ("results/confirmation_q2.jsonl", "results/tools/scenarios_q2.jsonl")

LATENCY_LIMIT_S = 60.0  # design objectives of Section 4.1: a recommendation within 60 s and under $0.10
COST_LIMIT_USD = 0.10

# The thesis reports one system, the Multi-Agent Pipeline: the full configuration with retrieval and the
# optimiser tool (internal name multi_rag_opt). multi and multi_rag are earlier design iterations.
PIPELINE, ONESHOT = (MODEL, "multi_rag_opt"), (MODEL, "oneshot")
EMHASS, WINDOW, HOURS = ("-", "emhass_rest"), ("-", "cheapest_window"), ("-", "cheapest_hours")


def _paired(means: pd.DataFrame, a: tuple[str, str], b: tuple[str, str], value: str) -> tuple[pd.Series, pd.Series]:
    wide = means.pivot_table(index="scenario_id", columns=["model", "system"], values=value)
    return wide[a], wide[b]


def _wilcoxon_row(sq: str, label: str, means: pd.DataFrame, a, b, value: str, higher: bool) -> dict:
    x, y = _paired(means, a, b, value)
    w = stats.wilcoxon_paired(x, y)
    diff = float((x - y).mean())
    return {"sq": sq, "hypothesis": label, "n": w["n"], "p": w["p"], "effect": w["r"], "estimate": diff,
            "direction_ok": diff > 0 if higher else diff < 0}  # fmt: skip


def _bound_row(sq: str, label: str, means: pd.DataFrame, system: tuple[str, str], value: str, limit: float) -> dict:
    """Mean per-scenario value below a fixed limit: one-sided one-sample t test (upper 95 % bound < limit)."""
    x = means[(means.model == system[0]) & (means.system == system[1])][value].dropna()
    t = scipy_stats.ttest_1samp(x, limit, alternative="less")
    upper = float(x.mean() + scipy_stats.t.ppf(0.95, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x)))
    return {"sq": sq, "hypothesis": label, "n": len(x), "p": float(t.pvalue), "effect": np.nan,
            "estimate": float(x.mean()), "direction_ok": True, "ci90": f"upper 95 % bound {upper:.4f}"}  # fmt: skip


def confirmatory_tests(means: pd.DataFrame) -> pd.DataFrame:
    """One row per registered test; `supported` requires Holm-adjusted p < ALPHA and the predicted direction.

    `estimate` is the mean paired difference (first minus second system), or the mean for a bound test.
    """
    rows = [
        # SQ1 (value and cost): against a language model that answers without tools, and the cost per run.
        _wilcoxon_row("SQ1", "H1a pipeline > oneshot (saving)", means, PIPELINE, ONESHOT, "saving_pct", True),
        _wilcoxon_row("SQ1", "H1b pipeline > oneshot (validity rate)", means, PIPELINE, ONESHOT, "feasible_rate", True),
        _bound_row("SQ1", f"H1c pipeline latency < {LATENCY_LIMIT_S:.0f} s", means, PIPELINE, "latency_s", LATENCY_LIMIT_S),
        _bound_row("SQ1", f"H1c pipeline API cost < ${COST_LIMIT_USD:.2f}", means, PIPELINE, "cost_usd", COST_LIMIT_USD),
        # SQ2 (conditions): against the tools households deploy, over all regimes, loads and limits.
        _wilcoxon_row("SQ2", "H2a pipeline > cheapest_window (saving)", means, PIPELINE, WINDOW, "saving_pct", True),
        _wilcoxon_row("SQ2", "H2b pipeline > cheapest_hours (saving)", means, PIPELINE, HOURS, "saving_pct", True),
    ]
    # H2c: the pipeline saves as much as EMHASS, within +/- MARGIN_PP (paired t TOST).
    x, y = _paired(means, PIPELINE, EMHASS, "saving_pct")
    t = stats.tost_paired(x, y, MARGIN_PP)
    rows.append({"sq": "SQ2", "hypothesis": f"H2c pipeline = emhass_rest within +/-{MARGIN_PP} pp (saving)",
                 "n": t["n"], "p": t["p_tost_t"], "effect": np.nan, "estimate": t["mean_diff"], "direction_ok": True,
                 "ci90": f"[{t['ci90_low']:.3f}, {t['ci90_high']:.3f}]"})  # fmt: skip
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
