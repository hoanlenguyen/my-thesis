from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from hems.data.prices import load_price_csv, to_daily_slots
from hems.data.refit import detect_cycles
from hems.data.scenarios import INSTANCES_PER_TYPE, select_days
from hems.data.tariff import Tariff


def test_detect_cycles_merges_short_gaps_and_builds_15min_profiles() -> None:
    index = pd.date_range("2014-01-01 08:00", "2014-01-01 14:00", freq="8s")
    watts = pd.Series(1.0, index=index)
    watts["2014-01-01 09:00":"2014-01-01 09:30"] = 2000  # heating
    watts["2014-01-01 09:35":"2014-01-01 10:29:59"] = 300  # after a 5-min pause: same cycle
    watts["2014-01-01 12:00":"2014-01-01 12:10"] = 500  # too short to count
    cycles = detect_cycles(watts)
    assert len(cycles) == 1
    profile = cycles[0]
    assert len(profile) == 6  # 90 min -> 6 slots
    assert profile[0] == pytest.approx(2.0, abs=0.01)
    assert profile[-1] == pytest.approx(0.3, abs=0.01)


def test_hourly_prices_expand_to_96_slots_and_dst_days_drop(tmp_path) -> None:
    times = pd.date_range("2022-10-29 00:00", "2022-11-01 00:00", freq="1h", tz="Europe/Helsinki", inclusive="left")
    csv = tmp_path / "prices.csv"
    pd.DataFrame({"timestamp": times.tz_convert("UTC").tz_localize(None), "price": np.arange(len(times), dtype=float) * 10}).to_csv(
        csv, index=False
    )
    days = to_daily_slots(load_price_csv(csv, unit="EUR/MWh", source_tz="UTC"))
    assert date(2022, 10, 30) not in days.index  # DST end: 25-hour day
    assert list(days.index) == [date(2022, 10, 29), date(2022, 10, 31)]
    first = days.loc[date(2022, 10, 29)].to_numpy()
    assert len(first) == 96 and first[0] == first[3] == 0.0 and first[4] == pytest.approx(0.01)


def test_select_days_fills_every_type() -> None:
    rng = np.random.default_rng(0)
    dates = pd.date_range("2022-01-01", "2025-12-31", freq="D").date
    hours = np.arange(96) / 4
    rows = []
    for d in dates:
        amplitude = rng.uniform(0.005, 0.2)
        day = 0.08 + amplitude * np.sin(hours / 24 * 2 * np.pi)
        if d.month in (6, 7) and rng.random() < 0.3:
            day[40:60] = -0.01
        rows.append(day)
    frame = pd.DataFrame(rows, index=dates)
    chosen = select_days(frame, rng)
    assert all(len(v) == INSTANCES_PER_TYPE for v in chosen.values())
    assert not set(chosen["A"]) & set(chosen["B"])
    assert all(d.month == 12 and d.year == 2022 for d in chosen["E"])
    assert all(d.month in (12, 1, 2) for d in chosen["D"])


def test_consumer_price_positive_on_negative_spot() -> None:
    assert (Tariff().consumer_price([-0.05, 0.0, 0.3]) > 0).all()
