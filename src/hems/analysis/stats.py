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
