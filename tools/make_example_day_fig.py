"""Thesis figure: the plan the Household Assistant (Gemma 4 E4B) committed for pilot plan S6 (20 September 2016).

Reads the stored app output of the ReAct run (no model or optimiser call) and draws its first 24 hours: the planned
power of the car, the washing machine and the home battery against the PV forecast, and the import price.

    uv run python tools/make_example_day_fig.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "prototypes/react_gateway/out/app/gemma4-e4b/S6.json"
OUT = ROOT / "attachments/gateway/example_day_s6.png"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()

    app = json.loads(args.source.read_text(encoding="utf-8"))
    rows = app["timeline_hourly"][: args.hours]
    hours = [r["hour"][-5:] for r in rows]
    x = list(range(len(rows)))
    pv = [r["pv_forecast_kw"] for r in rows]
    car = [r["car_kw"] for r in rows]
    wash = [r["appliances_kw"] for r in rows]
    battery = [r["battery_kw"] for r in rows]  # + charging, - discharging
    price = [r["price_eur_kwh"] for r in rows]
    away = [i for i, h in enumerate(hours) if "18:00" <= h < "22:00"]

    plt.rcParams.update({"font.family": "Times New Roman", "font.size": 10})
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(6.3, 4.6), sharex=True,
                                      gridspec_kw={"height_ratios": [2.6, 1], "hspace": 0.08})
    for ax in (top, bottom):
        if away:
            ax.axvspan(away[0] - 0.5, away[-1] + 0.5, color="0.88", zorder=0, lw=0)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color="0.9", lw=0.6, zorder=0)

    width = 0.75
    top.bar(x, car, width, color="#2a78d6", label="Car charging", zorder=2)
    top.bar(x, wash, width, bottom=car, color="#eb6834", hatch="////", edgecolor="white", lw=0,
            label="Washing machine", zorder=2)
    top.bar(x, battery, width, color="#1baf7a", hatch="....", edgecolor="white", lw=0,
            label="Home battery (below 0: discharging)", zorder=2)
    top.plot(x, pv, color="#b77a00", lw=1.6, ls="--", label="PV forecast", zorder=3)
    top.axhline(0, color="0.4", lw=0.6)
    top.set_ylabel("Power (kW)")
    if away:
        top.text((away[0] + away[-1]) / 2, max(pv) * 0.92, "away", ha="center", va="top", fontsize=9, color="0.35")
    top.legend(loc="upper right", fontsize=8.5, frameon=False, ncol=2)
    top.set_ylim(min(battery) - 0.4, max(pv) + 0.9)

    bottom.step(x, price, where="mid", color="#6250d6", lw=1.6)
    bottom.set_ylabel("Price\n(EUR/kWh)")
    bottom.set_xticks(x[::2], hours[::2])
    bottom.set_xlim(-0.6, len(x) - 0.4)
    bottom.set_xlabel(f"Hour, from {app['household_message']['sent'][:10]} 08:00")
    lo, hi = min(price), max(price)
    bottom.set_ylim(lo - 0.01, hi + 0.01)

    fig.savefig(args.out, dpi=300, bbox_inches="tight")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
