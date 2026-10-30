"""Thesis figures from the recorded held-out run Q3 (display only: no test is computed or changed here).

    uv run python -m hems.analysis.figures            # -> results/figures/*.pdf

The numbers come from the same run files and scoring as hems.analysis.confirm_q3, so every figure agrees with the
tables of Chapter 5.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from hems.analysis import metrics  # noqa: E402
from hems.analysis.confirm_q3 import MODEL, RUN_FILES  # noqa: E402
from hems.core.models import Scenario  # noqa: E402
from hems.data.electrified import SAUNA_KW, SAUNA_SLOTS, SAUNA_START_SLOT  # noqa: E402

OUT = Path("results/figures")
SCENARIOS = Path("data/scenarios_q3")
DEMO_DAY = "Q3-PE01-80"  # the day of Table tab:demo
PATTERN_DAYS = {"Stable": "Q3-SL01-80", "Volatile": "Q3-VL01-80", "Price spike": "Q3-PL01-80",
                "Negative prices": "Q3-NL05-80"}  # fmt: skip  # NL05: seven slots below zero, visible at this scale
TEXT_WIDTH_IN = 6.1  # the thesis text block

INK, GREEN, AMBER, RED, GREY, LIGHT = "#0B2B33", "#00996B", "#E8A317", "#C2413A", "#9DB0B4", "#D5DEE0"
KIND_COLORS = {"washing_machine": "#2F6F8F", "tumble_dryer": "#7FB3C8", "dishwasher": AMBER, "ev_charger": GREEN}
KIND_LABELS = {"washing_machine": "Washing", "tumble_dryer": "Drying", "dishwasher": "Dishwasher", "ev_charger": "Car"}
LOAD_LABELS = {"light": "Light", "heavy": "Heavy", "electrified": "Electrified"}


def _style() -> None:
    plt.rcParams.update({
        "font.family": "serif", "font.serif": ["Times New Roman", "Liberation Serif", "DejaVu Serif"],
        "font.size": 9, "axes.titlesize": 9, "axes.labelsize": 9, "legend.fontsize": 8, "xtick.labelsize": 8,
        "ytick.labelsize": 8, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#555555",
        "pdf.fonttype": 42,
    })  # fmt: skip


def _runs() -> pd.DataFrame:
    runs = metrics.load_runs(list(RUN_FILES))
    return runs[runs.model.isin(["-", MODEL])]


def _scenario(scenario_id: str) -> Scenario:
    return Scenario.load(SCENARIOS / f"{scenario_id}.json")


def _hours(ax: plt.Axes) -> None:
    ax.set_xlim(0, 96)
    ax.set_xticks(range(0, 97, 12), [f"{h:02d}:00" for h in range(0, 25, 3)])


def demo_day(runs: pd.DataFrame) -> Path:
    """The demonstration day: the price and the household load under three schedules, against the 8 kW limit."""
    sc = _scenario(DEMO_DAY)
    # run 0 of the deterministic systems, run 1 of the systems with a language model (as in Table tab:demo)
    day = runs[(runs.scenario_id == DEMO_DAY) & runs.run.isin([0, 1])].set_index("system")
    panels = [("No scheduling", "naive"), ("Cheapest-hours automation", "cheapest_hours"),
              ("Multi-Agent Pipeline (optimal)", "multi_duo")]  # fmt: skip
    slots = np.arange(96)
    sauna = np.zeros(96)
    sauna[SAUNA_START_SLOT : SAUNA_START_SLOT + SAUNA_SLOTS] = SAUNA_KW
    base = np.array(sc.base_load_kw) - sauna

    fig, axes = plt.subplots(4, 1, figsize=(TEXT_WIDTH_IN, 6.4), sharex=True,
                             gridspec_kw={"height_ratios": [0.8, 1, 1, 1]})  # fmt: skip
    price = np.array(sc.price_eur_per_kwh) * 100
    axes[0].step(slots, price, where="post", color=INK, lw=1.2)
    axes[0].set_ylabel("c/kWh")
    axes[0].set_title("Consumer price, 15 October 2025 (spike day)", loc="left")
    for ax, (title, system) in zip(axes[1:], panels):
        starts = day.loc[system, "schedule_slots"]
        bottom = base.copy()
        ax.bar(slots, base, width=1, align="edge", color=LIGHT, label="Base load")
        ax.bar(slots, sauna, width=1, align="edge", bottom=bottom, color=GREY, label="Sauna (fixed)")
        bottom = bottom + sauna
        for kind in KIND_COLORS:
            load = np.zeros(96)
            for a in sc.appliances:
                if a.kind == kind:
                    s = starts[a.id]
                    load[s : s + a.duration_slots] += a.profile_kw[: 96 - s]
            ax.bar(slots, load, width=1, align="edge", bottom=bottom, color=KIND_COLORS[kind], label=KIND_LABELS[kind])
            bottom = bottom + load
        ax.axhline(sc.peak_limit_kw, color=RED, ls="--", lw=1)
        peak = bottom.max()
        verdict = "valid" if day.loc[system, "feasible"] else "breaks the limit"
        ax.set_title(f"{title}: peak {peak:.1f} kW, {verdict}", loc="left")
        ax.set_ylim(0, 12)
        ax.set_ylabel("kW")
    axes[1].text(95.5, sc.peak_limit_kw + 0.3, "8 kW limit", color=RED, ha="right", va="bottom", fontsize=8)
    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=6, frameon=False, bbox_to_anchor=(0.5, -0.01))
    _hours(axes[-1])
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    return _save(fig, "demo_day")


def price_patterns() -> Path:
    """One light-load day of each price pattern: the spot price the patterns are defined on, on a common scale."""
    fig, axes = plt.subplots(2, 2, figsize=(TEXT_WIDTH_IN, 3.6), sharex=True, sharey=True)
    for ax, (label, scenario_id) in zip(axes.flat, PATTERN_DAYS.items()):
        sc = _scenario(scenario_id)
        spot = np.array(sc.spot_eur_per_kwh) * 100
        ax.step(np.arange(96), spot, where="post", color=INK, lw=1.1)
        ax.axhline(0, color=GREY, lw=0.8)
        ax.set_title(f"{label} ({sc.date})", loc="left")
        if ax in axes[:, 0]:
            ax.set_ylabel("Spot price (c/kWh)")
        _hours(ax)
        ax.set_xticks(range(0, 97, 24), [f"{h:02d}:00" for h in range(0, 25, 6)])
    fig.tight_layout()
    return _save(fig, "price_patterns")


def _load_of(scenario_type: pd.Series) -> pd.Series:
    return scenario_type.str.split("-").str[1]


def saving_by_load(scored: pd.DataFrame) -> Path:
    """Pooled saving (and valid share where below 100 %) per household load, as in the Q3 results."""
    systems = [("multi_duo", "Pipeline = EMHASS = optimum", GREEN), ("cheapest_window", "Cheapest window", AMBER),
               ("cheapest_hours", "Cheapest-hours automation", RED), ("oneshot", "LLM without tools", GREY)]  # fmt: skip
    scored = scored.assign(load=_load_of(scored.scenario_type))
    fig, ax = plt.subplots(figsize=(TEXT_WIDTH_IN, 2.9))
    width = 0.2
    for k, (system, label, color) in enumerate(systems):
        rows = scored[scored.system == system]
        for j, load in enumerate(LOAD_LABELS):
            r = rows[rows.load == load]
            saving = r.saving_eur.sum() / r.naive_cost.sum() * 100
            valid = r.feasible.mean() * 100
            x = j + (k - 1.5) * width
            ax.bar(x, saving, width * 0.92, color=color, label=label if j == 0 else None)
            note = f"{saving:.1f}" + (f"\n({valid:.0f} %)" if valid < 99.95 else "")
            ax.text(x, saving + 0.3, note, ha="center", va="bottom", fontsize=7)
    ax.set_xticks(range(3), LOAD_LABELS.values())
    ax.set_ylabel("Saving vs no scheduling (%)")
    ax.set_ylim(0, 20)
    ax.legend(ncol=4, frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.16))
    fig.tight_layout()
    return _save(fig, "saving_by_load")


def advantage_by_day(scored: pd.DataFrame) -> Path:
    """Per-scenario advantage of the pipeline over each rule, electrified days against the others (H2d, H2e)."""
    means = metrics.per_scenario(scored)
    wide = means.pivot_table(index=["scenario_id", "scenario_type"], columns="system", values="saving_pct").reset_index()
    electrified = _load_of(wide.scenario_type) == "electrified"
    rng = np.random.default_rng(0)  # horizontal jitter only
    fig, axes = plt.subplots(1, 2, figsize=(TEXT_WIDTH_IN, 2.8), sharey=True)
    for ax, (rule, label) in zip(axes, [("cheapest_hours", "Over the cheapest-hours automation (H2d)"),
                                        ("cheapest_window", "Over the cheapest window (H2e)")]):  # fmt: skip
        diff = wide.multi_duo - wide[rule]
        for x, mask, name in [(0, ~electrified, "Other days\n(n = 48)"), (1, electrified, "Electrified\n(n = 24)")]:
            values = diff[mask].to_numpy()
            ax.scatter(x + rng.uniform(-0.18, 0.18, len(values)), values, s=10, color=GREEN if x else INK, alpha=0.7,
                       linewidths=0)  # fmt: skip
            ax.hlines(values.mean(), x - 0.28, x + 0.28, color=RED, lw=1.5)
            ax.text(x + 0.3, values.mean(), f"mean {values.mean():.1f}", va="center", fontsize=7, color=RED)
        ax.set_xticks([0, 1], ["Other days\n(n = 48)", "Electrified\n(n = 24)"])
        ax.set_xlim(-0.5, 1.75)
        ax.axhline(0, color=GREY, lw=0.8)
        ax.set_title(label, loc="left")
    axes[0].set_ylabel("Pipeline saving minus rule saving (pt)")
    fig.tight_layout()
    return _save(fig, "advantage_by_day")


def one_or_two(runs: pd.DataFrame) -> Path:
    """Response time and API cost per run: the pipeline against the single agent in the harness (SQ3)."""
    designs = [("multi_duo", "Multi-Agent\nPipeline"), ("single_harness", "Single agent\nin the harness")]
    fig, axes = plt.subplots(1, 2, figsize=(TEXT_WIDTH_IN, 2.6))
    for ax, (column, label, scale) in zip(axes, [("latency_s", "Response time per run (s)", 1.0),
                                                ("cost_usd", "API cost per run (US cents)", 100.0)]):  # fmt: skip
        data = [runs[runs.system == s][column].to_numpy() * scale for s, _ in designs]
        box = ax.boxplot(data, widths=0.45, patch_artist=True, showfliers=True,
                         flierprops={"markersize": 3, "markeredgecolor": GREY})  # fmt: skip
        for patch, color in zip(box["boxes"], [GREEN, INK]):
            patch.set(facecolor=color, alpha=0.35, edgecolor=color)
        for median in box["medians"]:
            median.set(color=RED, lw=1.5)
        ax.set_xticks([1, 2], [name for _, name in designs])
        ax.set_ylabel(label)
        ax.set_ylim(bottom=0)
    fig.tight_layout()
    return _save(fig, "one_or_two")


def _save(fig: plt.Figure, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.pdf"
    fig.savefig(path, bbox_inches="tight")
    fig.savefig(OUT / f"{name}.png", dpi=150, bbox_inches="tight")  # preview only
    plt.close(fig)
    return path


def main() -> None:
    _style()
    runs = _runs()
    scored = metrics.scored_runs(runs)
    for path in (demo_day(runs), price_patterns(), saving_by_load(scored), advantage_by_day(scored),
                 one_or_two(runs)):  # fmt: skip
        print(path)


if __name__ == "__main__":
    main()
