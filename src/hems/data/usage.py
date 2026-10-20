"""Usual run times of each household's appliances from REFIT, and the benchmark whose windows follow them.

REFIT records power only; it does not say when a household allows an appliance to run. The earlier benchmarks drew
each window by a fixed random rule (``hems.data.scenarios._window``). Here the window comes from the household's own
habit instead: the clock times at which its REFIT cycles of that appliance started.

Window rule (one window per appliance):
    ready time = the 25th percentile of the household's start times of that appliance kind
    finish by  = the 75th percentile of those start times + the cycle's length, and at least MIN_SLACK_SLOTS beyond the
                 cycle, never after midnight
If the scenario's household owns no appliance of that kind, the median of the per-household percentiles over all
households that do is used. Times are local clock times of the REFIT recording (UK), applied as local clock times of
the Finnish price day: a habit of starting the washing machine at 10:00 is kept as 10:00.

``build_usage_benchmark`` makes the set from an existing factorial set: the same price days, households, measured
cycles and peak limits, with only the windows (and the request text) replaced. Differences in results between the
two sets therefore come from the windows alone.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from hems.core.models import SLOT_MINUTES, SLOTS_PER_DAY, Scenario, load_scenarios
from hems.data import refit
from hems.data.scenarios import build_request
from hems.solvers.milp import solve_milp

USAGE_PATH = Path("data/usage/usage_times.json")
PERCENTILES = (25, 50, 75)
MIN_SLACK_SLOTS = 8  # at least two hours of room beyond the cycle, so scheduling has a choice
LIMIT_STEP_KW = 0.5


def start_minutes(refit_dir: str | Path, houses: tuple[int, ...] = refit.ALL_HOUSES) -> dict[int, dict[str, list[int]]]:
    """Minute of the day at which each REFIT cycle started, per house and appliance kind (all monitors of a kind)."""
    out: dict[int, dict[str, list[int]]] = {}
    for house in houses:
        df = refit.load_house(refit_dir, house)
        for column, kind in refit.FLEXIBLE_COLUMNS[house].items():
            cycles = refit.timed_cycles(df[column], max_gap_min=refit.MERGE_GAP_MIN[kind])
            minutes = [int(t.hour * 60 + t.minute) for t, _profile in cycles]
            out.setdefault(house, {}).setdefault(kind, []).extend(minutes)
    return out


def usage_times(starts: dict[int, dict[str, list[int]]]) -> dict:
    """Percentiles of the start minute per house and kind, and the median over houses per kind (the fallback)."""
    houses: dict[str, dict[str, dict]] = {}
    for house, kinds in starts.items():
        for kind, minutes in kinds.items():
            if minutes:
                p = np.percentile(minutes, PERCENTILES)
                houses.setdefault(str(house), {})[kind] = {
                    "cycles": len(minutes), **{f"p{q}_min": int(round(v)) for q, v in zip(PERCENTILES, p, strict=True)}}
    pooled = {}
    for kind in refit.FLEXIBLE_KINDS:
        rows = [h[kind] for h in houses.values() if kind in h]
        if rows:
            pooled[kind] = {"houses": len(rows),
                            **{f"p{q}_min": int(round(np.median([r[f"p{q}_min"] for r in rows]))) for q in PERCENTILES}}
    return {"percentiles": list(PERCENTILES), "houses": houses, "pooled": pooled,
            "note": "minute of the day (local time of the REFIT recording) at which detected cycles started"}


def window(usage: dict, house: int, kind: str, duration_slots: int) -> tuple[int, int, str]:
    """(ready slot, finish-by slot, source) of one appliance under the window rule of this module."""
    own = usage["houses"].get(str(house), {}).get(kind)
    stats, source = (own, f"house {house}") if own else (usage["pooled"][kind], "all households")
    earliest = int(stats["p25_min"]) // SLOT_MINUTES
    latest_start = max(int(np.ceil(stats["p75_min"] / SLOT_MINUTES)), earliest)
    deadline = min(SLOTS_PER_DAY, max(latest_start + duration_slots, earliest + duration_slots + MIN_SLACK_SLOTS))
    earliest = min(earliest, deadline - duration_slots - MIN_SLACK_SLOTS)  # late habits: move the ready time earlier
    return max(0, earliest), deadline, source


def house_of(scenario: Scenario) -> int:
    match = re.search(r"REFIT house (\d+)", scenario.notes)
    if not match:
        raise ValueError(f"{scenario.id}: no REFIT house in notes {scenario.notes!r}")
    return int(match.group(1))


def with_usage_windows(scenario: Scenario, usage: dict, id_prefix: str = "U-") -> Scenario:
    """The scenario with every appliance's window from the household's usual run times; the peak limit is raised in
    steps of LIMIT_STEP_KW only if no schedule fits (recorded in notes), as when the benchmark was built."""
    house = house_of(scenario)
    apps, sources = [], set()
    for a in scenario.appliances:
        earliest, deadline, source = window(usage, house, a.kind, a.duration_slots)
        sources.add(source)
        apps.append(a.model_copy(update={"earliest_slot": earliest, "deadline_slot": deadline, "windows": None,
                                         "default_start_slot": earliest}))  # fmt: skip
    notes = f"REFIT house {house}. Windows from usual run times ({', '.join(sorted(sources))})."
    limit = scenario.peak_limit_kw
    while True:
        new = scenario.model_copy(update={"id": f"{id_prefix}{scenario.id}", "appliances": apps,
                                          "peak_limit_kw": round(limit, 2), "notes": notes})  # fmt: skip
        if solve_milp(new).status == "Optimal":
            break
        limit += LIMIT_STEP_KW
        notes = f"{notes} Peak limit raised to {limit:.2f} kW for feasibility."
    new.user_request = build_request(new)
    return Scenario.model_validate(new.model_dump())  # re-run the model's checks on the new windows


def build_usage_benchmark(source_dir: str | Path, out_dir: str | Path, usage_path: str | Path = USAGE_PATH,
                          id_prefix: str = "U-") -> dict:  # fmt: skip
    usage = json.loads(Path(usage_path).read_text(encoding="utf-8"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written, raised = [], []
    for scenario in load_scenarios(source_dir):
        new = with_usage_windows(scenario, usage, id_prefix)
        new.save(out / f"{new.id}.json")
        written.append(new.id)
        if "raised" in new.notes:
            raised.append(new.id)
    manifest = {
        "design": "factorial set with windows from the households' usual run times (hems.data.usage)",
        "source_set": str(source_dir), "usage_times": str(usage_path), "id_prefix": id_prefix,
        "window_rule": {"ready": "p25 of start times", "finish_by": "p75 of start times + cycle length",
                        "min_slack_slots": MIN_SLACK_SLOTS, "fallback": "median over households owning the kind"},
        "scenarios": len(written), "peak_limit_raised": raised,
    }  # fmt: skip
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest
