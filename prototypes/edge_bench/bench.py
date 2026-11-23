"""Edge benchmark (SQ4 of the follow-up thesis): how fast a gateway-class device runs the gateway's language model.

Sends the 22 plans of the plan pilot to an Ollama server, one at a time, exactly as the pilot does (structured
``HouseholdPlan`` through function calling, up to two validation retries), and records Ollama's own timings for
every call: model load, prompt reading (prefill) and writing (generation), in tokens per second, plus the wall-clock
time per plan. The plans are also scored, so a device run can be checked against the laptop run.

The script runs on the laptop; the model runs where ``--host`` points:

- Raspberry Pi 5 (16 GB) or the Ryzen mini PC: install Ollama on the device, ``ollama pull gemma4:e4b``, start it
  listening on the network (``OLLAMA_HOST=0.0.0.0 ollama serve``) and pass ``--host http://<device>:11434``;
- laptop GPU (reference): ``--host http://localhost:11434``;
- laptop CPU only, four threads (a rough stand-in until the devices arrive): add ``--cpu-only --threads 4``.

Read the device's power meter at idle and during the run and pass the readings with ``--idle-w`` / ``--load-w``;
energy per plan is then load power x time per plan. The device's optimiser time is measured separately by
``mpc_time.py`` on the device itself.

    uv run python prototypes/edge_bench/bench.py --device pi5-16gb --host http://pi5.local:11434 --model gemma4-e4b
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

sys.path.insert(0, str(Path(__file__).parents[1] / "plan_pilot"))
from pilot import HERE as PILOT_DIR, RETRIES, HouseholdPlan, plan_num_ctx, retry_message, score, summarize, system_prompt  # noqa: E402
from pilot import user_message  # noqa: E402

from hems.agents.llm import MODELS, OLLAMA_NUM_CTX  # noqa: E402

HERE = Path(__file__).parent
NS = 1e9


def model_for(name: str, host: str, cpu_only: bool, threads: int | None, num_ctx: int) -> ChatOllama:
    spec = MODELS[name]
    if spec.provider != "ollama":
        raise SystemExit(f"{name} is not an Ollama model")
    return ChatOllama(model=spec.model_id, base_url=host, temperature=0.0, num_ctx=num_ctx,
                      reasoning=spec.ollama_think, num_predict=spec.ollama_num_predict,
                      num_gpu=0 if cpu_only else spec.ollama_num_gpu, num_thread=threads, keep_alive="30m")  # fmt: skip


def run_plan(model: ChatOllama, plan: dict, household: dict, retries: int) -> tuple[dict | None, list[dict], float]:
    """One plan as the pilot runs it; returns the answer, Ollama's timings per call and the wall-clock seconds."""
    structured = model.with_structured_output(HouseholdPlan, include_raw=True, method="function_calling")
    messages = [SystemMessage(system_prompt(household)), HumanMessage(user_message(plan))]
    calls, result = [], None
    started = time.perf_counter()
    for _ in range(retries + 1):
        try:
            out = structured.invoke(messages)
        except Exception as exc:  # Ollama's HTTP 500 on a malformed call
            calls.append({"error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            messages = [*messages, retry_message(None, str(exc)[:200])]
            continue
        raw = out.get("raw")
        meta = getattr(raw, "response_metadata", {}) or {}
        calls.append({k: meta.get(k) for k in ("load_duration", "prompt_eval_count", "prompt_eval_duration",
                                               "eval_count", "eval_duration", "total_duration", "done_reason")})  # fmt: skip
        if out.get("parsed") is not None:
            result = out["parsed"].model_dump()
            break
        if meta.get("done_reason") == "length":
            break
        problem = str(out.get("parsing_error") or "You answered in text without calling the HouseholdPlan tool.")
        messages = [*messages, retry_message(raw, problem[:200])]
    return result, calls, time.perf_counter() - started


def rate(tokens: list[int], durations: list[int]) -> float | None:
    seconds = sum(d for d in durations if d) / NS
    return round(sum(t for t in tokens if t) / seconds, 2) if seconds > 0 else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device", required=True, help="label, e.g. pi5-16gb, ryzen-minipc, laptop-gpu")
    parser.add_argument("--host", default="http://localhost:11434")
    parser.add_argument("--model", default="gemma4-e4b")
    parser.add_argument("--cpu-only", action="store_true")
    parser.add_argument("--threads", type=int)
    parser.add_argument("--num-ctx", type=int, help="default: the plan pilot's (the laptop rows of 10-12 Nov ran the "
                        "first prompt with 32,768)")  # fmt: skip
    parser.add_argument("--retries", type=int, default=RETRIES)
    parser.add_argument("--plans", nargs="*", help="plan ids (default: all 22)")
    parser.add_argument("--idle-w", type=float, help="device power at idle (meter reading, W)")
    parser.add_argument("--load-w", type=float, help="device power while generating (meter reading, W)")
    parser.add_argument("--out-dir", type=Path, default=HERE / "out", help="(edge kit: the code is mounted read-only)")
    args = parser.parse_args()
    data = json.loads((PILOT_DIR / "plans.json").read_text(encoding="utf-8"))
    household = data["household"]
    plans = [p for p in data["plans"] if not args.plans or p["id"] in args.plans]
    args.num_ctx = args.num_ctx or plan_num_ctx(args.model) or OLLAMA_NUM_CTX
    model = model_for(args.model, args.host, args.cpu_only, args.threads, args.num_ctx)
    print(f"{args.device}: {args.model} at {args.host}, {len(plans)} plans", flush=True)
    model.invoke("Say OK.")  # load the model first, so the first plan is not charged for it
    out_path = args.out_dir / f"{args.device}_{args.model}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with out_path.open("w") as out:
        for plan in plans:
            started_at = time.time()  # wall clock, to match the plan to the power meter's log (edge kit)
            got, calls, wall = run_plan(model, plan, household, args.retries)
            ok = [c for c in calls if "error" not in c]
            row = {"device": args.device, "model": args.model, "id": plan["id"], "wall_s": round(wall, 1),
                   "started_at": round(started_at, 2), "ended_at": round(time.time(), 2),
                   "calls": len(calls), "prompt_tokens": sum(c["prompt_eval_count"] or 0 for c in ok),
                   "output_tokens": sum(c["eval_count"] or 0 for c in ok),
                   "prefill_tok_s": rate([c["prompt_eval_count"] for c in ok], [c["prompt_eval_duration"] for c in ok]),
                   "gen_tok_s": rate([c["eval_count"] for c in ok], [c["eval_duration"] for c in ok]),
                   **score(plan, got or {}, household), "output": got}  # fmt: skip
            rows.append(row)
            out.write(json.dumps(row) + "\n")
            out.flush()
            print(f"{plan['id']}: {row['wall_s']:6.1f} s, {row['output_tokens']:5d} tokens out, "
                  f"prefill {row['prefill_tok_s']} tok/s, generation {row['gen_tok_s']} tok/s", flush=True)  # fmt: skip
    walls = sorted(r["wall_s"] for r in rows)
    summary = {
        "device": args.device, "model": args.model, "host_os": platform.platform(), "date": datetime.now().isoformat(),
        "cpu_only": args.cpu_only, "threads": args.threads, "num_ctx": args.num_ctx, "plans": len(rows),
        "mean_s_per_plan": round(sum(walls) / len(walls), 1),
        "p95_s_per_plan": walls[min(len(walls) - 1, int(round(0.95 * (len(walls) - 1))))],
        "prefill_tok_s": rate([r["prompt_tokens"] for r in rows],
                              [r["prompt_tokens"] / r["prefill_tok_s"] * NS if r["prefill_tok_s"] else 0 for r in rows]),
        "gen_tok_s": rate([r["output_tokens"] for r in rows],
                          [r["output_tokens"] / r["gen_tok_s"] * NS if r["gen_tok_s"] else 0 for r in rows]),
        "idle_w": args.idle_w, "load_w": args.load_w,
        "wh_per_plan": round(args.load_w * sum(walls) / len(walls) / 3600, 3) if args.load_w else None,
        **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in summarize(rows).items()},
    }  # fmt: skip
    (args.out_dir / f"{args.device}_{args.model}_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
