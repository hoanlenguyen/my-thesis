"""Rewrites the pilot and development plans in everyday wording, with the household's usual settings (13 Nov 2026).

The first plans gave an exact charge target and time in almost every message. Smart-charging apps keep the target
and "ready by" time as a standing setting (e.g. Octopus Intelligent Go's default of 80 % by 08:00), and a household
writes short messages ("charge the car for work tomorrow", "charge it full"). The household now has usual settings
(80 %, ready at 07:30); a message without a target or a time uses them (a named day without a time: 07:30 on that
day), "full" means 100 %. A car charge the charger cannot complete in time is committed with a warning (the car
charges as much as it can); the gateway asks only when a time or amount is vague or requests contradict each other
(author's decisions, 13 Nov 2026). Dates, car charge and plan ids stay; texts and answer keys change (DRAFT keys:
the author checks them). The exact-wording plans are archived in ``archive/``.

    uv run python prototypes/plan_pilot/rewrite_plans.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).parent
USUAL = {"car_target_pct": 80, "car_ready_by": "07:30", "car_ready_days": "every day",
         "note": "set once in the app; used when a message gives no target or no time"}  # fmt: skip


def ev(departure: str, pct: float | None = None, kwh: float | None = None, **extra) -> dict:
    item = {"departure": departure}
    if pct is not None:
        item["target_pct"] = pct
    if kwh is not None:
        item["energy_kwh"] = kwh
    return {**item, **extra}


# id: (text, later text or None, key)
PLANS = {
    "S1": ("Charge the car for work tomorrow.", None,
           {"decision": "commit", "ev": [ev("2016-03-14 07:30", 80)]}),
    "S2": ("Out at work from 8:30 till 5 today. Dishwasher done before we're home please.", None,
           {"decision": "commit", "appliances": [{"appliance": "dishwasher", "deadline": "2016-11-08 17:00"}],
            "away": [{"start": "2016-11-08 08:30", "end": "2016-11-08 17:00"}]}),
    "S3": ("Charge the car full, and make it nice and warm in the morning, 22-23 from 6 to 8.", None,
           {"decision": "commit", "ev": [ev("2016-01-20 07:30", 100)],
            "comfort": [{"start": "2016-01-20 06:00", "end": "2016-01-20 08:00", "min_c": 22, "max_c": 23}]}),
    "S4": ("Home all day, don't need the car. Washing between 10 and 3 please.", None,
           {"decision": "commit", "appliances": [{"appliance": "washing_machine", "earliest": "2016-06-07 10:00",
                                                  "deadline": "2016-06-07 15:00"}]}),
    "S5": ("Charge it to 100%, and turn the heating down to 18-20 overnight, midnight to 6.", None,
           {"decision": "commit", "ev": [ev("2016-02-03 07:30", 100)],
            "comfort": [{"start": "2016-02-03 00:00", "end": "2016-02-03 06:00", "min_c": 18, "max_c": 20}]}),
    "S6": ("Going out tonight from 6 to 10. Car at 70% by 6 and the washing finished by half five.", None,
           {"decision": "commit", "ev": [ev("2016-09-20 18:00", 70)],
            "appliances": [{"appliance": "washing_machine", "deadline": "2016-09-20 17:30"}],
            "away": [{"start": "2016-09-20 18:00", "end": "2016-09-20 22:00"}]}),
    "C1": ("Car for 8 please.", "Back home and plugged in. I need it again at half four, the usual charge is fine.",
           {"decision": "commit", "ev": [ev("2016-03-15 16:30", 80)]}),
    "C2": ("Out all day, 8:30 to 6.", "Coming home early, back at half two. Make it warm, 22-23, until 9.",
           {"decision": "commit", "away": [{"start": "2016-12-06 08:30", "end": "2016-12-06 14:30"}],
            "comfort": [{"start": "2016-12-06 14:30", "end": "2016-12-06 21:00", "min_c": 22, "max_c": 23}]}),
    "C3": ("Out tonight 7:30 to 10:30, dishwasher done by 9.",
           "Change of plan, we're staying in. The dishwasher just needs to be done by 7 tomorrow.",
           {"decision": "commit", "appliances": [{"appliance": "dishwasher", "deadline": "2016-07-13 07:00"}]}),
    "C4": ("Car for the gym at 6.", "Skipping the gym. Just the usual for tomorrow then.",
           {"decision": "commit", "ev": [ev("2016-10-05 07:30", 80)]}),
    "C5": ("Usual charge for tomorrow.", "Actually charge it full, long drive. And a wash overnight, done by 6.",
           {"decision": "commit", "ev": [ev("2016-04-20 07:30", 100)],
            "appliances": [{"appliance": "washing_machine", "deadline": "2016-04-20 06:00"}]}),
    "A1": ("Long trip tomorrow, leaving really early. Make sure the car is full.", None,
           {"decision": "ask", "clarify": ["ev"]}),
    "A2": ("Visiting friends for a few hours this afternoon, turn the heat down while we're out.", None,
           {"decision": "ask", "clarify": ["away", "comfort"]}),
    "A3": ("Charge the car before I head out, and the dishwasher by 6pm.", None,
           {"decision": "ask", "appliances": [{"appliance": "dishwasher", "deadline": "2016-05-24 18:00"}],
            "clarify": ["ev"]}),
    "A4": ("Car's plugged in for the commute tomorrow. Make the house extra warm tonight.", None,
           {"decision": "ask", "ev": [ev("2016-11-23 07:30", 80)], "clarify": ["comfort"]}),
    "A5": ("Need the car charged by lunchtime, and a load of washing today.", None,
           {"decision": "ask", "appliances": [{"appliance": "washing_machine", "deadline": "2016-08-10 00:00"}],
            "clarify": ["ev"]}),
    "A6": ("Away for the weekend.", None, {"decision": "ask", "clarify": ["away"]}),
    "X1": ("Just got home, need it full for 5am.", None,
           {"decision": "commit", "ev": [ev("2016-02-12 05:00", 100, feasible=False)]}),
    "X2": ("We're out 9 to 5, put the heating on away mode. But keep it at 23 all day, 8 to 6.", None,
           {"decision": "ask", "away": [{"start": "2016-12-13 09:00", "end": "2016-12-13 17:00"}],
            "clarify": ["conflict", "comfort"]}),
    "X3": ("Taking the car to work tomorrow, 8 to 5. Charge it to 90% from the solar panels at midday.", None,
           {"decision": "ask", "away": [{"start": "2016-07-26 08:00", "end": "2016-07-26 17:00"}],
            "clarify": ["conflict", "ev"]}),
    "X4": ("Charge it full before we go to dinner at 8.", None,
           {"decision": "commit", "ev": [ev("2016-10-18 20:00", 100, feasible=False)]}),
    "X5": ("Usual charge for tomorrow, but no power from the grid tonight.", None,
           {"decision": "ask", "ev": [ev("2016-01-13 07:30", 80, feasible=False, infeasible_because=(
               "no grid at night: 20 kWh needed, the home battery holds 10 kWh and there is no PV in a January "
               "night"))], "clarify": ["conflict", "ev"]}),
    # development plans
    "DS1": ("Usual charge for tomorrow, and run the dishwasher overnight, done by 7.", None,
            {"decision": "commit", "ev": [ev("2016-04-06 07:30", 80)],
             "appliances": [{"appliance": "dishwasher", "deadline": "2016-04-06 07:00"}]}),
    "DS2": ("Washing done by noon please, and we're out 1 to 4.", None,
            {"decision": "commit", "appliances": [{"appliance": "washing_machine", "deadline": "2016-10-21 12:00"}],
             "away": [{"start": "2016-10-21 13:00", "end": "2016-10-21 16:00"}]}),
    "DS3": ("Add 10 kWh to the car for quarter past seven tomorrow, and 21-22 in the house from 6 to 8.", None,
            {"decision": "commit", "ev": [ev("2016-12-02 07:15", kwh=10)],
             "comfort": [{"start": "2016-12-02 06:00", "end": "2016-12-02 08:00", "min_c": 21, "max_c": 22}]}),
    "DS4": ("No car today. Washing and dishwasher, both done by 6pm.", None,
            {"decision": "commit", "appliances": [{"appliance": "washing_machine", "deadline": "2016-08-15 18:00"},
                                                  {"appliance": "dishwasher", "deadline": "2016-08-15 18:00"}]}),
    "DC1": ("Car at 70% by 5.", "Plans changed, leaving at 3 instead, same charge.",
            {"decision": "commit", "ev": [ev("2016-05-03 15:00", 70)]}),
    "DC2": ("Out skiing 9 to 7.", "Back at 5 instead, warm it up to 22-23 until 10.",
            {"decision": "commit", "away": [{"start": "2016-02-20 09:00", "end": "2016-02-20 17:00"}],
             "comfort": [{"start": "2016-02-20 17:00", "end": "2016-02-20 22:00", "min_c": 22, "max_c": 23}]}),
    "DC3": ("Dishwasher done by 10 please.", "Forget the dishwasher. Charge the car full for tomorrow though.",
            {"decision": "commit", "ev": [ev("2016-09-08 07:30", 100)]}),
    "DA1": ("Charge the car for my trip on Saturday.", None,
            {"decision": "commit", "ev": [ev("2016-04-02 07:30", 80)]}),
    # no deadline: the cheapest time within the known day-ahead prices (to the end of tomorrow); author, 13 Nov 2026
    "DA2": ("Run the washing sometime when it's cheap.", None,
            {"decision": "commit", "appliances": [{"appliance": "washing_machine", "deadline": "2016-11-04 00:00"}]}),
    "DA3": ("Car full for my trip, leaving early tomorrow.", None, {"decision": "ask", "clarify": ["ev"]}),
    "DA4": ("Guests tonight, make it cosy.", None, {"decision": "ask", "clarify": ["comfort"]}),
    "DX1": ("Charge it full for 5:30.", None,
            {"decision": "commit", "ev": [ev("2016-05-18 05:30", 100, feasible=False)]}),
    "DX2": ("On holiday till Friday 6pm. Heating on away mode, but keep it at 22 the whole time.", None,
            {"decision": "ask", "away": [{"start": "2016-12-19 07:00", "end": "2016-12-23 18:00"}],
             "clarify": ["conflict", "comfort"]}),
    "DX3": ("Dishwasher and washing, both done by 9.", None,
            {"decision": "ask", "appliances": [{"appliance": "dishwasher", "deadline": "2016-08-02 21:00"},
                                               {"appliance": "washing_machine", "deadline": "2016-08-02 21:00"}],
             "clarify": ["conflict", "appliance"]}),
}


def main() -> None:
    (HERE / "archive").mkdir(exist_ok=True)
    for name in ("plans.json", "plans_dev.json"):
        path = HERE / name
        archived = HERE / "archive" / name.replace(".json", "_exact_wording.json")
        if not archived.exists():
            shutil.copy(path, archived)
        data = json.loads(archived.read_text(encoding="utf-8"))
        data["household"]["usual"] = USUAL
        data["household"]["appliances"] = {"dishwasher": "measured cycle about 1 h, 0.76 kWh",
                                           "washing_machine": "measured cycle about 2.25 h, 0.85 kWh"}  # fmt: skip
        for plan in data["plans"]:
            text, later, key = PLANS[plan["id"]]
            plan["text"], plan["key"] = text, key
            if plan.get("change"):
                plan["change"]["text"] = later
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{name}: {len(data['plans'])} plans rewritten; exact wording in {archived.name}")


if __name__ == "__main__":
    main()
