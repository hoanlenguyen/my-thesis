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
(GPT-4o-mini, live, the two-agent pipeline of design iteration 10; under 10 s and about USD 0.001 per run). This module is not used by any benchmark.
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
import urllib.error
import queue
import threading
import urllib.request
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.callbacks import BaseCallbackHandler
from pydantic import BaseModel, Field

from hems.core.evaluate import appliance_cost, evaluate
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
    "naive": "No scheduling", "milp": "Optimum with the fee (upper bound)",
    "multi_duo": "Multi-Agent Pipeline", "multi_duo_thoughts": "Multi-Agent Pipeline",
    "timer": "Smart timer (own heuristic)", "cheapest_hours": "Cheapest hours (HA blueprint)",
    "cheapest_window": "Cheapest window (HA Nordpool Planner)",
    "emhass_rest": "EMHASS",
}  # fmt: skip
TOOL_SYSTEMS = ("naive", "timer", "cheapest_hours", "cheapest_window")  # the optimum is computed with the fee

@asynccontextmanager
async def _warm_up(_app: FastAPI) -> AsyncIterator[None]:
    """Load the case library, the REFIT cycles and the agent libraries once at start-up, so the first
    recommendation does not wait for them (about 4 s)."""
    from langchain_openai import ChatOpenAI  # noqa: F401 - the model client

    from hems.agents.multi_agent import build_pipeline  # noqa: F401 - imports LangChain and LangGraph
    from hems.rag import default_retriever

    default_retriever()
    typical_cycles()
    refit_shape()
    yield


app = FastAPI(title="HEMS demo API", lifespan=_warm_up)
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
    """The appliance's cycle per 15-minute slot. A measured REFIT cycle keeps its shape when the household
    changes its runtime or peak power: it is stretched to the runtime and scaled so its peak is that power."""
    entry = CATALOG[kind]
    if not entry["measured"]:
        power = power_kw if power_kw is not None else entry["power_kw"]
        minutes = duration_min if duration_min is not None else entry["duration_min"]
        return [round(float(power), 3)] * max(1, int(np.ceil(minutes / 15)))
    measured = np.asarray(typical_cycles()[kind], dtype=float)
    slots = max(1, int(np.ceil(duration_min / 15))) if duration_min is not None else len(measured)
    if slots != len(measured):  # stretch or compress in time, keeping the shape
        old = (np.arange(len(measured)) + 0.5) / len(measured)
        measured = np.interp((np.arange(slots) + 0.5) / slots, old, measured)
    if power_kw is not None and measured.max() > 0 and abs(power_kw - measured.max()) > 1e-3:
        measured = measured * power_kw / measured.max()
    return [round(float(p), 3) for p in measured]


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


class PeriodIn(BaseModel):
    start: str = Field(description='"HH:MM"')
    end: str = Field(description='"HH:MM" or "24:00"')


class ApplianceIn(BaseModel):
    kind: str
    ready: str = Field("07:00", description='"HH:MM"')
    finish_by: str = Field("22:00", description='"HH:MM" or "24:00"')
    # Allowed periods, e.g. 06:00-09:00 and 18:00-22:00; the cycle must start and finish inside one of them.
    # When given, they replace ready/finish_by.
    periods: list[PeriodIn] | None = None
    power_kw: float | None = Field(None, gt=0, le=50, description="peak power; default from the catalog")
    duration_min: int | None = Field(None, ge=15, le=1440, description="runtime; default from the catalog")


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


def _periods(item: ApplianceIn, name: str, cycle_slots: int) -> list[tuple[int, int]]:
    """The appliance's allowed periods as sorted, disjoint slot ranges; overlapping or touching periods are merged.
    Every period must be long enough for one whole cycle."""
    raw = item.periods or [PeriodIn(start=item.ready, end=item.finish_by)]
    spans = []
    for p in raw:
        start, end = _slot(p.start), _slot(p.end, end=True)
        if end <= start:
            raise HTTPException(422, f"{name}: the period {p.start}-{p.end} ends before it starts")
        if end - start < cycle_slots:
            raise HTTPException(422, f"{name}: the period {p.start}-{p.end} is shorter than its "
                                     f"{cycle_slots * 15}-minute cycle")  # fmt: skip
        spans.append((start, end))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


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
        name = f"{CATALOG[item.kind]['label']}{'' if counts[item.kind] == 1 else ' ' + str(counts[item.kind])}"
        periods = _periods(item, name, len(profile))
        earliest, deadline = periods[0][0], periods[-1][1]
        appliances.append(FlexibleAppliance(id=f"{item.kind}_{counts[item.kind]}", kind=item.kind, profile_kw=profile,
                                            earliest_slot=earliest, deadline_slot=deadline, default_start_slot=earliest,
                                            windows=periods if len(periods) > 1 else None))  # fmt: skip
    tariff = Tariff()
    scenario = Scenario(
        id=f"demo-{day.isoformat()}", type="demo", date=day.isoformat(),
        start_time=datetime.combine(day, datetime.min.time()),
        spot_eur_per_kwh=[round(float(p), 5) for p in spot],
        price_eur_per_kwh=[round(float(p), 5) for p in tariff.consumer_price(spot)],
        base_load_kw=[round(float(b), 3) for b in base], peak_limit_kw=body.peak_limit_kw, appliances=appliances,
        user_request="", notes="demo: profile entered in the browser",
    )  # fmt: skip
    def when(a: FlexibleAppliance) -> str:
        if a.windows is None:
            return f"ready from {scenario.slot_to_time(a.earliest_slot)}, must finish by {scenario.boundary_to_time(a.deadline_slot)}"
        periods = " or ".join(f"{scenario.slot_to_time(s)}-{scenario.boundary_to_time(e)}" for s, e in a.windows)
        return f"may run only within {periods} (start and finish inside one period)"

    lines = [f"- {a.kind.replace('_', ' ')} ({a.id}): {when(a)}" for a in appliances]
    scenario.user_request = (
        f"I'm on a spot-price electricity contract. Please schedule these appliance cycles for {scenario.date} so that my "
        "electricity cost is as low as possible, without exceeding my household peak load limit:\n" + "\n".join(lines)
    )
    return scenario, source


class ScheduleItem(BaseModel):
    """One appliance cycle of the recommendation."""

    applianceId: str  # noqa: N815 - JSON field names as the page uses them
    appliance: str
    start: str = Field(description='"HH:MM"')
    end: str = Field(description='"HH:MM", or "24:00" at midnight')
    period: str = Field(description='the allowed period the cycle runs in, e.g. "18:00-22:00"')
    energyKwh: float  # noqa: N815
    cost: float = Field(description="energy cost of this cycle, in `currency`")


class Recommendation(BaseModel):
    """The pipeline's daily recommendation in a fixed form. Only ``message`` is written by the language model;
    ``schedules`` and the figures come from the verified schedule as scored on the page."""

    message: str
    schedules: list[ScheduleItem]
    cost: float = Field(description="what the household pays: energy plus the fee above the peak limit")
    saving: float = Field(description="against starting every appliance as soon as it is ready")
    savingPct: float  # noqa: N815
    currency: str = "EUR"
    currencySymbol: str = "€"  # noqa: N815
    peakKw: float  # noqa: N815
    peakLimitKw: float  # noqa: N815
    valid: bool = Field(description="every appliance scheduled, every start inside its allowed period")
    date: str


class AgentOut(BaseModel):
    result: dict[str, Any]
    recommendation: Recommendation


def _recommendation(scenario: Scenario, result: dict[str, Any]) -> dict[str, Any]:
    """The fixed-form recommendation built around the pipeline's message from its scored result."""
    items = []
    for appliance_id, start in sorted(result["starts"].items(), key=lambda kv: (kv[1], kv[0])):
        a = _find(scenario, appliance_id)
        if a is None:
            continue
        end = start + a.duration_slots
        period = next(((p0, p1) for p0, p1 in a.window_periods() if p0 <= start and end <= p1), None)
        n = appliance_id.rsplit("_", 1)[-1]
        name = CATALOG.get(a.kind, {}).get("label", a.kind) + ("" if n == "1" else f" {n}")
        items.append(ScheduleItem(
            applianceId=appliance_id, appliance=name, start=scenario.slot_to_time(start),
            end=scenario.boundary_to_time(end),
            period=f"{scenario.slot_to_time(period[0])}-{scenario.boundary_to_time(period[1])}" if period else "outside",
            energyKwh=round(a.energy_kwh, 3), cost=round(appliance_cost(scenario, a, start), 4),
        ))  # fmt: skip
    return Recommendation(
        message=result["message"], schedules=items, cost=result["costEur"], saving=result["savingEur"],
        savingPct=result["savingPct"], peakKw=result["peakKw"], peakLimitKw=scenario.peak_limit_kw,
        valid=result["feasible"], date=scenario.date,
    ).model_dump()  # fmt: skip


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
    try:  # a stuck Docker engine can keep the port open without answering: give up quickly instead of after 60 s
        urllib.request.urlopen(EMHASS_URL, timeout=3).close()
    except urllib.error.HTTPError:
        pass  # it answered, so it is running
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
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
                        "deadline": a.deadline_slot, "periods": [list(p) for p in a.window_periods()],
                        "energyKwh": round(a.energy_kwh, 3)} for a in scenario.appliances],
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


def _summary_costs(scenario: Scenario, fee: float):  # type: ignore[no-untyped-def]
    """Cost lines for the pipeline's summary, scored as on the page: energy plus the fee for the day's highest load
    above the limit, against starting every appliance as soon as it is ready (the "Saving" column)."""
    naive = _naive(scenario, fee)

    def cost(s: dict[str, Any]) -> str:
        text = f"EUR {s['total']:.3f}"
        if s["fee"] > 0.0005:
            text += (f" (energy EUR {s['energy']:.3f} plus a fee of EUR {s['fee']:.3f} for {s['over']:.2f} kW above "
                     f"the {scenario.peak_limit_kw:.2f} kW limit)")  # fmt: skip
        return text

    def facts(schedule: dict[str, int]) -> str:
        s = score(scenario, schedule, fee)
        saving = naive["total"] - s["total"]
        share = f" ({saving / naive['total'] * 100:.0f} %)" if naive["total"] > 0 else ""
        return (f"\nCost of the scheduled cycles: {cost(s)}. Cost if every appliance started as soon as it is ready: "
                f"{cost(naive)}. Saving: EUR {saving:.3f}{share}.")  # fmt: skip

    return facts


@app.post("/api/plan/tools")
def plan_tools(body: PlanIn) -> dict[str, Any]:
    """The deterministic systems, the optimum with the fee and EMHASS: fast."""
    scenario, source = build_scenario(body)
    fee = body.fee_eur_per_kw
    records = {s: execute(scenario, s) for s in TOOL_SYSTEMS}
    best = optimum_with_fee(scenario, fee)
    records["milp"] = {"schedule_slots": best, "latency_s": None}
    # EMHASS gives each deferrable load one start-end window, so it is not run when an appliance has several periods.
    several_periods = any(a.windows is not None for a in scenario.appliances)
    if not several_periods and (emhass := _emhass(scenario)) is not None:
        records["emhass_rest"] = emhass
    naive = _naive(scenario, fee)
    results = [_result(scenario, s, r, naive, fee) for s, r in records.items()]
    return {**_scenario_payload(scenario, source), "feeEurPerKw": fee, "naiveCost": naive["total"],
            "milpCost": score(scenario, best, fee)["total"], "results": results, "emhass": "emhass_rest" in records,
            "emhassSkipped": "periods" if several_periods else None}  # fmt: skip


@app.post("/api/plan/agent", response_model=AgentOut)
def plan_agent(body: PlanIn) -> dict[str, Any]:
    """The Multi-Agent Pipeline with GPT-4o-mini, live, with its message to the household. Its tools and checks
    treat the limit as a target; exceeding it is charged the fee like every other system.

    Runs exactly the pipeline of /api/plan/agent/stream (same setup, and a summary that states the page's cost
    and saving including the fee) and returns only its final result: the scored ``result`` as on the page, and the
    ``recommendation`` in a fixed form ({message, schedules, cost, saving, currency, ...})."""
    scenario, _ = build_scenario(body)
    for chunk in _pipeline_events(scenario, body.fee_eur_per_kw):
        event = json.loads(chunk.removeprefix("data: "))
        if event.get("type") == "result":
            return {"result": event["result"], "recommendation": event["recommendation"]}
        if event.get("type") == "error":
            raise HTTPException(502, event.get("message") or "the pipeline stopped with an error")
    raise HTTPException(502, "the pipeline returned no result")


# ── The pipeline, agent by agent (streamed) ─────────────────────────────────

# Pipeline node -> the agent the page shows. The Resolver node also holds the Orchestrator's verification step.
# The two agents (Orchestrator, Scheduler) and the two deterministic steps, which the page shows by function name
AGENT_OF_NODE = {"orchestrator_plan": "orchestrator", "profile_data": "profile_data", "scheduler": "scheduler",
                 "verify_schedule": "verify_schedule", "orchestrator_finalize": "summary"}  # fmt: skip
# The pipeline run live: design iteration 10, two language-model agents (Orchestrator and Scheduler)
LIVE_SYSTEM = "multi_duo_thoughts"
REDUCED = {"errors": list, "tool_calls": int, "recoveries": int}  # state keys the pipeline adds up across nodes


def _node(metadata: dict[str, Any] | None) -> str | None:
    """The pipeline node a callback belongs to; inside an agent, the first part of the checkpoint namespace."""
    meta = metadata or {}
    namespace = str(meta.get("langgraph_checkpoint_ns") or "").split(":")[0]
    node = namespace if namespace in AGENT_OF_NODE else meta.get("langgraph_node")
    return node if node in AGENT_OF_NODE else None


class _AgentWatch(BaseCallbackHandler):
    """Turns the callbacks of a pipeline run into page events: an agent starts working, calls a tool, uses tokens."""

    def __init__(self, emit: Any) -> None:
        self.emit = emit
        self.tools: dict[Any, tuple[str | None, str, str, float]] = {}
        self.tokens: dict[str, int] = {}
        self.lock = threading.Lock()

    def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, **kwargs):  # type: ignore[no-untyped-def]
        if node := _node(metadata):
            self.emit({"type": "working", "node": node})

    def on_llm_end(self, response, *, run_id, metadata=None, **kwargs):  # type: ignore[no-untyped-def]
        try:
            usage = response.generations[0][0].message.usage_metadata or {}
        except (AttributeError, IndexError):
            return
        node = _node(metadata) or "?"
        with self.lock:
            self.tokens[node] = self.tokens.get(node, 0) + usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

    def on_tool_start(self, serialized, input_str, *, run_id, metadata=None, inputs=None, **kwargs):  # type: ignore[no-untyped-def]
        inputs = inputs if isinstance(inputs, dict) else {}
        thought = str(inputs.get("thought", ""))  # explicit Thought (iteration 11)
        args = json.dumps({k: v for k, v in inputs.items() if k != "thought"}, default=str) if inputs else str(input_str)
        self.tools[run_id] = (_node(metadata), (serialized or {}).get("name", "tool"), args, time.perf_counter(), thought)

    def on_tool_end(self, output, *, run_id, **kwargs):  # type: ignore[no-untyped-def]
        node, name, args, started, thought = self.tools.pop(run_id, (None, "tool", "", time.perf_counter(), ""))
        if node != "scheduler":  # the functions call tools internally; only the Scheduler agent's actions are shown
            return
        text = str(getattr(output, "content", output))
        self.emit({"type": "tool", "node": node, "name": name, "input": args[:300], "output": text[:600],
                   "thought": thought[:300], "ms": round((time.perf_counter() - started) * 1000)})  # fmt: skip


def _find(scenario: Scenario, appliance_id: Any) -> FlexibleAppliance | None:
    return next((a for a in scenario.appliances if a.id == appliance_id), None)


def _agent_output(node: str, update: dict[str, Any]) -> dict[str, Any]:
    """What an agent handed on, in a form the page can show."""

    def starts(assignments: Any) -> dict[str, str]:
        return {a.appliance_id: a.start_time for a in assignments or []}

    if node == "orchestrator_plan" and (brief := update.get("brief")):
        return {"appliances": brief.appliance_ids, "notes": brief.notes}
    if node == "profile_data" and (profile := update.get("profile")):
        return {"appliances": [{"id": p.appliance_id, "kind": p.kind, "flexible": p.flexible, "peakKw": p.peak_kw,
                                "durationMin": p.duration_minutes, "window": f"{p.earliest_time}-{p.deadline_time}"}
                               for p in profile.appliances]}  # fmt: skip
    if node == "scheduler" and (proposal := update.get("proposal")):
        return {"starts": starts(proposal.assignments), "costEur": proposal.total_cost_eur, "explanation": proposal.explanation}
    if node == "verify_schedule" and "feedback" in update:
        feedback = update.get("feedback") or ""
        return {"starts": update.get("checked") or {}, "feedback": feedback, "passed": not feedback}
    if node == "orchestrator_finalize":
        return {"starts": update.get("final") or {}, "summary": update.get("summary", "")}
    return {}


def _pipeline_events(scenario: Scenario, fee: float) -> Iterator[str]:
    """Run the Multi-Agent Pipeline (two agents, design iteration 10; the household data are profiled while the
    Orchestrator plans) and stream
    server-sent events: each agent starting, its tool calls, what it handed on, the summary as it is written, and
    finally the scored result, the same record as /api/plan/agent."""
    from langchain_core.callbacks import get_usage_metadata_callback

    from hems.agents.llm import make_model, usage_cost_usd
    from hems.agents.multi_agent import build_pipeline
    from hems.agents.types import AgentRun
    from hems.rag import default_retriever
    from hems.run import _record, parse_assignments

    events: queue.Queue[dict[str, Any] | None] = queue.Queue()
    started = time.perf_counter()

    def emit(event: dict[str, Any]) -> None:
        agent = AGENT_OF_NODE.get(event.get("node") or "")
        events.put({**event, "agent": agent, "t": round(time.perf_counter() - started, 2)})

    def work() -> None:
        try:
            watch = _AgentWatch(emit)
            model = make_model("gpt-4o-mini")
            pipeline = build_pipeline(scenario, lambda _role: model, retriever=default_retriever(), thoughts=True,
                                      parallel_start=True, summary_costs=_summary_costs(scenario, fee))  # fmt: skip
            state: dict[str, Any] = {key: kind() for key, kind in REDUCED.items()}
            emit({"type": "start"})
            with get_usage_metadata_callback() as usage_cb:
                stream = pipeline.stream({"request": scenario.user_request}, config={"recursion_limit": 50, "callbacks": [watch]},
                                         stream_mode=["updates", "messages"])  # fmt: skip
                for mode, chunk in stream:
                    if mode == "messages":
                        message, meta = chunk
                        if meta.get("langgraph_node") == "orchestrator_finalize" and getattr(message, "content", ""):
                            emit({"type": "summary_delta", "node": "orchestrator_finalize", "text": message.content})
                        continue
                    for node, update in chunk.items():
                        update = update or {}
                        for key, value in update.items():
                            state[key] = state[key] + value if key in REDUCED else value
                        if node in AGENT_OF_NODE:
                            output = _agent_output(node, update)
                            for row in output.get("appliances", []) if node == "profile_data" else []:
                                # show the true periods; the Profiler's profile has room for one window only
                                if isinstance(row, dict) and (a := _find(scenario, row.get("id"))) and a.windows:
                                    row["window"] = " or ".join(f"{scenario.slot_to_time(s)}-{scenario.boundary_to_time(e)}"
                                                                for s, e in a.windows)  # fmt: skip
                            emit({"type": "done", "node": node, "output": output,
                                  "tokens": watch.tokens.get(node, 0), "errors": update.get("errors", [])})  # fmt: skip
                usage = dict(usage_cb.usage_metadata)
            run = AgentRun(assignments=state.get("final"), explanation=state.get("summary", ""), errors=state["errors"],
                           tool_calls=state["tool_calls"], recoveries=state["recoveries"], iterations=state.get("iterations", 0))  # fmt: skip
            schedule, problems = parse_assignments(scenario, run.assignments)
            tokens_in, tokens_out, usd = usage_cost_usd(usage, "gpt-4o-mini")
            record = _record(scenario, LIVE_SYSTEM, "gpt-4o-mini", 0, run, schedule, problems,
                             time.perf_counter() - started, tokens_in, tokens_out, usd, None)  # fmt: skip
            result = _result(scenario, LIVE_SYSTEM, record, _naive(scenario, fee), fee)
            emit({"type": "result", "result": result, "recommendation": _recommendation(scenario, result)})
        except Exception as exc:  # noqa: BLE001 - shown on the page instead of a broken stream
            emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True).start()
    while (event := events.get()) is not None:
        yield f"data: {json.dumps(event, default=str)}\n\n"


@app.post("/api/plan/agent/stream")
def plan_agent_stream(body: PlanIn) -> StreamingResponse:
    """The Multi-Agent Pipeline agent by agent, as server-sent events (see _pipeline_events)."""
    scenario, _ = build_scenario(body)  # input errors are answered as JSON before the stream starts
    return StreamingResponse(_pipeline_events(scenario, body.fee_eur_per_kw), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})  # fmt: skip
