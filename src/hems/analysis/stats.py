"""Statistical tests for Chapter 5.4."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def wilcoxon_paired(multi: pd.Series, single: pd.Series) -> dict[str, float]:
    """Two-tailed Wilcoxon signed-rank test on per-scenario values, paired by index.

    zero_method="pratt" keeps tied pairs (e.g. both systems optimal in Type A)
    in the ranking instead of silently dropping them. Effect size r = |Z| / sqrt(N).
    """
    paired = pd.concat({"multi": multi, "single": single}, axis=1).dropna()
    n = len(paired)
    diff = paired.multi - paired.single
    if n == 0 or np.allclose(diff, 0):
        return {"n": n, "W": np.nan, "p": np.nan, "z": 0.0, "r": 0.0, "median_diff": 0.0}
    result = stats.wilcoxon(paired.multi, paired.single, zero_method="pratt", method="approx")
    z = float(result.zstatistic)
    return {
        "n": n,
        "W": float(result.statistic),
        "p": float(result.pvalue),
        "z": z,
        "r": abs(z) / np.sqrt(n),
        "median_diff": float(diff.median()),
    }


def compare_systems(scenario_means: pd.DataFrame, metric: str = "gap_pct") -> pd.DataFrame:
    """Multi vs single per model (overall and per scenario type)."""
    rows = []
    for model, group in scenario_means.groupby("model"):
        wide = group.pivot_table(index=["scenario_type", "scenario_id"], columns="system", values=metric)
        if not {"multi", "single"} <= set(wide.columns):
            continue
        rows.append({"model": model, "scope": "all", **wilcoxon_paired(wide.multi, wide.single)})
        for scenario_type, sub in wide.groupby(level="scenario_type"):
            rows.append({"model": model, "scope": f"type {scenario_type}", **wilcoxon_paired(sub.multi, sub.single)})
    return pd.DataFrame(rows)


def compare_to_baselines(scenario_means: pd.DataFrame, metric: str = "gap_pct") -> pd.DataFrame:
    """Each agent design vs the rule-based smart timer and vs the no-tools LLM of the same model.

    Negative median_diff = the agent design is better (lower gap) than the baseline.
    """
    rows = []
    wide = scenario_means.pivot_table(index="scenario_id", columns=["model", "system"], values=metric)
    feasible = scenario_means.pivot_table(index="scenario_id", columns=["model", "system"], values="feasible_rate")
    models = sorted({m for m, s in wide.columns if s in ("single", "multi")})
    for model in models:
        for system in ("single", "multi"):
            if (model, system) not in wide:
                continue
            for baseline in (("-", "timer"), (model, "oneshot")):
                if baseline not in wide:
                    continue
                test = wilcoxon_paired(wide[(model, system)], wide[baseline])
                rows.append({
                    "model": model,
                    "system": system,
                    "baseline": baseline[1],
                    "agent_mean": float(wide[(model, system)].mean()),
                    "baseline_mean": float(wide[baseline].mean()),
                    "agent_feasible": float(feasible[(model, system)].mean()),
                    "baseline_feasible": float(feasible[baseline].mean()),
                    **test,
                })  # fmt: skip
    return pd.DataFrame(rows)


EQUIVALENCE_MARGINS = (0.5, 1.0, 2.0)
"""Margins (percentage points of optimality gap) for the equivalence test; 1.0 is the primary one."""


def tost_paired(multi: pd.Series, single: pd.Series, margin: float) -> dict[str, float]:
    """Two one-sided tests (TOST) for equivalence of paired values within +/- margin.

    Equivalence is concluded when both one-sided nulls (mean difference <= -margin and
    >= +margin) are rejected, i.e. when the 90% confidence interval of the mean difference
    lies inside the margin. The paired t version tests the mean and is the conservative
    one reported in the thesis; the Wilcoxon version tests the typical (median) scenario
    and is reported alongside because the differences are heavy-tailed.
    """
    diff = (multi - single).dropna()
    n = len(diff)
    mean, se = float(diff.mean()), float(diff.std(ddof=1) / np.sqrt(n))
    t90 = stats.t.ppf(0.95, n - 1)
    p_t = max(
        stats.ttest_1samp(diff, -margin, alternative="greater").pvalue,
        stats.ttest_1samp(diff, margin, alternative="less").pvalue,
    )
    p_w = max(
        stats.wilcoxon(diff + margin, zero_method="pratt", alternative="greater", method="approx").pvalue,
        stats.wilcoxon(diff - margin, zero_method="pratt", alternative="less", method="approx").pvalue,
    )
    return {
        "n": n,
        "margin": margin,
        "mean_diff": mean,
        "ci90_low": mean - t90 * se,
        "ci90_high": mean + t90 * se,
        "p_tost_t": float(p_t),
        "p_tost_wilcoxon": float(p_w),
        "equivalent": bool(p_t < 0.05),
    }


def equivalence(scenario_means: pd.DataFrame, metric: str = "gap_pct", margins=EQUIVALENCE_MARGINS) -> pd.DataFrame:
    """Multi vs single equivalence test per model over all scenarios."""
    rows = []
    for model, group in scenario_means.groupby("model"):
        wide = group.pivot_table(index="scenario_id", columns="system", values=metric)
        if not {"multi", "single"} <= set(wide.columns):
            continue
        rows += [{"model": model, **tost_paired(wide.multi, wide.single, m)} for m in margins]
    return pd.DataFrame(rows)


EFFICIENCY_METRICS = ("tokens", "tokens_out", "tokens_total", "cost_usd", "latency_s", "tool_calls")


def efficiency_tests(scenario_means: pd.DataFrame) -> pd.DataFrame:
    """Wilcoxon test of multi vs single on per-scenario efficiency measures, with relative difference."""
    rows = []
    for model, group in scenario_means.groupby("model"):
        for metric in EFFICIENCY_METRICS:
            wide = group.pivot_table(index="scenario_id", columns="system", values=metric)
            if not {"multi", "single"} <= set(wide.columns):
                continue
            test = wilcoxon_paired(wide.multi, wide.single)
            rows.append({
                "model": model,
                "metric": metric,
                "single_mean": float(wide.single.mean()),
                "multi_mean": float(wide.multi.mean()),
                "rel_diff_pct": float((wide.multi.sum() - wide.single.sum()) / wide.single.sum() * 100)
                if wide.single.sum() else np.nan,
                "multi_lower": int((wide.multi < wide.single).sum()),
                "n": test["n"],
                "p": test["p"],
                "r": test["r"],
            })  # fmt: skip
    return pd.DataFrame(rows)


def characteristic_correlations(appliance_rows: pd.DataFrame) -> pd.DataFrame:
    """SQ2: Spearman correlation of per-appliance saving with cycle characteristics."""
    rows = []
    for (model, system), group in appliance_rows.groupby(["model", "system"]):
        for feature in ("duration_min", "peak_kw", "energy_kwh", "window_h"):
            if group[feature].nunique() < 2 or group.saving_eur.nunique() < 2:
                rho, p = np.nan, np.nan  # undefined for constant input
            else:
                rho, p = stats.spearmanr(group[feature], group.saving_eur)
            rows.append({"model": model, "system": system, "feature": feature, "rho": rho, "p": p, "n": len(group)})
    return pd.DataFrame(rows)
