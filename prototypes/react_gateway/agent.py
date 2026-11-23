"""ReAct home energy gateway (exploratory, 13 Nov 2026; not part of the thesis evaluation yet).

A ReAct agent reads the household's message and, through tools, the data the gateway has at that moment:

- ``get_home_state``: time, battery charge, car charge and charger, indoor temperature and comfort settings;
- ``get_prices``: day-ahead import price per hour from now to the end of tomorrow, and the feed-in price;
- ``get_weather_forecast``: PV output and heat demand forecast per hour (DWD weather-driven forecasts);
- ``get_appliances``: the house's measured dishwasher and washing machine cycles (energy, length, power profile);
- ``plan_schedule``: the household's requirements as constraints. The deterministic checker tests them first
  (a car charge that cannot be reached, a window shorter than the cycle, a missing target); if they pass, the MPC
  (``closed_loop.mpc``) plans every device on the forecasts and the tool returns the schedule, its expected cost
  and a requirements check. A call without any requirement is refused (a household message always asks for
  something), so the gateway can never commit an empty plan (rule added 13 Nov 2026 after the dev run, where
  Ministral 3 8B committed empty plans for vague or infeasible messages).

The agent answers with ``AppAnswer`` (commit or ask, questions, a short explanation). The schedule is never written
by the model: the household app shows the last ``plan_schedule`` result, so a committed plan is always the
optimiser's. Design reasons: the planning pilot (thesis 5.1) found a model planning on its own worse than the MPC,
and the plan pilot found models miscalculating feasibility, which the checker does exactly.

Per plan the run records the decision and item scores (``plan_pilot.score`` on the requirements of the last
``plan_schedule`` call), the time, tool calls and tokens, and the app output (``out/app/<model>/<plan>.json``);
with ``--loop`` a committed plan is also executed in the closed loop on the real day (``closed_loop.run``) and judged
against the answer key.

    uv run python prototypes/react_gateway/agent.py --raw-dir D:/Study/my-thesis/data/raw --models gemma4-e4b \
        --plans prototypes/plan_pilot/plans_dev.json --loop
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import numpy as np
from dotenv import load_dotenv
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.tools import tool
from pydantic import BaseModel, Field

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT / "closed_loop"), str(ROOT / "plan_pilot"), str(ROOT / "home_gateway")]
from closed_loop import APPLIANCE, Constraints, Status, World, constraints, judge, mpc, run  # noqa: E402
from gateway import forecasts_for  # noqa: E402
from pilot import Appliance, Comfort, Ev, Period, Question, now, parse, plan_num_ctx, score, summarize  # noqa: E402
from rescore_checker import check  # noqa: E402
from twin import Home, load_days  # noqa: E402

from hems.agents.harness import ReactResult, run_react  # noqa: E402
from hems.agents.llm import make_model, usage_cost_usd  # noqa: E402
from hems.core.models import SLOT_HOURS, SLOTS_PER_DAY  # noqa: E402

STEP_LIMIT = 24  # graph steps: about ten tool calls and the answer
# Dropped (author's decisions, 13 Nov 2026): Phi-4-mini and SmolLM3 3B. Neither made tool calls with its stock
# Ollama template; with custom tool templates (phi4-mini-tools.Modelfile, smollm3-tools.Modelfile) both called tools
# but never planned a schedule on the dev plans (SmolLM3: 10 of 14 answers failed, 78 s per plan, loops of up to
# 101 calls).
MODELS = ("gemma4-e4b", "gemma4-e2b", "ministral-3-8b", "ministral-3-3b", "nemotron3-nano-4b", "gpt-6-luna")
FMT = "%Y-%m-%d %H:%M"


# ── Schemas ──────────────────────────────────────────────────────────────────
class CarCharge(BaseModel):
    departure: str | None = Field(None, description="When the charge must be done, 'YYYY-MM-DD HH:MM'; only "
                                  "'YYYY-MM-DD' if the household named a day but no time; leave out if they gave "
                                  "neither (the usual ready-by time is used)")
    target_pct: float | None = Field(None, description="Charge to reach, %; 'full' is 100; leave out if the "
                                     "household gave none (the usual target is used)")
    energy_kwh: float | None = Field(None, description="Energy to add, kWh, if the household gave an amount")
    earliest: str | None = Field(None, description="Do not charge before this time, 'YYYY-MM-DD HH:MM', if stated")


class ApplianceRun(BaseModel):
    appliance: Literal["dishwasher", "washing_machine"]
    earliest: str | None = Field(None, description="May start from, 'YYYY-MM-DD HH:MM', if stated")
    deadline: str | None = Field(None, description="Must be finished by, 'YYYY-MM-DD HH:MM'; leave out if the "
                                 "household gave no deadline (it then runs at the cheapest time in the known prices)")


class Requirements(BaseModel):
    """The household's requirements, as the gateway's constraints."""

    # One optional list instead of a label per item (dev run, 13 Nov 2026: per-item labels made Gemma 4 E2B fail 5 of
    # 14 answers). The model copies the vague words; the code turns them into a question.
    unclear: list[str] = Field(default_factory=list, description="The household's own words for any time, amount "
                               "or temperature too vague to plan, e.g. ['leaving early'], ['by lunchtime'], ['the "
                               "weekend'], ['cosy']. Leave empty when everything is clear.")
    ev: list[CarCharge] = Field(default_factory=list, description="Car charging the household asked for")
    appliances: list[ApplianceRun] = Field(default_factory=list, description="Appliance runs the household asked for")
    away: list[Period] = Field(default_factory=list, description="Periods when everyone is away")
    comfort: list[Comfort] = Field(default_factory=list, description="Indoor temperature bands that differ from the default")


class AppAnswer(BaseModel):
    """The gateway's answer shown in the household app."""

    commit: bool = Field(description="true: apply the last schedule from plan_schedule; false: ask the household first")
    questions: list[Question] = Field(default_factory=list, description="Questions to the household (when commit is false)")
    explanation: str = Field(description="Two to four plain sentences for the household: what the gateway will do and why")


# ── The gateway at the time of the last message ──────────────────────────────
@dataclass
class Gateway:
    plan: dict
    household: dict
    world: World
    home: Home
    appliances: dict
    schedules: list[dict] = field(default_factory=list)  # every plan_schedule result, the last one is shown
    # False = the set-up without the checks and the rules in code (registered evaluation, 22 Nov 2026): plan_schedule
    # plans what it is given (the usual car settings are still filled in, because the optimiser needs a target and a
    # time), and the gateway applies whatever the model commits. True (default) = the design, unchanged.
    checks: bool = True

    def hour(self, k: int) -> str:
        return (self.world.t0 + timedelta(minutes=15 * int(k))).strftime(FMT)

    def hourly(self, values: np.ndarray) -> np.ndarray:
        """Hourly means from the next full hour, with the hour index of their first slot."""
        first = (-self.world.start) % 4
        n = (len(values) - first) // 4
        return values[first : first + 4 * n].reshape(n, 4).mean(axis=1), first

    def tools(self) -> list:
        gw, w, home = self, self.world, self.home
        f0 = w.forecast(0)
        pct = float(gw.plan.get("state", {}).get("ev_pct", 30.0))

        @tool
        def get_home_state() -> str:
            """Current time, home battery, car, charger, indoor temperature and comfort settings."""
            h = gw.household
            return (f"Now: {gw.hour(0)}. Planning horizon: until {gw.hour(w.horizon)}.\n"
                    f"Home battery: {home.battery_kwh:.0f} kWh, {home.soc_start * 100:.0f} % charged, up to "
                    f"{home.battery_kw:.0f} kW, kept above {home.soc_min * 100:.0f} %.\n"
                    f"Car: plugged in, {pct:.0f} % of {h['car_battery_kwh']} kWh; charger {h['charger_kw']} kW.\n"
                    f"Usual car settings (set in the app): {h['usual']['car_target_pct']} %, ready by "
                    f"{h['usual']['car_ready_by']} {h['usual']['car_ready_days']}; {h['usual']['note']}.\n"
                    f"Heat pump up to {home.hp_max_kw} kW. Indoor now {home.set_c:.0f} C; default comfort band "
                    f"{h['default_comfort_c'][0]}-{h['default_comfort_c'][1]} C; when everyone is away the gateway "
                    f"lets it fall to {h['away_setback_c']} C.")  # fmt: skip

        @tool
        def get_prices() -> str:
            """Day-ahead electricity import price per hour from now to the end of the horizon, and the feed-in price."""
            imp, first = gw.hourly(f0["import_price"])
            lines = [f"{gw.hour(first + 4 * i)[5:]}  {p:.3f}" for i, p in enumerate(imp)]
            cheap = ", ".join(gw.hour(first + 4 * i)[11:] for i in np.argsort(imp)[:4])
            return (f"Import price, EUR/kWh, per hour (MM-DD HH:MM  price):\n" + "\n".join(lines)
                    + f"\nCheapest hours: {cheap}. Feed-in price: {float(f0['export_price'].mean()):.3f} EUR/kWh.")  # fmt: skip

        @tool
        def get_weather_forecast() -> str:
            """Forecast PV output and the heat pump's heat demand per hour, from the weather forecast."""
            pv, first = gw.hourly(f0["pv"])
            heat, _ = gw.hourly(f0["heat"])
            sunny = [f"{gw.hour(first + 4 * i)[5:]} {v:.1f}" for i, v in enumerate(pv) if v >= 0.05]
            return (f"PV forecast, kW (only hours with output):\n" + ("\n".join(sunny) or "no PV output")
                    + f"\nHeat demand, kW heat, mean {heat.mean():.1f}, highest {heat.max():.1f} at "
                    f"{gw.hour(first + 4 * int(np.argmax(heat)))[11:]}.\nTotal PV forecast "
                    f"{float(f0['pv'].sum() * SLOT_HOURS):.1f} kWh; household base load about "
                    f"{float(f0['fixed'].mean()):.1f} kW.")  # fmt: skip

        @tool
        def get_appliances() -> str:
            """The house's measured appliance cycles: energy, length and power profile per 15 minutes."""
            return "\n".join(f"{name}: one cycle uses about {a['energy_kwh_median']} kWh and runs "
                             f"{a['duration_h_median']:g} h; power per 15 min {a['typical_profile_kw']} kW; not "
                             f"interruptible." for name, a in gw.appliances.items() if isinstance(a, dict))  # fmt: skip

        @tool(args_schema=Requirements)
        def plan_schedule(ev: list | None = None, appliances: list | None = None, away: list | None = None,
                          comfort: list | None = None, unclear: list | None = None) -> str:  # fmt: skip
            """Check the household's requirements and plan every device on the forecasts (MPC). Returns the schedule,
            its expected cost and whether each requirement is met, or the problems that need a question."""
            req = Requirements(ev=ev or [], appliances=appliances or [], away=away or [], comfort=comfort or [])
            got = req.model_dump()
            if not gw.checks:
                return gw.plan_unchecked(got)
            # Vague words are asked about, never filled with the usual settings (test run: "leaving really early"
            # became the usual 07:30). Developed on the dev plans only (DA3 "leaving early tomorrow").
            vague = [("other", f"the household's '{w}' is too vague to plan: ask what they mean")
                     for w in (unclear or []) if str(w).strip()]  # fmt: skip
            notes = gw.fill_usual(got)
            notes += gw.next_occurrence(got)
            notes.insert(0, gw.read_back(got))
            if not any(got.values()) and not vague:  # a message always asks for something: an empty plan was not understood
                gw.schedules.append({"requirements": got, "problems": ["no requirement given"]})
                return ("Not planned: no requirement was given. If the household's message is unclear, ask what "
                        "they need; otherwise call plan_schedule with their requirements.")  # fmt: skip
            # A car charge the charger cannot complete in time is not a question: the gateway charges as much as it
            # can and warns the household (author's decision, 13 Nov 2026); the other problems need a question.
            problems = list(vague)
            # A charge that may only start after the car has to be ready is a conflict, not a slow charger (X3 in
            # the test run: "car at work 8 to 5, charge it from the solar at midday").
            problems += [("conflict", f"the car must be ready at {e['departure']} but may only charge from "
                                      f"{e['earliest']}") for e in got.get("ev", [])
                         if e.get("earliest") and e.get("departure") and parse(e["earliest"]) >= parse(e["departure"])]  # fmt: skip
            problems += [(t, why) for t, why in check(gw.plan, got, gw.household) if not why.startswith("EV needs")]
            # a comfort band without a temperature changes nothing (DS3 in the dev run: the model dropped "21-22")
            problems += [("comfort", f"comfort band {c['start']} to {c['end']} has no temperature: give the one the "
                                     f"household asked for, or ask them") for c in got.get("comfort", [])
                         if c.get("min_c") is None and c.get("max_c") is None]  # fmt: skip
            if problems:
                gw.schedules.append({"requirements": got, "problems": [why for _, why in problems]})
                return "\n".join([*notes, "Not planned. Problems the household must resolve (ask about them, do not "
                                  "commit):", *(f"- [{t}] {why}" for t, why in problems)])  # fmt: skip
            # Charges due after the last hour with known day-ahead prices are planned later, when the prices are out.
            end = gw.world.t0 + timedelta(minutes=15 * gw.world.horizon)
            later = [e for e in got["ev"] if parse(e["departure"]) > end]
            for e in later:
                notes.append(f"Car: {e.get('target_pct') or e.get('energy_kwh')} {'%' if e.get('target_pct') else 'kWh'} "
                             f"by {e['departure']} is after the last known day-ahead price ({end:%a %H:%M}); the "
                             f"gateway plans this charge when the prices for that night are published.")  # fmt: skip
            result = gw.schedule({**got, "ev": [e for e in got["ev"] if e not in later]})
            result["requirements"] = got
            result["checks"] += [{"requirement": f"car by {e['departure']}", "met": True, "later": True} for e in later]
            result["text"] = "\n".join([*notes, result["text"]]) + "".join(
                f"; car by {e['departure']}: planned when the prices are published" for e in later
            ).replace("Requirements: ; ", "Requirements: ")
            result["notes"] = notes
            gw.schedules.append(result)
            return result["text"]

        return [get_home_state, get_prices, get_weather_forecast, get_appliances, plan_schedule]

    def plan_unchecked(self, got: dict) -> str:
        """plan_schedule without the checks and the rules in code: no question for vague words, no time rule, no
        feasibility or conflict check, no refusal of an empty plan. Only the usual car settings are filled in, and
        charges after the known prices are left for later, as in the design, so that the optimiser can plan at all."""
        notes = self.fill_usual(got)
        notes.insert(0, self.read_back(got))
        end = self.world.t0 + timedelta(minutes=15 * self.world.horizon)
        later = [e for e in got["ev"] if parse(e["departure"]) and parse(e["departure"]) > end]
        try:
            result = self.schedule({**got, "ev": [e for e in got["ev"] if e not in later]})
        except Exception as exc:  # unchecked input the optimiser cannot plan (e.g. a deadline before its start)
            self.schedules.append({"requirements": got, "problems": [f"optimiser failed: {str(exc)[:120]}"]})
            return "\n".join([*notes, f"Not planned: the optimiser could not plan these requirements ({str(exc)[:120]})."])
        result["requirements"] = got
        result["checks"] += [{"requirement": f"car by {e['departure']}", "met": True, "later": True} for e in later]
        result["text"] = "\n".join([*notes, result["text"]])
        result["notes"] = notes
        self.schedules.append(result)
        return result["text"]

    def when(self, value: str | None) -> str:
        """A time as the household would say it: weekday, clock time, part of the day and hours from now."""
        t = parse(value)
        if t is None:
            return "(no time)"
        part = ("night" if t.hour < 5 else "morning" if t.hour < 12 else "afternoon" if t.hour < 17
                else "evening" if t.hour < 22 else "night")  # fmt: skip
        hours = (t - self.world.t0).total_seconds() / 3600
        return f"{t:%a %H:%M} ({part}, {'in' if hours >= 0 else 'PAST,'} {abs(hours):.1f} h)"

    def read_back(self, got: dict) -> str:
        """The requirements in words, so the agent can check its reading of the message (time-format rule)."""
        lines = [f"Read back (message sent {self.world.t0:%a %H:%M}):"]
        for e in got.get("ev", []):
            what = f"{e['target_pct']:g} %" if e.get("target_pct") is not None else (
                f"+{e['energy_kwh']:g} kWh" if e.get("energy_kwh") is not None else "usual target")
            lines.append(f"- car {what} by {self.when(e.get('departure')) if e.get('departure') else 'usual time'}"
                         + (f", not before {self.when(e['earliest'])}" if e.get("earliest") else ""))  # fmt: skip
        for a in got.get("appliances", []):
            lines.append(f"- {a['appliance']} done by {self.when(a.get('deadline'))}"
                         + (f", not before {self.when(a['earliest'])}" if a.get("earliest") else ""))  # fmt: skip
        for a in got.get("away", []):
            lines.append(f"- away from {self.when(a.get('start'))} to {self.when(a.get('end'))}")
        for c in got.get("comfort", []):
            lines.append(f"- {c.get('min_c')}-{c.get('max_c')} C from {self.when(c.get('start'))} to "
                         f"{self.when(c.get('end'))}")  # fmt: skip
        return "\n".join(lines)

    def next_occurrence(self, got: dict) -> list[str]:
        """The time-format rule applied by code: a clock time the household wrote without am/pm ("by 9", "from 6 to
        8", "8:30") means its next occurrence after the message (an end time: after its start). If the model wrote
        such a time 12 h too late, it is moved back and a note says so. Times written with am/pm, on the 24-hour
        clock or filled from the usual settings are left alone."""
        text = " ".join([self.plan["text"], self.plan.get("change", {}).get("text", "")]).lower()
        not_time = r"(?!\d|\s*(?:am|pm|a\.m|p\.m|%|kwh|kw|c\b|°|degrees))"

        def bare(t: datetime) -> bool:
            h12 = t.hour % 12 or 12
            # a full stop after the number ends the sentence ("done by 9."), it is not a decimal point
            word = rf"(?<![\d:.]){h12}:{t.minute:02d}{not_time}" if t.minute else rf"(?<![\d:.]){h12}(?![:.]\d){not_time}"
            return re.search(word, text) is not None

        notes = []

        def fix(item: dict, field: str, after: datetime) -> datetime | None:
            t = parse(item.get(field))
            if t is None:
                return None
            if t - timedelta(hours=12) > after and bare(t):
                earlier = t - timedelta(hours=12)
                notes.append(f"Time rule: '{t:%H:%M}' read as {earlier:%a %H:%M}, the next occurrence of that clock "
                             f"time (the household wrote it without am/pm).")  # fmt: skip
                item[field] = earlier.strftime(FMT)
                return earlier
            return t

        t0 = self.world.t0
        for e in got.get("ev", []):
            fix(e, "departure", max(t0, fix(e, "earliest", t0) or t0))
        for a in got.get("appliances", []):
            fix(a, "deadline", max(t0, fix(a, "earliest", t0) or t0))
        for key in ("away", "comfort"):
            for period in got.get(key, []):
                start = fix(period, "start", t0)
                fix(period, "end", max(t0, start or t0))
        return notes

    def fill_usual(self, got: dict) -> list[str]:
        """Car items without a target or a time get the household's usual settings, applied by code; returns notes
        for the agent. No time: the next usual ready-by time; a day without a time ('YYYY-MM-DD'): the usual
        ready-by time on that day."""
        usual, notes = self.household["usual"], []
        h, m = map(int, usual["car_ready_by"].split(":"))
        for item in got.get("ev", []):
            if item.get("target_pct") is None and item.get("energy_kwh") is None:
                item["target_pct"] = float(usual["car_target_pct"])
                notes.append(f"Car target not given: used the usual {usual['car_target_pct']} %.")
            departure = (item.get("departure") or "").strip()
            if len(departure) == 10:  # a day without a time
                item["departure"] = f"{departure} {usual['car_ready_by']}"
                notes.append(f"Car time not given: used the usual ready-by time {usual['car_ready_by']} on {departure}.")
            elif not departure:
                ready = self.world.t0.replace(hour=h, minute=m)
                if ready <= self.world.t0:
                    ready += timedelta(days=1)
                item["departure"] = ready.strftime(FMT)
                notes.append(f"Car time not given: used the usual ready-by time {ready:%a %H:%M}.")
        # An appliance without a deadline runs at the cheapest time within the known day-ahead prices (author's
        # decision, 14 Nov 2026, DA2 "run the washing sometime when it's cheap").
        end = self.world.t0 + timedelta(minutes=15 * self.world.horizon)
        for item in got.get("appliances", []):
            if not (item.get("deadline") or "").strip():
                item["deadline"] = end.strftime(FMT)
                notes.append(f"{item['appliance'].replace('_', ' ').capitalize()} deadline not given: runs at the "
                             f"cheapest time before {end:%a %H:%M}, the end of the known prices.")  # fmt: skip
        return notes

    def schedule(self, got: dict) -> dict:
        """One MPC plan on the forecasts made now, with the app's timeline and a requirements check."""
        w, home = self.world, self.home
        c = constraints(self.plan, got, w.t0, w.horizon, home, self.household["car_battery_kwh"])
        st = Status(home.soc_start * home.battery_kwh, home.set_c, [e for *_, e in c.ev], {})
        f = w.forecast(0)
        p = mpc(f, 0, st, c, w, home)
        app = np.zeros(w.horizon)
        for n, (name, _, _) in enumerate(c.appliances):
            s = p["starts"].get(n)
            if s is not None:
                prof = APPLIANCE[name][: w.horizon - s]
                app[s : s + len(prof)] += prof
        ev = p["ev"].sum(axis=0) if len(c.ev) else np.zeros(w.horizon)
        price, export = f["import_price"], f["export_price"]
        # PV left after the base load and the planned heat pump: energy a device takes from it costs the lost
        # feed-in, not the import price
        surplus = np.clip(f["pv"] - f["fixed"] - p["hp"], 0.0, None)
        lines, checks, devices = [], [], []
        for i, (a, b, need) in enumerate(c.ev):
            got_kwh = float(p["ev"][i, :b].sum() * SLOT_HOURS)
            on = np.flatnonzero(p["ev"][i] > 0.05)
            when = f"{self.hour(on[0])[5:]} to {self.hour(on[-1] + 1)[5:]}" if len(on) else "not charged"
            lines.append(f"Car: {got_kwh:.1f} kWh charged {when}, done before {self.hour(b)[5:]}. "
                         f"Why: {self.reason(p['ev'][i], a, b, price, surplus)}")  # fmt: skip
            met = got_kwh >= need - 0.1
            possible = home.ev_max_kw * (b - a) * SLOT_HOURS
            warning = not met and possible < need - 0.1  # the charger cannot do it: charge what it can, warn
            if warning:
                pct = float(self.plan.get("state", {}).get("ev_pct", 30.0))
                reach = pct + got_kwh / self.household["car_battery_kwh"] * 100
                lines.append(f"WARNING for the household: the car cannot get the full {need:.1f} kWh by "
                             f"{self.hour(b)[5:]}; the charger adds at most {possible:.1f} kWh in that time, so the car "
                             f"will be at about {reach:.0f} %. It charges at full power until then.")  # fmt: skip
            checks.append({"requirement": f"car +{need:.1f} kWh by {self.hour(b)}", "met": met, "warning": warning})
            pct0 = float(self.plan.get("state", {}).get("ev_pct", 30.0))
            devices.append({"device": "car", "start": self.hour(on[0]) if len(on) else None,
                            "end": self.hour(on[-1] + 1) if len(on) else None, "ready_by": self.hour(b),
                            "energy_kwh": round(got_kwh, 2),
                            "charge_pct": [round(pct0), round(pct0 + got_kwh / self.household["car_battery_kwh"] * 100)],
                            "why": self.reason(p["ev"][i], a, b, price, surplus),
                            "warning": lines[-1].removeprefix("WARNING for the household: ") if warning else None})  # fmt: skip
        for n, (name, a, b) in enumerate(c.appliances):
            s = p["starts"].get(n)
            ok = s is not None and a <= s and s + len(APPLIANCE[name]) <= b
            load = np.zeros(w.horizon)
            if s is not None:
                prof = APPLIANCE[name][: w.horizon - s]
                load[s : s + len(prof)] = prof
            lines.append(f"{name.replace('_', ' ').capitalize()}: "
                         + (f"starts {self.hour(s)[5:]}, done {self.hour(s + len(APPLIANCE[name]))[5:]}. "
                            f"Why: {self.reason(load, a, b, price, surplus, len(APPLIANCE[name]))}" if s is not None
                            else "no slot found in its window."))  # fmt: skip
            checks.append({"requirement": f"{name} done by {self.hour(b)}", "met": bool(ok)})
            devices.append({"device": name, "start": self.hour(s) if s is not None else None,
                            "end": self.hour(s + len(APPLIANCE[name])) if s is not None else None,
                            "deadline": self.hour(b), "energy_kwh": round(float(load.sum() * SLOT_HOURS), 2),
                            "why": self.reason(load, a, b, price, surplus, len(APPLIANCE[name])) if s is not None
                            else "no slot found in its window"})  # fmt: skip
        # Too warm counts only while the heat pump heats: a lower band can only stop the heating, the house cools at
        # its own pace (S5 in the test run: 21 C at 22:30 cannot fall below 20 C by midnight).
        heating = p["hp"] > 0.05
        short_k = float((np.clip(c.low - p["indoor"], 0, None)
                         + np.clip(p["indoor"] - c.high, 0, None) * heating).sum() * SLOT_HOURS)  # fmt: skip
        if got.get("comfort") or got.get("away"):
            checks.append({"requirement": "indoor temperature in the requested bands", "met": short_k < 0.5})
        charge = np.flatnonzero(p["battery"] > 0.1)
        lines.append(f"Home battery: charges in {len(charge) / 4:.1f} h (mostly {self.hour(charge[0])[11:]}), "
                     f"discharges in {(p['battery'] < -0.1).sum() / 4:.1f} h." if len(charge) else
                     f"Home battery: no charging planned, discharges in {(p['battery'] < -0.1).sum() / 4:.1f} h.")  # fmt: skip
        lines.append(f"Heat pump: {float(p['hp'].sum() * SLOT_HOURS):.1f} kWh electricity over the horizon.")
        devices.append({"device": "home_battery", "charge_hours": len(charge) / 4,
                        "discharge_hours": float((p["battery"] < -0.1).sum() / 4),
                        "mostly_charges_at": self.hour(charge[0]) if len(charge) else None})  # fmt: skip
        devices.append({"device": "heat_pump", "energy_kwh": round(float(p["hp"].sum() * SLOT_HOURS), 2),
                        "indoor_c": [round(float(p["indoor"].min()), 1), round(float(p["indoor"].max()), 1)]})  # fmt: skip
        flex = ev + app

        def cost(load: np.ndarray) -> float:  # solar part at the feed-in price, the rest at the import price
            solar = np.minimum(load, surplus)
            return float(((load - solar) * price + solar * export).sum() * SLOT_HOURS)

        planned = cost(flex)
        # the same energy taken at once from now (car at full power, appliances started now), for the saving
        asap, left = np.zeros(w.horizon), float(ev.sum() * SLOT_HOURS)
        for t in range(w.horizon):
            take = min(home.ev_max_kw, left / SLOT_HOURS)
            asap[t] += take
            left -= take * SLOT_HOURS
        for name, _, _ in c.appliances:
            asap[: len(APPLIANCE[name])] += APPLIANCE[name][: w.horizon]
        at_once = cost(asap)
        lines.append(f"Car and appliances cost {planned:.2f} EUR at the planned times, {at_once:.2f} EUR if started "
                     f"now (saving {at_once - planned:.2f} EUR; solar energy valued at the feed-in price "
                     f"{float(export.mean()):.3f} EUR/kWh).")  # fmt: skip
        lines.append("Requirements: " + "; ".join(f"{x['requirement']}: {'met' if x['met'] else 'only partly, see WARNING' if x.get('warning') else 'NOT met'}" for x in checks))
        series = {"price_eur_kwh": price, "pv_forecast_kw": f["pv"], "car_kw": ev, "appliances_kw": app,
                  "battery_kw": p["battery"], "heat_pump_kw": p["hp"], "indoor_c": p["indoor"]}
        timeline = [{"hour": self.hour(k)[5:], **{name: round(float(v[k : k + 4].mean()), 3) for name, v in series.items()}}
                    for k in range(0, w.horizon, 4)]  # hourly means from the time of the message
        cost_eur = {"planned": round(planned, 2), "if_started_now": round(at_once, 2),
                    "saving": round(at_once - planned, 2), "solar_valued_at_eur_kwh": round(float(export.mean()), 3)}
        return {"requirements": got, "text": "\n".join(lines), "checks": checks, "devices": devices,
                "cost_eur": cost_eur, "timeline": timeline, "saving_eur": round(at_once - planned, 3)}

    def reason(self, load: np.ndarray, a: int, b: int, price: np.ndarray, surplus: np.ndarray,
               length: int = 1) -> str:  # fmt: skip
        """Why a device runs when it does, from the forecasts: its solar share, and the grid price it pays
        against the cheapest and dearest run it could have had in its window."""
        on = load > 0
        energy = float(load.sum() * SLOT_HOURS)
        if energy <= 0:
            return "nothing to run."
        solar = float(np.minimum(load, surplus).sum() * SLOT_HOURS)
        paid = float((load * price)[on].sum() / load[on].sum())
        # mean price of each possible run of the same length in the window [a, b)
        runs = [price[s : s + length].mean() for s in range(a, max(a + 1, b - length + 1))]
        cheapest = int(np.argmin(runs)) + a
        parts = []
        if solar >= 0.05:
            parts.append(f"{solar / energy:.0%} of its {energy:.2f} kWh from solar (PV forecast up to "
                         f"{float(surplus[on].max()):.1f} kW spare then)")  # fmt: skip
        parts.append(f"grid price then {paid:.3f} EUR/kWh; in its window the grid price ranges "
                     f"{min(runs):.3f}-{max(runs):.3f}, lowest from {self.hour(cheapest)[11:]}")  # fmt: skip
        return "; ".join(parts) + "."


SYSTEM = """You are the home energy gateway of a household. You read the household's message, look at the home's
data with your tools, plan the devices with the plan_schedule tool and answer for the household app.

Work in steps: think about what the household asks, call the tools you need (you may call several at once), read
their results, and act on them.

Requirements:
- Write every time as 'YYYY-MM-DD HH:MM' on the 24-hour clock, resolving "today", "tonight" and "tomorrow" from
  the time each message was sent; "midnight" at the end of a day is 00:00 of the next day, "noon" 12:00, "half
  five" 05:30 or 17:30. If a later message changes the plan, plan from that moment on with every requirement
  still in force.
- People write clock times without am/pm ("by 9", "from 6 to 8", "back at 5"). Such a time means its NEXT
  occurrence after the message was sent; an end time means its next occurrence after the start. Examples for a
  message sent at 20:30: "by 10" is 22:00 today; "from 5 to 7" is 05:00 to 07:00 tomorrow. Sent at 14:00: "home at
  4, warm until 11" is 16:00 to 23:00 today.
- plan_schedule reads your requirements back with the weekday, the part of the day and the hours from now. Check
  the read-back against the message; if a time is wrong, call plan_schedule again with the right one.
- Record only what the household asked for: a car item only when they ask for charge, an appliance only when they
  ask for it (a deadline), an away period (start and end), a comfort band (times and a temperature) only where it
  differs from the default.
- The household has usual car settings (get_home_state). When a message asks for charge without a target or a
  time ("charge the car", "the usual for tomorrow"), leave the missing value out: plan_schedule fills in the usual
  setting and says so. "Full" means 100 %.
- Never guess a vague number or time ("leaving early", "by lunchtime", "a few hours", "extra warm", "cosy"): ask.
- If anything is too vague to plan, copy the household's words into "unclear" (for example ["leaving early"]);
  plan_schedule then asks about them. Never replace a vague time with the usual one yourself.
- These are NOT unclear: a car request with only a day or no time at all (the usual ready-by time applies); an
  appliance with no deadline (leave the deadline out: it runs at the cheapest time in the known prices); and a
  vague word the message makes precise with numbers. Example: "warm it up nicely, 21 degrees from 5 to 7" is a
  comfort band of 21 C from 5 to 7, not unclear.
- Ask with topic "conflict" when requests contradict each other (for example away mode and a warm house at the
  same time, or charging without grid power when solar and battery cannot cover it).
- Do not work out yourself whether a charge or an appliance fits in time: plan_schedule checks it exactly. If it
  reports problems, ask the household about them. If it only warns that the car cannot be fully charged in time,
  commit: the gateway charges as much as it can, and your explanation must pass the warning on.

Answer:
- commit true only after plan_schedule returned a schedule (every requirement met, or a car charge with a
  warning) and nothing is unclear; otherwise commit false with one short question per unclear point.
- explanation: two to four plain sentences for the household, using plan_schedule's figures: when the car charges
  and each appliance runs, and why (the "Why" of each device: solar or low grid price), the saving, and any usual
  setting plan_schedule used."""


def message(plan: dict) -> str:
    text = f"Message sent {plan['sent']}:\n{plan['text']}"
    if plan.get("change"):
        text += f"\n\nLater message sent {plan['change']['sent']}:\n{plan['change']['text']}"
    return text


def run_plan(model_name: str, gw: Gateway) -> tuple[dict, dict]:
    model = make_model(model_name, num_ctx=plan_num_ctx(model_name))
    started = time.perf_counter()
    with get_usage_metadata_callback() as usage:
        try:
            r = run_react(model, gw.tools(), SYSTEM, AppAnswer, message(gw.plan), "gateway", STEP_LIMIT, {})
        except Exception as exc:  # e.g. Ollama's tool-call parser rejecting the model's output: a failed answer
            if "ResponseError" not in type(exc).__name__:
                raise
            r = ReactResult(None, 0, [f"gateway: provider rejected the model output ({str(exc)[:120]})"], 0)
    tokens_in, tokens_out, usd = usage_cost_usd(usage.usage_metadata, model_name)
    meta = {"latency_s": round(time.perf_counter() - started, 2), "tool_calls": r.tool_calls, "tokens_in": tokens_in,
            "tokens_out": tokens_out, "usd": usd, "recoveries": r.recoveries, "error": "; ".join(r.errors) or None,
            "schedule_calls": len(gw.schedules)}  # fmt: skip
    # The agent's actions in order: each model turn with the tools it called (AppAnswer = its final answer)
    meta["actions"] = [{"turn": turn, "tool": call["name"], "args": json.dumps(call.get("args", {}), ensure_ascii=False)[:300]}
                       for turn, m in enumerate((m for m in r.messages if getattr(m, "tool_calls", None)), start=1)
                       for call in m.tool_calls]  # fmt: skip
    last = gw.schedules[-1] if gw.schedules else None
    answer = r.output.model_dump() if r.output is not None else None
    if gw.checks:
        commit = bool(answer and answer["commit"] and last and "problems" not in last
                      and all(x["met"] or x.get("warning") for x in last.get("checks", [])))  # fmt: skip
    else:  # without the checks the gateway applies whatever the model commits
        commit = bool(answer and answer["commit"])
    got = {**(last["requirements"] if last else {}), "questions": (answer or {}).get("questions", []), "commit": commit}
    if answer is None:  # a failed answer is a question to the household
        got["questions"] = [{"topic": "other", "text": "(no valid answer)"}]
    meta["model_commit"] = bool(answer and answer["commit"])
    # The model layer's fallback triggers (Section 4.2 of the thesis): the answer failed validation (run_react already
    # retried), or the gateway refused a plan the model committed.
    meta["failed_answer"] = answer is None
    meta["checker_rejected"] = bool(gw.checks and meta["model_commit"] and not commit)
    last = last or {}
    message_in = {"sent": gw.plan["sent"], "text": gw.plan["text"], "car_pct": gw.plan.get("state", {}).get("ev_pct")}
    if gw.plan.get("change"):
        message_in["later"] = {"sent": gw.plan["change"]["sent"], "text": gw.plan["change"]["text"]}

    def status(x: dict) -> str:
        return "later" if x.get("later") else "met" if x["met"] else "partly" if x.get("warning") else "not met"

    app = {
        "plan": gw.plan["id"], "model": model_name,
        "household_message": message_in,
        "decision": "commit" if commit else "ask",
        "message_to_household": (answer or {}).get("explanation"),
        "questions": got["questions"],
        "notes": last.get("notes", []),
        "warnings": [d["warning"] for d in last.get("devices", []) if d.get("warning")],
        "requirements": [{"requirement": x["requirement"], "status": status(x)} for x in last.get("checks", [])],
        "problems": last.get("problems"),
        "schedule": last.get("devices") if commit else None,
        "cost_eur": last.get("cost_eur") if commit else None,
        "timeline_hourly": last.get("timeline") if commit else None,
    }  # fmt: skip
    return got, {**meta, "app": app}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--models", nargs="+", default=list(MODELS))
    parser.add_argument("--plans", type=Path, default=ROOT / "plan_pilot" / "plans.json")
    parser.add_argument("--ids", nargs="*", help="only these plans")
    parser.add_argument("--out", type=Path, default=HERE / "out" / "results.jsonl")
    parser.add_argument("--loop", action="store_true", help="execute committed plans in the closed loop")
    args = parser.parse_args()
    load_dotenv()
    home = Home()
    all_days = load_days(args.raw_dir, 2016, "de", "feedin")
    fcs = forecasts_for(all_days, "weather")
    days = {d.date: d for d in all_days}
    data = json.loads(args.plans.read_text(encoding="utf-8"))
    household = data["household"]
    plans = [p for p in data["plans"] if not args.ids or p["id"] in args.ids]
    appliances = json.loads((HERE / "appliances.json").read_text(encoding="utf-8"))
    done = set()
    if args.out.exists():
        done = {(r["model"], r["id"], r["plans_file"]) for r in map(json.loads, args.out.read_text(encoding="utf-8").splitlines())}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as out:
        for model_name in args.models:
            for plan in plans:
                if (model_name, plan["id"], args.plans.name) in done:
                    continue
                t0 = parse(now(plan))
                d0, d1 = t0.date().isoformat(), (t0.date() + timedelta(days=1)).isoformat()
                if d0 not in days or d1 not in days:
                    print(f"{plan['id']}: no data for {d0}/{d1}, skipped")
                    continue
                w = World(t0, t0.hour * 4 + t0.minute // 15, (days[d0], days[d1]), (fcs[d0], fcs[d1]))
                gw = Gateway(plan, household, w, home, appliances)
                got, meta = run_plan(model_name, gw)
                app = meta.pop("app")
                row = {"model": model_name, "plans_file": args.plans.name, **score(plan, got, household), **meta,
                       "output": got}  # fmt: skip
                if args.loop and got["commit"] and plan["key"].get("decision") == "commit":
                    key = constraints(plan, plan["key"], t0, w.horizon, home, household["car_battery_kwh"])
                    c = constraints(plan, got, t0, w.horizon, home, household["car_battery_kwh"])
                    ev_avail = (0, max([b for _, b, _ in key.ev], default=w.horizon))
                    ref = run(w, home, key, ev_avail)
                    ran = run(w, home, c, ev_avail)
                    names = [a[0] for a in key.appliances]
                    row["loop"] = judge(w, home, key, ran, ran["starts"], [a[0] for a in c.appliances])
                    row["loop"]["key_cost_eur"] = judge(w, home, key, ref, ref["starts"], names)["adjusted_cost_eur"]
                out.write(json.dumps(row) + "\n")
                out.flush()
                app["expected"] = plan["key"]  # the answer key, for checking
                app["check"] = {"decision_ok": row.get("decision_ok"), "items_right": row["tp"], "items_extra": row["fp"],
                                "items_missed": row["fn"], "met_on_real_day": row.get("loop", {}).get("met"),
                                "seconds": meta["latency_s"], "tool_calls": meta["tool_calls"]}  # fmt: skip
                app["actions"] = meta["actions"]
                app_path = HERE / "out" / "app" / model_name / f"{plan['id']}.json"
                app_path.parent.mkdir(parents=True, exist_ok=True)
                app_path.write_text(json.dumps(app, indent=1), encoding="utf-8")
                print(f"{model_name:14s} {plan['id']}: {'commit' if got['commit'] else 'ask':6s} "
                      f"key {plan['key'].get('decision', 'commit'):6s} tp {row['tp']} fp {row['fp']} fn {row['fn']} "
                      f"{meta['latency_s']:6.1f} s, {meta['tool_calls']} calls"
                      + (f", loop {'met' if row['loop']['met'] else 'MISSED'}" if "loop" in row else "")
                      + (f" ERROR {meta['error']}" if meta["error"] else ""), flush=True)  # fmt: skip
    report(args.out)


def report(path: Path) -> None:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    print(f"\n{'model':14s} {'plans file':16s} plans precision recall decision  s/plan  calls  loop met")
    for (m, pf) in dict.fromkeys((r["model"], r["plans_file"]) for r in rows):
        mine = [r for r in rows if r["model"] == m and r["plans_file"] == pf]
        s = summarize(mine)
        loop = [r["loop"]["met"] for r in mine if "loop" in r]
        print(f"{m:14s} {pf:16s} {len(mine):5d} {s['item_precision'] or 0:9.2f} {s['item_recall'] or 0:6.2f} "
              f"{s['decision_accuracy'] or 0:8.2f} {np.mean([r['latency_s'] for r in mine]):7.1f} "
              f"{np.mean([r['tool_calls'] for r in mine]):6.1f}  {sum(loop)}/{len(loop)}")  # fmt: skip


if __name__ == "__main__":
    main()
