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
(GPT-6 Luna, live, the two-agent pipeline of design iteration 10; under 10 s and about USD 0.001 per run). This module is not used by any benchmark.
"""

from __future__ import annotations

import importlib.util
import itertools
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
from typing import Any, Literal

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
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
# How long to wait for EMHASS to answer: a few seconds locally, longer in the cloud where it starts from zero
EMHASS_WAIT_S = float(os.environ.get("EMHASS_WAIT_S", "3"))
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
    "single_harness": "Single agent with harness", "single_harness_thoughts": "Single agent with harness",
    "timer": "Smart timer (own heuristic)", "cheapest_hours": "HA cheapest-hours blueprint",
    "cheapest_window": "HA Nordpool Planner", "oneshot": "LLM without tools",
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
# CORS_ORIGINS: the sites allowed to call the API, comma-separated (the deployed demo's address); "*" locally
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])

# ── Spending guard for a public deployment ──────────────────────────────────
# Every language-model run costs API money. LLM_DAILY_LIMIT caps the runs per UTC day for all visitors together,
# LLM_HOURLY_PER_IP the runs per visitor and hour (one click = 3 runs: both agent designs and the LLM without
# tools). 0 or unset = no limit, as when the demo runs locally. Counts are kept in memory, so the deployment runs
# one replica.
LLM_DAILY_LIMIT = int(os.environ.get("LLM_DAILY_LIMIT", "0"))
LLM_HOURLY_PER_IP = int(os.environ.get("LLM_HOURLY_PER_IP", "0"))
_usage_lock = threading.Lock()
_runs_per_day: dict[str, int] = {}
_runs_per_ip: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")  # set by the cloud ingress in front of the API
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "?")


def _allow_llm_run(request: Request) -> None:
    """Count one language-model run, or answer 429 when a limit is reached."""
    if not LLM_DAILY_LIMIT and not LLM_HOURLY_PER_IP:
        return
    now = time.time()
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    ip = _client_ip(request)
    with _usage_lock:
        if LLM_DAILY_LIMIT and _runs_per_day.get(day, 0) >= LLM_DAILY_LIMIT:
            raise HTTPException(429, "The live demo has reached its daily limit of language-model runs. "
                                     "Please try again tomorrow, or see the recorded results on the other pages.")  # fmt: skip
        recent = [t for t in _runs_per_ip.get(ip, []) if now - t < 3600]
        if LLM_HOURLY_PER_IP and len(recent) >= LLM_HOURLY_PER_IP:
            raise HTTPException(429, "Too many live runs from your address in the last hour. Please try again later.")
        _runs_per_ip[ip] = [*recent, now]
        if day not in _runs_per_day:  # a new day: keep only today's count
            _runs_per_day.clear()
        _runs_per_day[day] = _runs_per_day.get(day, 0) + 1


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
    # The agent design run live: the two-agent pipeline, or one agent in the same harness
    design: Literal["two_agents", "one_agent"] = "two_agents"


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
        message=result["message"], schedules=items, cost=result["costEur"],
        peakKw=result["peakKw"], peakLimitKw=scenario.peak_limit_kw,
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


EMHASS_MAX_RUNS = 16  # EMHASS runs once per combination of periods; more combinations would take too long


def _emhass_plan(module: Any, scenario: Scenario) -> tuple[dict[str, int | None], str] | None:
    """One EMHASS day-ahead plan with the household limit as its maximum grid power. EMHASS has no peak fee, so if
    no schedule fits under the limit it is asked again with the main fuse (17 kW) as the only limit, and pays the
    fee. None if the service is not running."""
    raw = json.loads(scenario.model_dump_json())
    starts: dict[str, int | None] = {a.id: None for a in scenario.appliances}
    status = "no plan"
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
    return starts, status


def _period_choices(scenario: Scenario) -> list[tuple[tuple[int, int], ...]]:
    """Every way to give each appliance one of its periods (only periods long enough for its cycle)."""
    options = [[(s, e) for s, e in a.window_periods() if e - s >= a.duration_slots] for a in scenario.appliances]
    return list(itertools.product(*options))


def _one_window_each(scenario: Scenario, choice: tuple[tuple[int, int], ...]) -> Scenario:
    """The scenario as EMHASS is configured for one combination: each appliance gets one period as its window."""
    apps = [a.model_copy(update={"windows": None, "earliest_slot": s, "deadline_slot": e, "default_start_slot": s})
            for a, (s, e) in zip(scenario.appliances, choice, strict=True)]  # fmt: skip
    return scenario.model_copy(update={"appliances": apps})


def _emhass_answers() -> bool:
    """Whether EMHASS is up. Locally it runs all the time, and a stuck Docker engine can keep the port open without
    answering, so the check gives up after a few seconds. In the cloud EMHASS scales to zero and needs about half a
    minute to start after a quiet period, so the check keeps trying for EMHASS_WAIT_S seconds."""
    deadline = time.monotonic() + EMHASS_WAIT_S
    while True:
        try:
            urllib.request.urlopen(EMHASS_URL, timeout=min(5.0, EMHASS_WAIT_S)).close()
            return True
        except urllib.error.HTTPError:
            return True  # it answered, so it is running
        except (urllib.error.URLError, TimeoutError, OSError):
            if time.monotonic() + 2 >= deadline:
                return False
            time.sleep(2)


def _emhass(scenario: Scenario, fee: float) -> dict[str, Any] | None:
    """EMHASS as deployed (REST, Docker). EMHASS gives each deferrable load one start-to-end window, so with
    several periods it is run once for each combination of periods (as a user would have to configure it), and the
    cheapest valid plan, scored like every other system, is kept. None if EMHASS is not running."""
    spec = importlib.util.spec_from_file_location("emhass_rest", ROOT / "tools" / "emhass_rest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    if not _emhass_answers():
        return None
    several = any(a.windows is not None for a in scenario.appliances)
    choices = _period_choices(scenario) if several else [()]
    started = time.perf_counter()
    best: tuple[tuple[bool, float], dict[str, int | None], str] | None = None
    for choice in choices:
        plan = _emhass_plan(module, _one_window_each(scenario, choice) if several else scenario)
        if plan is None:
            return None
        starts, status = plan
        scheduled = {k: v for k, v in starts.items() if v is not None}
        s = score(scenario, scheduled, fee)
        rank = (not (status == "Optimal" and s["valid"] and len(scheduled) == len(starts)), s["total"])
        if best is None or rank < best[0]:
            best = (rank, starts, status)
    from hems.run import external_record

    _, starts, status = best  # type: ignore[misc]
    record = external_record(scenario, "emhass_rest", starts, time.perf_counter() - started,
                             [] if status == "Optimal" else [f"EMHASS status {status}"])  # fmt: skip
    record["emhass_runs"] = len(choices)
    return record


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


# The single agent's request for the household message on the demo page: as prompts.HARNESS_MESSAGE, without a saving
DEMO_MESSAGE = (
    "Now write your message to the household: short and friendly (max 4 sentences), saying when each appliance "
    "runs and the cost of the day. Use only the figures given here, and do not mention any saving or comparison. If "
    "the peak-load check reports a conflict, say plainly that the schedule still exceeds the household limit; never "
    "claim constraints are met unless the check confirms it. Reply with the message only."
)


def _summary_costs(scenario: Scenario, fee: float):  # type: ignore[no-untyped-def]
    """The figures for the household message on the demo page: the cost as scored on the page (energy plus the fee
    for the day's highest load above the limit) and no saving. The page measures savings against the highest-cost
    system shown, which is not known when an agent writes its message, so the message leaves savings to the page.
    The evaluated prompts ask for a saving; this line overrides that request in the demo only."""

    def cost(s: dict[str, Any]) -> str:
        text = f"EUR {s['total']:.3f}"
        if s["fee"] > 0.0005:
            text += (f" (energy EUR {s['energy']:.3f} plus a fee of EUR {s['fee']:.3f} for {s['over']:.2f} kW above "
                     f"the {scenario.peak_limit_kw:.2f} kW limit)")  # fmt: skip
        return text

    def times(schedule: dict[str, int]) -> str:
        """Start and end of every cycle, so the message never has to work out an end time."""
        rows = []
        for appliance_id, start in sorted(schedule.items(), key=lambda kv: (kv[1], kv[0])):
            a = scenario.appliance(appliance_id)
            rows.append(f"- {appliance_id}: {scenario.slot_to_time(start)} to "
                        f"{scenario.boundary_to_time(start + a.duration_slots)} ({a.duration_slots * 15} min)")  # fmt: skip
        return "\nRun times (start to end):\n" + "\n".join(rows) if rows else ""

    def facts(schedule: dict[str, int]) -> str:
        return (f"{times(schedule)}\nCost of the scheduled cycles: {cost(score(scenario, schedule, fee))}.\n"
                "Do not mention any saving or comparison: the page shows the savings next to other systems.")  # fmt: skip

    return facts


@app.post("/api/plan/tools")
def plan_tools(body: PlanIn) -> dict[str, Any]:
    """The deterministic systems, the optimum with the fee and EMHASS: fast."""
    scenario, source = build_scenario(body)
    fee = body.fee_eur_per_kw
    records = {s: execute(scenario, s) for s in TOOL_SYSTEMS}
    best = optimum_with_fee(scenario, fee)
    records["milp"] = {"schedule_slots": best, "latency_s": None}
    # EMHASS gives each deferrable load one start-end window: with several periods it runs once per combination
    runs = len(_period_choices(scenario))
    too_many = runs > EMHASS_MAX_RUNS
    if not too_many and (emhass := _emhass(scenario, fee)) is not None:
        records["emhass_rest"] = emhass
    naive = _naive(scenario, fee)
    results = [_result(scenario, s, r, naive, fee) for s, r in records.items()]
    return {**_scenario_payload(scenario, source), "feeEurPerKw": fee, "naiveCost": naive["total"],
            "milpCost": score(scenario, best, fee)["total"], "results": results, "emhass": "emhass_rest" in records,
            "emhassSkipped": "periods" if too_many else None,
            "emhassRuns": records["emhass_rest"].get("emhass_runs", 1) if "emhass_rest" in records else 0}  # fmt: skip


@app.post("/api/plan/agent", response_model=AgentOut)
def plan_agent(body: PlanIn, request: Request) -> dict[str, Any]:
    """The Multi-Agent Pipeline with the live model (GPT-6 Luna), live, with its message to the household. Its tools and checks
    treat the limit as a target; exceeding it is charged the fee like every other system.

    Runs exactly the pipeline of /api/plan/agent/stream (same setup, and a summary that states the page's cost
    and saving including the fee) and returns only its final result: the scored ``result`` as on the page, and the
    ``recommendation`` in a fixed form ({message, schedules, cost, currency, ...})."""
    scenario, _ = build_scenario(body)
    _allow_llm_run(request)
    for chunk in _pipeline_events(scenario, body.fee_eur_per_kw, body.design):
        event = json.loads(chunk.removeprefix("data: "))
        if event.get("type") == "result":
            return {"result": event["result"], "recommendation": event["recommendation"]}
        if event.get("type") == "error":
            raise HTTPException(502, event.get("message") or "the pipeline stopped with an error")
    raise HTTPException(502, "the pipeline returned no result")


@app.post("/api/plan/oneshot")
def plan_oneshot(body: PlanIn, request: Request) -> dict[str, Any]:
    """The same language model (GPT-6 Luna) without tools: every price and base load in one prompt, one answer.
    Scored like every other system."""
    from langchain_core.callbacks import get_usage_metadata_callback

    from hems.agents.llm import make_model, usage_cost_usd
    from hems.agents.oneshot import run_oneshot
    from hems.run import _record, parse_assignments

    scenario, _ = build_scenario(body)
    _allow_llm_run(request)
    fee = body.fee_eur_per_kw
    started = time.perf_counter()
    try:
        with get_usage_metadata_callback() as usage_cb:
            run = run_oneshot(scenario, make_model(LIVE_MODEL))
            usage = dict(usage_cb.usage_metadata)
    except Exception as exc:  # noqa: BLE001 - the page shows the reason
        raise HTTPException(502, f"{type(exc).__name__}: {exc}") from exc
    schedule, problems = parse_assignments(scenario, run.assignments)
    tokens_in, tokens_out, usd = usage_cost_usd(usage, LIVE_MODEL)
    record = _record(scenario, "oneshot", LIVE_MODEL, 0, run, schedule, problems,
                     time.perf_counter() - started, tokens_in, tokens_out, usd, None)  # fmt: skip
    return {"result": _result(scenario, "oneshot", record, _naive(scenario, fee), fee)}


# ── The pipeline, agent by agent (streamed) ─────────────────────────────────

# Graph node -> the step the page shows. Two agents: Orchestrator (plan, summary) and Scheduler. One agent: the agent
# plans and fixes, then explains. Both designs share the deterministic steps, which the page shows by function name.
AGENT_OF_NODE = {"orchestrator_plan": "orchestrator", "profile_data": "profile_data", "scheduler": "scheduler",
                 "verify_schedule": "verify_schedule", "orchestrator_finalize": "summary",
                 "agent": "agent", "explain": "explain",
                 "retrieve_examples": "retrieve_examples"}  # fmt: skip  # RAG: shown as a step of its own
ACTING_NODES = ("scheduler", "agent")  # the language model agents that call tools
MESSAGE_NODES = ("orchestrator_finalize", "explain")  # where the household message is written
# The systems run live, with explicit Thoughts
LIVE_SYSTEMS = {"two_agents": "multi_duo_thoughts", "one_agent": "single_harness_thoughts"}
LIVE_MODEL = "gpt-6-luna"  # the model of the redesigned evaluation (hems.agents.llm.DEFAULT_MODEL)
REDUCED = {"errors": list, "tool_calls": int, "recoveries": int}  # state keys the pipeline adds up across nodes
INPUT_CHARS = 8000  # cap per part of an agent's input sent to the page


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
        self.tools: dict[Any, tuple[str | None, str, str, float, str, int]] = {}
        self.tokens: dict[str, int] = {}
        self.calls: dict[str, int] = {}  # model calls per node so far: tools requested by the same call share a turn
        self.lock = threading.Lock()

    def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, **kwargs):  # type: ignore[no-untyped-def]
        if node := _node(metadata):
            with self.lock:
                self.calls[node] = self.calls.get(node, 0) + 1
            self.emit({"type": "working", "node": node})
            self._input(node, messages[0] if messages else [], kwargs.get("invocation_params") or {})

    def _input(self, node: str, messages: list, params: dict[str, Any]) -> None:
        """The agent's input on its first model call (no answers or tool results yet): the system prompt, the message
        and the tools it may call. Later calls of the same agent only add its own Actions and Observations."""
        if node == "explain" and messages:  # the single agent's message: its conversation so far plus the figures
            self.emit({"type": "input", "node": node, "prompt": {
                "system": "(the agent's own system prompt and its whole conversation above)",
                "message": str(messages[-1].content)[:INPUT_CHARS], "tools": []}})  # fmt: skip
            return
        if any(m.type in ("ai", "tool") for m in messages):
            return
        text = lambda kind: "\n\n".join(str(m.content) for m in messages if m.type == kind)[:INPUT_CHARS]  # noqa: E731
        tools = [t.get("function", {}).get("name") or t.get("name", "") for t in params.get("tools") or []]
        self.emit({"type": "input", "node": node, "prompt": {"system": text("system"), "message": text("human"),
                                                              "tools": [t for t in tools if t]}})  # fmt: skip

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
        node = _node(metadata)
        turn = self.calls.get(node or "", 0)  # the model call that requested this tool
        self.tools[run_id] = (node, (serialized or {}).get("name", "tool"), args, time.perf_counter(), thought, turn)

    def on_tool_end(self, output, *, run_id, **kwargs):  # type: ignore[no-untyped-def]
        node, name, args, started, thought, turn = self.tools.pop(run_id, (None, "tool", "", time.perf_counter(), "", 0))
        if node not in ACTING_NODES:  # the functions call tools internally; only the acting agent's actions are shown
            return
        text = str(getattr(output, "content", output))
        self.emit({"type": "tool", "node": node, "name": name, "input": args[:300], "output": text[:4000],
                   "thought": thought[:300], "ms": round((time.perf_counter() - started) * 1000), "turn": turn})  # fmt: skip


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
    if node in ACTING_NODES and (proposal := update.get("proposal")):
        return {"starts": starts(proposal.assignments), "costEur": proposal.total_cost_eur, "explanation": proposal.explanation}
    if node == "verify_schedule" and "feedback" in update:
        feedback = update.get("feedback") or ""
        return {"starts": update.get("checked") or {}, "feedback": feedback, "passed": not feedback}
    if node in MESSAGE_NODES:
        return {"starts": update.get("final") or {}, "summary": update.get("summary", "")}
    return {}


def _pipeline_events(scenario: Scenario, fee: float, design: str = "two_agents") -> Iterator[str]:
    """Run the Multi-Agent Pipeline (two agents, design iteration 10; the household data are profiled while the
    Orchestrator plans) and stream
    server-sent events: each agent starting, its tool calls, what it handed on, the summary as it is written, and
    finally the scored result, the same record as /api/plan/agent."""
    from langchain_core.callbacks import get_usage_metadata_callback

    from hems.agents.llm import make_model, usage_cost_usd
    from hems.agents.harness_agent import build_harness_agent
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
            model = make_model(LIVE_MODEL)
            retriever = default_retriever()  # RAG: the solved days given to the acting agent as worked examples
            retriever = default_retriever()  # RAG: the solved days given to the acting agent as worked examples
            if design == "one_agent":
                pipeline = build_harness_agent(scenario, model, retriever=retriever, thoughts=True,
                                               summary_costs=_summary_costs(scenario, fee),
                                               message_instruction=DEMO_MESSAGE)  # fmt: skip
            else:
                pipeline = build_pipeline(scenario, lambda _role: model, retriever=retriever, thoughts=True,
                                          parallel_start=True, summary_costs=_summary_costs(scenario, fee))  # fmt: skip
            state: dict[str, Any] = {key: kind() for key, kind in REDUCED.items()}
            emit({"type": "start"})
            emit({"type": "working", "node": "retrieve_examples"})
            found = retriever.retrieve(scenario)
            emit({"type": "done", "node": "retrieve_examples", "tokens": 0, "errors": [], "output": {
                "library": len(retriever.cases),
                "examples": [{"id": c.id, "type": c.type, "date": c.date, "similarity": round(s, 2), "text": c.text}
                             for c, s in found]}})  # fmt: skip
            emit({"type": "working", "node": "retrieve_examples"})
            found = retriever.retrieve(scenario)
            emit({"type": "done", "node": "retrieve_examples", "tokens": 0, "errors": [], "output": {
                "library": len(retriever.cases),
                "examples": [{"id": c.id, "type": c.type, "date": c.date, "similarity": round(s, 2), "text": c.text}
                             for c, s in found]}})  # fmt: skip
            with get_usage_metadata_callback() as usage_cb:
                stream = pipeline.stream({"request": scenario.user_request}, config={"recursion_limit": 50, "callbacks": [watch]},
                                         stream_mode=["updates", "messages"])  # fmt: skip
                for mode, chunk in stream:
                    if mode == "messages":
                        message, meta = chunk
                        if (node := meta.get("langgraph_node")) in MESSAGE_NODES and getattr(message, "content", ""):
                            emit({"type": "summary_delta", "node": node, "text": message.content})
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
                           tool_calls=state["tool_calls"], recoveries=state["recoveries"], iterations=state.get("rounds", 0))  # fmt: skip
            schedule, problems = parse_assignments(scenario, run.assignments)
            tokens_in, tokens_out, usd = usage_cost_usd(usage, LIVE_MODEL)
            record = _record(scenario, LIVE_SYSTEMS[design], LIVE_MODEL, 0, run, schedule, problems,
                             time.perf_counter() - started, tokens_in, tokens_out, usd, None)  # fmt: skip
            result = _result(scenario, LIVE_SYSTEMS[design], record, _naive(scenario, fee), fee)
            emit({"type": "result", "result": result, "recommendation": _recommendation(scenario, result)})
        except Exception as exc:  # noqa: BLE001 - shown on the page instead of a broken stream
            emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True).start()
    while (event := events.get()) is not None:
        yield f"data: {json.dumps(event, default=str)}\n\n"


@app.post("/api/plan/agent/stream")
def plan_agent_stream(body: PlanIn, request: Request) -> StreamingResponse:
    """The Multi-Agent Pipeline agent by agent, as server-sent events (see _pipeline_events)."""
    scenario, _ = build_scenario(body)  # input errors are answered as JSON before the stream starts
    _allow_llm_run(request)
    return StreamingResponse(_pipeline_events(scenario, body.fee_eur_per_kw, body.design), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})  # fmt: skip
