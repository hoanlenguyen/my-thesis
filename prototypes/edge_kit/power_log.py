"""Logs the device's power at the wall from a Shelly smart plug, once a second (edge kit, 22 Nov 2026).

Standard library only, so it runs on the device's own Python (``python3 power_log.py ...``). Each line of the log is
one reading: wall-clock time, power in W and, when the plug reports it, its energy counter in Wh. Supports Shelly
Gen2+ plugs (Plus Plug S, ``/rpc/Switch.GetStatus?id=0``) and Gen1 plugs (Plug S, ``/meter/0``); ``--kind`` picks
one, ``auto`` tries Gen2 first. A reading that fails is skipped and counted; the logger never stops on its own.

    python3 prototypes/edge_kit/power_log.py --shelly 192.168.1.50 --out out/edge/pi5/power.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=2) as resp:
        return json.loads(resp.read().decode())


def reader(host: str, kind: str):
    """A function returning (watts, wh_total or None) for the plug at ``host``."""
    base = host if host.startswith("http") else f"http://{host}"

    def gen2() -> tuple[float, float | None]:
        s = get(f"{base}/rpc/Switch.GetStatus?id=0")
        return float(s["apower"]), float(s["aenergy"]["total"]) if "aenergy" in s else None

    def gen1() -> tuple[float, float | None]:
        s = get(f"{base}/meter/0")
        return float(s["power"]), float(s["total"]) / 60 if "total" in s else None  # Gen1 counts watt-minutes

    if kind == "gen2":
        return gen2
    if kind == "gen1":
        return gen1
    try:
        gen2()
        return gen2
    except Exception:
        gen1()  # raises if neither answers
        return gen1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shelly", required=True, help="the plug's address on the home network")
    parser.add_argument("--kind", choices=["auto", "gen1", "gen2"], default="auto")
    parser.add_argument("--every", type=float, default=1.0, help="seconds between readings")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    read = reader(args.shelly, args.kind)
    failed = 0
    print(f"logging {args.shelly} every {args.every} s to {args.out}", flush=True)
    with open(args.out, "a", encoding="utf-8") as out:
        while True:
            t = time.time()
            try:
                w, wh = read()
                out.write(json.dumps({"t": round(t, 2), "w": w, "wh_total": wh}) + "\n")
                out.flush()
            except Exception as exc:  # a missed reading leaves a gap; the analysis integrates over the readings it has
                failed += 1
                if failed % 30 == 1:
                    print(f"reading failed ({failed} so far): {exc}", file=sys.stderr, flush=True)
            time.sleep(max(0.0, args.every - (time.time() - t)))


if __name__ == "__main__":
    main()
