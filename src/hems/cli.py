"""Command line: hems <command> --help"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from hems.agents.llm import MODELS
from hems.core.models import Scenario, load_scenarios


def _scenarios(directory: str, ids: list[str] | None, limit: int | None) -> list[Scenario]:
    scenarios = load_scenarios(directory)
    if ids:
        scenarios = [s for s in scenarios if s.id in ids]
    if not scenarios:
        raise SystemExit(f"no scenarios found in {directory}")
    return scenarios[:limit] if limit else scenarios


def cmd_synth(args: argparse.Namespace) -> None:
    from hems.data.synthetic import generate

    scenarios = generate(args.out, per_type=args.per_type, seed=args.seed, peak_limit_kw=args.peak_limit)
    print(f"wrote {len(scenarios)} synthetic scenarios to {args.out}")


def cmd_build(args: argparse.Namespace) -> None:
    from hems.data.build import build_benchmark

    price_kwargs = {"unit": args.price_unit, "source_tz": args.price_tz, "vat_included": args.price_vat}
    if args.price_time_col:
        price_kwargs["time_col"] = args.price_time_col
    if args.price_col:
        price_kwargs["price_col"] = args.price_col
    manifest = build_benchmark(
        args.refit, args.prices, args.out, seed=args.seed, peak_limit_kw=args.peak_limit, price_kwargs=price_kwargs
    )
    print(json.dumps({k: manifest[k] for k in ("cycles_detected", "days", "price_days_available")}, indent=1))


def cmd_refit_inspect(args: argparse.Namespace) -> None:
    from hems.data.refit import inspect

    print(inspect(args.refit).to_string(index=False))


def cmd_run(args: argparse.Namespace) -> None:
    from hems.run import run_batch

    run_batch(
        _scenarios(args.scenarios, args.ids, args.limit),
        args.systems,
        args.models,
        args.runs,
        Path(args.out),
        summarize=not args.no_summary,
    )


def cmd_demo(args: argparse.Namespace) -> None:
    from hems.agents.llm import make_model
    from hems.agents.multi_agent import build_pipeline
    from hems.core.evaluate import evaluate
    from hems.run import execute, parse_assignments

    scenario = Scenario.load(args.scenario)
    print(scenario.user_request, "\n")
    if args.system != "multi" or not args.review:
        record = execute(scenario, args.system, args.model if args.system in ("single", "multi") else "-")
        print(json.dumps({k: record[k] for k in ("assignments", "cost_eur", "feasible", "violations", "latency_s", "tokens_in", "tokens_out", "explanation", "agent_errors")}, indent=1))  # fmt: skip
        return

    model = make_model(args.model)
    pipeline = build_pipeline(scenario, lambda _role: model, human_review=True)
    config = {"configurable": {"thread_id": scenario.id}, "recursion_limit": 50}
    for update in pipeline.stream({"request": scenario.user_request}, config=config, stream_mode="updates"):
        for node in update:
            print(f"-- {node} done")
    proposal = pipeline.get_state(config).values["resolution"]
    schedule, _ = parse_assignments(scenario, {a.appliance_id: a.start_time for a in proposal.assignments})
    print("Proposed:", {a.appliance_id: a.start_time for a in proposal.assignments}, evaluate(scenario, schedule))
    if input("Approve schedule? [y/N] ").strip().lower() != "y":
        print("Rejected; schedule not applied.")
        return
    final = pipeline.invoke(None, config=config)
    print(final.get("summary", ""))


def cmd_analyze(args: argparse.Namespace) -> None:
    import pandas as pd

    from hems.analysis.report import write_report

    scenarios = {s.id: s for s in load_scenarios(args.scenarios)}
    results = write_report(args.runs, scenarios, args.out)
    with pd.option_context("display.width", 160, "display.max_columns", 20):
        for name in ("gap_by_type", "wilcoxon", "conflict_resolution", "efficiency"):
            print(f"\n== {name}\n{results[name]}")
    print(f"\ntables and figures written to {args.out}")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="hems", description=__doc__)
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("synth", help="generate synthetic dev/pilot scenarios (not thesis data)")
    p.add_argument("--out", default="data/pilot")
    p.add_argument("--per-type", type=int, default=8)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--peak-limit", type=float, default=4.0)
    p.set_defaults(func=cmd_synth)

    p = sub.add_parser("build", help="build the 48-scenario benchmark from REFIT + Nord Pool FI")
    p.add_argument("--refit", required=True, help="directory with cleaned REFIT house CSVs")
    p.add_argument("--prices", required=True, help="CSV of Nord Pool FI spot prices")
    p.add_argument("--price-unit", default="EUR/MWh", choices=["EUR/MWh", "c/kWh", "EUR/kWh"])
    p.add_argument("--price-tz", default="UTC", help="timezone of naive timestamps in the price CSV")
    p.add_argument("--price-vat", type=float, default=0.0, help="VAT rate already included in the prices")
    p.add_argument("--price-time-col")
    p.add_argument("--price-col")
    p.add_argument("--out", default="data/scenarios")
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--peak-limit", type=float, default=4.0)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("refit-inspect", help="cycle statistics per mapped REFIT column")
    p.add_argument("--refit", required=True)
    p.set_defaults(func=cmd_refit_inspect)

    p = sub.add_parser("run", help="run systems over scenarios, appending to a JSONL file")
    p.add_argument("--scenarios", default="data/scenarios")
    p.add_argument("--systems", nargs="+", default=["milp", "naive", "single", "multi"], choices=["milp", "naive", "single", "multi"])
    p.add_argument("--models", nargs="+", default=["gpt-4o-mini"], choices=list(MODELS))
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--ids", nargs="*", help="only these scenario ids")
    p.add_argument("--limit", type=int, help="only the first N scenarios")
    p.add_argument("--out", default="results/runs.jsonl")
    p.add_argument("--no-summary", action="store_true", help="skip the orchestrator's natural-language summary")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("demo", help="run one scenario and print the result")
    p.add_argument("scenario")
    p.add_argument("--system", default="multi", choices=["milp", "naive", "single", "multi"])
    p.add_argument("--model", default="gpt-4o-mini", choices=list(MODELS))
    p.add_argument("--review", action="store_true", help="human-in-the-loop approval before finalising (multi only)")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("analyze", help="metrics, Wilcoxon tests, LaTeX tables and figures")
    p.add_argument("--runs", default="results/runs.jsonl")
    p.add_argument("--scenarios", default="data/scenarios")
    p.add_argument("--out", default="results")
    p.set_defaults(func=cmd_analyze)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
