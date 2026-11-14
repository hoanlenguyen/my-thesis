"""Summary of the ReAct gateway results (``out/results.jsonl``), rescored against the current answer keys.

The stored answers are scored again with ``plan_pilot.score``, so a key changed after a run (DA2 on 13 Nov 2026)
counts as it is now; the real-day check ("loop") is only available for plans whose key said commit at run time.

    uv run python prototypes/react_gateway/summary.py --plans prototypes/plan_pilot/plans_dev.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "plan_pilot"))
from pilot import score, summarize  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--results", type=Path, default=HERE / "out" / "results.jsonl")
    args = parser.parse_args()
    data = json.loads(args.plans.read_text(encoding="utf-8"))
    plans = {p["id"]: p for p in data["plans"]}
    rows = [r for r in map(json.loads, args.results.read_text(encoding="utf-8").splitlines())
            if r["plans_file"] == args.plans.name]  # fmt: skip
    for r in rows:  # rescore against the current keys
        r.update(score(plans[r["id"]], r["output"], data["household"]))
    models = list(dict.fromkeys(r["model"] for r in rows))
    by = {(r["model"], r["id"]): r for r in rows}
    print(f"{'model':16s} plans decisions precision recall  s/plan  calls  met on real day  failed")
    for m in models:
        mine = [r for r in rows if r["model"] == m]
        s = summarize(mine)
        loop = [r["loop"]["met"] for r in mine if "loop" in r]
        print(f"{m:16s} {len(mine):5d} {sum(r['decision_ok'] for r in mine):4d}/{len(mine):<4d} "
              f"{s['item_precision'] or 0:9.2f} {s['item_recall'] or 0:6.2f} {np.mean([r['latency_s'] for r in mine]):7.1f} "
              f"{np.mean([r['tool_calls'] for r in mine]):6.1f}  {sum(loop):4d}/{len(loop):<4d}       "
              f"{sum(bool(r['error']) for r in mine):4d}")  # fmt: skip
    print("\nplan  key     | " + " | ".join(models))
    for pid, plan in plans.items():
        cells = []
        for m in models:
            r = by.get((m, pid))
            if r is None:
                cells.append("-")
                continue
            c = ("ok " if r["decision_ok"] else "XX ") + ("commit" if r["output"]["commit"] else "ask")
            if "loop" in r:
                c += " met" if r["loop"]["met"] else " MISS"
            if r["fp"] or r["fn"]:
                c += f" +{r['fp']}-{r['fn']}"
            cells.append(c)
        print(f"{pid:5s} {plan['key']['decision']:7s} | " + " | ".join(cells))


if __name__ == "__main__":
    main()
