"""Estimated saving of each system over a household's whole REFIT recording period (for the demo).

Every washing-machine, dishwasher and tumble-dryer cycle the household actually ran (2013-2015) becomes a
cycle to schedule on its recording day: ready at its recorded start, to be finished by midnight. "No
scheduling" is the recorded start. Each day is priced at recent Finnish consumer prices: the same calendar
day in Oct 2025 - Sep 2026 (native 15-minute Elering prices, the thesis tariff), and the household's
typical base load counts towards the 8 kW peak limit, as in the benchmark (until 21 Oct 2026 the estimate used the
stylised 3.5 kW limit; those results are archived in results/fullperiod_strict35/).

Computed exactly per day: no scheduling, MILP optimum, smart timer, cheapest hours, and EMHASS (Docker
service, default settings, via tools/emhass_rest.py). The LLM systems are not run; the demo extrapolates
them from their share of the achievable saving on the benchmark. Cycles that cannot finish by midnight
from their recorded start keep their recorded time under every system and are counted separately.

Resumable: each finished household-day is appended to results/fullperiod/house_<n>.jsonl.

    uv run python tools/estimate_full_period.py [--houses 2 3] [--no-emhass]
    uv run python tools/estimate_full_period.py --summary     # -> demo/public/data/fullperiod.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from hems.core.evaluate import evaluate
from hems.core.models import SLOT_MINUTES, SLOTS_PER_DAY, FlexibleAppliance, Scenario
from hems.data.prices import load_price_csv, to_daily_slots
from hems.data.refit import ALL_HOUSES, FLEXIBLE_COLUMNS, MERGE_GAP_MIN, fixed_appliances, load_house, typical_base_load
from hems.data.tariff import Tariff
from hems.run import execute

ROOT = Path(__file__).resolve().parents[1]
REFIT = ROOT / "data" / "raw" / "refit"
PRICES = ROOT / "data" / "raw" / "prices_fi_elering.csv"
OUT = ROOT / "results" / "fullperiod"
DEMO = ROOT / "demo" / "public" / "data" / "fullperiod.json"
PEAK_LIMIT_KW = 8.0  # the Energy Authority's power-charge threshold, as in the benchmarks (hems.data.factorial)
PRICE_YEAR_START = date(2025, 10, 1)  # recent year: 1 Oct 2025 - 30 Sep 2026
RULE_SYSTEMS = ("naive", "milp", "timer", "cheapest_hours")

_spec = importlib.util.spec_from_file_location("emhass_rest", ROOT / "tools" / "emhass_rest.py")
emhass_rest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(emhass_rest)


def cycles_with_start(watts: pd.Series, max_gap_min: int, on_w: float = 20.0, min_duration_min: int = 20,
                      max_duration_min: int = 300, min_energy_kwh: float = 0.1) -> list[tuple[pd.Timestamp, list[float]]]:
    """Same rules as hems.data.refit.detect_cycles, but each cycle keeps its start time."""  # fmt: skip
    per_min = watts.resample("1min").mean().fillna(0.0)
    on = per_min > on_w
    if not on.any():
        return []
    on_times = per_min.index[on]
    breaks = np.flatnonzero(on_times[1:] - on_times[:-1] > pd.Timedelta(minutes=max_gap_min))
    starts, ends = np.r_[0, breaks + 1], np.r_[breaks, len(on_times) - 1]
    cycles = []
    for s, e in zip(starts, ends):
        segment = per_min[on_times[s] : on_times[e]]
        duration = len(segment)
        if not (min_duration_min <= duration <= max_duration_min):
            continue
        n_slots = int(np.ceil(duration / SLOT_MINUTES))
        padded = np.zeros(n_slots * SLOT_MINUTES)
        padded[:duration] = segment.to_numpy()
        profile = padded.reshape(n_slots, SLOT_MINUTES).mean(axis=1) / 1000
        if profile.sum() * SLOT_MINUTES / 60 >= min_energy_kwh:
            cycles.append((on_times[s], [round(float(p), 3) for p in profile]))
    return cycles


def recent_prices() -> tuple[pd.DataFrame, pd.DataFrame]:
    spot = to_daily_slots(load_price_csv(PRICES))
    spot = spot[spot.index >= date(PRICE_YEAR_START.year - 1, PRICE_YEAR_START.month, PRICE_YEAR_START.day)]
    consumer = spot.apply(lambda row: pd.Series(Tariff().consumer_price(row.to_numpy())), axis=1)
    return spot, consumer


def price_day(recorded: date, available: pd.Index) -> date | None:
    """Same calendar day in the recent price year (1 Oct 2025 - 30 Sep 2026). If that day has no prices
    (a daylight-saving change day, or after the data ends on 25 Sep 2026), the nearest day within one day,
    else the same calendar day one year earlier."""
    month, day = recorded.month, min(recorded.day, 28) if recorded.month == 2 else recorded.day
    year = PRICE_YEAR_START.year if (month, day) >= (PRICE_YEAR_START.month, PRICE_YEAR_START.day) else PRICE_YEAR_START.year + 1
    target = date(year, month, day)
    for candidate in (target, target - pd.Timedelta(days=1), target + pd.Timedelta(days=1), date(year - 1, month, day)):
        if candidate in available:
            return candidate
    return None


def emhass_cost(scenario: Scenario) -> tuple[float | None, bool]:
    raw = json.loads(scenario.model_dump_json())
    emhass_rest._call("http://localhost:5000/action/dayahead-optim", emhass_rest.runtime_params(raw, "profile"))
    starts, status = emhass_rest.starts_from_plan(emhass_rest._call("http://localhost:5000/api/v1/plan"), raw)
    if status != "Optimal" or any(v is None for v in starts.values()):
        return None, False
    result = evaluate(scenario, {k: v for k, v in starts.items() if v is not None})
    return result.cost_eur, result.feasible


def run_house(house: int, spot: pd.DataFrame, consumer: pd.DataFrame, with_emhass: bool) -> None:
    out = OUT / f"house_{house}.jsonl"
    done = {json.loads(line)["date"] for line in out.read_text(encoding="utf-8").splitlines()} if out.exists() else set()
    df = load_house(REFIT, house)
    df = df[df.Issues.fillna(0) == 0]
    base = typical_base_load(df, house)
    by_day: dict[date, list[tuple[str, int, list[float]]]] = defaultdict(list)
    for column, kind in FLEXIBLE_COLUMNS[house].items():
        for start, profile in cycles_with_start(df[column], MERGE_GAP_MIN[kind]):
            by_day[start.date()].append((kind, start.hour * 4 + start.minute // SLOT_MINUTES, profile))
    recorded_days = sorted(set(df.index.date))
    t0, n = time.perf_counter(), 0
    with out.open("a", encoding="utf-8") as fh:
        for day in recorded_days:
            if str(day) in done:
                continue
            cycles = sorted(by_day.get(day, []), key=lambda c: c[1])
            schedulable = [c for c in cycles if c[1] + len(c[2]) <= SLOTS_PER_DAY]
            record = {"date": str(day), "cycles": len(cycles), "pastMidnight": len(cycles) - len(schedulable)}
            pday = price_day(day, spot.index)
            if schedulable and pday is not None:
                counts: dict[str, int] = defaultdict(int)
                appliances = []
                for kind, start, profile in schedulable:
                    counts[kind] += 1
                    appliances.append(FlexibleAppliance(id=f"{kind}_{counts[kind]}", kind=kind, profile_kw=profile,
                                                        earliest_slot=start, deadline_slot=SLOTS_PER_DAY, default_start_slot=start))  # fmt: skip
                limit = max(PEAK_LIMIT_KW, float(base.max()) + max(a.peak_kw for a in appliances) + 0.2)
                scenario = Scenario(
                    id=f"H{house}-{day}", type="A", date=str(pday), start_time=datetime.combine(pday, datetime.min.time()),
                    spot_eur_per_kwh=[float(x) for x in spot.loc[pday]], price_eur_per_kwh=[float(x) for x in consumer.loc[pday]],
                    base_load_kw=[round(float(b), 3) for b in base], peak_limit_kw=round(limit, 2), appliances=appliances,
                    fixed_appliances=fixed_appliances(house), user_request="(full-period estimate)", synthetic=False,
                    notes=f"REFIT house {house}, recorded {day}, priced at {pday}",
                )  # fmt: skip
                record["priceDay"] = str(pday)
                for system in RULE_SYSTEMS:
                    r = execute(scenario, system)
                    record[system] = {"cost": r["cost_eur"], "feasible": r["feasible"]}
                if with_emhass:
                    cost, feasible = emhass_cost(scenario)
                    record["emhass_rest"] = {"cost": cost, "feasible": feasible}
            fh.write(json.dumps(record) + "\n")
            fh.flush()
            n += 1
    print(f"house {house}: {len(recorded_days)} recorded days, {n} new, {time.perf_counter() - t0:.0f} s", flush=True)


def summary() -> None:
    """Totals per household and system -> demo/public/data/fullperiod.json."""
    benchmarks = json.loads((DEMO.parent / "benchmarks.json").read_text(encoding="utf-8"))
    q = next(b for b in benchmarks if b["id"] == "q3")  # held-out set, recent (15-minute) price era, as here
    shares = {r["system"]: r["savingsCaptured"] for r in q["summary"] if r["model"] == "gpt-6-luna"}
    households = []
    for path in sorted(OUT.glob("house_*.jsonl"), key=lambda p: int(p.stem.split("_")[1])):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        scheduled = [r for r in rows if "naive" in r]
        naive = sum(r["naive"]["cost"] for r in scheduled)
        totals = {}
        for system in ("milp", "timer", "cheapest_hours", "emhass_rest"):
            have = [r for r in scheduled if system in r]
            if len(have) < len(scheduled):
                continue
            saving = sum(r["naive"]["cost"] - r[system]["cost"] for r in have if r[system]["feasible"] and r[system]["cost"] is not None)
            totals[system] = {"saving": round(saving, 2), "validDays": sum(r[system]["feasible"] for r in have), "estimated": False}
        optimum = totals["milp"]["saving"]
        for system in ("multi_duo", "single_harness", "oneshot"):
            if shares.get(system) is not None:
                totals[system] = {"saving": round(optimum * shares[system], 2), "validDays": None, "estimated": True,
                                  "share": shares[system]}  # fmt: skip
        households.append({
            "house": int(path.stem.split("_")[1]), "recordedDays": len(rows), "daysWithCycles": len(scheduled),
            "cycles": sum(r["cycles"] for r in rows), "cyclesPastMidnight": sum(r["pastMidnight"] for r in rows),
            "naiveCost": round(naive, 2), "firstDay": rows[0]["date"], "lastDay": rows[-1]["date"], "totals": totals,
        })  # fmt: skip
    DEMO.write_text(json.dumps({"priceYear": "Oct 2025 - Sep 2026", "households": households}, indent=1), encoding="utf-8")
    print(f"{len(households)} households -> {DEMO}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--houses", nargs="*", type=int, default=list(ALL_HOUSES))
    parser.add_argument("--no-emhass", action="store_true")
    parser.add_argument("--summary", action="store_true", help="only aggregate existing results")
    args = parser.parse_args()
    if not args.summary:
        OUT.mkdir(parents=True, exist_ok=True)
        spot, consumer = recent_prices()
        for house in args.houses:
            run_house(house, spot, consumer, not args.no_emhass)
    summary()


if __name__ == "__main__":
    main()
