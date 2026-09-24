"""Nord Pool FI day-ahead prices -> one 96-slot row per local day.

Accepts any CSV with a timestamp column and a price column (e.g. a
parassahko.fi or ENTSO-E export). Hourly prices (before the 1 Oct 2025 switch
to 15-minute MTU, including the Dec 2022 crisis) are repeated x4.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from hems.core.models import SLOT_MINUTES, SLOTS_PER_DAY

UNIT_TO_EUR_PER_KWH = {"EUR/MWh": 1 / 1000, "c/kWh": 1 / 100, "EUR/kWh": 1.0}
LOCAL_TZ = "Europe/Helsinki"


def load_price_csv(
    path: str | Path,
    time_col: str | None = None,
    price_col: str | None = None,
    unit: str = "EUR/MWh",
    source_tz: str = "UTC",
    vat_included: float = 0.0,
    sep: str | None = None,
) -> pd.Series:
    """Return spot EUR/kWh (excl. VAT) indexed by tz-aware local timestamps.

    ``vat_included``: VAT rate already contained in the prices (e.g. 0.255), which is removed.
    """
    df = pd.read_csv(path, sep=sep, engine="python")
    time_col = time_col or next(c for c in df.columns if pd.to_datetime(df[c], errors="coerce").notna().mean() > 0.9)
    price_col = price_col or next(c for c in df.columns if c != time_col and pd.api.types.is_numeric_dtype(df[c]))
    times = pd.to_datetime(df[time_col], utc=False)
    if times.dt.tz is None:
        times = times.dt.tz_localize(source_tz, ambiguous="infer", nonexistent="shift_forward")
    prices = pd.Series(df[price_col].astype(float).to_numpy() * UNIT_TO_EUR_PER_KWH[unit], index=times.dt.tz_convert(LOCAL_TZ))
    prices = prices / (1 + vat_included)
    return prices[~prices.index.duplicated()].sort_index()


def to_daily_slots(prices: pd.Series) -> pd.DataFrame:
    """Index = local date, columns 0..95. DST-change days (92/100 slots) are dropped."""
    step = prices.index.to_series().diff().median()
    end = prices.index[-1] + step
    grid = pd.date_range(prices.index[0], end, freq=f"{SLOT_MINUTES}min", inclusive="left", tz=LOCAL_TZ)
    slotted = prices.reindex(prices.index.union(grid)).ffill().reindex(grid)
    frame = pd.DataFrame({"price": slotted.to_numpy(), "date": grid.date, "slot": grid.hour * 4 + grid.minute // SLOT_MINUTES})
    counts = frame.groupby("date").size()
    full_days = counts[counts == SLOTS_PER_DAY].index
    wide = frame[frame.date.isin(full_days)].pivot(index="date", columns="slot", values="price")
    return wide.dropna()
