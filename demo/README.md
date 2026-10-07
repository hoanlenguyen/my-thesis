# HEMS agent demo

A small web app that replays the recorded thesis results: for each household-day it shows the prices,
what every system recommends (multi-agent pipeline, single agent, LLM without tools, smart timer,
Home Assistant cheapest hours, EMHASS, MILP optimum, no scheduling), the cost and saving of each
recommendation, its explanation and the resulting household load against the peak limit.
Nothing is run live; the data comes from `results/` via the exporter.

Theme, layout and components are adapted from the Low-carbon-alerts (Hiilivahti) app:
Nuxt 4, Nuxt UI 4, Tailwind 4 and Unovis charts.

## Run

```bash
# 1. export the recorded results (from the thesis repo root, after new runs)
uv run python tools/export_demo_data.py
#    household profiles from the raw REFIT files (once; ~10 min, needs data/raw/refit)
uv run python tools/export_household_profiles.py

# 2. start the demo (from demo/)
pnpm install
pnpm dev          # http://localhost:3001
```

`pnpm build` produces a static site in `.output/public` that can be hosted anywhere.

## Pages

- `/`: share of the achievable saving each system captures, valid schedules, time and API cost per day.
- `/households`: the 18 REFIT households; each profile lists all monitored appliances (scheduled,
  shiftable, not shiftable) with power, energy per day and typical use by hour from the 2013-2015 recordings.
- `/days`: all household-days of both benchmarks, filterable by scenario type.
- `/days/<benchmark>/<id>`: one day: the price the household pays by hour (or every 15 min), every
  system's schedule on a 24-hour timeline plus the household's non-shiftable appliances with their typical
  use, and for the selected system its recommendation card and load chart. A day's base load and fixed
  appliances come from one household; its cycles to schedule are REFIT cycles drawn from all households.
- `/today`: today's Nord Pool FI price by hour, fetched live from Sähkötin and converted with the
  thesis tariff (the only live part of the demo).

## "Try it" page (live)

`/try` runs the real systems on a profile entered in the browser. It needs the local Python API:

1. `scripts\demo-api.cmd` (or `uv run --extra demo uvicorn hems.demo_api:app --port 8001`) in the thesis root.
   Uses `ENTSOE_API_KEY` (day-ahead prices; the base load is the typical REFIT household shape) and
   `OPENAI_API_KEY` (Multi-Agent Pipeline, about USD 0.003 per run) from `.env`. EMHASS is included when the
   `emhass-thesis` Docker container answers on localhost:5000.
2. `scripts\demo-dev.cmd` (or `pnpm dev --port 3001` here). The dev server proxies `/api` to port 8001
   (`nitro.devProxy` in `nuxt.config.ts`). A static build calls `NUXT_PUBLIC_API_BASE` instead.
