"""EMHASS (Energy Management for Home Assistant) as a scheduling system.

EMHASS pins packages that conflict with this environment (e.g. numpy<2.3), so it lives in its own
virtual environment (.venv-emhass) and is called through tools/emhass_adapter.py as a subprocess:
the scenario goes in on stdin, the chosen start slots come back as JSON on the last stdout line.
Set HEMS_EMHASS_PYTHON to use a different interpreter.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from hems.core.models import Scenario, Schedule

REPO = Path(__file__).resolve().parents[3]
ADAPTER = REPO / "tools" / "emhass_adapter.py"
TIMEOUT_S = 600


@dataclass
class EmhassResult:
    schedule: Schedule
    errors: list[str]
    solve_s: float
    info: dict[str, str] = field(default_factory=dict)


def emhass_python() -> Path:
    if env := os.environ.get("HEMS_EMHASS_PYTHON"):
        return Path(env)
    sub = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    return REPO / ".venv-emhass" / sub


def emhass_schedule(scenario: Scenario, mode: str = "profile") -> EmhassResult:
    """Schedule one scenario with EMHASS. Raises RuntimeError if EMHASS cannot run (not recorded, retried)."""
    python = emhass_python()
    if not python.exists():
        raise RuntimeError(
            f"EMHASS environment not found at {python}. Create it with: uv venv .venv-emhass --python 3.12 && "
            'uv pip install --python .venv-emhass/Scripts/python.exe "emhass==0.18.4"'
        )
    proc = subprocess.run(
        [str(python), str(ADAPTER), "--stdin", "--mode", mode],
        input=scenario.model_dump_json(), capture_output=True, text=True, timeout=TIMEOUT_S, cwd=REPO,
    )  # fmt: skip
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if proc.returncode != 0 or not lines:
        raise RuntimeError(f"EMHASS adapter failed (exit {proc.returncode}): {proc.stderr.strip()[-500:]}")
    out = json.loads(lines[-1])
    schedule: Schedule = {k: v for k, v in out["starts"].items() if v is not None}
    errors = [] if out.get("status") == "Optimal" else [f"emhass: solver status {out.get('status')}"]
    errors += [f"emhass: no start for {k}" for k, v in out["starts"].items() if v is None]
    return EmhassResult(schedule, errors, float(out.get("solve_s", 0.0)),
                        {"tool_version": out.get("emhass_version", ""), "tool_config": mode})  # fmt: skip
