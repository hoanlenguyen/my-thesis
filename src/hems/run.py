"""Experiment runner: every (system, model, scenario, run) becomes one JSON line.

Runs already present in the output file are skipped, so an interrupted batch
resumes where it stopped. Provider/API failures are logged and NOT recorded,
so they are retried on the next invocation instead of counting as agent errors.
"""

from __future__ import annotations

import json
import os
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.callbacks import get_usage_metadata_callback

from hems.agents.errors import daily_quota_exhausted
from hems.agents.llm import MODELS, make_model, usage_cost_usd
from hems.agents.multi_agent import run_multi_agent
from hems.agents.oneshot import run_oneshot
from hems.agents.single_agent import run_single_agent
from hems.agents.types import AgentRun
from hems.core.evaluate import evaluate
from hems.core.models import Scenario, Schedule
from hems.solvers.milp import solve_milp
from hems.solvers.naive import naive_schedule, smart_timer_schedule

REFERENCE_SYSTEMS = ("milp", "naive", "timer")  # deterministic: one run, no model
AGENT_SYSTEMS = ("single", "multi")
LLM_SYSTEMS = (*AGENT_SYSTEMS, "oneshot")  # oneshot: LLM without tools (baseline)
ALL_SYSTEMS = (*REFERENCE_SYSTEMS, *LLM_SYSTEMS)


def run_key(system: str, model: str, scenario_id: str, run: int) -> str:
    return f"{system}|{model}|{scenario_id}|{run}"


def repair_tail(path: Path) -> bool:
    """Drop a partially written last line (the process was killed mid-write). Returns True if repaired."""
    if not path.exists() or path.stat().st_size == 0:
        return False
    data = path.read_bytes()
    if data.endswith(b"\n"):
        return False
    path.write_bytes(data[: data.rfind(b"\n") + 1])
    return True


def read_records(path: Path) -> list[dict[str, Any]]:
    """All complete records; malformed lines (e.g. from a hard power-off) are skipped."""
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def completed_keys(path: Path) -> set[str]:
    return {r["key"] for r in read_records(path)}


def append_record(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
        fh.flush()
        os.fsync(fh.fileno())  # a finished run survives a sudden shutdown


def parse_assignments(scenario: Scenario, assignments: dict[str, str] | None) -> tuple[Schedule, list[str]]:
    schedule: Schedule = {}
    problems: list[str] = []
    for appliance_id, clock in (assignments or {}).items():
        try:
            schedule[appliance_id] = scenario.time_to_slot(clock)
        except (ValueError, AttributeError):
            problems.append(f"{appliance_id}: unparseable start time {clock!r}")
    return schedule, problems


def execute(scenario: Scenario, system: str, model_name: str = "-", run: int = 0, summarize: bool = True) -> dict[str, Any]:
    key = run_key(system, model_name, scenario.id, run)
    run_id = str(uuid.uuid4())
    started = time.perf_counter()
    usage: dict[str, dict] = {}
    agent_run: AgentRun

    if system == "milp":
        result = solve_milp(scenario)
        schedule, parse_problems = result.schedule, [] if result.status == "Optimal" else [f"MILP status {result.status}"]
        agent_run = AgentRun(assignments={k: scenario.slot_to_time(v) for k, v in schedule.items()})
    elif system in ("naive", "timer"):
        schedule, parse_problems = (naive_schedule if system == "naive" else smart_timer_schedule)(scenario), []
        agent_run = AgentRun(assignments={k: scenario.slot_to_time(v) for k, v in schedule.items()})
    else:
        config = {
            "run_id": run_id,
            "run_name": key,
            "tags": [system, model_name, f"type-{scenario.type}"],
            "metadata": {"scenario_id": scenario.id, "run": run},
        }
        with get_usage_metadata_callback() as cb:
            if system == "single":
                agent_run = run_single_agent(scenario, make_model(model_name), config)
            elif system == "multi":
                model = make_model(model_name)
                agent_run = run_multi_agent(scenario, lambda _role: model, config, summarize=summarize)
            elif system == "oneshot":
                agent_run = run_oneshot(scenario, make_model(model_name), config)
            else:
                raise ValueError(f"unknown system {system}")
            usage = dict(cb.usage_metadata)
        schedule, parse_problems = parse_assignments(scenario, agent_run.assignments)

    latency = time.perf_counter() - started
    evaluation = evaluate(scenario, schedule)
    tokens_in, tokens_out, usd = usage_cost_usd(usage, model_name) if model_name in MODELS else (0, 0, 0.0)

    return {
        "key": key,
        "system": system,
        "model": model_name,
        "model_id": MODELS[model_name].model_id if model_name in MODELS else "-",
        "scenario_id": scenario.id,
        "scenario_type": scenario.type,
        "synthetic": scenario.synthetic,
        "run": run,
        "assignments": agent_run.assignments,
        "schedule_slots": schedule,
        "cost_eur": evaluation.cost_eur,
        "per_appliance_cost_eur": evaluation.per_appliance_cost_eur,
        "feasible": evaluation.feasible and not parse_problems,
        "violations": parse_problems + evaluation.violations,
        "peak_kw": evaluation.peak_kw,
        "latency_s": round(latency, 3),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(usd, 6),
        "tool_calls": agent_run.tool_calls,
        "iterations": agent_run.iterations,
        "recoveries": agent_run.recoveries,
        "agent_errors": agent_run.errors,
        "explanation": agent_run.explanation,
        "langsmith_run_id": run_id if system in LLM_SYSTEMS else None,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


Job = tuple[Scenario, str, str, int]  # scenario, system, model, run


def plan_jobs(scenarios: list[Scenario], systems: list[str], models: list[str], runs: int, order: str = "scenario") -> list[Job]:
    """All jobs of a batch. order="model" runs references first, then each model in the given order
    (e.g. the fast cloud model before the slow local one)."""
    jobs: list[Job] = []
    for scenario in scenarios:
        for system in systems:
            if system in REFERENCE_SYSTEMS:
                jobs.append((scenario, system, "-", 0))
            else:
                jobs += [(scenario, system, m, r) for m in models for r in range(1, runs + 1)]
    if order == "model":
        rank = {m: i for i, m in enumerate(["-", *models])}
        jobs.sort(key=lambda j: (rank[j[2]], j[3], j[0].id, j[1]))  # stable: scenario order kept within a run
    return jobs


def run_batch(
    scenarios: list[Scenario],
    systems: list[str],
    models: list[str],
    runs: int,
    out_path: Path,
    summarize: bool = True,
    order: str = "scenario",
) -> str:
    """Run every job not yet in ``out_path``. Returns "done", "quota" or "incomplete" (some jobs failed)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if repair_tail(out_path):
        print(f"repaired a partially written last line in {out_path}", flush=True)
    done = completed_keys(out_path)
    jobs = plan_jobs(scenarios, systems, models, runs, order)
    todo = [j for j in jobs if run_key(j[1], j[2], j[0].id, j[3]) not in done]
    print(f"{len(jobs)} jobs, {len(jobs) - len(todo)} already done, {len(todo)} to run -> {out_path}", flush=True)

    failed = 0
    for i, (scenario, system, model, run) in enumerate(todo, 1):
        label = run_key(system, model, scenario.id, run)
        try:
            record = execute(scenario, system, model, run, summarize=summarize)
        except KeyboardInterrupt:
            print(f"\ninterrupted during {label}; it will be rerun next time. {len(todo) - i + 1} jobs left.", flush=True)
            raise
        except Exception as exc:  # provider/network failure: leave unrecorded so a rerun retries it
            if daily_quota_exhausted(exc):
                print(f"[{i}/{len(todo)}] {label}: daily provider quota reached; stopping. Rerun the same command "
                      f"later to continue ({len(todo) - i + 1} jobs left).", flush=True)  # fmt: skip
                return "quota"
            failed += 1
            print(f"[{i}/{len(todo)}] {label} FAILED (not recorded)\n{traceback.format_exc(limit=3)}", flush=True)
            continue
        append_record(out_path, record)
        status = "ok" if record["feasible"] else "INFEASIBLE"
        print(
            f"[{i}/{len(todo)}] {label} cost EUR {record['cost_eur']:.4f} {status} "
            f"{record['latency_s']:.1f}s {record['tokens_in'] + record['tokens_out']} tok",
            flush=True,
        )
    return "incomplete" if failed else "done"
