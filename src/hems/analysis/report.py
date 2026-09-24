"""Write Chapter 5 tables (booktabs .tex) and figures (.pdf) from runs.jsonl.

main.tex can \\input{results/tables/<name>.tex}, so rerunning the analysis
updates the thesis.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from hems.analysis import metrics, stats  # noqa: E402
from hems.core.models import Scenario  # noqa: E402

SYSTEM_LABELS = {"single": "Single-agent", "multi": "Multi-agent"}


def _fmt(value: object) -> str:
    if isinstance(value, float):
        if pd.isna(value):
            return "--"
        return f"{value:.3g}" if abs(value) < 0.001 and value != 0 else f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value).replace("_", r"\_").replace("%", r"\%")


def to_booktabs(df: pd.DataFrame, caption: str, label: str) -> str:
    df = df.reset_index() if not isinstance(df.index, pd.RangeIndex) else df
    columns = [" / ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in df.columns]
    lines = [
        r"\begin{table}[h!]",
        rf"\caption{{{caption}}}",
        rf"\label{{{label}}}",
        r"\small",
        r"\begin{tabular}{" + "l" + "r" * (len(columns) - 1) + "}",
        r"\toprule",
        " & ".join(_fmt(c) for c in columns) + r" \\",
        r"\midrule",
        *(" & ".join(_fmt(v) for v in row) + r" \\" for row in df.itertuples(index=False)),
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


def gap_boxplot(scenario_means: pd.DataFrame, path: Path) -> None:
    models = sorted(scenario_means.model.unique())
    fig, axes = plt.subplots(1, len(models), figsize=(6 * len(models), 3.6), squeeze=False, sharey=True)
    for ax, model in zip(axes[0], models):
        sub = scenario_means[scenario_means.model == model]
        types = sorted(sub.scenario_type.unique())
        for offset, system in ((-0.18, "single"), (0.18, "multi")):
            data = [sub[(sub.scenario_type == t) & (sub.system == system)].gap_pct.dropna() for t in types]
            ax.boxplot(data, positions=[i + offset for i in range(len(types))], widths=0.3, patch_artist=True,
                       boxprops={"facecolor": "#9ecae1" if system == "single" else "#fdae6b"}, label=SYSTEM_LABELS[system])  # fmt: skip
        ax.set_xticks(range(len(types)), types)
        ax.set_title(model)
        ax.set_xlabel("Scenario type")
        ax.axhline(0, color="grey", lw=0.8)
    axes[0][0].set_ylabel("Optimality gap (%)")
    axes[0][0].legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def write_report(runs_path: str | Path, scenarios: dict[str, Scenario], out_dir: str | Path) -> dict[str, pd.DataFrame]:
    out = Path(out_dir)
    (out / "tables").mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(parents=True, exist_ok=True)

    runs = metrics.load_runs(runs_path)
    scored = metrics.scored_runs(runs)
    if scored.empty:
        raise SystemExit("no single/multi agent runs with matching milp+naive references in " + str(runs_path))
    means = metrics.per_scenario(scored)
    naive = runs[runs.system == "naive"]
    appliance_rows = metrics.per_appliance(scored, naive, scenarios)

    results = {
        "gap_by_type": metrics.summary_by_type(means),
        "wilcoxon": stats.compare_systems(means, "gap_pct"),
        "wilcoxon_savings_captured": stats.compare_systems(means, "savings_captured"),
        "conflict_resolution": metrics.conflict_resolution_rate(scored, scenarios),
        "efficiency": metrics.efficiency(scored),
        "per_appliance": appliance_rows.groupby(["model", "system", "kind"]).saving_eur.agg(["mean", "std", "count"]).reset_index()
        if not appliance_rows.empty
        else pd.DataFrame(),
        "characteristics": stats.characteristic_correlations(appliance_rows) if not appliance_rows.empty else pd.DataFrame(),
    }
    captions = {
        "gap_by_type": ("Mean optimality gap (\\%) by scenario type.", "tab:gap-by-type"),
        "wilcoxon": ("Wilcoxon signed-rank test, multi- vs single-agent optimality gap.", "tab:wilcoxon"),
        "wilcoxon_savings_captured": ("Wilcoxon signed-rank test on savings captured.", "tab:wilcoxon-savings"),
        "conflict_resolution": ("Conflict resolution rate in scenarios requiring coordination.", "tab:conflicts"),
        "efficiency": ("Feasibility, latency, tokens and API cost per run.", "tab:efficiency"),
        "per_appliance": ("Mean saving per appliance cycle vs. no scheduling (EUR).", "tab:per-appliance"),
        "characteristics": ("Spearman correlation of saving with appliance characteristics.", "tab:characteristics"),
    }
    for name, df in results.items():
        df.to_csv(out / "tables" / f"{name}.csv", index=not isinstance(df.index, pd.RangeIndex))
        if not df.empty:
            caption, label = captions[name]
            (out / "tables" / f"{name}.tex").write_text(to_booktabs(df, caption, label), encoding="utf-8")
    if not means.empty:
        gap_boxplot(means, out / "figures" / "gap_by_type.pdf")
    return results
