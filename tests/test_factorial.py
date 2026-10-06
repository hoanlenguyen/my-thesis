"""Factorial benchmark design: regime selection and the within-day crossing of the peak limit."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from hems.data.factorial import LIMITS, LOADS, REGIMES, compose_cell, select_regime_days
from hems.data.synthetic import FIXED, PROFILE_POOL, synthetic_base_load
from hems.data.tariff import Tariff
from hems.solvers.milp import solve_milp


def _days(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = {}
    for i in range(n):
        level, spread = rng.uniform(0.02, 0.2), rng.uniform(0.001, 0.15)
        prices = level + spread * np.sin(np.linspace(0, 2 * np.pi, 96) + rng.uniform(0, 6))
        if i % 10 == 0:
            prices[40:48] = -0.01  # two hours below zero
        rows[date(2024, 1, 1) + timedelta(days=i)] = prices
    return pd.DataFrame.from_dict(rows, orient="index")


def test_regime_days_are_disjoint_and_match_their_regime() -> None:
    days = _days()
    chosen = select_regime_days(days, np.random.default_rng(1), per_cell=4, exclude={date(2024, 1, 1)})
    assert set(chosen) == {(r, lo) for r in REGIMES for lo in LOADS}
    picked = [d for ds in chosen.values() for d in ds]
    assert len(picked) == len(set(picked)) == 4 * len(REGIMES) * len(LOADS)
    assert date(2024, 1, 1) not in picked
    for d in chosen["negative", "light"] + chosen["negative", "heavy"]:
        assert (days.loc[d] < 0).sum() >= 4
    for regime in ("stable", "volatile", "spike"):
        for d in chosen[regime, "light"]:
            assert (days.loc[d] >= 0).all()
    std = lambda r: np.mean([days.loc[d].std() for lo in LOADS for d in chosen[r, lo]])  # noqa: E731
    assert std("stable") < std("volatile")


def test_cell_crosses_the_limit_on_the_same_day_and_appliances() -> None:
    rng = np.random.default_rng(3)
    spot = 0.05 + 0.04 * np.sin(np.linspace(0, 2 * np.pi, 96))
    strict, realistic = compose_cell(
        "VH01", "volatile", "heavy", date(2024, 1, 15), spot, synthetic_base_load(rng), PROFILE_POOL, FIXED, rng,
        Tariff(), 1,
    )  # fmt: skip
    assert (strict.id, realistic.id) == ("VH01-35", "VH01-80")
    assert strict.type == "volatile-heavy-strict" and realistic.type == "volatile-heavy-realistic"
    assert strict.appliances == realistic.appliances and strict.price_eur_per_kwh == realistic.price_eur_per_kwh
    assert strict.peak_limit_kw >= LIMITS["strict"] and realistic.peak_limit_kw == max(LIMITS["realistic"], strict.peak_limit_kw)
    assert len(strict.appliances) == 5
    for s in (strict, realistic):
        assert solve_milp(s).status == "Optimal"
