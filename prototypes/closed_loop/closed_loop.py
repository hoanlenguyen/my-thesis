"""Closed-loop pilot (exploratory, Cycle 2 of the follow-up thesis; not part of the thesis evaluation).

The plan pilot scored the constraints a model reads from a household's plan against an answer key. Here the
constraints go through the rest of the gateway on the real house-days: checker -> MPC -> control layer, and the
household's requirements (the answer key) are checked on what the control layer actually did (H2), with the
cost compared with the same plan given as exact parameters (the key) and with rules.

No model is called: the constraints are the answers stored by the plan pilot (``plan_pilot/results.jsonl``),
gated by the checker of ``plan_pilot/rescore_checker.py``. Only the 11 plans whose key says "commit" are run (for
the others the household's answer to the question is unknown). An answer the checker or the model turns into a
question is not executed and is reported as "asked".

World (OPSD ``DE_KN_residential4``, German setup as in ``home_gateway``): from the time of the last message to
the end of the next day, with the house's measured PV, load, heat demand and COP; the recorded EV sessions are
replaced by the plan's car: plugged in from the last message with the stated charge and gone at the key's
departure. Appliances (assumptions): dishwasher 1.0 kWh over 2.5 h, washing machine 0.9 kWh over 2 h, not
interruptible.

Gateway: an MPC (MILP) re-solved every hour on the weather forecasts of ``home_gateway`` from the measured
state, with the committed constraints: comfort band per slot (away: down to the set-back), EV energy by
departure, appliance windows; shortfalls are allowed at a high penalty so the MPC never fails. The control layer
follows the plan, keeps the committed comfort band, charges at full power when a deadline needs it, starts an
appliance at the last possible slot if the plan has not, and holds the planned grid exchange with the battery.

Rules: heat pump at the set point, the car charged at full power from plug-in to the key's energy, appliances
started at once (or at the key's earliest time), battery in self-consumption mode.

    uv run python prototypes/closed_loop/closed_loop.py --raw-dir D:/Study/my-thesis/data/raw
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pulp

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT / "home_gateway"), str(ROOT / "plan_pilot")]
from gateway import Forecasts, forecasts_for  # noqa: E402
from pilot import now, parse  # noqa: E402
from rescore_checker import gated  # noqa: E402
from twin import Day, Home, load_days  # noqa: E402

from hems.core.models import SLOT_HOURS, SLOTS_PER_DAY  # noqa: E402

HERE = Path(__file__).parent
APPLIANCE = {"dishwasher": (10, 0.4), "washing_machine": (8, 0.45)}  # (slots, kW)
SETBACK_C = 17.0
PENALTY_KWH, PENALTY_KSLOT, PENALTY_APPLIANCE = 5.0, 5.0, 20.0  # EUR per kWh short, per K x slot, per missed run
REPLAN_SLOTS = 4
COMFORT_TOL_KH = 0.5
EV_TOL_KWH = 1.0
SYSTEMS = ("gpt-6-luna", "gemma4-e4b", "qwen3-8b", "qwen3-30b-a3b", "gpt-oss-20b")


# ── Constraints from a HouseholdPlan ─────────────────────────────────────────
@dataclass
class Constraints:
    low: np.ndarray  # comfort band per horizon slot
    high: np.ndarray
    ev: list[tuple[int, int, float]]  # (available from, departure, kWh to add), horizon slots
    appliances: list[tuple[str, int, int]]  # (name, earliest start, deadline)


def to_slot(t0: datetime, value: str | None, horizon: int, default: int) -> int:
    t = parse(value)
    if t is None:
        return default
    return int(np.clip(round((t - t0).total_seconds() / 900), 0, horizon))


def constraints(plan: dict, got: dict, t0: datetime, horizon: int, home: Home, battery_kwh: float) -> Constraints:
    low, high = np.full(horizon, home.comfort_min_c), np.full(horizon, home.comfort_max_c)
    for period in got.get("away", []):
        a, b = to_slot(t0, period.get("start"), horizon, 0), to_slot(t0, period.get("end"), horizon, 0)
        low[a:b] = SETBACK_C
    bands = [(to_slot(t0, c.get("start"), horizon, 0), to_slot(t0, c.get("end"), horizon, 0), c)
             for c in got.get("comfort", [])]  # fmt: skip
    for a, b, c in sorted(bands, key=lambda x: x[1] - x[0], reverse=True):  # narrower bands override wider
        if c.get("min_c") is not None:
            low[a:b] = float(c["min_c"])
        if c.get("max_c") is not None:
            high[a:b] = float(c["max_c"])
    high = np.maximum(high, low)
    pct = float(plan.get("state", {}).get("ev_pct", 30.0))
    ev = []
    for item in got.get("ev", []):
        need = float(item["energy_kwh"]) if item.get("energy_kwh") is not None else \
            max(0.0, (float(item.get("target_pct") or pct) - pct) / 100 * battery_kwh)
        ev.append((to_slot(t0, item.get("earliest"), horizon, 0), to_slot(t0, item.get("departure"), horizon, horizon), need))
    apps = [(a["appliance"], to_slot(t0, a.get("earliest"), horizon, 0), to_slot(t0, a.get("deadline"), horizon, horizon))
            for a in got.get("appliances", []) if a.get("appliance") in APPLIANCE]  # fmt: skip
    return Constraints(low, high, ev, apps)


# ── World: the two days from the last message on ─────────────────────────────
@dataclass
class World:
    t0: datetime
    start: int  # slot of t0 in the first day
    days: tuple[Day, Day]
    fcs: tuple[Forecasts, Forecasts]
    horizon: int = field(init=False)

    def __post_init__(self) -> None:
        self.horizon = 2 * SLOTS_PER_DAY - self.start

    def actual(self, name: str) -> np.ndarray:
        return np.concatenate([getattr(d, name) for d in self.days])[self.start :]

    def forecast(self, k: int) -> dict[str, np.ndarray]:
        """Forecasts made at horizon slot ``k`` for the rest of the horizon."""
        a = self.start + k
        first = self.fcs[0].at(min(a, SLOTS_PER_DAY - 1))
        second = self.fcs[1].at(None if a < SLOTS_PER_DAY else a - SLOTS_PER_DAY)
        return {key: np.concatenate([first[key], second[key]])[self.start :] for key in first}


@dataclass
class Status:
    soc: float
    indoor: float
    ev_left: list[float]
    started: dict[int, int]  # appliance index -> start slot


def mpc(f: dict[str, np.ndarray], k: int, st: Status, c: Constraints, w: World, home: Home) -> dict[str, np.ndarray]:
    H = w.horizon
    slots = range(k, H)
    m = pulp.LpProblem("loop", pulp.LpMinimize)
    hp = {t: pulp.LpVariable(f"h{t}", 0, home.hp_max_kw) for t in slots}
    ch = {t: pulp.LpVariable(f"c{t}", 0, home.battery_kw) for t in slots}
    dis = {t: pulp.LpVariable(f"d{t}", 0, home.battery_kw) for t in slots}
    imp = {t: pulp.LpVariable(f"i{t}", 0) for t in slots}
    exp = {t: pulp.LpVariable(f"x{t}", 0) for t in slots}
    soc = {t: pulp.LpVariable(f"s{t}", home.soc_min * home.battery_kwh, home.battery_kwh) for t in range(k, H + 1)}
    temp = {t: pulp.LpVariable(f"T{t}", 10, 30) for t in range(k, H + 1)}
    dev = {t: pulp.LpVariable(f"u{t}", 0) for t in slots}
    evv = {(i, t): pulp.LpVariable(f"e{i}_{t}", 0, home.ev_max_kw)
           for i, (a, b, _) in enumerate(c.ev) for t in range(max(k, a), b)}  # fmt: skip
    short = {i: pulp.LpVariable(f"short{i}", 0) for i in range(len(c.ev))}
    app_power = {t: 0.0 for t in slots}
    missed = []
    for n, (name, a, b) in enumerate(c.appliances):
        length, kw = APPLIANCE[name]
        if n in st.started:
            for t in range(max(k, st.started[n]), min(H, st.started[n] + length)):
                app_power[t] = app_power[t] + kw
            continue
        y = {s: pulp.LpVariable(f"y{n}_{s}", cat="Binary") for s in range(max(k, a), b - length + 1)}
        miss = pulp.LpVariable(f"miss{n}", cat="Binary")
        m += pulp.lpSum(y.values()) + miss == 1
        missed.append(miss)
        for s, v in y.items():
            for t in range(s, s + length):
                app_power[t] = app_power[t] + kw * v
    price = float(f["import_price"].mean())
    m += (pulp.lpSum((f["import_price"][t] * imp[t] - f["export_price"][t] * exp[t]) * SLOT_HOURS for t in slots)
          - price * (home.efficiency * soc[H] + home.capacity_kwh_per_k * temp[H] / float(f["cop"].mean()))
          + PENALTY_KWH * pulp.lpSum(short.values()) + PENALTY_KSLOT * pulp.lpSum(dev.values())
          + PENALTY_APPLIANCE * pulp.lpSum(missed))  # fmt: skip
    m += soc[k] == st.soc
    m += temp[k] == st.indoor
    for i in range(len(c.ev)):
        m += pulp.lpSum(v for (j, _), v in evv.items() if j == i) * SLOT_HOURS + short[i] == st.ev_left[i]
    for t in slots:
        ev = pulp.lpSum(v for (_, u), v in evv.items() if u == t)
        m += f["fixed"][t] + hp[t] + ev + app_power[t] + ch[t] - dis[t] - f["pv"][t] == imp[t] - exp[t]
        m += ev <= home.ev_max_kw
        m += soc[t + 1] == soc[t] + SLOT_HOURS * (home.efficiency * ch[t] - dis[t] / home.efficiency)
        m += home.capacity_kwh_per_k * (temp[t + 1] - temp[t]) == SLOT_HOURS * (
            f["cop"][t] * hp[t] - f["heat"][t] - home.loss_kw_per_k * (temp[t] - home.set_c))
        m += dev[t] >= c.low[t] - temp[t + 1]
        m += dev[t] >= temp[t + 1] - c.high[t]
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=60))

    def arr(values: dict) -> np.ndarray:
        out = np.zeros(H)
        for t, v in values.items():
            out[t] = pulp.value(v) or 0.0
        return out

    starts = {}
    for v in m.variables():
        if v.name.startswith("y") and (v.value() or 0) > 0.5:
            n, s = v.name[1:].split("_")
            starts[int(n)] = int(s)
    ev_plan = np.zeros((len(c.ev), H))
    for (i, t), v in evv.items():
        ev_plan[i, t] = pulp.value(v) or 0.0
    return {"hp": arr(hp), "grid": arr(imp) - arr(exp), "ev": ev_plan, "starts": starts}


def run(w: World, home: Home, c: Constraints | None, ev_avail: tuple[int, int], rules_ev: float = 0.0,
        rules_apps: list[tuple[str, int, int]] | None = None) -> dict:  # fmt: skip
    """Executes the horizon slot by slot; ``c`` None = rules (car target ``rules_ev``, appliances ``rules_apps``)."""
    apps = c.appliances if c else (rules_apps or [])
    H = w.horizon
    pv, fixed, heat, cop = (w.actual(n) for n in ("pv", "fixed", "heat", "cop"))
    n_ev = len(c.ev) if c else 1
    st = Status(home.soc_start * home.battery_kwh, home.set_c,
                [e for *_, e in c.ev] if c else [rules_ev], {})  # fmt: skip
    hp, ev, app, bat = (np.zeros(H) for _ in range(4))
    soc, indoor = np.zeros(H + 1), np.zeros(H + 1)
    soc[0], indoor[0] = st.soc, st.indoor
    plan = None
    for t in range(H):
        if c is not None and t % REPLAN_SLOTS == 0:
            plan = mpc(w.forecast(t), t, st, c, w, home)
        low, high = (c.low[t], c.high[t]) if c else (home.comfort_min_c, home.comfort_max_c)
        loss = heat[t] + home.loss_kw_per_k * (st.indoor - home.set_c)
        floor = (home.capacity_kwh_per_k * (low - st.indoor) / SLOT_HOURS + loss) / cop[t]
        ceiling = (home.capacity_kwh_per_k * (high - st.indoor) / SLOT_HOURS + loss) / cop[t]
        target = plan["hp"][t] if plan else (home.capacity_kwh_per_k * (home.set_c - st.indoor) / SLOT_HOURS + loss) / cop[t]
        hp[t] = float(np.clip(np.clip(target, floor, ceiling), 0.0, home.hp_max_kw))
        st.indoor += SLOT_HOURS * (cop[t] * hp[t] - loss) / home.capacity_kwh_per_k
        # appliances
        for n, (name, a, b) in enumerate(apps):
            if n in st.started:
                continue
            due = plan["starts"].get(n) == t or t >= b - APPLIANCE[name][0] if c else t >= a
            if due:
                st.started[n] = t
        for n, s in st.started.items():
            length, kw = APPLIANCE[apps[n][0]]
            if s <= t < s + length:
                app[t] += kw
        # EV: only while the car is there
        if ev_avail[0] <= t < ev_avail[1]:
            for i in range(n_ev):
                a, b = (c.ev[i][0], min(c.ev[i][1], ev_avail[1])) if c else ev_avail
                if not a <= t < b or st.ev_left[i] <= 1e-6:
                    continue
                wanted = plan["ev"][i, t] if c else home.ev_max_kw
                must = max(0.0, st.ev_left[i] / SLOT_HOURS - home.ev_max_kw * (b - t - 1))
                power = min(home.ev_max_kw - ev[t], st.ev_left[i] / SLOT_HOURS, max(wanted, must))
                ev[t] += power
                st.ev_left[i] -= power * SLOT_HOURS
        net = fixed[t] + hp[t] + ev[t] + app[t] - pv[t]
        wanted = plan["grid"][t] - net if plan else -net
        room = (home.battery_kwh - st.soc) / (home.efficiency * SLOT_HOURS)
        available = max((st.soc - home.soc_min * home.battery_kwh) * home.efficiency / SLOT_HOURS, 0.0)
        bat[t] = float(np.clip(wanted, -min(home.battery_kw, available), min(home.battery_kw, room)))
        st.soc += SLOT_HOURS * (bat[t] * home.efficiency if bat[t] > 0 else bat[t] / home.efficiency)
        soc[t + 1], indoor[t + 1] = st.soc, st.indoor
    grid = fixed + hp + ev + app + bat - pv
    return {"imports": np.clip(grid, 0, None), "exports": np.clip(-grid, 0, None), "ev": ev, "indoor": indoor,
            "soc": soc, "starts": dict(st.started)}


def judge(w: World, home: Home, key: Constraints, r: dict, apps_started: dict[int, int] | None,
          app_names: list[str]) -> dict:  # fmt: skip
    """Requirements of the answer key on what was executed, and the adjusted cost."""
    ev_ok = all(r["ev"][:b].sum() * SLOT_HOURS >= need - EV_TOL_KWH for _, b, need in key.ev)
    low, high = key.low, key.high
    t_mid = r["indoor"][1:]
    comfort_kh = float((np.clip(low - t_mid, 0, None) + np.clip(t_mid - high, 0, None)).sum() * SLOT_HOURS)
    app_ok = True
    for name, a, b in key.appliances:
        length = APPLIANCE[name][0]
        starts = [s for n, s in (apps_started or {}).items() if app_names[n] == name]
        app_ok &= any(a <= s and s + length <= b for s in starts)
    imp_price, exp_price, cop = w.actual("import_price"), w.actual("export_price"), w.actual("cop")
    cost = float(((imp_price * r["imports"] - exp_price * r["exports"]) * SLOT_HOURS).sum())
    stored = ((r["soc"][-1] - home.soc_start * home.battery_kwh) * home.efficiency
              + home.capacity_kwh_per_k * (r["indoor"][-1] - home.set_c) / float(cop.mean()))  # fmt: skip
    met = ev_ok and app_ok and comfort_kh < COMFORT_TOL_KH
    return {"met": met, "ev_ok": ev_ok, "appliances_ok": app_ok, "comfort_kh": round(comfort_kh, 2),
            "adjusted_cost_eur": round(cost - stored * float(imp_price.mean()), 3)}  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=HERE / "out" / "results.jsonl")
    args = parser.parse_args()
    home = Home()
    all_days = load_days(args.raw_dir, 2016, "de", "feedin")
    fcs = forecasts_for(all_days, "weather")
    days = {d.date: d for d in all_days}
    pilot_dir = ROOT / "plan_pilot"
    data = json.loads((pilot_dir / "plans.json").read_text(encoding="utf-8"))
    household, plans = data["household"], [p for p in data["plans"] if p["key"].get("decision") == "commit"]
    answers: dict[tuple[str, str], dict | None] = {}
    for line in (pilot_dir / "results.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        answers[(row["model"].split("/")[0], row["id"])] = row["output"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as out:
        for plan in plans:
            t0 = parse(now(plan))
            d0 = t0.date().isoformat()
            d1 = (t0.date() + timedelta(days=1)).isoformat()
            if d0 not in days or d1 not in days:
                print(f"{plan['id']}: no data for {d0}/{d1}, skipped")
                continue
            start = t0.hour * 4 + t0.minute // 15
            w = World(t0, start, (days[d0], days[d1]), (fcs[d0], fcs[d1]))
            key = constraints(plan, plan["key"], t0, w.horizon, home, household["car_battery_kwh"])
            key_names = [a[0] for a in key.appliances]
            ev_avail = (0, max([b for _, b, _ in key.ev], default=w.horizon))
            # rules: the household sets the car's target in the app; appliances start at once
            rules_r = run(w, home, None, ev_avail, rules_ev=sum(e for *_, e in key.ev), rules_apps=key.appliances)
            rows = {"rules": judge(w, home, key, rules_r, rules_r["starts"], key_names)}
            ref = run(w, home, key, ev_avail)
            rows["key"] = judge(w, home, key, ref, ref["starts"], key_names)
            for system in SYSTEMS:
                got = answers.get((system, plan["id"]))
                after, _ = gated(plan, got, household)
                if not after.get("commit"):
                    rows[system] = {"asked": True}
                    continue
                c = constraints(plan, after, t0, w.horizon, home, household["car_battery_kwh"])
                r = run(w, home, c, ev_avail)
                rows[system] = judge(w, home, key, r, r["starts"], [a[0] for a in c.appliances])
            for system, row in rows.items():
                out.write(json.dumps({"id": plan["id"], "system": system, **row}) + "\n")
            out.flush()
            print(plan["id"], {s: ("asked" if r.get("asked") else f"{'met' if r['met'] else 'MISSED'} "
                                   f"{r['adjusted_cost_eur']:.2f}") for s, r in rows.items()}, flush=True)  # fmt: skip
    summarize(args.out)


def summarize(path: Path) -> None:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    systems = list(dict.fromkeys(r["system"] for r in rows))
    key_cost = {r["id"]: r["adjusted_cost_eur"] for r in rows if r["system"] == "key"}
    print(f"\n{'system':14s} executed met asked  cost vs key (EUR, executed plans)")
    for s in systems:
        mine = [r for r in rows if r["system"] == s]
        ran = [r for r in mine if not r.get("asked")]
        extra = sum(r["adjusted_cost_eur"] - key_cost[r["id"]] for r in ran)
        print(f"{s:14s} {len(ran):8d} {sum(r['met'] for r in ran):3d} {len(mine) - len(ran):5d}  {extra:+.2f}")


if __name__ == "__main__":
    main()
