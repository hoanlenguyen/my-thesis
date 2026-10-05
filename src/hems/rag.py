"""Retrieval-augmented generation for the pipeline (design iteration 7): a case library of solved days.

The library holds days that are in no benchmark: hourly prices up to 30 Sep 2025 minus every day of the
main benchmark (the 15-minute sets Q and Q2 start on 1 Oct 2025). Each case is composed exactly like a
benchmark scenario (same REFIT cycle pool, scenario types and peak limit) and solved with the MILP. At
run time the k most similar cases are retrieved and their optimal staggering is given to the Scheduler
and the Resolver as worked examples. Retrieval uses a fixed numeric description of the day (price shape
and appliance structure), not text embeddings, so it is deterministic and free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from hems.core.evaluate import appliance_cost, evaluate, total_load
from hems.core.models import Scenario, load_scenarios
from hems.data import prices as price_data
from hems.data import refit
from hems.data.build import load_household_data
from hems.data.scenarios import compose_scenario, select_days
from hems.data.tariff import Tariff
from hems.solvers.milp import solve_milp
from hems.solvers.naive import has_coordination_conflict, naive_schedule

LIBRARY_PATH = Path("data/rag/cases.jsonl")
TOP_K = 2
LABELS = {"washing_machine": "washing machine", "dishwasher": "dishwasher", "tumble_dryer": "tumble dryer"}


# ── Day description used for retrieval ────────────────────────────────────────


def features(scenario: Scenario) -> dict[str, list[float]]:
    """Price shape (24 hourly consumer prices, z-scored) and appliance structure (6 values, roughly 0-1)."""
    price = np.asarray(scenario.price_eur_per_kwh).reshape(24, 4).mean(axis=1)
    shape = (price - price.mean()) / price.std() if price.std() > 1e-9 else np.zeros(24)
    apps = scenario.appliances
    headroom = max(0.1, scenario.peak_limit_kw - max(scenario.base_load_kw))
    pairs = [(a, b) for i, a in enumerate(apps) for b in apps[i + 1 :]]
    overlap = (
        sum(min(a.deadline_slot, b.deadline_slot) > max(a.earliest_slot, b.earliest_slot) for a, b in pairs) / len(pairs)
        if pairs
        else 0.0
    )
    structure = [
        len(apps) / 5,
        min(2.0, sum(a.peak_kw for a in apps) / headroom) / 2,
        float(np.mean([(a.deadline_slot - a.earliest_slot) / 96 for a in apps])),
        overlap,
        float(has_coordination_conflict(scenario)),
        min(3.0, (price.max() - price.min()) / max(1e-6, abs(price.mean()))) / 3,
    ]
    return {"shape": [round(float(v), 4) for v in shape], "structure": [round(float(v), 4) for v in structure]}


def similarity(f1: dict[str, list[float]], f2: dict[str, list[float]]) -> float:
    """Half price-shape cosine similarity, half structural closeness; 1 = identical."""
    a, b = np.asarray(f1["shape"]), np.asarray(f2["shape"])
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    shape = float(a @ b / norm) if norm > 1e-9 else 0.0
    gap = float(np.linalg.norm(np.asarray(f1["structure"]) - np.asarray(f2["structure"])))
    return 0.5 * shape + 0.5 * float(np.exp(-2 * gap))


# ── Worked example text ───────────────────────────────────────────────────────


def example_text(scenario: Scenario, optimal: dict[str, int]) -> str:
    """How the optimum handled this day, in the agents' vocabulary (clock times, kW, EUR)."""
    sc = scenario
    price_c = np.asarray(sc.price_eur_per_kwh) * 100
    cheapest = {a.id: min(a.valid_starts(), key=lambda s, a=a: appliance_cost(sc, a, s)) for a in sc.appliances}
    unconstrained_peak = float(total_load(sc, cheapest).max())
    naive_cost = evaluate(sc, naive_schedule(sc)).cost_eur
    opt_cost = evaluate(sc, optimal).cost_eur
    cheap_hour = int(np.argmin(price_c.reshape(24, 4).mean(axis=1)))
    lines = [
        f"Day with {len(sc.appliances)} appliances, peak limit {sc.peak_limit_kw:.2f} kW, prices "
        f"{price_c.min():.1f}-{price_c.max():.1f} c/kWh, cheapest hour {cheap_hour:02d}:00.",
        (
            f"Every appliance at its own cheapest start would reach {unconstrained_peak:.2f} kW: OVER the limit, "
            "so the optimum staggers them."
            if unconstrained_peak > sc.peak_limit_kw + 1e-6
            else f"Every appliance at its own cheapest start stays within the limit ({unconstrained_peak:.2f} kW)."
        ),
        f"Optimal plan, cost EUR {opt_cost:.3f} (starting each when ready: EUR {naive_cost:.3f}):",
    ]
    order = sorted(sc.appliances, key=lambda a: optimal[a.id])
    for a in order:
        start, own = optimal[a.id], cheapest[a.id]
        extra = appliance_cost(sc, a, start) - appliance_cost(sc, a, own)
        moved = "at its own cheapest start" if start == own else (
            f"its own cheapest start {sc.slot_to_time(own)}, +EUR {extra:.3f} to avoid overload"
        )
        lines.append(
            f"- {a.id} ({a.duration_slots * 15} min, peak {a.peak_kw:.1f} kW, window {sc.slot_to_time(a.earliest_slot)}-"
            f"{sc.boundary_to_time(a.deadline_slot)}): {sc.slot_to_time(start)}-"
            f"{sc.boundary_to_time(start + a.duration_slots)}, {moved}"
        )
    links = []
    for prev, nxt in zip(order, order[1:]):
        end = optimal[prev.id] + prev.duration_slots
        gap = optimal[nxt.id] - end
        if gap == 0:
            links.append(f"{nxt.id} starts as {prev.id} ends")
        elif gap < 0:
            links.append(f"{nxt.id} overlaps {prev.id} by {-gap * 15} min (combined load stays within the limit)")
        else:
            links.append(f"{nxt.id} starts {gap * 15} min after {prev.id} ends")
    if links:
        lines.append("Pattern: " + "; ".join(links) + ".")
    return "\n".join(lines)


# ── Library ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Case:
    id: str
    type: str
    date: str
    features: dict[str, list[float]]
    text: str


def build_library(
    refit_dir: str | Path,
    price_csv: str | Path,
    out_path: str | Path = LIBRARY_PATH,
    *,
    exclude_dirs: tuple[str | Path, ...] = ("data/scenarios", "data/scenarios_15min"),
    per_type: int = 30,
    seed: int = 7,
    date_to: date = date(2025, 9, 30),
    peak_limit_kw: float = 3.5,
    houses: tuple[int, ...] = refit.ALL_HOUSES,
    tariff: Tariff = Tariff(),
) -> dict:
    rng = np.random.default_rng(seed)
    excluded = {date.fromisoformat(s.date) for d in exclude_dirs if Path(d).exists() for s in load_scenarios(d)}
    pool, base_loads, _ = load_household_data(refit_dir, houses)
    days = price_data.to_daily_slots(price_data.load_price_csv(price_csv))
    days = days[[d <= date_to for d in days.index]]
    # Type E uses the highest-peak days of the period: most Dec 2022 crisis days are in the main benchmark.
    # Few winter days are volatile enough for type D, so that type may have fewer cases.
    chosen = select_days(days, rng, crisis=None, per_type=per_type, exclude=excluded, allow_fewer=True)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    base_houses = list(rng.permutation(houses))
    written = 0
    with out.open("w", encoding="utf-8") as fh:
        for scenario_type, type_days in chosen.items():
            for i, day in enumerate(type_days, 1):
                house = int(base_houses[written % len(base_houses)])
                scenario = compose_scenario(
                    scenario_id=f"L-{scenario_type}{i:02d}", scenario_type=scenario_type,  # type: ignore[arg-type]
                    day=day, spot_eur_per_kwh=days.loc[day].to_numpy(), base_load_kw=base_loads[house],
                    profile_pool=pool, fixed_appliances=refit.fixed_appliances(house), rng=rng, tariff=tariff,
                    peak_limit_kw=peak_limit_kw,
                )  # fmt: skip
                optimal = solve_milp(scenario).schedule
                record = {
                    "id": scenario.id, "type": scenario_type, "date": scenario.date, "house": house,
                    "features": features(scenario), "text": example_text(scenario, optimal),
                }  # fmt: skip
                fh.write(json.dumps(record) + "\n")
                written += 1
    manifest = {
        "cases": written, "per_type": per_type, "seed": seed, "price_csv": str(price_csv),
        "price_days_up_to": date_to.isoformat(), "excluded_benchmark_days": len(excluded),
        "days": {t: [d.isoformat() for d in ds] for t, ds in chosen.items()},
    }  # fmt: skip
    out.with_name("manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def load_library(path: str | Path = LIBRARY_PATH) -> list[Case]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [Case(r["id"], r["type"], r["date"], r["features"], r["text"]) for r in map(json.loads, filter(None, lines))]


class Retriever:
    """k most similar solved days, as a block of text for the agents' messages."""

    def __init__(self, cases: list[Case], k: int = TOP_K):
        self.cases, self.k = cases, k

    def retrieve(self, scenario: Scenario) -> list[tuple[Case, float]]:
        query = features(scenario)
        dates = {scenario.date}  # never retrieve the day itself (cannot happen by construction; kept as a guard)
        scored = [(c, similarity(query, c.features)) for c in self.cases if c.date not in dates]
        return sorted(scored, key=lambda cs: cs[1], reverse=True)[: self.k]

    def __call__(self, scenario: Scenario) -> str:
        examples = [f"Example {i} ({c.id}, similarity {s:.2f}):\n{c.text}" for i, (c, s) in enumerate(self.retrieve(scenario), 1)]
        return (
            "Worked examples: similar past days solved optimally. Their prices and appliances differ from today, so "
            "use them as patterns for staggering, not as answers; always check today's prices and loads with your tools.\n\n"
            + "\n\n".join(examples)
        )


_default: Retriever | None = None


def default_retriever() -> Retriever:
    global _default
    if _default is None:
        _default = Retriever(load_library())
    return _default
