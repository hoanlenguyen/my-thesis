"""Plan-interpretation pilot (exploratory, step 3 of the follow-up plan; not part of the thesis evaluation).

Tests the first risk of the reframed follow-up thesis: whether turning a household's plain-language plan into
constraints is hard enough to measure. A language model reads one plan (and, for "change" plans, a later
message) and returns a ``HouseholdPlan``: EV requirements, appliance windows, away periods, comfort bands and
clarifying questions. No tools, one structured call per plan (the extraction step only).

Version 2 (1 Nov 2026): plans bound to dates with the car's charge at the last message, a commit-or-ask decision,
and the answer-key rules of the protocol (section 5). Version 1 results are in ``results_v1.jsonl``.

Scoring against the answer keys in ``plans.json`` (DRAFT keys: the author checks them before any result is used):

- discrete items (EV, appliances, away): an item matches when every field the key gives agrees (times within 15
  min, EV target within 5 percentage points or energy within 1 kWh, converted with the car's arrival charge);
  precision and recall pooled over plans. Items of a topic the key marks for clarification are not counted as
  false positives (a reasonable default plus a question is acceptable). After a change, periods are compared from
  the time of the change (a period already running may start at its original time or at the change);
- comfort: hourly minimum and maximum temperature over 48 h from the plan's day, defaults 20-22 C, narrower bands
  override wider ones; the share of hours where both agree within 0.5 C, for plans whose key has comfort;
- clarification: on ambiguous and conflicting plans, whether a question on an accepted topic was asked; on the
  other plans, whether a question was asked although none was needed (false alarm); clarification F1 over both;
- decision: whether ``commit`` agrees with the key ("commit" or "ask").

The self-test also checks the keys' EV feasibility flags against the charger (energy needed vs hours x kW).

    uv run python prototypes/plan_pilot/pilot.py --models gpt-6-luna gpt-oss-20b
    uv run python prototypes/plan_pilot/pilot.py --self-test     # scores the answer keys against themselves
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from hems.agents.llm import make_model, usage_cost_usd

HERE = Path(__file__).parent
FMT = "%Y-%m-%d %H:%M"
TIME_TOL = timedelta(minutes=15)
PCT_TOL, KWH_TOL, TEMP_TOL = 5.0, 1.0, 0.5


# ── Output schema ────────────────────────────────────────────────────────────
class Ev(BaseModel):
    departure: str = Field(description="When the charge must be done, 'YYYY-MM-DD HH:MM'")
    target_pct: float | None = Field(None, description="Battery charge to reach, %, if the household gave one")
    energy_kwh: float | None = Field(None, description="Energy to add, kWh, if the household gave an amount")
    earliest: str | None = Field(None, description="Do not charge before this time, 'YYYY-MM-DD HH:MM', if stated")


class Appliance(BaseModel):
    appliance: Literal["dishwasher", "washing_machine"]
    earliest: str | None = Field(None, description="May start from, 'YYYY-MM-DD HH:MM', if stated")
    deadline: str = Field(description="Must be finished by, 'YYYY-MM-DD HH:MM'")


class Period(BaseModel):
    start: str = Field(description="'YYYY-MM-DD HH:MM'")
    end: str = Field(description="'YYYY-MM-DD HH:MM'")


class Comfort(BaseModel):
    start: str = Field(description="'YYYY-MM-DD HH:MM'")
    end: str = Field(description="'YYYY-MM-DD HH:MM'")
    min_c: float | None = Field(None, description="Lowest acceptable indoor temperature, C")
    max_c: float | None = Field(None, description="Highest acceptable indoor temperature, C")


class Question(BaseModel):
    topic: Literal["ev", "appliance", "comfort", "away", "conflict", "other"]
    text: str


class HouseholdPlan(BaseModel):
    """The household's requirements as constraints for the home energy gateway."""

    ev: list[Ev] = []
    appliances: list[Appliance] = []
    away: list[Period] = []
    comfort: list[Comfort] = []
    questions: list[Question] = []
    commit: bool = Field(description="true if the plan can be applied as it is; false if a question must be answered first")


def system_prompt(household: dict) -> str:
    return f"""You turn a household's messages into constraints for its home energy gateway.

The home: {household['place']}. The car battery holds {household['car_battery_kwh']} kWh, the charger gives
{household['charger_kw']} kW, and {household['car_arrival']}. Indoor temperature is kept between
{household['default_comfort_c'][0]} and {household['default_comfort_c'][1]} C unless the household asks otherwise; when everyone is away
the gateway lets it drop to {household['away_setback_c']} C.
Appliances: dishwasher ({household['appliances']['dishwasher']}), washing machine ({household['appliances']['washing_machine']}).

Rules:
- Write every time as an absolute date and time 'YYYY-MM-DD HH:MM', resolving "today", "tonight" and "tomorrow"
  from the time each message was sent. "Midnight" at the end of a day is 00:00 of the next day.
- Record only what the household asked for. List comfort bands only where they differ from the default. Record
  an away period as such; add a comfort band for it only if the household names a temperature.
- If a later message changes the plan, return the plan from that moment on: every requirement still in force,
  including those from the first message that the change does not affect, but not requirements already over.
- Ask a question only when information the gateway needs is missing (for example how much charge, or when) or
  when the request cannot be met as stated; use topic "conflict" for a request that is impossible. Do not invent
  missing numbers.
- Set commit to false when you ask a question that must be answered before the plan is applied, otherwise true.
  Even when you ask, list every requirement that is already clear."""


def now(plan: dict) -> str:
    """Time of the last message: the plan is in force from here on."""
    return plan["change"]["sent"] if plan.get("change") else plan["sent"]


def user_message(plan: dict) -> str:
    text = f"Message sent {plan['sent']}:\n{plan['text']}"
    if plan.get("change"):
        text += f"\n\nLater message sent {plan['change']['sent']}:\n{plan['change']['text']}"
    if plan.get("state"):
        text += f"\n\nGateway status at {now(plan)}: car plugged in at {plan['state']['ev_pct']} % charge."
    return text


# ── Scoring ──────────────────────────────────────────────────────────────────
def parse(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value.strip()[:16], FMT)
    except ValueError:
        return None


def close(key: str | None, got: str | None) -> bool:
    if key is None:
        return True
    a, b = parse(key), parse(got)
    return a is not None and b is not None and abs(a - b) <= TIME_TOL


def ev_match(key: dict, got: dict, household: dict, plan: dict) -> bool:
    if not close(key["departure"], got.get("departure")) or not close(key.get("earliest"), got.get("earliest")):
        return False
    capacity = household["car_battery_kwh"]
    arrival_pct = float(plan.get("state", {}).get("ev_pct", 30.0))

    def pct(item: dict) -> float | None:
        if item.get("target_pct") is not None:
            return float(item["target_pct"])
        if item.get("energy_kwh") is not None:
            return arrival_pct + float(item["energy_kwh"]) / capacity * 100
        return None

    if key.get("target_pct") is not None:
        return pct(got) is not None and abs(pct(got) - key["target_pct"]) <= PCT_TOL
    if key.get("energy_kwh") is not None:
        if got.get("energy_kwh") is not None:
            return abs(float(got["energy_kwh"]) - key["energy_kwh"]) <= KWH_TOL
        return pct(got) is not None and abs(pct(got) - pct(key)) <= KWH_TOL / capacity * 100
    return True


def appliance_match(key: dict, got: dict, _household: dict, _plan: dict) -> bool:
    return (key["appliance"] == got.get("appliance") and close(key["deadline"], got.get("deadline"))
            and close(key.get("earliest"), got.get("earliest")))  # fmt: skip


def period_match(key: dict, got: dict, _household: dict, plan: dict) -> bool:
    start = parse(now(plan))

    def clipped(value: str | None) -> str | None:  # a running period counts from the last message on
        t = parse(value)
        return value if t is None or t >= start else start.strftime(FMT)

    return close(clipped(key["start"]), clipped(got.get("start"))) and close(key["end"], got.get("end"))


MATCHERS = {"ev": ev_match, "appliances": appliance_match, "away": period_match}
TOPIC = {"ev": "ev", "appliances": "appliance", "away": "away"}


def match_items(keys: list[dict], got: list[dict], match, household: dict, plan: dict) -> tuple[int, list[int]]:
    """Greedy one-to-one matching; returns true positives and the indices of unmatched predictions."""
    free = list(range(len(got)))
    hits = 0
    for key in keys:
        for i in free:
            if match(key, got[i], household, plan):
                hits += 1
                free.remove(i)
                break
    return hits, free


def comfort_profile(items: list[dict], day0: datetime, default: tuple[float, float]) -> list[tuple[float, float]]:
    hours = [day0 + timedelta(hours=h) for h in range(48)]
    profile = [list(default) for _ in hours]
    spans = []
    for item in items:
        start, end = parse(item.get("start")), parse(item.get("end"))
        if start is not None and end is not None and end > start:
            spans.append((end - start, start, end, item))
    for _, start, end, item in sorted(spans, key=lambda s: s[0], reverse=True):  # narrower bands override wider
        for h, t in enumerate(hours):
            if start <= t < end:
                if item.get("min_c") is not None:
                    profile[h][0] = float(item["min_c"])
                if item.get("max_c") is not None:
                    profile[h][1] = float(item["max_c"])
    return [tuple(p) for p in profile]


def score(plan: dict, got: dict, household: dict) -> dict:
    key = plan["key"]
    clarify = set(key.get("clarify", []))
    out: dict = {"id": plan["id"], "kind": plan["kind"]}
    tp = fp = fn = 0
    for field, match in MATCHERS.items():
        hits, unmatched = match_items(key.get(field, []), got.get(field, []), match, household, plan)
        tp += hits
        fn += len(key.get(field, [])) - hits
        if TOPIC[field] not in clarify:
            fp += len(unmatched)
    out.update(tp=tp, fp=fp, fn=fn)
    if key.get("comfort"):
        day0 = parse(plan["sent"]).replace(hour=0, minute=0)
        default = tuple(household["default_comfort_c"])
        want = comfort_profile(key["comfort"], day0, default)
        have = comfort_profile(got.get("comfort", []), day0, default)
        agree = sum(abs(a[0] - b[0]) <= TEMP_TOL and abs(a[1] - b[1]) <= TEMP_TOL for a, b in zip(want, have))
        out["comfort_agree"] = agree / len(want)
    topics = {q.get("topic") for q in got.get("questions", [])}
    if clarify:
        out["clarify_hit"] = bool(topics & clarify)
    else:
        out["false_question"] = bool(topics)
    if "decision" in key:
        out["decision_ok"] = got.get("commit") is (key["decision"] == "commit")
    return out


def summarize(rows: list[dict]) -> dict:
    tp, fp, fn = (sum(r[k] for r in rows) for k in ("tp", "fp", "fn"))
    comfort = [r["comfort_agree"] for r in rows if "comfort_agree" in r]
    needed = [r for r in rows if "clarify_hit" in r]
    unneeded = [r for r in rows if "false_question" in r]
    decided = [r for r in rows if "decision_ok" in r]
    hit = sum(r["clarify_hit"] for r in needed)
    missed, false = len(needed) - hit, sum(r["false_question"] for r in unneeded)
    return {
        "plans": len(rows),
        "item_precision": tp / (tp + fp) if tp + fp else None,
        "item_recall": tp / (tp + fn) if tp + fn else None,
        "comfort_hours_agree": sum(comfort) / len(comfort) if comfort else None,
        "clarify_recall": sum(r["clarify_hit"] for r in needed) / len(needed) if needed else None,
        "false_questions": false / len(unneeded) if unneeded else None,
        "clarify_f1": 2 * hit / (2 * hit + false + missed) if hit + false + missed else None,
        "decision_accuracy": sum(r["decision_ok"] for r in decided) / len(decided) if decided else None,
    }


def check_feasibility(plans: list[dict], household: dict) -> list[str]:
    """Keys whose EV feasibility flag disagrees with the charger (energy needed vs hours to departure x kW); keys
    marked infeasible for another reason (``infeasible_because``) are listed for information."""
    notes = []
    for plan in plans:
        pct = float(plan.get("state", {}).get("ev_pct", 30.0))
        for ev in plan["key"].get("ev", []):
            if ev.get("target_pct") is None and ev.get("energy_kwh") is None:
                continue
            need = ev["energy_kwh"] if ev.get("energy_kwh") is not None else \
                (ev["target_pct"] - pct) / 100 * household["car_battery_kwh"]
            hours = (parse(ev["departure"]) - parse(ev.get("earliest") or now(plan))).total_seconds() / 3600
            possible = hours * household["charger_kw"]
            line = f"{plan['id']}: need {need:.1f} kWh, charger gives {possible:.1f} kWh in {hours:.1f} h"
            if ev.get("infeasible_because"):
                notes.append(f"{line}; infeasible because {ev['infeasible_because']}")
            elif ev.get("feasible", True) != (need <= possible):
                notes.append(f"{line}; MISMATCH with feasible={ev.get('feasible', True)}")
    return notes


# ── Running ──────────────────────────────────────────────────────────────────
def retry_message(raw: object, problem: str) -> HumanMessage:
    """Feedback after an invalid answer: what the model sent and why it was rejected."""
    calls = getattr(raw, "tool_calls", None) or []
    sent = json.dumps(calls[0].get("args"), ensure_ascii=False) if calls else str(getattr(raw, "content", ""))[:1500]
    return HumanMessage(
        f"Your last answer could not be used:\n{problem[:1200]}\n\nWhat you sent:\n{sent[:1500]}\n\n"
        "Answer again with the complete plan. Every EV item needs 'departure', every appliance item needs "
        "'appliance' (dishwasher or washing_machine) and 'deadline', every question needs 'topic' (one of ev, "
        "appliance, comfort, away, conflict, other) and 'text', and 'commit' is true or false. Times as "
        "'YYYY-MM-DD HH:MM'."
    )


def extract(model_name: str, plan: dict, household: dict, method: str | None = None,
            retries: int = 0) -> tuple[dict | None, dict]:  # fmt: skip
    """``method``: LangChain structured-output method (None = the provider's default; "function_calling" = a tool
    call, as the thesis harness uses; with Ollama's default JSON-schema mode gpt-oss-20b returned empty plans).
    ``retries``: how often an answer that fails validation is sent back with the errors (as the thesis harness's
    recovery nudge; 0 = one attempt)."""
    kwargs = {"method": method} if method else {}
    model = make_model(model_name).with_structured_output(HouseholdPlan, include_raw=True, **kwargs)
    messages = [SystemMessage(system_prompt(household)), HumanMessage(user_message(plan))]
    started = time.perf_counter()
    result, errors, attempts = None, [], 0
    with get_usage_metadata_callback() as usage:
        for attempts in range(1, retries + 2):
            try:
                out = model.invoke(messages)
            except Exception as exc:  # provider failure (e.g. Ollama's HTTP 500 on a malformed call)
                problem, raw = f"{type(exc).__name__}: {exc}", None
            else:
                if out.get("parsed") is not None:
                    result = out["parsed"]
                    break
                raw = out.get("raw")
                if raw is not None and raw.response_metadata.get("done_reason") == "length":
                    errors.append("output cap reached (ollama_num_predict)")  # a failed answer, not retried
                    break
                if out.get("parsing_error") is not None:
                    problem = f"{type(out['parsing_error']).__name__}: {out['parsing_error']}"
                else:  # answered in prose without calling the tool (gpt-oss-20b after a first rejection)
                    problem = "You answered in text without calling the HouseholdPlan tool. Call the tool."
            errors.append(problem[:200])
            messages = [*messages, retry_message(raw, problem)]
    tokens_in, tokens_out, usd = usage_cost_usd(usage.usage_metadata, model_name)
    meta = {"latency_s": round(time.perf_counter() - started, 2), "tokens_in": tokens_in, "tokens_out": tokens_out,
            "usd": usd, "attempts": attempts, "error": None if result is not None else (errors[-1] if errors else None),
            "retried_errors": errors if result is not None else errors[:-1]}  # fmt: skip
    return (result.model_dump() if result is not None else None), meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="*", default=["gpt-6-luna"])
    parser.add_argument("--plans", type=Path, default=HERE / "plans.json")
    parser.add_argument("--out", type=Path, default=HERE / "results.jsonl")
    parser.add_argument("--method", choices=["function_calling", "json_schema", "json_mode"], default=None,
                        help="structured-output method; recorded as model/method")  # fmt: skip
    parser.add_argument("--retries", type=int, default=0, help="resend invalid answers with the errors (label +retryN)")
    parser.add_argument("--self-test", action="store_true", help="score the answer keys against themselves")
    args = parser.parse_args()
    data = json.loads(args.plans.read_text(encoding="utf-8"))
    household, plans = data["household"], data["plans"]

    if args.self_test:
        rows = []
        for plan in plans:
            perfect = {k: v for k, v in plan["key"].items() if k not in ("clarify", "decision")}
            perfect["questions"] = [{"topic": t, "text": "?"} for t in plan["key"].get("clarify", [])[:1]]
            perfect["commit"] = plan["key"].get("decision", "commit") == "commit"
            rows.append(score(plan, perfect, household))
        print(json.dumps(summarize(rows), indent=1))
        print("\n".join(check_feasibility(plans, household)) or "EV feasibility flags agree with the charger")
        return

    load_dotenv()
    done = set()
    if args.out.exists():
        done = {(r["model"], r["id"]) for r in map(json.loads, args.out.read_text(encoding="utf-8").splitlines())}
    with args.out.open("a", encoding="utf-8") as out:
        for base_model in args.models:
            model_name = (f"{base_model}/{args.method}" if args.method else base_model) + \
                (f"+retry{args.retries}" if args.retries else "")
            for plan in plans:
                if (model_name, plan["id"]) in done:
                    continue
                got, meta = extract(base_model, plan, household, args.method, args.retries)
                row = {"model": model_name, **score(plan, got or {}, household), **meta, "output": got}
                out.write(json.dumps(row) + "\n")
                out.flush()
                print(f"{model_name:12s} {plan['id']}: tp {row['tp']} fp {row['fp']} fn {row['fn']}"
                      + (f" comfort {row['comfort_agree']:.2f}" if "comfort_agree" in row else "")
                      + (f" clarify {row['clarify_hit']}" if "clarify_hit" in row else "")
                      + (f" false_q {row['false_question']}" if "false_question" in row else "")
                      + (f" ERROR {meta['error']}" if meta["error"] else ""))  # fmt: skip
    rows = [json.loads(line) for line in args.out.read_text(encoding="utf-8").splitlines()]
    for model_name in sorted({r["model"] for r in rows}):
        mine = [r for r in rows if r["model"] == model_name]
        by_kind = {kind: summarize([r for r in mine if r["kind"] == kind]) for kind in sorted({r["kind"] for r in mine})}
        print(f"\n{model_name}: {json.dumps(summarize(mine))}")
        for kind, s in by_kind.items():
            print(f"  {kind:9s} {json.dumps(s)}")
        print(f"  cost USD {sum(r['usd'] for r in mine):.4f}, mean latency {sum(r['latency_s'] for r in mine) / len(mine):.1f} s,"
              f" errors {sum(bool(r['error']) for r in mine)}")  # fmt: skip


if __name__ == "__main__":
    main()
