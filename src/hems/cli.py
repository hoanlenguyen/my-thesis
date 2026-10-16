"""Command line: hems <command> --help"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.runnables import RunnableConfig

from hems.agents.llm import MODELS
from hems.core.models import Scenario, load_scenarios
from hems.run import ALL_SYSTEMS


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
    from hems.data.refit import ALL_HOUSES

    from datetime import date

    manifest = build_benchmark(
        args.refit, args.prices, args.out, seed=args.seed, peak_limit_kw=args.peak_limit, price_kwargs=price_kwargs,
        houses=tuple(args.houses) if args.houses else ALL_HOUSES,
        date_from=date.fromisoformat(args.date_from) if args.date_from else None,
        date_to=date.fromisoformat(args.date_to) if args.date_to else None,
        crisis=None if args.spike_days == "top" else ("2022-12-01", "2022-12-31"),
        id_prefix=args.id_prefix, exclude_dirs=tuple(args.exclude or ()),
    )  # fmt: skip
    print(json.dumps({k: manifest[k] for k in ("cycles_detected", "days", "price_days_available")}, indent=1))


def cmd_prices(args: argparse.Namespace) -> None:
    from datetime import date

    from hems.data.fetch_prices import fetch

    df = fetch(args.source, date.fromisoformat(args.start), date.fromisoformat(args.end), args.out, area=args.area)
    step = df.timestamp_utc.diff().value_counts().head(2).to_dict()
    print(f"{len(df)} prices {df.timestamp_utc.min()} .. {df.timestamp_utc.max()} (steps: {step}) -> {args.out}")


def cmd_refit_inspect(args: argparse.Namespace) -> None:
    from hems.data.refit import ALL_HOUSES, inspect

    print(inspect(args.refit, tuple(args.houses) if args.houses else ALL_HOUSES).to_string(index=False))


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
    from hems.run import LLM_SYSTEMS, execute, parse_assignments

    scenario = Scenario.load(args.scenario)
    print(scenario.user_request, "\n")
    if args.system != "multi_duo" or not args.review:
        record = execute(scenario, args.system, args.model if args.system in LLM_SYSTEMS else "-")
        print(json.dumps({k: record[k] for k in ("assignments", "cost_eur", "feasible", "violations", "latency_s", "tokens_in", "tokens_out", "explanation", "agent_errors")}, indent=1))  # fmt: skip
        return

    model = make_model(args.model)
    pipeline = build_pipeline(scenario, lambda _role: model, human_review=True)
    config: RunnableConfig | None = {"configurable": {"thread_id": scenario.id}, "recursion_limit": 50}
    for update in pipeline.stream({"request": scenario.user_request}, config=config, stream_mode="updates"):
        for node in update:
            print(f"-- {node} done")
    checked = pipeline.get_state(config).values["checked"]  # the schedule after the verification step
    schedule, _ = parse_assignments(scenario, checked)
    print("Proposed:", checked, evaluate(scenario, schedule))
    if input("Approve schedule? [y/N] ").strip().lower() != "y":
        print("Rejected; schedule not applied.")
        return
    final = pipeline.invoke(None, config=config)
    print(final.get("summary", ""))


def cmd_campaign(args: argparse.Namespace) -> None:
    from hems import campaign

    plan = campaign.Plan.load(args.plan)
    if args.action == "status":
        print(campaign.status(plan))
        return
    outcome = campaign.run(plan, summarize=not args.no_summary)
    raise SystemExit(0 if outcome == "done" else 3)  # non-zero lets a scheduler know work remains


def cmd_resolution(args: argparse.Namespace) -> None:
    import pandas as pd

    from hems.analysis.resolution import compare_resolution

    rows, by_type = compare_resolution(load_scenarios(args.scenarios), args.out)
    with pd.option_context("display.width", 160, "display.max_columns", 20, "display.float_format", "{:.3f}".format):
        print(by_type.to_string(index=False))
    print(f"\nper-scenario results and LaTeX table written to {args.out}")


def cmd_analyze(args: argparse.Namespace) -> None:
    import pandas as pd

    from hems.analysis.report import write_report

    scenarios = {s.id: s for s in load_scenarios(args.scenarios)}
    results = write_report(args.runs, scenarios, args.out)
    with pd.option_context("display.width", 160, "display.max_columns", 20):
        for name in ("gap_by_type", "wilcoxon", "baselines", "equivalence", "conflict_resolution", "efficiency", "efficiency_tests"):
            print(f"\n== {name}\n{results[name]}")
    print(f"\ntables and figures written to {args.out}")


def cmd_import_schedules(args: argparse.Namespace) -> None:
    """Score schedules from an external tool (tools/emhass_adapter.py output) and append them as run records."""
    from hems.run import append_record, completed_keys, external_record, run_key

    data = json.loads(Path(args.schedules).read_text(encoding="utf-8"))
    scenarios = {s.id: s for s in load_scenarios(args.scenarios)}
    out = Path(args.out)
    done = completed_keys(out)
    added = 0
    for scenario_id, result in data["schedules"].items():
        if run_key(args.system, "-", scenario_id, 0) in done:
            continue
        status = result.get("status", "")
        errors = [] if status in ("", "Optimal") else [f"{args.system}: solver status {status}"]
        record = external_record(scenarios[scenario_id], args.system, result["starts"], result.get("solve_s", 0.0), errors)
        record["tool_version"] = data.get("emhass_version", "")
        record["tool_config"] = data.get("mode", "")
        append_record(out, record)
        added += 1
        print(f"{record['key']} cost EUR {record['cost_eur']:.4f} {'ok' if record['feasible'] else 'INFEASIBLE'}")
    print(f"{added} records added to {out}")


def cmd_confirm(args: argparse.Namespace) -> None:
    import pandas as pd

    from hems.analysis.confirm import run

    result = run(args.runs)
    with pd.option_context("display.width", 200, "display.max_columns", 20, "display.max_colwidth", 60):
        print(result.to_string(index=False))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(args.out, index=False)
        print(f"\nwritten to {args.out}")


def cmd_rag_build(args: argparse.Namespace) -> None:
    from hems.rag import build_library

    manifest = build_library(args.refit, args.prices, args.out, per_cell=args.per_cell, seed=args.seed)
    print(json.dumps({k: manifest[k] for k in ("cases", "excluded_benchmark_days", "price_days_up_to")}, indent=1))
    print({cell: len(days) for cell, days in manifest["days"].items()})


def cmd_build_factorial(args: argparse.Namespace) -> None:
    from datetime import date

    from hems.data.factorial import build_factorial
    from hems.data.tariff import Tariff

    manifest = build_factorial(
        args.refit, args.prices, args.out, per_cell=args.per_cell, seed=args.seed, id_prefix=args.id_prefix,
        date_from=date.fromisoformat(args.date_from) if args.date_from else None,
        date_to=date.fromisoformat(args.date_to) if args.date_to else None, exclude_dirs=tuple(args.exclude),
        tariff=Tariff.uk_2015() if args.tariff == "uk2015" else Tariff(), local_tz=args.tz,
        price_scale=args.price_scale, allow_fewer=args.allow_fewer,
    )  # fmt: skip
    print(json.dumps({k: manifest[k] for k in ("price_period", "excluded_days", "price_days_available")}, indent=1))
    print(f"{len(manifest['scenarios'])} scenarios")


def main() -> None:
    # Windows consoles default to cp1252; model output (e.g. "≈") must never crash a batch while logging.
    # Line buffering makes progress visible immediately when output goes to a log file.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
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
    p.add_argument("--peak-limit", type=float, default=3.5, help="household peak limit in kW")
    p.add_argument("--houses", type=int, nargs="*", help="REFIT houses to use (default: all except refit.EXCLUDED_HOUSES)")
    p.add_argument("--from", dest="date_from", help="only price days on/after this date (e.g. 2025-10-01 for 15-min prices)")
    p.add_argument("--to", dest="date_to", help="only price days on/before this date")
    p.add_argument("--spike-days", choices=["crisis", "top"], default="crisis",
                   help="type E days: Dec 2022 crisis, or the 16 highest-peak days of the period")
    p.add_argument("--id-prefix", default="", help="prefix for scenario ids, e.g. Q- for the 15-min set")
    p.add_argument("--exclude", nargs="*", help="scenario directories whose days must not be reused (e.g. data/scenarios_15min for Q2)")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("prices", help="download Nord Pool FI day-ahead prices (EUR/MWh, UTC) to CSV")
    p.add_argument("--source", default="elering", choices=["elering", "entsoe", "sahkotin"])
    p.add_argument("--start", default="2022-01-01")
    p.add_argument("--end", default="2026-09-25", help="exclusive")
    p.add_argument("--out", default="data/raw/prices_fi.csv")
    p.add_argument("--area", default="FI", choices=["FI", "GB"], help="bidding zone (GB: ENTSO-E only, GBP/MWh)")
    p.set_defaults(func=cmd_prices)

    p = sub.add_parser("refit-inspect", help="cycle statistics per mapped REFIT column")
    p.add_argument("--refit", required=True)
    p.add_argument("--houses", type=int, nargs="*")
    p.set_defaults(func=cmd_refit_inspect)

    p = sub.add_parser("run", help="run systems over scenarios, appending to a JSONL file")
    p.add_argument("--scenarios", default="data/scenarios")
    p.add_argument("--systems", nargs="+", default=["milp", "naive", "multi_duo"], choices=list(ALL_SYSTEMS))
    p.add_argument("--models", nargs="+", default=["gpt-4o-mini"], choices=list(MODELS))
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--ids", nargs="*", help="only these scenario ids")
    p.add_argument("--limit", type=int, help="only the first N scenarios")
    p.add_argument("--out", default="results/runs.jsonl")
    p.add_argument("--no-summary", action="store_true", help="skip the orchestrator's natural-language summary")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("demo", help="run one scenario and print the result")
    p.add_argument("scenario")
    p.add_argument("--system", default="multi_duo", choices=list(ALL_SYSTEMS))
    p.add_argument("--model", default="gpt-4o-mini", choices=list(MODELS))
    p.add_argument("--review", action="store_true", help="human-in-the-loop approval before finalising (multi_duo only)")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("campaign", help="resumable evaluation from a plan file (configs/*.json)")
    p.add_argument("action", choices=["run", "status"])
    p.add_argument("--plan", default="configs/full_evaluation.json")
    p.add_argument("--no-summary", action="store_true", help="skip the orchestrator's natural-language summary")
    p.set_defaults(func=cmd_campaign)

    p = sub.add_parser("resolution", help="MILP: value of 15-min vs hourly price information")
    p.add_argument("--scenarios", default="data/scenarios_15min")
    p.add_argument("--out", default="results/resolution")
    p.set_defaults(func=cmd_resolution)

    p = sub.add_parser("analyze", help="metrics, Wilcoxon tests, LaTeX tables and figures")
    p.add_argument("--runs", nargs="+", default=["results/runs.jsonl"], help="one or more run files (merged)")
    p.add_argument("--scenarios", default="data/scenarios")
    p.add_argument("--out", default="results")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("import-schedules", help="score schedules from an external HEMS tool (e.g. EMHASS) as run records")
    p.add_argument("schedules", help="JSON written by tools/emhass_adapter.py")
    p.add_argument("--system", required=True, help='system name for the records, e.g. "emhass"')
    p.add_argument("--scenarios", default="data/scenarios")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_import_schedules)

    p = sub.add_parser("confirm", help="pre-registered confirmatory tests of H1 and H2 (docs/preregistration.md)")
    p.add_argument("--runs", default="results/confirmation.jsonl")
    p.add_argument("--out", default="results/confirmation/confirmatory_tests.csv")
    p.set_defaults(func=cmd_confirm)

    p = sub.add_parser("rag-build", help="build the RAG case library of solved days outside every benchmark")
    p.add_argument("--refit", default="data/raw/refit")
    p.add_argument("--prices", default="data/raw/prices_fi_sahkotin.csv")
    p.add_argument("--out", default="data/rag/cases.jsonl")
    p.add_argument("--per-cell", type=int, default=20, help="days per regime x load cell (each under both limits)")
    p.add_argument("--seed", type=int, default=7)
    p.set_defaults(func=cmd_rag_build)

    p = sub.add_parser("build-factorial", help="build a factorial benchmark: price regime x load x peak limit")
    p.add_argument("--refit", default="data/raw/refit")
    p.add_argument("--prices", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--per-cell", type=int, default=6, help="days per regime x load cell")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--id-prefix", default="")
    p.add_argument("--from", dest="date_from")
    p.add_argument("--to", dest="date_to")
    p.add_argument("--exclude", nargs="*", default=[], help="scenario directories whose days must not be reused")
    p.add_argument("--tz", default="Europe/Helsinki", help="time zone of the household day (Europe/London for UK)")
    p.add_argument("--price-scale", type=float, default=1.0, help="multiply prices, e.g. EUR per GBP for GB prices")
    p.add_argument("--tariff", default="fi", choices=["fi", "uk2015"], help="consumer tariff (data.tariff)")
    p.add_argument("--allow-fewer", action="store_true", help="take every candidate day when a pattern has too few")
    p.set_defaults(func=cmd_build_factorial)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
