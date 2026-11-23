"""Collect the writers' returned sheets into the held-out plan file to be keyed (draft, 21 Nov 2026).

Reads ``writer_sheets/returned/W*.md`` (the sheets as the writers send them back), takes the text after each
``Message:`` and ``Second message:`` (the lines starting with ``>``), and writes ``plans_heldout.json`` in the format
of ``plan_pilot/plans.json``: the pilot household, and per card the id, plan type, send time, the car's charge at the
last message, the message(s) and an empty ``key`` for the author. Cards are never overwritten once keyed: an
existing ``plans_heldout.json`` keeps its keys and only missing messages are filled in.

    uv run python prototypes/heldout/collect.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent


def read_sheet(path: Path) -> dict[str, dict[str, str]]:
    """{card id: {"text": first message, "change": second message}} from one returned sheet."""
    out: dict[str, dict[str, str]] = {}
    current, field = None, None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## (H\d{3})\s*$", line)
        if m:
            current, field = m.group(1), None
            out[current] = {}
        elif current and line.strip() == "Message:":
            field = "text"
        elif current and line.strip() == "Second message:":
            field = "change"
        elif current and field and line.startswith(">"):
            text = line[1:].strip()
            if text:
                out[current][field] = (out[current].get(field, "") + " " + text).strip()
        elif current and field and line.strip() and not line.startswith(">"):
            field = None
    return out


def main() -> None:
    cards = {c["id"]: c for c in json.loads((HERE / "scenarios.json").read_text(encoding="utf-8"))["cards"]}
    pilot = json.loads((ROOT / "plan_pilot" / "plans.json").read_text(encoding="utf-8"))
    target = HERE / "plans_heldout.json"
    if target.exists():
        data = json.loads(target.read_text(encoding="utf-8"))
    else:
        data = {"status": "DRAFT: held-out plans, messages by writers W1-W4, keys by the author, checked by a second "
                          "person; registered before any run.",
                "household": pilot["household"], "plans": []}  # fmt: skip
    plans = {p["id"]: p for p in data["plans"]}
    texts: dict[str, dict[str, str]] = {}
    for sheet in sorted((HERE / "writer_sheets" / "returned").glob("W*.md")):
        texts.update(read_sheet(sheet))
    for cid, card in cards.items():
        plan = plans.setdefault(cid, {"id": cid, "kind": card["kind"], "writer": card["writer"], "sent": card["sent"],
                                      "state": {"ev_pct": card["car_pct"]}, "text": "", "key": {}})  # fmt: skip
        if card.get("change"):
            plan.setdefault("change", {"sent": card["change"]["sent"], "text": ""})
            plan["state"] = {"ev_pct": card["change"]["car_pct"]}
        got = texts.get(cid, {})
        if not plan["text"] and got.get("text"):
            plan["text"] = got["text"]
        if plan.get("change") is not None and not plan["change"]["text"] and got.get("change"):
            plan["change"]["text"] = got["change"]
    data["plans"] = [plans[cid] for cid in cards]
    target.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    written = sum(bool(p["text"]) for p in data["plans"])
    changes = [p for p in data["plans"] if "change" in p]
    keyed = sum(bool(p["key"]) for p in data["plans"])
    print(f"{target}: {written}/{len(cards)} messages, {sum(bool(p['change']['text']) for p in changes)}/"
          f"{len(changes)} second messages, {keyed} keyed")


if __name__ == "__main__":
    main()
