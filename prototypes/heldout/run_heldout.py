"""Runner of the registered evaluation (SQ1): every model in every set-up, three runs per plan (draft, 22 Nov 2026).

Set-ups (thesis Section 3.5, ``config_heldout.json``):

- ``slm_no_checks``: a small model whose planning tool plans without the checks and the rules in code
  (``Gateway(checks=False)``); the gateway applies whatever the model commits;
- ``slm_checks``: a small model with the checks and the rules in code (the design);
- ``slm_checks_fallback``: ``slm_checks`` with the model layer's cloud fallback: when the small model's answer failed
  validation (``run_react`` has already retried) or the gateway refused a plan the model committed, the cloud model
  answers the same plan in the same agent, and its answer passes the same checks. One small-model run gives both the
  ``slm_checks`` row and the ``slm_checks_fallback`` row (written together), so the two differ only by the fallback;
- ``llm``: the cloud model in the same agent with the checks.

Committed plans whose key says commit are executed in closed loop on the real day and judged against the key
(``closed_loop.run`` / ``judge``), with EMHASS as the optimiser (``--emhass``; the registered evaluation) or the
thesis MPC (``--optimiser pulp``, for tests only). The optimiser is deterministic, so a closed-loop day is cached by
plan, optimiser and constraints (``<out>.loopcache.jsonl``): identical requirements are executed once.

Resumes where it stopped. A call that fails for a reason outside the model (network, DNS, Ollama or EMHASS down) is
not recorded; the unit is retried on the next start. Provider rejections of the model's output are failed answers
and are recorded, as in the pilots.

    uv run python prototypes/heldout/run_heldout.py --plans prototypes/plan_pilot/plans_dev.json \
        --models gemma4-e4b --runs 1 --emhass http://localhost:5001 --out prototypes/heldout/out/dev_test.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import traceback
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT / "emhass_gateway"), str(ROOT / "react_gateway")]
import agent  # noqa: E402
import closed_loop  # noqa: E402  (on the path through agent)
import emhass_gateway  # noqa: E402
from agent import Gateway, Home, World, constraints, forecasts_for, judge, load_days, now, parse, run_plan, score  # noqa: E402

SETUPS = ("slm_no_checks", "slm_checks", "slm_checks_fallback", "llm")
SMALL_MODELS = ("gemma4-e4b", "gemma4-e2b", "ministral-3-8b", "ministral-3-3b", "nemotron3-nano-4b")
CLOUD = "gpt-6-luna"


def fallback_needed(meta: dict) -> bool:
    """The model layer's trigger (thesis Section 4.2): a failed answer, or a committed plan the gateway refused."""
    return bool(meta.get("failed_answer") or meta.get("checker_rejected"))


def emhass_replan(f: dict, k: int, st, c, w: World, home: Home, url: str, log: list, last: dict) -> dict:
    """``closed_loop.mpc`` for a replan at horizon slot ``k``, solved by EMHASS.

    ``emhass_gateway.emhass_mpc`` plans from the time of the message (k = 0, the planning tool). In the closed loop it
    gets constraints shifted to slot k: the comfort band from k on, car and appliance windows relative to k, and the
    remaining profile of appliances already running added to the base load (as ``closed_loop.mpc`` does). An
    appliance whose window has passed or no longer fits its cycle is left out; ``closed_loop.run`` starts it when due.
    EMHASS needs a horizon of at least five steps, so in the last hour the gateway keeps its last plan (``last``).
    """
    H = w.horizon
    if H - k < 5 and "plan" in last:
        return last["plan"]
    fixed = f["fixed"].copy()
    keep = []  # (index in c.appliances, shifted window)
    for n, (name, a, b) in enumerate(c.appliances):
        prof = closed_loop.APPLIANCE[name]
        if n in st.started:
            s = st.started[n]
            for t in range(max(k, s), min(H, s + len(prof))):
                fixed[t] += float(prof[t - s])
        elif b - max(a, k) >= len(prof):
            keep.append((n, (name, max(a - k, 0), b - k)))
    shifted = closed_loop.Constraints(c.low[k:], c.high[k:],
                                      [(max(a - k, 0), max(b - k, 0), need) for a, b, need in c.ev],
                                      [x for _, x in keep])  # fmt: skip
    p = emhass_gateway.emhass_mpc({**f, "fixed": fixed}, k, st, shifted, w, home, url, log)
    p["starts"] = {keep[j][0]: s for j, s in p["starts"].items()}  # back to the indices of c.appliances
    last["plan"] = p
    return p


class Loop:
    """Closed-loop execution with a cache: (plan, optimiser, constraints) -> judged result."""

    def __init__(self, path: Path, emhass_url: str | None) -> None:
        self.path, self.url = path, emhass_url
        self.name = "emhass" if emhass_url else "pulp"
        self.cache: dict[str, dict] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                self.cache[row["cache_key"]] = row["result"]

    def run(self, w: World, home: Home, c, ev_avail: tuple[int, int], solves: list) -> dict:
        if self.url is None:
            return closed_loop.run(w, home, c, ev_avail)
        original = closed_loop.mpc  # closed_loop.run replans through its module-level mpc
        last: dict = {}
        closed_loop.mpc = lambda f, k, st, cc, ww, hh: emhass_replan(f, k, st, cc, ww, hh, self.url, solves, last)
        try:
            return closed_loop.run(w, home, c, ev_avail)
        finally:
            closed_loop.mpc = original

    def judged(self, plan: dict, got: dict, w: World, home: Home, household: dict) -> dict:
        t0 = w.t0
        key = constraints(plan, plan["key"], t0, w.horizon, home, household["car_battery_kwh"])
        c = constraints(plan, got, t0, w.horizon, home, household["car_battery_kwh"])
        ev_avail = (0, max([b for _, b, _ in key.ev], default=w.horizon))

        def digest(x) -> str:
            return hashlib.sha1(json.dumps([x.low.round(3).tolist(), x.high.round(3).tolist(), x.ev, x.appliances],
                                           default=str).encode()).hexdigest()[:16]  # fmt: skip

        key_id = f"{plan['id']}|{self.name}|key|{digest(key)}"
        sys_id = f"{plan['id']}|{self.name}|{digest(key)}|{digest(c)}"
        if key_id not in self.cache:
            solves: list = []
            try:
                ref = self.run(w, home, key, ev_avail, solves)
                result = judge(w, home, key, ref, ref["starts"], [a[0] for a in key.appliances]) | {"solves": len(solves)}
            except RuntimeError as exc:  # EMHASS found no optimal plan for the key: no reference cost
                result = {"met": False, "error": str(exc)[:200], "solves": len(solves)}
            self.store(key_id, result)
        if sys_id not in self.cache and digest(c) == digest(key):  # the key's own requirements: the same day
            self.store(sys_id, self.cache[key_id])
        if sys_id not in self.cache:
            solves = []
            try:
                r = self.run(w, home, c, ev_avail, solves)
                result = judge(w, home, key, r, r["starts"], [a[0] for a in c.appliances]) | {"solves": len(solves)}
            except RuntimeError as exc:  # EMHASS found no optimal plan for these constraints: nothing executed
                result = {"met": False, "error": str(exc)[:200], "solves": len(solves)}
            self.store(sys_id, result)
        return {**self.cache[sys_id], "key_cost_eur": self.cache[key_id].get("adjusted_cost_eur"), "optimiser": self.name}

    def store(self, cache_key: str, result: dict) -> None:
        self.cache[cache_key] = result
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"cache_key": cache_key, "result": result}) + "\n")


def answer(model: str, plan: dict, data: dict, w: World, home: Home, appliances: dict, emhass_url: str | None,
           checks: bool) -> tuple[dict, dict]:  # fmt: skip
    """One run of the Household Assistant on one plan; the planning tool uses EMHASS when a URL is given."""
    if emhass_url:
        gw = emhass_gateway.EmhassGateway(plan, data["household"], w, home, appliances, checks=checks, url=emhass_url)
    else:
        gw = Gateway(plan, data["household"], w, home, appliances, checks=checks)
    got, meta = run_plan(model, gw)
    meta.pop("app", None)
    if emhass_url:
        meta["emhass_solves"] = gw.solves
    return got, meta


def row_for(setup: str, model: str, run: int, plan: dict, data: dict, got: dict, meta: dict, plans_file: str,
            optimiser: str) -> dict:  # fmt: skip
    return {"setup": setup, "model": model, "run": run, "id": plan["id"], "kind": plan.get("kind"),
            "plans_file": plans_file, "optimiser": optimiser, **score(plan, got, data["household"]), **meta,
            "output": got}  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("D:/Study/my-thesis/data/raw"))
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--ids", nargs="*", help="only these plans")
    parser.add_argument("--models", nargs="+", default=list(SMALL_MODELS), help="small models")
    parser.add_argument("--cloud", default=CLOUD)
    parser.add_argument("--setups", nargs="+", default=list(SETUPS), choices=SETUPS)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--emhass", default=None, help="EMHASS URL (registered evaluation); without it: thesis MPC")
    parser.add_argument("--no-loop", action="store_true", help="skip the closed loop")
    parser.add_argument("--num-thread", type=int, default=None, help="Ollama threads (see emhass_gateway.py)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    load_dotenv()
    if args.num_thread:
        make_model = agent.make_model

        def make_with_threads(*a, **k):
            model = make_model(*a, **k)
            model.num_thread = args.num_thread
            return model

        agent.make_model = make_with_threads
    optimiser = "emhass" if args.emhass else "pulp"
    if args.emhass:
        version = emhass_gateway.call(f"{args.emhass}/api/v1/last-run").get("emhass_version", "?")
        print(f"EMHASS {version} at {args.emhass}")
    home = Home()
    all_days = load_days(args.raw_dir, 2016, "de", "feedin")
    fcs = forecasts_for(all_days, "weather")
    days = {d.date: d for d in all_days}
    data = json.loads(args.plans.read_text(encoding="utf-8"))
    appliances = json.loads((ROOT / "react_gateway" / "appliances.json").read_text(encoding="utf-8"))
    plans = [p for p in data["plans"] if (not args.ids or p["id"] in args.ids) and p.get("text")]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if args.out.exists():
        done = {(r["setup"], r["model"], r["run"], r["id"], r["plans_file"])
                for r in map(json.loads, args.out.read_text(encoding="utf-8").splitlines())}  # fmt: skip
    loop = None if args.no_loop else Loop(args.out.with_suffix(".loopcache.jsonl"), args.emhass)
    units = []  # (run, model, setups answered by one model run)
    for run in range(1, args.runs + 1):
        for model in args.models:
            if "slm_no_checks" in args.setups:
                units.append((run, model, ("slm_no_checks",)))
            paired = tuple(s for s in ("slm_checks", "slm_checks_fallback") if s in args.setups)
            if paired:
                units.append((run, model, paired))
        if "llm" in args.setups:
            units.append((run, args.cloud, ("llm",)))
    skipped = 0
    with args.out.open("a", encoding="utf-8") as out:
        for run, model, setups in units:
            for plan in plans:
                todo = [s for s in setups if (s, model, run, plan["id"], args.plans.name) not in done]
                if not todo:
                    continue
                t0 = parse(now(plan))
                d0, d1 = t0.date().isoformat(), (t0.date() + timedelta(days=1)).isoformat()
                w = World(t0, t0.hour * 4 + t0.minute // 15, (days[d0], days[d1]), (fcs[d0], fcs[d1]))
                try:
                    started = time.time()
                    got, meta = answer(model, plan, data, w, home, appliances, args.emhass,
                                       checks=setups != ("slm_no_checks",))  # fmt: skip
                    rows = {}
                    for s in setups:
                        rows[s] = row_for(s, model, run, plan, data, got, dict(meta), args.plans.name, optimiser)
                    if "slm_checks_fallback" in setups:
                        fb = rows["slm_checks_fallback"]
                        fb["fallback"] = fallback_needed(meta)
                        if fb["fallback"]:
                            got2, meta2 = answer(args.cloud, plan, data, w, home, appliances, args.emhass, checks=True)
                            fb.update(score(plan, got2, data["household"]))
                            fb["output"] = got2
                            fb["fallback_model"] = args.cloud
                            fb["fallback_meta"] = meta2
                            fb["latency_s"] = round(meta["latency_s"] + meta2["latency_s"], 2)
                            fb["usd"] = (meta.get("usd") or 0.0) + (meta2.get("usd") or 0.0)
                    if loop is not None:
                        for s, row in rows.items():
                            if row["output"].get("commit") and plan["key"].get("decision") == "commit":
                                row["loop"] = loop.judged(plan, row["output"], w, home, data["household"])
                    for s in todo:
                        rows[s]["started_at"], rows[s]["ended_at"] = round(started, 2), round(time.time(), 2)
                    out.write("".join(json.dumps(rows[s], default=str) + "\n" for s in todo))
                    out.flush()
                    status = " ".join(f"{s}:{'commit' if rows[s]['output'].get('commit') else 'ask'}"
                                      + (f"/{'met' if rows[s]['loop']['met'] else 'MISSED'}" if "loop" in rows[s] else "")
                                      + ("+fallback" if rows[s].get("fallback") else "") for s in todo)  # fmt: skip
                    print(f"run {run} {model:18s} {plan['id']}: key {plan['key'].get('decision', 'commit'):6s} {status} "
                          f"{meta['latency_s']:.1f} s" + (f" ERROR {meta['error']}" if meta.get("error") else ""),
                          flush=True)  # fmt: skip
                except KeyboardInterrupt:
                    raise
                except Exception as exc:  # outside the model: not recorded, retried on the next start
                    skipped += 1
                    print(f"run {run} {model} {plan['id']}: NOT RECORDED ({type(exc).__name__}: {str(exc)[:160]})",
                          file=sys.stderr, flush=True)  # fmt: skip
                    traceback.print_exc(limit=2, file=sys.stderr)
    print(f"done; {skipped} unit(s) not recorded" if skipped else "done")
    if skipped:
        sys.exit(1)


if __name__ == "__main__":
    main()
