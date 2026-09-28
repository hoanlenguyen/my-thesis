"""Value of 15-minute price information (MILP only, no LLM).

For each scenario with native 15-minute prices:
* ``opt_15``     — MILP schedule planned on the real 15-min prices;
* ``hourly_plan``— MILP schedule planned on hourly-averaged prices (what a household could see before the
                   1 Oct 2025 switch), then settled at the real 15-min prices;
* ``naive``      — every appliance starts when ready.

``hourly_plan - opt_15`` is the saving that is only reachable with 15-minute price information. Hourly
prices make the four quarters of an hour tie; a negligible ramp (1e-7 EUR/kWh per slot) breaks ties
towards the earliest start, so the result does not depend on the solver's arbitrary choice.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from hems.core.evaluate import evaluate
from hems.core.models import SLOTS_PER_DAY, Scenario
from hems.solvers.milp import solve_milp
from hems.solvers.naive import naive_schedule

TIE_BREAK_EUR_PER_KWH = 1e-7


def hourly_prices(prices: list[float]) -> list[float]:
    hourly = np.asarray(prices, dtype=float).reshape(-1, 4).mean(axis=1).repeat(4)
    return list(hourly + TIE_BREAK_EUR_PER_KWH * np.arange(SLOTS_PER_DAY))


def compare_scenario(scenario: Scenario) -> dict:
    opt = solve_milp(scenario)
    hourly_view = scenario.model_copy(update={"price_eur_per_kwh": hourly_prices(scenario.price_eur_per_kwh)})
    hourly = solve_milp(hourly_view)
    if opt.status != "Optimal" or hourly.status != "Optimal":
        raise RuntimeError(f"{scenario.id}: MILP status {opt.status}/{hourly.status}")

    cost_15 = evaluate(scenario, opt.schedule).cost_eur
    cost_hourly = evaluate(scenario, hourly.schedule).cost_eur  # settled at the real 15-min prices
    cost_naive = evaluate(scenario, naive_schedule(scenario)).cost_eur
    spot = np.asarray(scenario.spot_eur_per_kwh).reshape(-1, 4)
    return {
        "scenario_id": scenario.id,
        "scenario_type": scenario.type,
        "date": scenario.date,
        "intra_hour_spread_c_kwh": float((spot.max(axis=1) - spot.min(axis=1)).mean() * 100),
        "naive_eur": cost_naive,
        "hourly_plan_eur": cost_hourly,
        "opt_15_eur": cost_15,
        "value_15min_eur": cost_hourly - cost_15,
        "value_15min_pct": (cost_hourly - cost_15) / cost_hourly * 100,
        "saving_opt_15_pct": (cost_naive - cost_15) / cost_naive * 100,
        "saving_hourly_plan_pct": (cost_naive - cost_hourly) / cost_naive * 100,
        "share_of_saving_from_15min": (cost_hourly - cost_15) / (cost_naive - cost_15)
        if cost_naive - cost_15 > 1e-9
        else np.nan,
        "starts_changed": sum(opt.schedule[a] != hourly.schedule[a] for a in opt.schedule),
        "appliances": len(scenario.appliances),
    }


def _share_of_saving(frame: pd.DataFrame) -> float:
    """Share of the achievable saving (naive -> 15-min optimum) that needs 15-min information, in %."""
    achievable = (frame.naive_eur - frame.opt_15_eur).sum()
    return float((frame.hourly_plan_eur - frame.opt_15_eur).sum() / achievable * 100) if achievable > 1e-9 else np.nan


def compare_resolution(scenarios: list[Scenario], out_dir: str | Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = pd.DataFrame([compare_scenario(s) for s in scenarios])
    by_type = (
        rows.groupby("scenario_type")
        .agg(
            intra_hour_spread_c_kwh=("intra_hour_spread_c_kwh", "mean"),
            saving_hourly_plan_pct=("saving_hourly_plan_pct", "mean"),
            saving_opt_15_pct=("saving_opt_15_pct", "mean"),
            value_15min_pct=("value_15min_pct", "mean"),
            value_15min_eur=("value_15min_eur", "mean"),
            scenarios_improved=("value_15min_eur", lambda v: int((v > 1e-6).sum())),
            scenarios=("scenario_id", "count"),
        )
        .reset_index()
    )
    by_type["share_of_saving_pct"] = [_share_of_saving(rows[rows.scenario_type == t]) for t in by_type.scenario_type]
    totals = rows[["naive_eur", "hourly_plan_eur", "opt_15_eur"]].sum()
    overall = {
        "scenario_type": "All",
        "intra_hour_spread_c_kwh": rows.intra_hour_spread_c_kwh.mean(),
        "saving_hourly_plan_pct": (totals.naive_eur - totals.hourly_plan_eur) / totals.naive_eur * 100,
        "saving_opt_15_pct": (totals.naive_eur - totals.opt_15_eur) / totals.naive_eur * 100,
        "value_15min_pct": (totals.hourly_plan_eur - totals.opt_15_eur) / totals.hourly_plan_eur * 100,
        "value_15min_eur": rows.value_15min_eur.mean(),
        "scenarios_improved": int((rows.value_15min_eur > 1e-6).sum()),
        "scenarios": len(rows),
        "share_of_saving_pct": _share_of_saving(rows),
    }
    by_type = pd.concat([by_type, pd.DataFrame([overall])], ignore_index=True)

    if out_dir is not None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        rows.to_csv(out / "resolution_scenarios.csv", index=False)
        by_type.to_csv(out / "resolution_by_type.csv", index=False)
        (out / "resolution_by_type.tex").write_text(thesis_table(by_type), encoding="utf-8")
    return rows, by_type


def _pct(value: float) -> str:
    return f"{value:.1f}\\,\\%"


def thesis_table(by_type: pd.DataFrame) -> str:
    """Table for main.tex via \\input{results/resolution/resolution_by_type.tex}; needs booktabs + makecell."""
    header = " & ".join(
        [
            "Type",
            r"\makecell{Intra-hour\\spread\\(c/kWh)}",
            r"\makecell{Saving,\\hourly\\plan}",
            r"\makecell{Saving,\\15-min\\plan}",
            r"\makecell{Additional\\cost\\reduction}",
            r"\makecell{Share of\\saving\\needing\\15-min}",
            r"\makecell{Scenarios\\improved}",
        ]
    )
    lines = [
        "% Generated by `hems resolution` -- do not edit by hand.",
        r"\begin{table}[h!]",
        r"\caption{Optimal schedule cost with hourly vs.\ 15-minute price information (MILP, Q scenarios).}",
        r"\label{tab:resolution}",
        r"\small",
        r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}lcccccc}",
        r"\toprule",
        header + r" \\",
        r"\midrule",
    ]
    for row in by_type.itertuples(index=False):
        if row.scenario_type == "All":
            lines.append(r"\midrule")
        cells = [
            str(row.scenario_type),
            f"{row.intra_hour_spread_c_kwh:.2f}",
            _pct(row.saving_hourly_plan_pct),
            _pct(row.saving_opt_15_pct),
            _pct(row.value_15min_pct),
            _pct(row.share_of_saving_pct),
            f"{row.scenarios_improved}/{row.scenarios}",
        ]
        lines.append(" & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular*}", r"\end{table}", ""]
    return "\n".join(lines)


