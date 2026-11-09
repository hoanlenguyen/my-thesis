"""Rescores the stored plan-pilot outputs with a deterministic checker (exploratory, SQ3 of the follow-up thesis).

No model is called again. For each stored answer (``results.jsonl``) the checker looks only at the model's output
and the gateway state the model was given, never at the answer key:

- an EV requirement without a target (no % and no kWh) is incomplete: the MPC cannot plan it;
- an EV requirement is infeasible when the energy to add exceeds what the charger can deliver between the last
  message (or the stated earliest time) and the departure, or when the departure has already passed;
- an appliance requirement is infeasible when its window (from the last message or the stated earliest time to
  the deadline) is shorter than the cycle, or the deadline has passed;
- a comfort band with a minimum above its maximum is invalid.

Four set-ups are scored with the pilot's own scoring:

- ``alone``: the stored answer as it is (the pilot's numbers);
- ``checker``: when the checker flags an answer the model would commit, the gateway does not commit and asks the household
  (topic "conflict" for infeasible, "ev" for an incomplete EV item); an answer that failed validation also ends in
  a question;
- ``fallback``: when the checker flags an answer or the answer failed, the cloud LLM's stored answer for the same
  plan replaces it and is checked in turn (the fallback share is reported);
- the cloud LLM itself with the checker, for reference.

Checker rules that need what the output schema cannot express (a grid limit, an away period that contradicts a
comfort band) are not implemented, so such conflicts stay undetected; this is reported, not tuned.

    uv run python prototypes/plan_pilot/rescore_checker.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from pilot import HERE, now, parse, score, summarize

CYCLE_H = {"dishwasher": 2.5, "washing_machine": 2.0}
LLM = "gpt-6-luna/function_calling+retry2"


def check(plan: dict, got: dict, household: dict) -> list[tuple[str, str]]:
    """Problems found in one answer, as (topic for the question, reason)."""
    problems = []
    start = parse(now(plan))
    pct_now = float(plan.get("state", {}).get("ev_pct", 30.0))
    capacity, charger = household["car_battery_kwh"], household["charger_kw"]
    for ev in got.get("ev", []):
        departure, earliest = parse(ev.get("departure")), parse(ev.get("earliest"))
        if ev.get("target_pct") is None and ev.get("energy_kwh") is None:
            problems.append(("ev", "EV requirement without a target"))
            continue
        if departure is None or departure <= start:
            problems.append(("conflict", "EV departure missing or already passed"))
            continue
        need = float(ev["energy_kwh"]) if ev.get("energy_kwh") is not None else \
            max(0.0, (float(ev["target_pct"]) - pct_now) / 100 * capacity)
        hours = (departure - max(start, earliest or start)).total_seconds() / 3600
        if need > hours * charger + 1e-9:
            problems.append(("conflict", f"EV needs {need:.1f} kWh, charger gives {hours * charger:.1f} kWh"))
    for app in got.get("appliances", []):
        deadline, earliest = parse(app.get("deadline")), parse(app.get("earliest"))
        if deadline is None or deadline <= start:
            problems.append(("conflict", f"{app.get('appliance')} deadline missing or passed"))
        elif deadline - max(start, earliest or start) < timedelta(hours=CYCLE_H.get(app.get("appliance"), 2.0)):
            problems.append(("conflict", f"{app.get('appliance')} window shorter than its cycle"))
    for band in got.get("comfort", []):
        if band.get("min_c") is not None and band.get("max_c") is not None and band["min_c"] > band["max_c"]:
            problems.append(("conflict", "comfort minimum above maximum"))
    return problems


def gated(plan: dict, got: dict | None, household: dict) -> tuple[dict, bool]:
    """The answer after the checker: (answer, flagged). A failed answer becomes a question to the household. The
    checker gates only what would be committed: an answer that already asks the household is passed on."""
    if got is None:
        return {"questions": [{"topic": "other", "text": "(no valid answer)"}], "commit": False}, True
    problems = check(plan, got, household)
    if not problems or got.get("commit") is False:
        return got, False
    asked = {q.get("topic") for q in got.get("questions", [])}
    extra = [{"topic": t, "text": why} for t, why in problems if t not in asked]
    return {**got, "questions": [*got.get("questions", []), *extra], "commit": False}, True


def main() -> None:
    data = json.loads((HERE / "plans.json").read_text(encoding="utf-8"))
    household, plans = data["household"], {p["id"]: p for p in data["plans"]}
    rows = [json.loads(line) for line in (HERE / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    by_model = defaultdict(dict)
    for row in rows:
        by_model[row["model"]][row["id"]] = row
    llm = by_model[LLM]
    report, details = {}, []
    for model, answers in by_model.items():
        sets = defaultdict(list)
        fallbacks = flagged_n = 0
        for pid, row in answers.items():
            plan, got = plans[pid], row["output"]
            sets["alone"].append(score(plan, got or {}, household))
            after, flagged = gated(plan, got, household)
            flagged_n += flagged
            sets["checker"].append(score(plan, after, household))
            if flagged and model != LLM:
                fallbacks += 1
                after, _ = gated(plan, llm[pid]["output"], household)
            sets["fallback"].append(score(plan, after, household))
            if got is not None and check(plan, got, household):
                details.append(f"{model.split('/')[0]:14s} {pid}: {'; '.join(w for _, w in check(plan, got, household))}"
                               + f" (model {'commits' if got.get('commit') else 'asks'};"
                               + f" key: {plan['key'].get('decision', 'commit')})")
        report[model.split("/")[0]] = {
            name: {k: (round(v, 3) if isinstance(v, float) else v) for k, v in summarize(r).items()
                   if k in ("item_precision", "item_recall", "clarify_f1", "decision_accuracy")}
            for name, r in sets.items()} | {"flagged": flagged_n, "fallback_share": round(fallbacks / len(answers), 3)}
    out = HERE / "out" / "rescore_checker.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    print("\nFlagged answers:\n" + "\n".join(details))


if __name__ == "__main__":
    main()
