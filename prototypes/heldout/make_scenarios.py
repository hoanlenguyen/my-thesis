"""Scenario cards for the held-out plan set (draft for the registration, 21 Nov 2026).

Each card is a real house-day of OPSD ``DE_KN_residential4`` (2016, as in the pilots) with the situation a plan
writer is asked to put into their own words: the time the message is sent, the car's charge, who is home and what
they want. The writer's message, not the card, is what the agents read and what the author keys.

Selection (seed 2027):

- days with data for the day and the next (plans span two days); not a date of the development or test plans
  (``plan_pilot/plans_dev.json``, ``plans.json``) or the day after, and not in the four September weeks on which the
  expert MPC setting was tuned (2016-09-05 to 2016-10-02);
- stratified by season (winter Dec-Feb, spring Mar-May, summer Jun-Aug, autumn Sep-Nov) x weather class (tertiles of
  daily DWD global radiation among the eligible days of the season): 10 days per cell, 120 cards;
- plan types: 40 simple, 40 change, 20 ambiguous, 20 conflicting, assigned at random; each of four writers (W1-W4)
  gets 10 / 10 / 5 / 5;
- the price pattern of the day (flat, evening peak, volatile) is recorded for the descriptive analysis.

Situations are drawn from the household of the pilots (``plan_pilot/plans.json``: 40 kWh car, 3.7 kW charger, usual
charge 80 % by 07:30, comfort 20-22 C, away setback 17 C, dishwasher about 1 h, washing machine about 2.25 h).
Simple and change cards are feasible (checked: energy needed <= charger kW x hours, appliance window >= cycle);
conflicting cards are built to be impossible or contradictory.

    uv run python prototypes/heldout/make_scenarios.py --raw-dir D:/Study/my-thesis/data/raw
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "home_gateway"))
from twin import load_days  # noqa: E402

SEED = 2027
FMT = "%Y-%m-%d %H:%M"
CAR_KWH, CHARGER_KW = 40.0, 3.7
CYCLE_H = {"dishwasher": 1.0, "washing_machine": 2.25}
APPLIANCE_NAME = {"dishwasher": "dishwasher", "washing_machine": "washing machine"}
TUNE = (date(2016, 9, 5), date(2016, 10, 2))
KINDS = {"simple": 40, "change": 40, "ambiguous": 20, "conflict": 20}
WRITERS = ["W1", "W2", "W3", "W4"]
SEASON = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
          6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}  # fmt: skip


def at(day: date, hhmm: str, plus_days: int = 0) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m) + timedelta(days=plus_days)


def clock(t: datetime) -> str:
    return t.strftime("%H:%M")


def when(t: datetime, sent: datetime) -> str:
    """'at 07:30 tomorrow' / 'at 17:30 today' relative to the message."""
    d = (t.date() - sent.date()).days
    return f"{clock(t)} {'today' if d == 0 else 'tomorrow' if d == 1 else t.strftime('%A')}"


def price_pattern(prices: np.ndarray, high_spread: float) -> str:
    """Volatile: hourly spread in the top third of the year's days; evening peak: else the dearest hour is 17-20;
    flat: the rest. (Consumer prices: the spot part is small, so the spread is a few cents.)"""
    hourly = prices.reshape(24, -1).mean(axis=1)
    if hourly.max() - hourly.min() > high_spread:
        return "volatile"
    return "evening peak" if 17 <= int(hourly.argmax()) <= 20 else "flat"


class Maker:
    def __init__(self, rng: np.random.Generator) -> None:
        self.rng = rng

    def pick(self, options):
        return options[int(self.rng.integers(len(options)))]

    def time_between(self, day: date, start: str, end: str, step_min: int = 15, plus_days: int = 0) -> datetime:
        a, b = at(day, start, plus_days), at(day, end, plus_days)
        n = int((b - a).total_seconds() // (step_min * 60))
        return a + timedelta(minutes=step_min * int(self.rng.integers(n + 1)))

    # ── requirement elements: (facts for the key reference, situation sentence) ──
    def ev_next_morning(self, day: date, sent: datetime, car: int) -> tuple[dict, str]:
        dep = self.time_between(day, "06:00", "08:30", plus_days=1)
        target = self.pick([None, 60, 70, 80, 90, 100])
        if dep.weekday() >= 5:  # tomorrow is Saturday or Sunday
            reason = self.pick(["go on a day trip", "drive to visit family", "go to an early sports match"])
        else:
            reason = self.pick(["drive to work", "drive the children to school and go on to work",
                                "have an early meeting in town"])  # fmt: skip
        if target is None:  # the usual charge
            return ({"ev": {"departure": "usual 07:30", "target_pct": 80}},
                    f"Tomorrow you {reason} and leave at the usual time; the usual charge is enough.")
        return ({"ev": {"departure": dep.strftime(FMT), "target_pct": target}},
                f"Tomorrow you {reason} and leave at {clock(dep)}; you want the car at {target} %.")

    def ev_same_day(self, day: date, sent: datetime, car: int) -> tuple[dict, str]:
        dep = sent + timedelta(hours=int(self.rng.integers(4, 9)))
        kwh = int(self.rng.integers(8, 21))
        if self.rng.random() < 0.5:
            return ({"ev": {"departure": dep.strftime(FMT), "energy_kwh": kwh}},
                    f"You need the car at {when(dep, sent)} for a trip that takes about {kwh} kWh.")
        target = min(100, car + 10 * int(self.rng.integers(3, 6)))
        return ({"ev": {"departure": dep.strftime(FMT), "target_pct": target}},
                f"You need the car at {when(dep, sent)}, charged to {target} %.")

    def appliance(self, day: date, sent: datetime, kind: str | None = None) -> tuple[dict, str]:
        kind = kind or self.pick(list(CYCLE_H))
        earliest_h = CYCLE_H[kind] + 1.0
        deadline = sent + timedelta(hours=float(self.rng.integers(int(np.ceil(earliest_h)), 13)))
        deadline = deadline.replace(minute=(deadline.minute // 15) * 15)
        quiet = self.rng.random() < 0.25 and sent.hour < 9
        facts = {"appliance": kind, "deadline": deadline.strftime(FMT)}
        text = f"The {APPLIANCE_NAME[kind]} is loaded and should be finished by {when(deadline, sent)}"
        if quiet:
            start = sent.replace(hour=9, minute=0)
            facts["earliest"] = start.strftime(FMT)
            text += ", but not running before 09:00 (someone is still asleep)"
        return {"appliances": facts}, text + "."

    def away(self, day: date, sent: datetime) -> tuple[dict, str]:
        start = max(sent + timedelta(hours=1), self.time_between(day, "08:00", "18:00"))
        end = start + timedelta(hours=float(self.rng.integers(3, 10)))
        what = self.pick(["visiting relatives", "at a football match", "on a day trip", "at work and then shopping"])
        return ({"away": {"start": start.strftime(FMT), "end": end.strftime(FMT)}},
                f"Everyone is out ({what}) from {when(start, sent)} until {when(end, sent)}; the house can cool down.")

    def comfort(self, day: date, sent: datetime) -> tuple[dict, str]:
        warm = self.rng.random() < 0.6
        if warm:
            start = self.time_between(day, "17:00", "19:00")
            start = max(start, sent + timedelta(hours=1))
            end = start + timedelta(hours=float(self.rng.integers(3, 6)))
            lo = int(self.pick([22, 23]))
            return ({"comfort": {"start": start.strftime(FMT), "end": end.strftime(FMT), "min_c": lo}},
                    f"Guests come at {when(start, sent)} and stay until about {when(end, sent)}; "
                    f"you want at least {lo} degrees then.")
        start = at(day, "23:00")
        end = at(day, "06:30", 1)
        hi = int(self.pick([18, 19]))
        return ({"comfort": {"start": start.strftime(FMT), "end": end.strftime(FMT), "max_c": hi}},
                f"You sleep better in a cool house: no more than {hi} degrees from 23:00 until 06:30.")

    # ── cards by type ──
    def simple(self, day: date) -> dict:
        """A feasible plan with every detail given (redrawn until the car and appliance checks pass)."""
        for _ in range(100):
            card = self._simple(day)
            if feasible(card):
                return card
        raise RuntimeError(f"no feasible simple card for {day}")

    def _simple(self, day: date) -> dict:
        evening = self.rng.random() < 0.6
        sent = self.time_between(day, "18:00", "22:00") if evening else self.time_between(day, "06:30", "09:00")
        car = int(self.rng.integers(2, 7)) * 10
        parts = []
        if evening:
            parts.append(self.ev_next_morning(day, sent, car))
            if self.rng.random() < 0.5:
                parts.append(self.appliance(day, sent, "dishwasher"))
        else:
            first = self.pick(["ev", "away", "appliance"])
            parts.append(self.ev_same_day(day, sent, car) if first == "ev" else
                         self.away(day, sent) if first == "away" else self.appliance(day, sent))  # fmt: skip
            if self.rng.random() < 0.5:
                parts.append(self.pick([self.comfort, lambda d, s: self.appliance(d, s)])(day, sent))
        return self.card(sent, car, parts, instruction=(
            "Write the message you would send the home app, in your own words. Give the details the situation gives; "
            "you can leave out what the app already knows (the usual car charge is 80 % by 07:30)."))

    def ambiguous(self, day: date) -> dict:
        card = self.simple(day)
        vague = []
        for f in card["facts"]:
            if "ev" in f:
                vague.append(self.pick(["how much charge (say something like 'enough' or 'well charged')",
                                        "when you leave (say something like 'early' or 'in the morning')"]))
            if "away" in f:
                vague.append("when you will be back (say something like 'for a few hours')")
            if "comfort" in f:
                vague.append("the temperature (say something like 'extra warm' or 'nice and cool')")
            if "appliances" in f:
                vague.append("when it must be done (say something like 'sometime' or 'whenever it's cheap')")
        card["instruction"] = ("Write the message you would send in a hurry, in your own words. Keep this one thing vague, "
                               f"the way people do: {self.pick(vague)}. Give the other details as usual.")
        return card

    def change(self, day: date) -> dict:
        card = self.simple(day)
        sent = datetime.strptime(card["sent"], FMT)
        # the later message comes 1-3 h after an evening message (before midnight), 2-5 h after a morning one
        later = sent + timedelta(minutes=15 * int(self.rng.integers(4, 13) if sent.hour >= 12 else self.rng.integers(8, 21)))
        later = min(later, at(day, "23:30"))
        ev = next((f["ev"] for f in card["facts"] if "ev" in f), None)
        dep = None
        if ev:
            dep = datetime.strptime(ev["departure"], FMT) if ev["departure"][0].isdigit() else at(day, "07:30", 1)
        options = ["add_appliance"] + (["add_comfort"] if later.hour <= 16 else [])  # guests arrive 17-19
        if dep and dep > later + timedelta(hours=2):
            options.append("ev_earlier")
            if (ev.get("target_pct") or 0) < 100 and \
                    (100 - card["car_pct"]) / 100 * CAR_KWH <= (dep - later).total_seconds() / 3600 * CHARGER_KW:
                options.append("ev_more")
        if any("away" in f for f in card["facts"]):
            options.append("back_early")
        what = self.pick(options)
        if what == "ev_earlier":
            new = dep - timedelta(minutes=int(self.rng.integers(2, 5)) * 15)
            change = f"The plan has changed: you now need the car at {when(new, later)} instead."
        elif what == "ev_more":
            change = "The trip is longer than you thought: you now want the car full (100 %)."
        elif what == "back_early":
            ret = later + timedelta(minutes=30)
            change = f"Plans changed: everyone is back home at {when(ret, later)}, earlier than planned."
        elif what == "add_comfort":
            change = self.comfort(day, later)[1]
        else:  # add an appliance the plan does not have yet, or cancel one when it has both
            planned = [f["appliances"]["appliance"] for f in card["facts"] if "appliances" in f]
            free = [a for a in CYCLE_H if a not in planned]
            if free:
                change = self.appliance(day, later, self.pick(free))[1]
            else:
                what = "cancel_appliance"
                change = f"You have decided not to run the {APPLIANCE_NAME[self.pick(planned)]} after all."
        card["change"] = {"sent": later.strftime(FMT), "what": what, "situation": change, "car_pct": card["car_pct"]}
        card["instruction"] += (" Then write the second, later message that tells the app what changed, "
                                "as you would send it at that time.")
        return card

    def conflict(self, day: date) -> dict:
        what = self.pick(["ev_too_much", "ev_too_much", "appliance_too_late", "away_and_warm", "no_grid"])
        if what == "ev_too_much":
            sent = self.time_between(day, "21:00", "23:30")
            car = int(self.pick([10, 15, 20]))
            hours = float(self.rng.integers(3, 6))
            dep = sent + timedelta(hours=hours)
            parts = [({"ev": {"departure": dep.strftime(FMT), "target_pct": 100}},
                      f"You must leave at {when(dep, sent)} for a long drive and want the car full (100 %).")]
            note = (f"needs {(100 - car) / 100 * CAR_KWH:.0f} kWh, the charger gives at most "
                    f"{hours * CHARGER_KW:.1f} kWh by then")
        elif what == "appliance_too_late":
            sent = self.time_between(day, "14:00", "19:00")
            car = int(self.rng.integers(3, 7)) * 10
            deadline = sent + timedelta(minutes=int(self.rng.integers(4, 8)) * 15)
            parts = [({"appliances": {"appliance": "washing_machine", "deadline": deadline.strftime(FMT)}},
                      f"You just loaded the washing machine and need the washing done by {when(deadline, sent)}.")]
            note = f"the washing machine needs about 2.25 h, only {(deadline - sent).seconds / 3600:.2f} h left"
        elif what == "away_and_warm":
            sent = self.time_between(day, "07:00", "08:30")
            car = int(self.rng.integers(3, 7)) * 10
            start, end = at(day, "09:00"), at(day, "17:00")
            parts = [({"away": {"start": start.strftime(FMT), "end": end.strftime(FMT)}},
                      "Everyone is out from 09:00 until 17:00, so the heating can go to away mode."),
                     ({"comfort": {"start": at(day, '08:00').strftime(FMT), "end": at(day, '18:00').strftime(FMT),
                                   "min_c": 23}},
                      "At the same time you want the house kept at 23 degrees all day, from 08:00 to 18:00 (the dog stays in).")]  # noqa: E501
            note = "away setback and 23 C over the same hours contradict each other"
        else:
            sent = self.time_between(day, "19:00", "21:30")
            car = int(self.pick([20, 30]))
            parts = [self.ev_next_morning(day, sent, car),
                     ({"no_grid": True}, "You also want no electricity taken from the grid tonight (only the home battery).")]
            note = "the home battery (10 kWh) cannot give the car's charge overnight without the grid"
        card = self.card(sent, car, parts, instruction=(
            "Write the message you would send the home app, in your own words, asking for all of it as the situation "
            "says. Do not point out the problem yourself."))
        card["conflict_note"] = note
        return card

    def card(self, sent: datetime, car: int, parts: list[tuple[dict, str]], instruction: str) -> dict:
        return {"sent": sent.strftime(FMT), "car_pct": car, "facts": [p[0] for p in parts],
                "situation": " ".join(p[1] for p in parts), "instruction": instruction}


def feasible(card: dict) -> bool:
    """The charger can add the car's energy before departure, and each appliance cycle fits its window."""
    sent = datetime.strptime(card["sent"], FMT)
    for f in card["facts"]:
        if "ev" in f:
            ev = f["ev"]
            dep = datetime.strptime(ev["departure"], FMT) if ev["departure"][0].isdigit() else \
                sent.replace(hour=7, minute=30) + timedelta(days=1 if sent.hour >= 8 else 0)
            need = ev.get("energy_kwh") or max(0, ev["target_pct"] - card["car_pct"]) / 100 * CAR_KWH
            if need > (dep - sent).total_seconds() / 3600 * CHARGER_KW or dep <= sent:
                return False
        if "appliances" in f:
            a = f["appliances"]
            start = max(sent, datetime.strptime(a["earliest"], FMT)) if a.get("earliest") else sent
            if (datetime.strptime(a["deadline"], FMT) - start).total_seconds() / 3600 < CYCLE_H[a["appliance"]]:
                return False
    return True


def used_dates() -> set[date]:
    used = set()
    for name in ("plans.json", "plans_dev.json"):
        for p in json.loads((ROOT / "plan_pilot" / name).read_text(encoding="utf-8"))["plans"]:
            d = datetime.strptime(p["sent"], FMT).date()
            used |= {d, d + timedelta(days=1)}
    return used


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("D:/Study/my-thesis/data/raw"))
    parser.add_argument("--out", type=Path, default=HERE / "scenarios.json")
    args = parser.parse_args()
    rng = np.random.default_rng(SEED)
    days = load_days(args.raw_dir, 2016, "de", "feedin")
    by_date = {date.fromisoformat(d.date): d for d in days}
    ghi = {k: float(d.ghi.sum()) for k, d in by_date.items() if d.ghi is not None}
    if len(ghi) < len(by_date) * 0.9:
        raise SystemExit("DWD radiation missing for most days: check the weather data in --raw-dir")
    used = used_dates()
    eligible = [k for k in sorted(ghi)
                if k + timedelta(days=1) in by_date and k not in used and not TUNE[0] <= k <= TUNE[1]]
    bounds = {}  # weather tertiles of the eligible days within each season (over the year, winter has no sunny days)
    for season in set(SEASON.values()):
        bounds[season] = np.quantile([ghi[k] for k in eligible if SEASON[k.month] == season], [1 / 3, 2 / 3])
    cells: dict[tuple[str, str], list[date]] = {}
    for k in eligible:
        low, high = bounds[SEASON[k.month]]
        weather = "overcast" if ghi[k] < low else "variable" if ghi[k] < high else "sunny"
        cells.setdefault((SEASON[k.month], weather), []).append(k)
    chosen = []
    for cell in sorted(cells):
        pool = cells[cell]
        if len(pool) < 10:
            raise SystemExit(f"only {len(pool)} days in {cell}")
        chosen += [(cell, pool[i]) for i in sorted(rng.choice(len(pool), 10, replace=False))]
    kinds = [k for k, n in KINDS.items() for _ in range(n)]
    rng.shuffle(kinds)
    writer_of: list[str] = [""] * len(kinds)
    for kind in KINDS:
        idx = [i for i, k in enumerate(kinds) if k == kind]
        rng.shuffle(idx)
        for j, i in enumerate(idx):
            writer_of[i] = WRITERS[j % len(WRITERS)]
    spreads = [np.ptp(d.import_price.reshape(24, -1).mean(axis=1)) for d in days]
    high_spread = float(np.quantile(spreads, 2 / 3))
    maker = Maker(rng)
    cards = []
    for i, ((season, weather), d) in enumerate(chosen):
        kind = kinds[i]
        card = getattr(maker, kind)(d)
        day = by_date[d]
        cards.append({"id": f"H{i + 1:03d}", "writer": writer_of[i], "kind": kind, "date": d.isoformat(),
                      "weekday": d.strftime("%A"), "season": season, "weather": weather,
                      "price_pattern": price_pattern(day.import_price, high_spread), **card})  # fmt: skip
    out = {"status": ("DRAFT 21 Nov 2026: scenario cards for the held-out plan set, not registered. Generated by "
                      "make_scenarios.py (seed 2027). Writers see only their own cards, via writer_sheets/."),
           "house": "DE_KN_residential4, 2016 (OPSD); household as in plan_pilot/plans.json",
           "cards": cards}  # fmt: skip
    args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(cards)} cards -> {args.out}")
    print("kinds", dict(Counter(c["kind"] for c in cards)))
    print("writers x kinds", dict(Counter((c["writer"], c["kind"]) for c in cards)))
    print("seasons x weather", dict(Counter((c["season"], c["weather"]) for c in cards)))
    print("price patterns", dict(Counter(c["price_pattern"] for c in cards)))
    write_sheets(cards, HERE / "writer_sheets")


def write_sheets(cards: list[dict], folder: Path) -> None:
    """One Markdown sheet per writer: the house, the rules and their cards, without the plan type or the facts."""
    folder.mkdir(exist_ok=True)
    intro = (HERE / "writer_instructions.md").read_text(encoding="utf-8")
    for w in WRITERS:
        lines = [intro.rstrip(), "", f"# Your situations ({w})", ""]
        for c in (c for c in cards if c["writer"] == w):
            sent = datetime.strptime(c["sent"], FMT)
            lines += [f"## {c['id']}", "",
                      f"**{sent.strftime('%A %d %B %Y, %H:%M')}.** The car is plugged in at {c['car_pct']} %.", "",
                      c["situation"], "", f"*{c['instruction']}*", "", "Message:", "", "> ", ""]  # fmt: skip
            if c.get("change"):
                later = datetime.strptime(c["change"]["sent"], FMT)
                lines += [f"**Later, {later.strftime('%A %H:%M')}.** The car is at {c['change']['car_pct']} %. "
                          + c["change"]["situation"], "", "Second message:", "", "> ", ""]  # fmt: skip
        (folder / f"{w}.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"writer sheets -> {folder}")


if __name__ == "__main__":
    main()
