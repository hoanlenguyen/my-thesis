# HEMS agent demo

A small web app that replays the recorded thesis results: for each household-day it shows the prices,
what every system recommends (Multi-Agent Pipeline, LLM without tools, EMHASS, Home Assistant cheapest
window and cheapest hours, smart timer, MILP optimum, no scheduling), the cost and saving of each
recommendation, its explanation and the resulting household load against the peak limit.
Nothing is run live; the data comes from `results/` via the exporter.

Benchmarks: the held-out set Q2 (confirmatory, default view; `results/confirmation_q2.jsonl`) and the
factorial set v2 (exploratory; `results/main_v2.jsonl`, which also holds the two earlier design
iterations, hidden unless switched on). Both are 96 household-days: price pattern (stable, volatile,
spike, negative) × household load (light, heavy) × peak limit (strict 3.5 kW, realistic 8 kW).

Theme, layout and components are adapted from the Low-carbon-alerts (Hiilivahti) app:
Nuxt 4, Nuxt UI 4, Tailwind 4 and Unovis charts.

## Run

```bash
# 1. export the recorded results (from the thesis repo root, after new runs)
uv run python tools/export_demo_data.py
#    household profiles from the raw REFIT files (once; ~10 min, needs data/raw/refit)
uv run python tools/export_household_profiles.py
#    whole-period estimate per household (re-aggregate only; LLM shares come from Q2)
uv run python tools/estimate_full_period.py --summary

# 2. start the demo (from demo/)
pnpm install
pnpm dev          # http://localhost:3001
```

`pnpm build` produces a static site in `.output/public` that can be hosted anywhere.

## Pages

- `/`: saving compared with no scheduling (pooled over runs, as in the thesis tables) against the optimum,
  share of the optimal saving, valid schedules, time and API cost per day (LLM targets: below 60 s and
  USD 0.10 per recommendation, a missed target is flagged), and the saving by condition (price pattern,
  load, peak limit; SQ2), as in the thesis table `tab:q2-conditions`.
- `/households`: the 18 REFIT households; each profile lists all monitored appliances (scheduled,
  shiftable, not shiftable) with power, energy per day and typical use by hour from the 2013-2015 recordings.
- `/days`: all household-days of both benchmarks, filterable by price pattern, load and peak limit. Days
  whose limit was raised above 3.5 or 8 kW are marked, and so are days with almost nothing to save (no
  scheduling already near the optimum, or breaking the limit while the best valid schedule costs as much).
- `/days/<benchmark>/<id>`: one day: the price the household pays by hour (or every 15 min), every
  system's schedule on a 24-hour timeline plus the household's non-shiftable appliances with their typical
  use, and for the selected system its recommendation card and load chart. A day's base load and fixed
  appliances come from one household; its cycles to schedule are REFIT cycles drawn from all households.
- `/today`: today's Nord Pool FI price by hour, fetched live from Sähkötin and converted with the
  thesis tariff (the only live part of the demo).

## "Try it" page (live)

`/try` runs the real systems on a profile entered in the browser. Each appliance may have several allowed
periods (e.g. 06:00-09:00 and 18:00-22:00); a cycle must start and finish inside one of them. EMHASS is
then left out, since it takes one window per appliance. It needs the local Python API:

1. `scripts\demo-api.cmd` (or `uv run --extra demo uvicorn hems.demo_api:app --port 8001`) in the thesis root.
   Uses `ENTSOE_API_KEY` (day-ahead prices; the base load is the typical REFIT household shape) and
   `OPENAI_API_KEY` (Multi-Agent Pipeline, about USD 0.003 per run) from `.env`. EMHASS is included when the
   `emhass-thesis` Docker container answers on localhost:5000.
2. `scripts\demo-dev.cmd` (or `pnpm dev --port 3001` here). The dev server proxies `/api` to port 8001
   (`nitro.devProxy` in `nuxt.config.ts`). A static build calls `NUXT_PUBLIC_API_BASE` instead.
