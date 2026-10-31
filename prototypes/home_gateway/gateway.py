"""Home energy gateway with an agent layer, on the digital twin (exploratory, not part of the thesis evaluation).

The twin (``twin.py``) scores strategies that know the whole day. Here the gateway only knows forecasts and what
it has measured so far, as a real one would:

- PV and heat demand: the actual value times (1 + error), with a seeded AR(1) error per day whose weight grows
  with lead time (full weight for the day-ahead plan made at midnight); the household load: the mean of the
  same slot over the previous seven days;
- EV sessions: unknown until the car plugs in (its energy and window are then known, as an app would report).

Every plan is executed by the same deterministic control layer (``execute``), which keeps the indoor temperature
in the comfort band, charges the car at full power when its deadline requires it, charges a car that no plan
covers with the "min + PV" rule, and keeps the battery within its limits. Strategies on sample days:

- rules:      the twin's rule set (no forecasts needed);
- day_ahead:  one LP plan at midnight on the day-ahead forecasts;
- mpc_hourly: the LP re-solved every hour and at each plug-in, with the latest forecasts and measured state;
- mpc_events: the LP re-solved at the agent's checkpoints (00, 06, 12, 18 h and each plug-in), default settings;
- agent:      a ReAct agent called at the same checkpoints. It reads the situation, may run the LP with its own
              settings (PV forecast derating, battery reserve, comfort band, grid limit), checks the plan and
              decides to commit it or keep the current one;
- optimum:    the twin's perfect-foresight LP.

Each sample day starts from the reference state (battery ``soc_start``, set point); costs are adjusted for the
state a strategy leaves at midnight (stored battery energy and heat, valued at the day's mean import price),
so no strategy gains by emptying the battery or cooling the house.

    uv run python prototypes/home_gateway/gateway.py --raw-dir D:/Study/my-thesis/data/raw --models gpt-6-luna
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import pulp
from dotenv import load_dotenv
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from twin import Day, Home, Result, load_days, rules

from hems.agents.harness import ReactResult, run_react
from hems.agents.llm import make_model, usage_cost_usd
from hems.core.models import SLOT_HOURS, SLOTS_PER_DAY

PV_ERROR_SD = 0.35  # "noise" forecasts: relative error of PV; "weather" forecasts: of global radiation
HEAT_ERROR_SD = 0.10  # "noise" forecasts: relative error of heat demand
TEMP_ERROR_SD_K = 1.5  # "weather" forecasts: day-ahead air temperature error
HEATING_BASE_C = 15.5  # heating-degree base of the fitted heat model
ERROR_RHO = 0.9  # AR(1) correlation between 15-min slots
FULL_ERROR_LEAD_H = 12  # intraday forecasts reach the full day-ahead error at this lead time
CHECKPOINTS = (0, 24, 48, 72)  # 00:00, 06:00, 12:00, 18:00
AGENT_STEP_LIMIT = 24
SEED = 2026


# ── Forecasts ────────────────────────────────────────────────────────────────
@dataclass
class Forecasts:
    """Forecast errors of one day; ``at(tau)`` gives the forecasts made at slot ``tau``."""

    day: Day
    pv_error: np.ndarray
    heat_error: np.ndarray  # "weather": temperature error in K
    fixed_forecast: np.ndarray
    models: WeatherModels | None = None  # set: forecasts from DWD weather; None: actual values with noise

    def at(self, tau: int | None) -> dict[str, np.ndarray]:
        """``tau=None``: the day-ahead forecasts (made the day before, full error)."""
        lead_h = (np.arange(SLOTS_PER_DAY) - (tau or 0)) * SLOT_HOURS
        weight = np.ones(SLOTS_PER_DAY) if tau is None else np.clip(lead_h / FULL_ERROR_LEAD_H, 0.0, 1.0)
        if self.models is None:
            pv = np.clip(self.day.pv * (1 + self.pv_error * weight), 0.0, None)
            heat = np.clip(self.day.heat * (1 + self.heat_error * weight), 0.0, None)
        else:
            # Weather forecast = observed weather + error; the fitted models' own error stays in. Past slots are
            # measured, so they are the actual values.
            ghi = np.clip(self.day.ghi * (1 + self.pv_error * weight), 0.0, None)
            temp = self.day.temp + self.heat_error * weight
            pv, heat = self.models.pv(self.day, ghi), self.models.heat(temp)
            if tau is not None:
                pv[:tau], heat[:tau] = self.day.pv[:tau], self.day.heat[:tau]
        return {"pv": pv, "heat": heat, "fixed": self.fixed_forecast, "cop": self.day.cop,
                "import_price": self.day.import_price, "export_price": self.day.export_price}  # fmt: skip


@dataclass(frozen=True)
class WeatherModels:
    """PV = monthly factor x global radiation; heat = a + b x heating degrees (both least squares over the year)."""

    pv_factor: dict[int, float]  # kW per W/m2, by month
    heat_a: float
    heat_b: float

    @classmethod
    def fit(cls, days: list[Day]) -> WeatherModels:
        factors = {}
        for month in range(1, 13):
            sel = [d for d in days if int(d.date[5:7]) == month]
            ghi = np.concatenate([d.ghi for d in sel]) if sel else np.zeros(1)
            pv = np.concatenate([d.pv for d in sel]) if sel else np.zeros(1)
            factors[month] = float(ghi @ pv / (ghi @ ghi)) if ghi @ ghi > 0 else 0.0
        degrees = np.concatenate([np.clip(HEATING_BASE_C - d.temp, 0, None) for d in days])
        heat = np.concatenate([d.heat for d in days])
        b, a = np.polyfit(degrees, heat, 1)
        return cls(factors, float(a), float(b))

    def pv(self, day: Day, ghi: np.ndarray) -> np.ndarray:
        return self.pv_factor[int(day.date[5:7])] * ghi

    def heat(self, temp: np.ndarray) -> np.ndarray:
        return np.clip(self.heat_a + self.heat_b * np.clip(HEATING_BASE_C - temp, 0, None), 0.0, None)


def ar1(rng: np.random.Generator, sd: float) -> np.ndarray:
    noise = np.zeros(SLOTS_PER_DAY)
    noise[0] = rng.normal(0, sd)
    for t in range(1, SLOTS_PER_DAY):
        noise[t] = ERROR_RHO * noise[t - 1] + rng.normal(0, sd * np.sqrt(1 - ERROR_RHO**2))
    return noise


def forecasts_for(days: list[Day], kind: str = "noise") -> dict[str, Forecasts]:
    """Seeded per date, so every strategy sees the same forecasts. ``kind``: "noise" or "weather"."""
    models = WeatherModels.fit([d for d in days if d.ghi is not None]) if kind == "weather" else None
    out = {}
    for i, day in enumerate(days):
        rng = np.random.default_rng([SEED, int(day.date.replace("-", ""))])
        history = [d.fixed for d in days[max(0, i - 7) : i]] or [day.fixed]
        second = ar1(rng, TEMP_ERROR_SD_K if models else HEAT_ERROR_SD)
        out[day.date] = Forecasts(day, ar1(rng, PV_ERROR_SD), second, np.mean(history, axis=0),
                                  models if day.ghi is not None else None)  # fmt: skip
    return out


# ── Planning (LP from slot tau) ──────────────────────────────────────────────
@dataclass(frozen=True)
class Settings:
    """What the agent may change; the defaults are what the MPC baselines use."""

    pv_derate: float = 1.0  # plan with this share of the PV forecast
    battery_reserve_pct: float | None = None  # battery charge to keep at midnight (default: Home.soc_start)
    comfort_min_c: float | None = None  # narrower comfort band than the house's (default: the house's)
    comfort_max_c: float | None = None
    grid_limit_kw: float | None = None  # cap on grid import


@dataclass
class Plan:
    made_at: int
    hp: np.ndarray
    ev: np.ndarray
    battery: np.ndarray  # + charge, - discharge
    soc: np.ndarray
    indoor: np.ndarray
    expected_cost_eur: float
    settings: Settings
    sessions: frozenset[int]  # EV sessions this plan covers
    grid: np.ndarray = field(default_factory=lambda: np.zeros(SLOTS_PER_DAY))  # planned import - export, kW


@dataclass
class State:
    soc: float
    indoor: float
    ev_left: dict[int, float]  # remaining kWh per session index


def solve(f: dict[str, np.ndarray], tau: int, state: State, known: list[int], day: Day, home: Home,
          s: Settings) -> Plan | None:  # fmt: skip
    """Cheapest plan for slots tau..95 on forecasts ``f`` from the measured state."""
    slots, bounds = range(tau, SLOTS_PER_DAY), range(tau, SLOTS_PER_DAY + 1)
    low = min(s.comfort_min_c if s.comfort_min_c is not None else home.comfort_min_c, state.indoor)
    high = max(s.comfort_max_c if s.comfort_max_c is not None else home.comfort_max_c, state.indoor)
    reserve = (s.battery_reserve_pct / 100 * home.battery_kwh if s.battery_reserve_pct is not None
               else home.soc_min * home.battery_kwh)  # fmt: skip
    price = float(f["import_price"].mean())  # value of energy left at midnight, as in ``score``
    m = pulp.LpProblem("plan", pulp.LpMinimize)
    hp = {t: pulp.LpVariable(f"h{t}", 0, home.hp_max_kw) for t in slots}
    ch = {t: pulp.LpVariable(f"c{t}", 0, home.battery_kw) for t in slots}
    dis = {t: pulp.LpVariable(f"d{t}", 0, home.battery_kw) for t in slots}
    imp = {t: pulp.LpVariable(f"i{t}", 0, s.grid_limit_kw) for t in slots}
    exp = {t: pulp.LpVariable(f"x{t}", 0) for t in slots}
    soc = {t: pulp.LpVariable(f"s{t}", home.soc_min * home.battery_kwh, home.battery_kwh) for t in bounds}
    temp = {t: pulp.LpVariable(f"T{t}", low, high) for t in bounds}
    evv = {(i, t): pulp.LpVariable(f"e{i}_{t}", 0, home.ev_max_kw)
           for i in known for t in range(max(tau, day.sessions[i][0]), day.sessions[i][1])}  # fmt: skip
    ev = {t: pulp.lpSum(v for (_, u), v in evv.items() if u == t) for t in slots}
    stored = (home.efficiency * soc[SLOTS_PER_DAY]
              + home.capacity_kwh_per_k * temp[SLOTS_PER_DAY] / float(f["cop"].mean()))  # fmt: skip
    m += pulp.lpSum((f["import_price"][t] * imp[t] - f["export_price"][t] * exp[t]) * SLOT_HOURS for t in slots) \
        - price * stored
    m += soc[tau] == state.soc
    m += soc[SLOTS_PER_DAY] >= min(reserve, home.battery_kwh)
    m += temp[tau] == state.indoor
    for i in known:
        m += pulp.lpSum(v for (j, _), v in evv.items() if j == i) * SLOT_HOURS == state.ev_left[i]
    for t in slots:
        m += f["fixed"][t] + hp[t] + ev[t] + ch[t] - dis[t] - s.pv_derate * f["pv"][t] == imp[t] - exp[t]
        m += ev[t] <= home.ev_max_kw
        m += soc[t + 1] == soc[t] + SLOT_HOURS * (home.efficiency * ch[t] - dis[t] / home.efficiency)
        m += home.capacity_kwh_per_k * (temp[t + 1] - temp[t]) == SLOT_HOURS * (
            f["cop"][t] * hp[t] - f["heat"][t] - home.loss_kw_per_k * (temp[t] - home.set_c))
    if m.solve(pulp.PULP_CBC_CMD(msg=False)) != pulp.LpStatusOptimal:
        return None

    def full(values: dict, n: int = SLOTS_PER_DAY) -> np.ndarray:
        out = np.zeros(n)
        for t, v in values.items():
            out[t] = pulp.value(v) or 0.0
        return out

    return Plan(tau, full(hp), full(ev), full(ch) - full(dis), full(soc, SLOTS_PER_DAY + 1),
                full(temp, SLOTS_PER_DAY + 1), float(pulp.value(m.objective) or 0.0), s, frozenset(known),
                full(imp) - full(exp))  # fmt: skip


def check(plan: Plan, state: State, home: Home) -> list[str]:
    """Independent check of a plan before it is committed (the harness's role)."""
    problems = []
    if plan.indoor[plan.made_at :].min() < home.comfort_min_c - 1e-6:
        problems.append(f"indoor temperature falls to {plan.indoor[plan.made_at:].min():.1f} C")
    if plan.soc[-1] < home.soc_min * home.battery_kwh - 1e-6:
        problems.append("battery below its minimum")
    for i in plan.sessions:
        if abs(plan.ev[plan.made_at :].sum() * SLOT_HOURS - sum(state.ev_left[j] for j in plan.sessions)) > 0.05:
            problems.append(f"EV session {i} does not receive its energy")
            break
    return problems


# ── Control layer ────────────────────────────────────────────────────────────
@dataclass
class Run:
    result: Result
    replans: int = 0
    agent_calls: int = 0
    tool_calls: int = 0
    errors: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0
    latency_s: float = 0.0
    decisions: list[str] = field(default_factory=list)


Planner = Callable[[int, State, list[int], Plan | None, str], Plan | None]


def execute(day: Day, home: Home, planner: Planner | None, triggers: set[int]) -> Run:
    """Run the day slot by slot; ``planner`` is called at the trigger slots and at each plug-in."""
    state = State(home.soc_start * home.battery_kwh, home.set_c, {i: e for i, (_, _, e) in enumerate(day.sessions)})
    hp, ev, bat = np.zeros(SLOTS_PER_DAY), np.zeros(SLOTS_PER_DAY), np.zeros(SLOTS_PER_DAY)
    soc, indoor = np.zeros(SLOTS_PER_DAY + 1), np.zeros(SLOTS_PER_DAY + 1)
    soc[0], indoor[0] = state.soc, state.indoor
    plan: Plan | None = None
    replans = 0
    starts = {first: i for i, (first, _, _) in enumerate(day.sessions)}
    for t in range(SLOTS_PER_DAY):
        known = [i for i, (first, end, _) in enumerate(day.sessions) if first <= t < end and state.ev_left[i] > 1e-6]
        if planner is not None and (t in triggers or t in starts):
            reason = f"car plugged in (session {starts[t]})" if t in starts else "scheduled check"
            new = planner(t, state, known, plan, reason)
            if new is not None and new is not plan:
                plan, replans = new, replans + 1
        # heat pump: follow the plan, but keep the house inside the comfort band
        target = plan.hp[t] if plan is not None else day.heat[t] / day.cop[t]
        loss = day.heat[t] + home.loss_kw_per_k * (state.indoor - home.set_c)

        def next_temp(power: float) -> float:
            return state.indoor + SLOT_HOURS * (day.cop[t] * power - loss) / home.capacity_kwh_per_k

        floor = (home.capacity_kwh_per_k * (home.comfort_min_c - state.indoor) / SLOT_HOURS + loss) / day.cop[t]
        ceiling = (home.capacity_kwh_per_k * (home.comfort_max_c - state.indoor) / SLOT_HOURS + loss) / day.cop[t]
        hp[t] = float(np.clip(np.clip(target, floor, ceiling), 0.0, home.hp_max_kw))
        state.indoor = next_temp(hp[t])
        # EV: the plan for sessions it covers, "min + PV" for the others; full power when the deadline needs it
        surplus = day.pv[t] - day.fixed[t] - hp[t]
        for i in known:
            first, end, _ = day.sessions[i]
            wanted = plan.ev[t] if plan is not None and i in plan.sessions else max(surplus, 0.0)
            must = max(0.0, state.ev_left[i] / SLOT_HOURS - home.ev_max_kw * (end - t - 1))
            power = min(home.ev_max_kw - ev[t], state.ev_left[i] / SLOT_HOURS, max(wanted, must))
            ev[t] += power
            state.ev_left[i] -= power * SLOT_HOURS
            surplus -= power
        # battery: the plan's setpoint (self-consumption without a plan), within its limits
        net = day.fixed[t] + hp[t] + ev[t] - day.pv[t]
        # Hold the planned grid exchange: the battery absorbs the forecast error (self-consumption without a plan).
        # Until 30 Oct 2026 the battery followed the planned power, so a PV shortfall was charged from the grid.
        wanted = plan.grid[t] - net if plan is not None else -net
        room = (home.battery_kwh - state.soc) / (home.efficiency * SLOT_HOURS)
        available = max((state.soc - home.soc_min * home.battery_kwh) * home.efficiency / SLOT_HOURS, 0.0)
        bat[t] = float(np.clip(wanted, -min(home.battery_kw, available), min(home.battery_kw, room)))
        state.soc += SLOT_HOURS * (bat[t] * home.efficiency if bat[t] > 0 else bat[t] / home.efficiency)
        soc[t + 1], indoor[t + 1] = state.soc, state.indoor
    grid = day.fixed + hp + ev + bat - day.pv
    result = Result(np.clip(grid, 0, None), np.clip(-grid, 0, None), hp, ev, bat, soc, indoor)
    return Run(result, replans)


# ── Strategies ───────────────────────────────────────────────────────────────
def lp_planner(fc: Forecasts, day: Day, home: Home, day_ahead: bool = False) -> Planner:
    def planner(t: int, state: State, known: list[int], current: Plan | None, _reason: str) -> Plan | None:
        return solve(fc.at(None if day_ahead else t), t, state, known, day, home, Settings()) or current

    return planner


def perfect_foresight(day: Day, home: Home) -> Run:
    """The same LP on the actual data, knowing every EV session from midnight (the upper bound)."""
    actual = {"pv": day.pv, "heat": day.heat, "fixed": day.fixed, "cop": day.cop,
              "import_price": day.import_price, "export_price": day.export_price}  # fmt: skip
    state = State(home.soc_start * home.battery_kwh, home.set_c, {i: e for i, (_, _, e) in enumerate(day.sessions)})
    plan = solve(actual, 0, state, list(range(len(day.sessions))), day, home, Settings())
    return execute(day, home, lambda *_: plan, {0})


SYSTEM_PROMPT = """You are the planning agent of a home energy gateway. The home has rooftop PV, a heat pump, an EV \
charger and a home battery; electricity is bought at a dynamic price and sold at the spot price.

At each check you get the situation. Decide whether the current plan should be kept or replaced, using the tools:
- get_forecast shows the hourly forecast for the rest of the day;
- optimize_plan computes the cheapest plan with the settings you choose. Use its settings to handle forecast
  uncertainty, e.g. pv_derate below 1 when PV has been falling short of the forecast, a higher battery reserve
  before an uncertain evening, or a grid limit to avoid a high peak;
- check_plan checks the last computed plan.
Then answer with GatewayDecision: action "commit" to put the last computed plan into effect (it must pass
check_plan), or "keep" to stay with the current plan. The control layer keeps the comfort band, the car's
deadline and the battery limits whatever you decide. Keep the reason to one short sentence."""


class GatewayDecision(BaseModel):
    action: Literal["commit", "keep"]
    reason: str = Field(description="One short sentence")


def agent_planner(fc: Forecasts, day: Day, home: Home, model: BaseChatModel, model_name: str, run_log: Run) -> Planner:
    def planner(t: int, state: State, known: list[int], current: Plan | None, reason: str) -> Plan | None:
        f = fc.at(t)
        so_far = slice(0, t)
        candidate: dict[str, Plan | None] = {"plan": None}

        @tool
        def get_forecast() -> str:
            """Hourly forecast for the rest of the day: PV, household load, heat demand, import price."""
            rows = ["hour | PV kW | load kW | heat kW | import c/kWh"]
            for h in range(t // 4, 24):
                part = slice(h * 4, h * 4 + 4)
                rows.append(f"{h:02d} | {f['pv'][part].mean():.2f} | {f['fixed'][part].mean():.2f} | "
                            f"{f['heat'][part].mean():.2f} | {f['import_price'][part].mean() * 100:.1f}")  # fmt: skip
            return "\n".join(rows)

        @tool
        def optimize_plan(pv_derate: float = 1.0, battery_reserve_pct: float | None = None,
                          comfort_min_c: float | None = None, comfort_max_c: float | None = None,
                          grid_limit_kw: float | None = None) -> str:  # fmt: skip
            """Cheapest plan from now to midnight with the given settings (all optional).

            pv_derate: share of the PV forecast to plan with (0.5-1.0). battery_reserve_pct: minimum battery charge
            at midnight (10-100; default none: energy left at midnight is already valued, so set a reserve only
            for a reason). comfort_min_c/comfort_max_c: narrower band within 20-22 C. grid_limit_kw: cap on grid
            import."""
            s = Settings(float(np.clip(pv_derate, 0.3, 1.2)), battery_reserve_pct, comfort_min_c, comfort_max_c,
                         grid_limit_kw)  # fmt: skip
            plan = solve(f, t, state, known, day, home, s)
            candidate["plan"] = plan
            if plan is None:
                return "No feasible plan with these settings."
            hours = [f"{h:02d}h bat {plan.soc[h * 4] / home.battery_kwh * 100:.0f}% T {plan.indoor[h * 4]:.1f}"
                     for h in range(t // 4, 24, 3)]  # fmt: skip
            ev_h = sorted({u // 4 for u in range(t, SLOTS_PER_DAY) if plan.ev[u] > 0.05})
            return (f"Plan: expected cost {plan.expected_cost_eur:.2f} EUR to midnight; heat pump "
                    f"{plan.hp[t:].sum() * SLOT_HOURS:.1f} kWh; EV charging in hours {ev_h or 'none'}; "
                    f"peak import {max(0.0, (f['fixed'] + plan.hp + plan.ev + plan.battery - s.pv_derate * f['pv'])[t:].max()):.1f} kW; "
                    + "; ".join(hours))  # fmt: skip

        @tool
        def check_plan() -> str:
            """Check the last computed plan before committing it."""
            plan = candidate["plan"]
            if plan is None:
                return "No plan computed yet (or the last one was infeasible)."
            problems = check(plan, state, home)
            return "OK" if not problems else "Problems: " + "; ".join(problems)

        pv_err = (day.pv[so_far].sum() - f["pv"][so_far].sum()) * SLOT_HOURS
        pv_fc_dayahead = fc.at(None)["pv"][so_far].sum() * SLOT_HOURS
        cars = "; ".join(f"session {i}: {state.ev_left[i]:.1f} kWh left, plugged until "
                         f"{day.sessions[i][1] // 4:02d}:{day.sessions[i][1] % 4 * 15:02d}" for i in known) or "no car"
        current_text = ("no plan yet (default control)" if current is None else
                        f"plan made at {current.made_at // 4:02d}:{current.made_at % 4 * 15:02d}, "
                        f"settings {current.settings}, covers EV sessions {sorted(current.sessions) or 'none'}")
        message = (f"Check at {t // 4:02d}:{t % 4 * 15:02d} ({reason}). Indoor {state.indoor:.1f} C, battery "
                   f"{state.soc / home.battery_kwh * 100:.0f}%. EV: {cars}. PV so far today "
                   f"{day.pv[so_far].sum() * SLOT_HOURS:.1f} kWh vs day-ahead forecast {pv_fc_dayahead:.1f} kWh "
                   f"({pv_err:+.1f}). Current: {current_text}.")  # fmt: skip
        started = time.perf_counter()
        with get_usage_metadata_callback() as usage:
            try:
                out = run_react(model, [get_forecast, optimize_plan, check_plan], SYSTEM_PROMPT, GatewayDecision,
                                message, "gateway", AGENT_STEP_LIMIT, None)  # fmt: skip
            except Exception as exc:  # e.g. Ollama's HTTP 500 for a malformed tool call: the check is missed
                if type(exc).__name__ != "ResponseError":
                    raise
                out = ReactResult(None, 0, [f"gateway: {str(exc)[:160]}"], 0)
        tin, tout, usd = usage_cost_usd(usage.usage_metadata, model_name)
        run_log.agent_calls += 1
        run_log.tool_calls += out.tool_calls
        run_log.errors += out.errors
        run_log.tokens_in, run_log.tokens_out, run_log.usd = run_log.tokens_in + tin, run_log.tokens_out + tout, run_log.usd + usd
        run_log.latency_s += time.perf_counter() - started
        decision = out.output
        if decision is None:
            run_log.decisions.append(f"{t}: no decision, keep")
            return current
        plan = candidate["plan"]
        if decision.action == "commit" and plan is not None and not check(plan, state, home):
            run_log.decisions.append(f"{t}: commit {plan.settings} - {decision.reason}")
            return plan
        run_log.decisions.append(f"{t}: {decision.action}{' (rejected)' if decision.action == 'commit' else ''} - "
                                 f"{decision.reason}")  # fmt: skip
        return current

    return planner


# ── Scoring ──────────────────────────────────────────────────────────────────
def score(day: Day, home: Home, r: Result) -> dict[str, float]:
    cost = float(((day.import_price * r.imports - day.export_price * r.exports) * SLOT_HOURS).sum())
    price = float(day.import_price.mean())
    stored = ((r.soc[-1] - home.soc_start * home.battery_kwh) * home.efficiency
              + home.capacity_kwh_per_k * (r.indoor[-1] - home.set_c) / float(day.cop.mean()))  # fmt: skip
    return {"cost_eur": cost, "end_state_eur": stored * price, "adjusted_cost_eur": cost - stored * price,
            "peak_import_kw": float(r.imports.max()), "min_indoor_c": float(r.indoor.min()),
            "ev_kwh": float(r.ev.sum() * SLOT_HOURS)}  # fmt: skip


def sample_days(days: list[Day], n: int) -> list[Day]:
    """One day per month nearest the 12th (days with an EV session preferred)."""
    by_month: dict[str, list[Day]] = {}
    for d in days:
        by_month.setdefault(d.date[:7], []).append(d)
    chosen = []
    for month in sorted(by_month)[:n]:
        candidates = sorted(by_month[month], key=lambda d: (not d.sessions, abs(int(d.date[8:]) - 12)))
        chosen.append(candidates[0])
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--year", type=int, default=2016)
    parser.add_argument("--days", type=int, default=12)
    parser.add_argument("--models", nargs="*", default=[], help="LLM agents to run (e.g. gpt-6-luna gpt-oss-20b)")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "out")
    parser.add_argument("--market", choices=["fi", "de"], default="fi")
    parser.add_argument("--export", choices=["spot", "feedin"], default=None, help="default: feedin for de, spot for fi")
    parser.add_argument("--forecast", choices=["noise", "weather"], default="noise")
    args = parser.parse_args()
    load_dotenv()  # API keys from the repository's .env, as the hems CLI does
    home = Home()
    export = args.export or ("feedin" if args.market == "de" else "spot")
    days = load_days(args.raw_dir, args.year, args.market, export)
    fcs = forecasts_for(days, args.forecast)
    tag = "" if (args.market, args.forecast) == ("fi", "noise") else f"_{args.market}_{export}_{args.forecast}"
    chosen = sample_days(days, args.days)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"gateway_{args.year}{tag}.jsonl"
    done = {(r["date"], r["strategy"]) for r in map(json.loads, path.read_text().splitlines())} if path.exists() else set()
    triggers_events, triggers_hourly = set(CHECKPOINTS), set(range(0, SLOTS_PER_DAY, 4))
    with path.open("a") as out:
        for day in chosen:
            fc = fcs[day.date]
            strategies: dict[str, Callable[[], Run]] = {
                "rules": lambda: Run(rules(day, home, home.soc_start * home.battery_kwh, home.set_c)),
                "day_ahead": lambda: execute(day, home, lp_planner(fc, day, home, day_ahead=True), {0}),
                "mpc_hourly": lambda: execute(day, home, lp_planner(fc, day, home), triggers_hourly),
                "mpc_events": lambda: execute(day, home, lp_planner(fc, day, home), triggers_events),
                "optimum": lambda: perfect_foresight(day, home),
            }
            for name in args.models:
                def run_agent(name: str = name) -> Run:
                    log = Run(Result(*([np.zeros(1)] * 7)))
                    planner = agent_planner(fc, day, home, make_model(name), name, log)
                    run = execute(day, home, planner, triggers_events)
                    run.agent_calls, run.tool_calls, run.errors = log.agent_calls, log.tool_calls, log.errors
                    run.tokens_in, run.tokens_out, run.usd, run.latency_s = log.tokens_in, log.tokens_out, log.usd, log.latency_s
                    run.decisions = log.decisions
                    return run

                strategies[f"agent:{name}"] = run_agent
            for strategy, run_fn in strategies.items():
                if (day.date, strategy) in done:
                    continue
                run = run_fn()
                record = {"date": day.date, "strategy": strategy, **score(day, home, run.result), "replans": run.replans,
                          "agent_calls": run.agent_calls, "tool_calls": run.tool_calls, "errors": run.errors,
                          "tokens_in": run.tokens_in, "tokens_out": run.tokens_out, "usd": run.usd,
                          "agent_latency_s": run.latency_s, "decisions": run.decisions}  # fmt: skip
                out.write(json.dumps(record) + "\n")
                out.flush()
                print(f"{day.date} {strategy:22s} adjusted {record['adjusted_cost_eur']:6.2f} EUR, peak "
                      f"{record['peak_import_kw']:4.1f} kW, min {record['min_indoor_c']:.1f} C"
                      + (f", {run.agent_calls} checks, {run.tool_calls} tools, ${run.usd:.4f}" if run.agent_calls else ""))  # fmt: skip
    summarize(path)


def summarize(path: Path) -> None:
    frame = pd.DataFrame(map(json.loads, path.read_text().splitlines()))
    complete = frame.groupby("date").strategy.nunique()
    frame = frame[frame.date.isin(complete[complete == complete.max()].index)]
    table = frame.groupby("strategy").agg(
        days=("date", "nunique"), adjusted_cost_eur=("adjusted_cost_eur", "sum"), peak_kw=("peak_import_kw", "max"),
        min_indoor_c=("min_indoor_c", "min"), replans=("replans", "mean"), agent_calls=("agent_calls", "sum"),
        usd=("usd", "sum"), agent_latency_s=("agent_latency_s", "mean"),
    )  # fmt: skip
    rules_cost, best = table.adjusted_cost_eur["rules"], table.adjusted_cost_eur["optimum"]
    table["gap_closed_pct"] = 100 * (rules_cost - table.adjusted_cost_eur) / (rules_cost - best) if rules_cost != best else 0
    print(table.round(3).to_string())


if __name__ == "__main__":
    main()
