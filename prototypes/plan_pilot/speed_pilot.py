"""Speed pilot for the local models (exploratory, 13 Nov 2026; development plans only).

Runs ``pilot.extract`` (the pilot prompt and run settings) on ``plans_dev.json`` with Ollama settings that
may make a call faster, without touching the frozen registry in ``hems.agents.llm``:

- ``ctx``: context window (``num_ctx``). The registry uses 32,768 tokens for the agents' long conversations; a plan
  call needs a few thousand, and a smaller KV cache leaves room on the 8 GB GPU for more of the model's layers.
- ``think``: reasoning setting (False = off, "low" for gpt-oss, None = model default).

Every setting is labelled in the output, e.g. ``gemma4-e4b+ctx8k+think-off``; the baseline (``+base``) uses the
registry's settings and runs in the same session so the times compare. The 22 pilot plans are not used.

    uv run python prototypes/plan_pilot/speed_pilot.py --models gemma4-e4b --ctx 8192 --think off
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import pilot  # noqa: E402
from hems.agents import llm  # noqa: E402

THINK = {"default": "keep", "off": False, "low": "low", "on": True}


def patched(ctx: int | None, think: object):
    def make(name: str, temperature: float = 0.0, seed: int | None = None, num_ctx: int | None = None):
        spec = llm.MODELS[name]
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=spec.model_id, temperature=temperature, seed=seed, num_ctx=ctx or num_ctx or llm.OLLAMA_NUM_CTX,
            reasoning=spec.ollama_think if think == "keep" else think, num_predict=spec.ollama_num_predict,
            num_gpu=spec.ollama_num_gpu, keep_alive="30m",
        )  # fmt: skip

    return make


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--ctx", type=int, default=None, help="num_ctx (default: the pilot's plan-sized window)")
    parser.add_argument("--think", choices=sorted(THINK), default="default")
    parser.add_argument("--plans", type=Path, default=HERE / "plans_dev.json")
    parser.add_argument("--out", type=Path, default=HERE / "results_speed.jsonl")
    args = parser.parse_args()
    data = json.loads(args.plans.read_text(encoding="utf-8"))
    household, plans = data["household"], data["plans"]
    pilot.make_model = patched(args.ctx, THINK[args.think])
    tag = "".join([f"+ctx{args.ctx // 1024}k" if args.ctx else "", "" if args.think == "default" else
                   f"+think-{args.think}"]) or "+base"  # fmt: skip
    done = set()
    if args.out.exists():
        done = {(r["model"], r["id"]) for r in map(json.loads, args.out.read_text(encoding="utf-8").splitlines())}
    with args.out.open("a", encoding="utf-8") as out:
        for base in args.models:
            label = base + tag
            pilot.extract(base, plans[0], household, retries=0)  # warm-up: load the model
            for plan in plans:
                if (label, plan["id"]) in done:
                    continue
                got, meta = pilot.extract(base, plan, household)
                row = {"model": label, **pilot.score(plan, got or {}, household), **meta, "output": got}
                out.write(json.dumps(row) + "\n")
                out.flush()
                print(f"{label:28s} {plan['id']}: {meta['latency_s']:6.1f} s, {meta['tokens_out']} out, "
                      f"attempts {meta['attempts']}, decision_ok {row.get('decision_ok')}", flush=True)  # fmt: skip


if __name__ == "__main__":
    main()
