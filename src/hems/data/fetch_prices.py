"""Download Nord Pool FI day-ahead spot prices into a CSV that ``load_price_csv`` reads.

Output columns: ``timestamp_utc, price_eur_mwh`` (spot, excl. VAT).

Sources
* ``entsoe``   — ENTSO-E Transparency Platform (bidding zone FI). Official, citable,
  native 15-min resolution from 1 Oct 2025. Needs a free API token
  (register at transparency.entsoe.eu, then e-mail transparency@entsoe.eu with
  subject "Restful API access"); put it in .env as ENTSOE_API_KEY.
* ``elering``  — Elering (Estonian TSO) public Nord Pool price API, no token.
  FI zone with native 15-min resolution from 1 Oct 2025 (hourly before).
* ``sahkotin`` — sahkotin.fi public API, no token. Same Nord Pool FI values but
  hourly only (15-min periods are returned as hourly averages). Fine for
  development; prefer ENTSO-E for the thesis benchmark.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

SAHKOTIN_URL = "https://sahkotin.fi/prices"


def fetch_sahkotin(start: date, end: date) -> pd.DataFrame:
    frames = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(end, chunk_start + timedelta(days=366))
        params = {"start": f"{chunk_start.isoformat()}T00:00:00.000Z", "end": f"{chunk_end.isoformat()}T00:00:00.000Z"}
        response = requests.get(SAHKOTIN_URL, params=params, timeout=120)
        response.raise_for_status()
        rows = response.json()["prices"]
        frames.append(pd.DataFrame({"timestamp_utc": [r["date"] for r in rows], "price_eur_mwh": [r["value"] for r in rows]}))
        chunk_start = chunk_end
    df = pd.concat(frames, ignore_index=True)
    df["timestamp_utc"] = pd.to_datetime(df.timestamp_utc, utc=True)
    return df


ELERING_URL = "https://dashboard.elering.ee/api/nps/price"


def fetch_elering(start: date, end: date) -> pd.DataFrame:
    """Elering (Estonian TSO) Nord Pool price API: FI zone, native 15-min from 1 Oct 2025, hourly before."""
    frames = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(end, chunk_start + timedelta(days=31))
        params = {"start": f"{chunk_start.isoformat()}T00:00:00.000Z", "end": f"{chunk_end.isoformat()}T00:00:00.000Z"}
        response = requests.get(ELERING_URL, params=params, timeout=120)
        response.raise_for_status()
        rows = [r for r in response.json()["data"]["fi"] if r["timestamp"] < pd.Timestamp(chunk_end, tz="UTC").timestamp()]
        frames.append(pd.DataFrame({"timestamp_utc": [r["timestamp"] for r in rows], "price_eur_mwh": [r["price"] for r in rows]}))
        chunk_start = chunk_end
    df = pd.concat(frames, ignore_index=True)
    df["timestamp_utc"] = pd.to_datetime(df.timestamp_utc, unit="s", utc=True)
    return df


AREA_TZ = {"FI": "Europe/Helsinki", "GB": "Europe/London"}


def fetch_entsoe(start: date, end: date, api_key: str | None = None, area: str = "FI") -> pd.DataFrame:
    """Day-ahead prices of a bidding zone, in the zone's currency per MWh (EUR for FI, GBP for GB)."""
    from entsoe.entsoe import EntsoePandasClient

    api_key = api_key or os.environ.get("ENTSOE_API_KEY")
    if not api_key:
        raise SystemExit("ENTSOE_API_KEY is not set (see src/hems/data/fetch_prices.py for how to get one)")
    client = EntsoePandasClient(api_key=api_key)
    tz = AREA_TZ[area]
    series = client.query_day_ahead_prices(area, start=pd.Timestamp(start, tz=tz), end=pd.Timestamp(end, tz=tz))
    series = series[~series.index.duplicated()].sort_index()
    timestamps = pd.DatetimeIndex(series.index).tz_convert("UTC")
    column = "price_gbp_mwh" if area == "GB" else "price_eur_mwh"
    return pd.DataFrame({"timestamp_utc": timestamps, column: series.to_numpy()})


def fetch(source: str, start: date, end: date, out: str | Path, area: str = "FI") -> pd.DataFrame:
    if source == "entsoe":
        df = fetch_entsoe(start, end, area=area)
    elif area != "FI":
        raise SystemExit(f"--area {area} needs --source entsoe")
    else:
        df = {"sahkotin": fetch_sahkotin, "elering": fetch_elering}[source](start, end)
    df = df.drop_duplicates("timestamp_utc").sort_values("timestamp_utc")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.assign(timestamp_utc=df.timestamp_utc.dt.strftime("%Y-%m-%dT%H:%M:%SZ")).to_csv(out, index=False)
    return df
