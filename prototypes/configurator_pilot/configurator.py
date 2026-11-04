"""Configurator pilot (exploratory, step 4 of the follow-up plan; not part of the thesis evaluation).

Tests the riskiest part of SQ2: does a language-model Configurator set the MPC better than a deterministic
auto-tuner that sees the same history? Built on the gateway twin (``prototypes/home_gateway``), German setup
(``--market de --export feedin --forecast weather``), OPSD ``residential4`` 2016.

Settings in scope (the confirmatory scope of SQ2): PV forecast derating and battery reserve at midnight. Every
system runs the MPC at the gateway's checkpoints (00, 06, 12, 18 h and each EV plug-in) through the same control
layer; each day starts from the reference state and is scored by adjusted cost (as ``gateway.score``).

Systems, per evaluation week:

- default:     MPC with default settings (no derating, no reserve);
- tuned:       MPC with the settings that were best by grid search on a separate exploratory period (the expert
               configuration), fixed for every week;
- auto_tuner:  before each week, the grid point with the lowest backtest cost over the previous ``--history``
               weeks (no language model);
- agent:<m>:   before each week, a ReAct Configurator with ``history_summary`` and ``backtest`` proposes settings;
               the harness applies them only if their backtest is not worse than the current settings';
- rules, optimum: the twin's rules and perfect foresight, for the rules-to-optimum gap.

Backtests are cached by (settings, date), so the agent and the auto-tuner share runs.

    uv run python prototypes/configurator_pilot/configurator.py --raw-dir D:/Study/my-thesis/data/raw --models gpt-6-luna
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.tools import tool
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parents[1] / "home_gateway"))
from gateway import (CHECKPOINTS, Forecasts, Plan, Run, Settings, State, execute, forecasts_for,  # noqa: E402
                     perfect_foresight, score, solve)  # fmt: skip
from twin import Day, Home, load_days, rules  # noqa: E402

from hems.agents.harness import ReactResult, run_react  # noqa: E402
from hems.agents.llm import make_model, usage_cost_usd  # noqa: E402
from hems.core.models import SLOT_HOURS  # noqa: E402

DERATES = (0.6, 0.7, 0.8, 0.9, 1.0)
RESERVES: tuple[float | None, ...] = (None, 50.0)
GRID = [Settings(pv_derate=d, battery_reserve_pct=r) for d in DERATES for r in RESERVES]
AGENT_STEP_LIMIT = 20
HERE = Path(__file__).parent


# ── Running the MPC with given settings ──────────────────────────────────────
def mpc(fc: Forecasts, day: Day, home: Home, s: Settings):
    def planner(t: int, state: State, known: list[int], current: Plan | None, _reason: str) -> Plan | None:
        return solve(fc.at(t), t, state, known, day, home, s) or current

    return planner


class Backtester:
    """Adjusted cost of the checkpoint MPC with given settings, cached per (settings, date)."""

    def __init__(self, days: dict[str, Day], fcs: dict[str, Forecasts], home: Home):
        self.days, self.fcs, self.home = days, fcs, home
        self.cache: dict[tuple[float, float | None, str], dict] = {}
        self.runs = 0

    def day(self, s: Settings, d: str) -> dict:
        key = (round(s.pv_derate, 3), s.battery_reserve_pct, d)
        if key not in self.cache:
            day = self.days[d]
            run = execute(day, self.home, mpc(self.fcs[d], day, self.home, s), set(CHECKPOINTS))
            self.cache[key] = score(day, self.home, run.result)
            self.runs += 1
        return self.cache[key]

    def cost(self, s: Settings, dates: list[str]) -> float:
        return sum(self.day(s, d)["adjusted_cost_eur"] for d in dates)


def week_dates(start: date) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range(7)]


def label(s: Settings) -> str:
    return f"derate {s.pv_derate:.2f}, reserve {'none' if s.battery_reserve_pct is None else f'{s.battery_reserve_pct:.0f} %'}"


# ── The Configurator agent ───────────────────────────────────────────────────
SYSTEM_PROMPT = """You are the Configurator of a home energy gateway in Konstanz, Germany. The home has rooftop PV, \
a 10 kWh home battery, a heat pump and an EV charger. An MPC plans the devices at 00, 06, 12 and 18 h and at each \
plug-in, using day-ahead forecasts of PV (from weather forecasts), heat demand and household load.

Once a week you choose two MPC settings for the coming week:
- pv_derate (0.5-1.0): the share of the PV forecast the MPC plans with;
- battery_reserve_pct (10-100, or null for none): the minimum battery charge at midnight. Energy left at midnight
  is already valued in the MPC's objective.

Use history_summary to see how the forecasts and the house behaved in the past weeks, and backtest to compare
candidate settings on those weeks (lower adjusted cost is better). Then answer with MpcSettings. The harness
applies your settings only if their backtest is not worse than the current settings'."""


class MpcSettings(BaseModel):
    pv_derate: float = Field(description="Share of the PV forecast to plan with, 0.5-1.0")
    battery_reserve_pct: float | None = Field(None, description="Minimum battery charge at midnight, %, or null")
    reason: str = Field(description="One short sentence")


def weather_classes(days: list[Day]) -> dict[str, str]:
    """Overcast / variable / sunny by tertiles of daily global radiation over the year."""
    sums = {d.date: float(d.ghi.sum()) for d in days if d.ghi is not None}
    low, high = np.quantile(list(sums.values()), [1 / 3, 2 / 3])
    return {k: "overcast" if v < low else "variable" if v < high else "sunny" for k, v in sums.items()}


def history_text(history: list[str], days: dict[str, Day], fcs: dict[str, Forecasts], classes: dict[str, str],
                 current: Settings, bt: Backtester) -> str:  # fmt: skip
    rows = ["date | weather | PV actual kWh | PV day-ahead forecast kWh | actual/forecast | EV kWh | mean import c/kWh"]
    ratios: dict[str, list[float]] = {}
    for d in history:
        day, fc = days[d], fcs[d]
        actual = float(day.pv.sum() * SLOT_HOURS)
        forecast = float(fc.at(None)["pv"].sum() * SLOT_HOURS)
        ratio = actual / forecast if forecast > 0.1 else float("nan")
        ratios.setdefault(classes.get(d, "?"), []).append(ratio)
        ev = sum(e for _, _, e in day.sessions)
        rows.append(f"{d} | {classes.get(d, '?')} | {actual:.1f} | {forecast:.1f} | {ratio:.2f} | {ev:.1f} | "
                    f"{day.import_price.mean() * 100:.1f}")  # fmt: skip
    by_class = "; ".join(f"{k}: mean {np.nanmean(v):.2f} over {len(v)} days" for k, v in sorted(ratios.items()))
    total_a = sum(days[d].pv.sum() for d in history) * SLOT_HOURS
    total_f = sum(fcs[d].at(None)["pv"].sum() for d in history) * SLOT_HOURS
    return ("\n".join(rows) + f"\nPV actual/forecast by weather: {by_class}. Whole period: {total_a / total_f:.2f}.\n"
            f"Current settings: {label(current)}; their backtest on these days: "
            f"{bt.cost(current, history):.2f} EUR adjusted cost.")  # fmt: skip


def agent_configure(model_name: str, history: list[str], days: dict[str, Day], fcs: dict[str, Forecasts],
                    classes: dict[str, str], current: Settings, bt: Backtester) -> tuple[Settings, dict]:  # fmt: skip
    @tool
    def history_summary() -> str:
        """Day by day for the past weeks: weather class, PV actual vs day-ahead forecast, EV energy, prices; and the
        current settings with their backtest cost."""
        return history_text(history, days, fcs, classes, current, bt)

    tried: list[str] = []

    @tool
    def backtest(pv_derate: float, battery_reserve_pct: float | None = None) -> str:
        """Adjusted cost (EUR) of the MPC with these settings over the past weeks, with the coldest indoor
        temperature and the EV energy delivered."""
        s = Settings(float(np.clip(pv_derate, 0.5, 1.0)),
                     None if battery_reserve_pct is None else float(np.clip(battery_reserve_pct, 10, 100)))  # fmt: skip
        per_day = [bt.day(s, d) for d in history]
        tried.append(label(s))
        return (f"{label(s)}: adjusted cost {sum(r['adjusted_cost_eur'] for r in per_day):.2f} EUR over {len(history)} "
                f"days; coldest {min(r['min_indoor_c'] for r in per_day):.1f} C; EV "
                f"{sum(r['ev_kwh'] for r in per_day):.1f} kWh")  # fmt: skip

    model = make_model(model_name)
    message = (f"Configure the MPC for the week starting {(date.fromisoformat(history[-1]) + timedelta(days=1))}. "
               f"Current settings: {label(current)}.")  # fmt: skip
    started = time.perf_counter()
    with get_usage_metadata_callback() as usage:
        try:
            out = run_react(model, [history_summary, backtest], SYSTEM_PROMPT, MpcSettings, message, "configurator",
                            AGENT_STEP_LIMIT, None)  # fmt: skip
        except Exception as exc:  # Ollama's HTTP 500 on a malformed tool call: keep the current settings
            if type(exc).__name__ != "ResponseError":
                raise
            out = ReactResult(None, 0, [f"configurator: {str(exc)[:160]}"], 0)
    tin, tout, usd = usage_cost_usd(usage.usage_metadata, model_name)
    meta = {"tool_calls": out.tool_calls, "errors": out.errors, "tokens_in": tin, "tokens_out": tout, "usd": usd,
            "latency_s": round(time.perf_counter() - started, 1), "backtests": tried}  # fmt: skip
    if out.output is None:
        return current, {**meta, "decision": "no answer, keep"}
    proposed = Settings(float(np.clip(out.output.pv_derate, 0.5, 1.0)),
                        None if out.output.battery_reserve_pct is None
                        else float(np.clip(out.output.battery_reserve_pct, 10, 100)))  # fmt: skip
    if bt.cost(proposed, history) <= bt.cost(current, history) + 1e-9:
        return proposed, {**meta, "decision": f"apply {label(proposed)} - {out.output.reason}"}
    return current, {**meta, "decision": f"rejected {label(proposed)} (backtest worse) - {out.output.reason}"}


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--models", nargs="*", default=[])
    parser.add_argument("--start", default="2016-03-07", help="first evaluation week (a Monday)")
    parser.add_argument("--weeks", type=int, default=8)
    parser.add_argument("--history", type=int, default=2, help="weeks of history for the backtest")
    parser.add_argument("--tune-start", default="2016-09-05", help="exploratory period for the tuned reference")
    parser.add_argument("--tune-weeks", type=int, default=4)
    parser.add_argument("--out", type=Path, default=HERE / "out" / "results.jsonl")
    args = parser.parse_args()
    load_dotenv()
    home = Home()
    all_days = load_days(args.raw_dir, 2016, "de", "feedin")
    fcs = forecasts_for(all_days, "weather")
    days = {d.date: d for d in all_days}
    classes = weather_classes(all_days)
    bt = Backtester(days, fcs, home)

    def available(dates: list[str]) -> list[str]:
        return [d for d in dates if d in days]

    tune_dates = available([d for w in range(args.tune_weeks)
                            for d in week_dates(date.fromisoformat(args.tune_start) + timedelta(weeks=w))])  # fmt: skip
    tuned = min(GRID, key=lambda s: bt.cost(s, tune_dates))
    print(f"tuned on {len(tune_dates)} days from {args.tune_start}: {label(tuned)}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    current = {"auto_tuner": Settings(), **{f"agent:{m}": Settings() for m in args.models}}
    with args.out.open("w") as out:
        for w in range(args.weeks):
            start = date.fromisoformat(args.start) + timedelta(weeks=w)
            week = available(week_dates(start))
            history = available([d for k in range(args.history, 0, -1) for d in week_dates(start - timedelta(weeks=k))])
            chosen: dict[str, tuple[Settings, dict]] = {
                "default": (Settings(), {}), "tuned": (tuned, {}),
                "auto_tuner": (min(GRID, key=lambda s: bt.cost(s, history)), {}),
            }  # fmt: skip
            for m in args.models:
                chosen[f"agent:{m}"] = agent_configure(m, history, days, fcs, classes, current[f"agent:{m}"], bt)
            for name, (s, meta) in chosen.items():
                if name in current:
                    current[name] = s
                record = {"week": start.isoformat(), "system": name, "settings": label(s),
                          "adjusted_cost_eur": bt.cost(s, week), "history_cost_eur": bt.cost(s, history), **meta}  # fmt: skip
                out.write(json.dumps(record) + "\n")
                print(f"{start} {name:18s} {label(s):28s} week {record['adjusted_cost_eur']:7.2f} EUR"
                      + (f"  {meta['decision']}" if "decision" in meta else ""), flush=True)  # fmt: skip
            for name, fn in (("rules", lambda d: Run(rules(days[d], home, home.soc_start * home.battery_kwh, home.set_c))),
                             ("optimum", lambda d: perfect_foresight(days[d], home))):  # fmt: skip
                cost = sum(score(days[d], home, fn(d).result)["adjusted_cost_eur"] for d in week)
                out.write(json.dumps({"week": start.isoformat(), "system": name, "adjusted_cost_eur": cost}) + "\n")
            out.flush()
    print(f"\n{bt.runs} day backtests run")
    summarize(args.out)


def summarize(path: Path) -> None:
    frame = pd.DataFrame(map(json.loads, path.read_text().splitlines()))
    table = frame.groupby("system").adjusted_cost_eur.sum().to_frame("adjusted_cost_eur")
    default, tuned = table.adjusted_cost_eur["default"], table.adjusted_cost_eur["tuned"]
    rules_cost, best = table.adjusted_cost_eur["rules"], table.adjusted_cost_eur["optimum"]
    table["saving_vs_default_eur"] = default - table.adjusted_cost_eur
    # meaningful only when the tuned reference beats the default
    table["share_of_default_to_tuned_gap_pct"] = 100 * (default - table.adjusted_cost_eur) / (default - tuned) \
        if default > tuned else float("nan")
    table["rules_to_optimum_gap_closed_pct"] = 100 * (rules_cost - table.adjusted_cost_eur) / (rules_cost - best)
    if "usd" in frame:
        table["usd"] = frame.groupby("system").usd.sum()
    print(table.round(2).to_string())
    print("\nSettings per week:")
    print(frame[frame.settings.notna()].pivot(index="week", columns="system", values="settings").to_string())


if __name__ == "__main__":
    main()
