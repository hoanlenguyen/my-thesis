"""Resumable evaluation campaigns: stop the laptop whenever, run the same command later.

A campaign is a JSON plan (``configs/*.json``) naming the scenarios, systems, models, runs and output
file. ``hems campaign run`` does everything needed to continue it:

* refuses to start twice on the same output file (lock file with the owner's PID),
* repairs a results file whose last line was cut off by a hard shutdown,
* starts the local Ollama server if a local model is in the plan and it is not running,
* keeps Windows from sleeping while jobs run (released on exit; closing the lid may still sleep,
  depending on power settings),
* runs only the jobs not yet recorded, flushing each finished job to disk immediately.

Interrupting (Ctrl+C, closing the window, shutting down) loses at most the job in progress.
``hems campaign status`` shows progress and a rough time estimate.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.error import URLError
from urllib.request import urlopen

from hems.agents.llm import MODELS
from hems.core.models import load_scenarios
from hems.run import plan_jobs, read_records, run_batch, run_key

OLLAMA_URL = "http://127.0.0.1:11434/api/version"
OLLAMA_DEFAULT_EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"


@dataclass(frozen=True)
class Plan:
    name: str
    scenarios: str
    systems: list[str]
    models: list[str]
    runs: int
    out: str
    order: str = "model"
    ids: list[str] | None = None
    # Whether the agent systems also write the household message (one more model call per run). Off unless a plan
    # asks for it (since 19 Oct 2026); every plan run before then had it on and says "message": true.
    message: bool = False

    @classmethod
    def load(cls, path: str | Path) -> Plan:
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))

    def jobs(self):
        scenarios = load_scenarios(self.scenarios)
        if self.ids:
            scenarios = [s for s in scenarios if s.id in self.ids]
        return plan_jobs(scenarios, self.systems, self.models, self.runs, self.order)


# ── single instance ──────────────────────────────────────────────────────────


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":  # os.kill(pid, 0) would terminate the process on Windows
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@contextmanager
def single_instance(out_path: Path) -> Iterator[None]:
    lock = out_path.with_suffix(out_path.suffix + ".lock")
    if lock.exists():
        try:
            pid = int(lock.read_text().strip() or 0)
        except ValueError:
            pid = 0
        if pid and pid != os.getpid() and _pid_alive(pid):
            raise SystemExit(f"another campaign (PID {pid}) is already writing {out_path}; not starting a second one")
        lock.unlink(missing_ok=True)  # stale lock from a killed run
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(os.getpid()))
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


# ── environment ──────────────────────────────────────────────────────────────


@contextmanager
def keep_awake() -> Iterator[None]:
    """Ask Windows not to sleep while this process runs (per-process request, no settings changed)."""
    if sys.platform != "win32":
        yield
        return
    es_continuous, es_system_required = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required)
    try:
        yield
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous)


def _ollama_up() -> bool:
    try:
        with urlopen(OLLAMA_URL, timeout=3):
            return True
    except (URLError, OSError):
        return False


def ensure_ollama(models: list[str]) -> None:
    if not any(MODELS[m].provider == "ollama" for m in models) or _ollama_up():
        return
    exe = shutil.which("ollama") or str(OLLAMA_DEFAULT_EXE)
    if not Path(exe).exists():
        raise SystemExit("Ollama is needed for a local model but was not found; install it or start it manually")
    print("starting Ollama server ...", flush=True)
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    for _ in range(60):
        if _ollama_up():
            print("Ollama server is up", flush=True)
            return
        time.sleep(1)
    raise SystemExit("Ollama server did not start within 60 s")


# ── commands ─────────────────────────────────────────────────────────────────


def status(plan: Plan) -> str:
    out = Path(plan.out)
    records = {r["key"]: r for r in read_records(out)}
    total: Counter[tuple[str, str]] = Counter()
    done: Counter[tuple[str, str]] = Counter()
    for scenario, system, model, run in plan.jobs():
        group = (system, model)
        total[group] += 1
        done[group] += run_key(system, model, scenario.id, run) in records

    lines = [f"campaign '{plan.name}' -> {out}", f"{'system':7} {'model':14} {'done':>9}  est. remaining"]
    remaining_s = 0.0
    for group in sorted(total, key=lambda g: (g[1] != "-", g[1], g[0])):
        system, model = group
        latencies = [r["latency_s"] for r in records.values() if r["system"] == system and r["model"] == model]
        left = total[group] - done[group]
        eta = statistics.median(latencies) * left if latencies and left else 0.0
        remaining_s += eta
        eta_txt = "-" if not left else (f"~{eta / 3600:.1f} h" if latencies else "unknown")
        lines.append(f"{system:7} {model:14} {done[group]:>4}/{total[group]:<4}  {eta_txt}")
    all_done, all_total = sum(done.values()), sum(total.values())
    lines.append(f"total {all_done}/{all_total} jobs ({all_done / all_total:.0%}); ~{remaining_s / 3600:.1f} h of compute left")
    return "\n".join(lines)


def run(plan: Plan) -> str:
    out = Path(plan.out)
    with single_instance(out):
        ensure_ollama(plan.models)
        print(status(plan), flush=True)
        scenarios = load_scenarios(plan.scenarios)
        if plan.ids:
            scenarios = [s for s in scenarios if s.id in plan.ids]
        with keep_awake():
            outcome = run_batch(scenarios, plan.systems, plan.models, plan.runs, out, summarize=plan.message, order=plan.order)
        print(status(plan), flush=True)
        messages = {
            "done": "campaign complete.",
            "quota": "stopped at a provider's daily quota; run the same command again later.",
            "incomplete": "some jobs failed (network/provider); run the same command again to retry them.",
        }
        print(messages[outcome], flush=True)
        return outcome
