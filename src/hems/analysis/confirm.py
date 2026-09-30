"""Pre-registered confirmatory tests of H1 and H2 (docs/preregistration.md).

Do not change this file after the pre-registration is committed: the confirmatory
result is whatever these functions return on results/confirmation.jsonl.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hems.analysis import metrics, stats

MODEL = "gpt-4o-mini"
ALPHA = 0.05
MARGIN_PP = 1.0


def holm(p_values: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values, in the input order."""
    m = len(p_values)
    order = np.argsort(p_values)
    adjusted = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return adjusted.tolist()


def _paired(means: pd.DataFrame, a: tuple[str, str], b: tuple[str, str], value: str) -> tuple[pd.Series, pd.Series]:
    wide = means.pivot_table(index="scenario_id", columns=["model", "system"], values=value)
    return wide[a], wide[b]


def confirmatory_tests(means: pd.DataFrame) -> pd.DataFrame:
    """One row per pre-registered test; `supported` requires Holm-adjusted p < ALPHA and the predicted direction.

    `estimate` is the mean paired difference (first minus second system); its sign decides the direction.
    """
    single, multi, oneshot = (MODEL, "single"), (MODEL, "multi"), (MODEL, "oneshot")
    rows = []

    # H1 (SQ1): each agent design has a lower optimality gap than the no-tools baseline.
    for design in (single, multi):
        a, b = _paired(means, design, oneshot, "gap_pct")
        w = stats.wilcoxon_paired(a, b)
        diff = float((a - b).mean())
        rows.append({"sq": "SQ1", "hypothesis": f"H1 {design[1]} < oneshot (gap)", "n": w["n"], "p": w["p"],
                     "effect": w["r"], "estimate": diff, "direction_ok": diff < 0})  # fmt: skip

    # H2a (SQ2): pipeline and single agent equivalent in gap within +/- MARGIN_PP (paired t TOST).
    a, b = _paired(means, multi, single, "gap_pct")
    t = stats.tost_paired(a, b, MARGIN_PP)
    rows.append({"sq": "SQ2", "hypothesis": f"H2a multi = single within +/-{MARGIN_PP} pp (gap)", "n": t["n"],
                 "p": t["p_tost_t"], "effect": np.nan, "estimate": t["mean_diff"], "direction_ok": True,
                 "ci90": f"[{t['ci90_low']:.3f}, {t['ci90_high']:.3f}]"})  # fmt: skip

    # H2b (SQ2): pipeline uses fewer input tokens and has lower API cost; H2c: longer latency.
    for value, label, lower in (("tokens", "H2b multi < single (input tokens)", True),
                                ("cost_usd", "H2b multi < single (API cost)", True),
                                ("latency_s", "H2c multi > single (latency)", False)):  # fmt: skip
        a, b = _paired(means, multi, single, value)
        w = stats.wilcoxon_paired(a, b)
        diff = float((a - b).mean())
        rows.append({"sq": "SQ2", "hypothesis": label, "n": w["n"], "p": w["p"], "effect": w["r"],
                     "estimate": diff, "direction_ok": diff < 0 if lower else diff > 0})  # fmt: skip

    result = pd.DataFrame(rows)
    result["p_holm"] = np.nan
    for sq, group in result.groupby("sq"):
        result.loc[group.index, "p_holm"] = holm(group.p.tolist())
    result["supported"] = (result.p_holm < ALPHA) & result.direction_ok
    return result


def run(runs_path: str) -> pd.DataFrame:
    runs = metrics.load_runs(runs_path)
    means = metrics.per_scenario(metrics.scored_runs(runs[runs.model.isin(["-", MODEL])]))
    return confirmatory_tests(means)
