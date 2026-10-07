"""Local API for the demo's "Try it" view: run the real systems on a household profile entered in the browser.

    uv run --extra demo uvicorn hems.demo_api:app --port 8001

Prices: the official Finnish day-ahead prices from ENTSO-E (ENTSOE_API_KEY). Base load: the typical
daily shape of the REFIT households, scaled to the household's average base load. The peak limit is soft:
a schedule may exceed it, and pays a fee per kW of the day's highest load above it (default EUR 1.97/kW,
Helen's power charge with VAT). Appliance cycles: measured REFIT cycles
for the washing machine, dishwasher and tumble dryer; constant power for the other kinds, as in the
Low-carbon-alerts appliance catalog.

The systems run exactly as in the evaluation (hems.run.execute): no scheduling, MILP optimum, smart
timer, cheapest hours, cheapest window, EMHASS (Docker REST, if reachable) and the Multi-Agent Pipeline
(GPT-4o-mini, live; about 20 s and USD 0.003 per run). This module is not used by any benchmark.
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
import urllib.error
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from hems.core.evaluate import evaluate
from hems.core.models import SLOTS_PER_DAY, FlexibleAppliance, Scenario, load_scenarios
from hems.data import prices as price_data
from hems.data.tariff import Tariff
from hems.run import execute

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
TZ = "Europe/Helsinki"
EMHASS_URL = os.environ.get("EMHASS_URL_DEMO", "http://localhost:5000")
CACHE = ROOT / "results" / "demo_cache"
# Default average base load per home type (kW); the user can override it.
HOUSING_BASE_KW = {"apartment": 0.25, "house": 0.45, "house_electric": 1.2}

# Appliance catalog: the three REFIT kinds use a measured cycle; the others a constant power, with the
# typical power and duration of the Low-carbon-alerts catalog (server/database/migrations/0012_appliances.sql).
CATALOG = {
    "washing_machine": {"label": "Washing machine", "measured": True},
    "dishwasher": {"label": "Dishwasher", "measured": True},
    "tumble_dryer": {"label": "Tumble dryer", "measured": True},
    "ev_charger": {"label": "EV charger", "measured": False, "power_kw": 7.0, "duration_min": 240},
    "sauna": {"label": "Sauna", "measured": False, "power_kw": 7.0, "duration_min": 60},
    "hot_tub": {"label": "Hot tub", "measured": False, "power_kw": 4.0, "duration_min": 120},
    "electric_oven": {"label": "Electric oven", "measured": False, "power_kw": 2.5, "duration_min": 60},
}
SYSTEM_LABELS = {
    "naive": "No scheduling", "milp": "Optimum with the fee (upper bound)", "multi_rag_opt": "Multi-Agent Pipeline",
    "timer": "Smart timer (own heuristic)", "cheapest_hours": "Cheapest hours", "cheapest_window": "Cheapest window",
    "emhass_rest": "EMHASS",
}  # fmt: skip
TOOL_SYSTEMS = ("naive", "timer", "cheapest_hours", "cheapest_window")  # the optimum is computed with the fee

app = FastAPI(title="HEMS demo API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── Appliance cycles ─────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def typical_cycles() -> dict[str, list[float]]:
    """For each REFIT kind, the measured cycle with the median energy among the exploratory benchmark's cycles."""
    by_kind: dict[str, list[list[float]]] = {}
    for scenario in load_scenarios(ROOT / "data" / "scenarios_v2"):
        for a in scenario.appliances:
            by_kind.setdefault(a.kind, []).append(a.profile_kw)
    out = {}
    for kind, cycles in by_kind.items():
        unique = {tuple(c) for c in cycles}
        ranked = sorted(unique, key=lambda c: sum(c) * 0.25)
        out[kind] = list(ranked[len(ranked) // 2])
    return out


def cycle_for(kind: str, power_kw: float | None, duration_min: int | None) -> list[float]:
    entry = CATALOG[kind]
    if entry["measured"] and power_kw is None and duration_min is None:
        return typical_cycles()[kind]
    power = power_kw if power_kw is not None else entry.get("power_kw", max(typical_cycles().get(kind, [2.0])))
    minutes = duration_min if duration_min is not None else entry.get("duration_min", len(typical_cycles().get(kind, [0] * 4)) * 15)
    return [round(float(power), 3)] * max(1, int(np.ceil(minutes / 15)))


# ── Prices (ENTSO-E) ────────────────────────────────────────────────────────


def day_prices(day: date) -> np.ndarray:
    """96 spot prices in EUR/kWh for the local day, cached on disk."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"prices_{day.isoformat()}.json"
    if path.exists():
        return np.asarray(json.loads(path.read_text()))
    from hems.data.fetch_prices import fetch_entsoe

    try:
        df = fetch_entsoe(day - timedelta(days=1), day + timedelta(days=2))
    except Exception as exc:  # noqa: BLE001 - no data yet, network or key problems
        raise HTTPException(404, f"No day-ahead prices for {day} from ENTSO-E yet ({type(exc).__name__}). "
                                 "Prices for tomorrow are published around 14:00 CET.") from exc  # fmt: skip
    series = pd.Series(df.price_eur_mwh.to_numpy() / 1000, index=pd.DatetimeIndex(df.timestamp_utc).tz_convert(TZ))
    days = price_data.to_daily_slots(series.sort_index())
    if day not in days.index:
        raise HTTPException(404, f"No complete price day for {day} (daylight-saving change or not yet published).")
    values = days.loc[day].to_numpy(dtype=float)
    path.write_text(json.dumps([round(v, 6) for v in values]))
    return values


# ── Base load (REFIT household shape) ────────────────────────────────────────


@lru_cache(maxsize=1)
def refit_shape() -> np.ndarray:
    """Hourly shape (mean 1) of the median base load of the REFIT households in the exploratory benchmark."""
    loads = np.array([s.base_load_kw for s in load_scenarios(ROOT / "data" / "scenarios_v2")])
    hourly = np.median(loads, axis=0).reshape(24, 4).mean(axis=1)
    return hourly / hourly.mean()


def base_load(mean_kw: float) -> tuple[np.ndarray, dict[str, str]]:
    """96 slots of base load: the REFIT household shape scaled to the household's average base load."""
    source = {"source": "refit", "label": "typical REFIT household shape (median of the 18 homes)", "day": ""}
    return np.repeat(refit_shape() * mean_kw, 4), source


# ── Soft peak limit: a fee per kW above the limit ────────────────────────────


def score(scenario: Scenario, schedule: dict[str, int], fee_eur_per_kw: float) -> dict[str, Any]:
    """Energy cost plus the fee for the highest load above the limit. Exceeding the limit is allowed; only a
    missing appliance or a start outside its window makes a schedule invalid."""
    ev = evaluate(scenario, schedule)
    problems = [v for v in ev.violations if not v.startswith("peak limit")]
    over = max(0.0, ev.peak_kw - scenario.peak_limit_kw)
    fee = fee_eur_per_kw * over
    return {"energy": ev.cost_eur, "fee": fee, "total": ev.cost_eur + fee, "peak": ev.peak_kw, "over": over,
            "valid": not problems, "violations": problems}  # fmt: skip


def optimum_with_fee(scenario: Scenario, fee_eur_per_kw: float) -> dict[str, int]:
    """MILP of Section 4.5 with the peak constraint relaxed by a priced excess: the cheapest schedule once the fee
    is counted (it exceeds the limit only when the energy saved is worth more than the fee)."""
    import pulp

    from hems.core.evaluate import appliance_cost

    prob = pulp.LpProblem("demo_soft_peak", pulp.LpMinimize)
    x = {(a.id, s): prob.add_variable(f"x_{i}_{s}", cat="Binary")
         for i, a in enumerate(scenario.appliances) for s in a.valid_starts()}  # fmt: skip
    excess = prob.add_variable("excess_kw", lowBound=0)
    prob += pulp.lpSum(appliance_cost(scenario, a, s) * x[a.id, s] for a in scenario.appliances for s in a.valid_starts()) \
        + fee_eur_per_kw * excess  # fmt: skip
    for a in scenario.appliances:
        prob += pulp.lpSum(x[a.id, s] for s in a.valid_starts()) == 1
    for t in range(SLOTS_PER_DAY):
        terms = [a.profile_kw[t - s] * x[a.id, s] for a in scenario.appliances for s in a.valid_starts() if 0 <= t - s < a.duration_slots]
        if terms:
            prob += pulp.lpSum(terms) + scenario.base_load_kw[t] <= scenario.peak_limit_kw + excess
    prob.solve(pulp.COIN_CMD(msg=False, timeLimit=30))
    return {a.id: next(s for s in a.valid_starts() if x[a.id, s].value() > 0.5) for a in scenario.appliances}


# ── Scenario from the profile ────────────────────────────────────────────────


class ApplianceIn(BaseModel):
    kind: str
    ready: str = Field("07:00", description='"HH:MM"')
    finish_by: str = Field("22:00", description='"HH:MM" or "24:00"')
    power_kw: float | None = None
    duration_min: int | None = None


class PlanIn(BaseModel):
    date: str | None = None  # default: today
    housing: str = "house"
    base_kw: float | None = None
    peak_limit_kw: float = 8.0
    # Fee per kW of the day's highest load above the limit. Default: Helen Sahkoverkko's power charge of
    # EUR 1.57 per kW and month excluding VAT, with 25.5 % VAT, counted as if this day set the month's peak.
    fee_eur_per_kw: float = 1.97
    appliances: list[ApplianceIn]


def _slot(clock: str, end: bool = False) -> int:
    hh, mm = (int(x) for x in clock.strip().split(":")[:2])
    minutes = hh * 60 + mm
    if not 0 <= minutes <= 1440 or (minutes == 1440 and not end):
        raise HTTPException(422, f"invalid time {clock!r}")
    return int(np.ceil(minutes / 15)) if end else minutes // 15


def build_scenario(body: PlanIn) -> tuple[Scenario, dict[str, Any]]:
    day = date.fromisoformat(body.date) if body.date else date.today()
    if body.housing not in HOUSING_BASE_KW:
        raise HTTPException(422, f"housing must be one of {sorted(HOUSING_BASE_KW)}")
    if not body.appliances:
        raise HTTPException(422, "add at least one appliance")
    if body.fee_eur_per_kw < 0:
        raise HTTPException(422, "the fee cannot be negative")
    spot = day_prices(day)
    base, source = base_load(body.base_kw or HOUSING_BASE_KW[body.housing])
    counts: dict[str, int] = {}
    appliances = []
    for item in body.appliances:
        if item.kind not in CATALOG:
            raise HTTPException(422, f"unknown appliance {item.kind!r}")
        counts[item.kind] = counts.get(item.kind, 0) + 1
        profile = cycle_for(item.kind, item.power_kw, item.duration_min)
        earliest, deadline = _slot(item.ready), _slot(item.finish_by, end=True)
        name = f"{CATALOG[item.kind]['label']}{'' if counts[item.kind] == 1 else ' ' + str(counts[item.kind])}"
        if deadline - earliest < len(profile):
            raise HTTPException(422, f"{name}: the window {item.ready}-{item.finish_by} is shorter than its "
                                     f"{len(profile) * 15}-minute cycle")  # fmt: skip
        appliances.append(FlexibleAppliance(id=f"{item.kind}_{counts[item.kind]}", kind=item.kind, profile_kw=profile,
                                            earliest_slot=earliest, deadline_slot=deadline, default_start_slot=earliest))  # fmt: skip
    tariff = Tariff()
    scenario = Scenario(
        id=f"demo-{day.isoformat()}", type="demo", date=day.isoformat(),
        start_time=datetime.combine(day, datetime.min.time()),
        spot_eur_per_kwh=[round(float(p), 5) for p in spot],
        price_eur_per_kwh=[round(float(p), 5) for p in tariff.consumer_price(spot)],
        base_load_kw=[round(float(b), 3) for b in base], peak_limit_kw=body.peak_limit_kw, appliances=appliances,
        user_request="", notes="demo: profile entered in the browser",
    )  # fmt: skip
    lines = [f"- {a.kind.replace('_', ' ')} ({a.id}): ready from {scenario.slot_to_time(a.earliest_slot)}, "
             f"must finish by {scenario.boundary_to_time(a.deadline_slot)}" for a in appliances]  # fmt: skip
    scenario.user_request = (
        f"I'm on a spot-price electricity contract. Please schedule these appliance cycles for {scenario.date} so that my "
        "electricity cost is as low as possible, without exceeding my household peak load limit:\n" + "\n".join(lines)
    )
    return scenario, source


def _result(scenario: Scenario, system: str, record: dict[str, Any], naive: dict[str, Any], fee: float) -> dict[str, Any]:
    """A system's schedule scored with the fee; an invalid schedule (missing appliance, start outside its window)
    is scored at the cost of no scheduling, so it saves nothing."""
    starts = {k: v for k, v in (record.get("schedule_slots") or {}).items() if v is not None}
    s = score(scenario, starts, fee)
    total = s["total"] if s["valid"] else naive["total"]
    saving = naive["total"] - total
    return {
        "system": system, "label": SYSTEM_LABELS.get(system, system), "starts": starts,
        "energyEur": round(s["energy"], 4), "feeEur": round(s["fee"], 4), "costEur": round(s["total"], 4),
        "feasible": s["valid"], "violations": s["violations"] + record.get("agent_errors", []),
        "peakKw": round(s["peak"], 2), "overKw": round(s["over"], 2),
        "savingEur": round(saving, 4), "savingPct": round(saving / naive["total"] * 100, 2) if naive["total"] > 0 else 0.0,
        "latencyS": record.get("latency_s"), "tokens": (record.get("tokens_in") or 0) + (record.get("tokens_out") or 0),
        "usd": record.get("cost_usd"), "message": record.get("explanation") or "",
    }  # fmt: skip


def _emhass(scenario: Scenario) -> dict[str, Any] | None:
    """EMHASS with the household limit as its maximum grid power. EMHASS has no peak fee, so if no schedule fits
    under the limit it is asked again with the main fuse (17 kW) as the only limit, and pays the fee."""
    spec = importlib.util.spec_from_file_location("emhass_rest", ROOT / "tools" / "emhass_rest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    raw = json.loads(scenario.model_dump_json())
    started = time.perf_counter()
    starts, status = {a.id: None for a in scenario.appliances}, "no plan"
    for limit in (scenario.peak_limit_kw, max(17.0, scenario.peak_limit_kw)):
        params = module.runtime_params(raw, "profile")
        params["maximum_power_from_grid"] = limit * 1000
        try:
            module._call(f"{EMHASS_URL}/action/dayahead-optim", params, timeout=60)
            plan = module._call(f"{EMHASS_URL}/api/v1/plan", timeout=30)
        except urllib.error.HTTPError:  # EMHASS answers 400 when no schedule fits under this limit
            status = f"infeasible under {limit:g} kW"
            continue
        except (urllib.error.URLError, TimeoutError, OSError):  # service not running
            return None
        starts, status = module.starts_from_plan(plan, raw)
        if status == "Optimal" and all(v is not None for v in starts.values()):
            break
    from hems.run import external_record

    return external_record(scenario, "emhass_rest", starts, time.perf_counter() - started,
                           [] if status == "Optimal" else [f"EMHASS status {status}"])  # fmt: skip


def _scenario_payload(scenario: Scenario, source: dict[str, str]) -> dict[str, Any]:
    return {
        "date": scenario.date, "peakLimitKw": scenario.peak_limit_kw, "baseLoad": source,
        "spotEurPerKwh": scenario.spot_eur_per_kwh, "priceEurPerKwh": scenario.price_eur_per_kwh,
        "baseLoadKw": scenario.base_load_kw,
        "appliances": [{"id": a.id, "kind": a.kind, "profileKw": a.profile_kw, "earliest": a.earliest_slot,
                        "deadline": a.deadline_slot, "energyKwh": round(a.energy_kwh, 3)} for a in scenario.appliances],
    }  # fmt: skip


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/api/catalog")
def catalog() -> dict[str, Any]:
    cycles = typical_cycles()
    items = []
    for kind, entry in CATALOG.items():
        profile = cycles[kind] if entry["measured"] else cycle_for(kind, None, None)
        items.append({"kind": kind, "label": entry["label"], "measured": entry["measured"], "peakKw": max(profile),
                      "durationMin": len(profile) * 15, "energyKwh": round(sum(profile) * 0.25, 2)})  # fmt: skip
    return {"appliances": items, "housing": HOUSING_BASE_KW, "entsoe": bool(os.environ.get("ENTSOE_API_KEY")),
            "emhassUrl": EMHASS_URL}  # fmt: skip


@app.get("/api/day")
def day(
    day_str: str | None = Query(None, alias="date"), housing: str = "house", base_kw: float | None = None
) -> dict[str, Any]:
    if housing not in HOUSING_BASE_KW:
        raise HTTPException(422, f"housing must be one of {sorted(HOUSING_BASE_KW)}")
    d = date.fromisoformat(day_str) if day_str else date.today()
    spot = day_prices(d)
    base, source = base_load(base_kw or HOUSING_BASE_KW[housing])
    return {"date": d.isoformat(), "spotEurPerKwh": [round(float(p), 5) for p in spot],
            "priceEurPerKwh": [round(float(p), 5) for p in Tariff().consumer_price(spot)],
            "baseLoadKw": [round(float(b), 3) for b in base], "baseLoad": source}  # fmt: skip


def _naive(scenario: Scenario, fee: float) -> dict[str, Any]:
    return score(scenario, {a.id: a.default_start_slot for a in scenario.appliances}, fee)


@app.post("/api/plan/tools")
def plan_tools(body: PlanIn) -> dict[str, Any]:
    """The deterministic systems, the optimum with the fee and EMHASS: fast."""
    scenario, source = build_scenario(body)
    fee = body.fee_eur_per_kw
    records = {s: execute(scenario, s) for s in TOOL_SYSTEMS}
    best = optimum_with_fee(scenario, fee)
    records["milp"] = {"schedule_slots": best, "latency_s": None}
    if (emhass := _emhass(scenario)) is not None:
        records["emhass_rest"] = emhass
    naive = _naive(scenario, fee)
    results = [_result(scenario, s, r, naive, fee) for s, r in records.items()]
    return {**_scenario_payload(scenario, source), "feeEurPerKw": fee, "naiveCost": naive["total"],
            "milpCost": score(scenario, best, fee)["total"], "results": results, "emhass": "emhass_rest" in records}  # fmt: skip


@app.post("/api/plan/agent")
def plan_agent(body: PlanIn) -> dict[str, Any]:
    """The Multi-Agent Pipeline with GPT-4o-mini, live, with its message to the household. Its tools and checks
    treat the limit as a target; exceeding it is charged the fee like every other system."""
    scenario, _ = build_scenario(body)
    record = execute(scenario, "multi_rag_opt", "gpt-4o-mini", summarize=True)
    return {"result": _result(scenario, "multi_rag_opt", record, _naive(scenario, body.fee_eur_per_kw), body.fee_eur_per_kw)}
