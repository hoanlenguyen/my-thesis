# EMHASS gateway demonstration (option B, exploratory)

Not part of the thesis evaluation: the design keeps its own MPC. This demonstrates the two-device deployment of
Figure 1.2 with an optimiser households already run:

| Device | Here (simulated) | Later (real) |
|---|---|---|
| Home energy gateway | Docker on the laptop, limited to a Raspberry Pi 5's 4 cores and 8 GB: EMHASS 0.18.4 (REST, no Home Assistant) | Raspberry Pi 5, same containers (arm64) |
| Companion device | the laptop's Ollama (Gemma 4 E4B), reached by the gateway over the network | the laptop or a mini PC |

The Household Assistant is the ReAct agent of `react_gateway/agent.py`, unchanged (prompt, tools, checker). Only
the optimiser behind `plan_schedule` differs: `emhass_gateway.py` sends the checked constraints and the forecasts to
EMHASS (`naive-mpc-optim`) instead of solving the thesis MPC.

## Run

```bash
docker compose -f prototypes/emhass_gateway/docker-compose.yml up -d emhass          # gateway: EMHASS on :5001
docker compose -f prototypes/emhass_gateway/docker-compose.yml run --rm assistant --ids DS1   # one dev plan
docker compose -f prototypes/emhass_gateway/docker-compose.yml run --rm assistant --out /out/dev.jsonl   # all 14
```

Ollama must be running on the laptop (the companion). The assistant container reaches it at
`host.docker.internal:11434`; `COMPANION=http://<host>:11434` points it elsewhere. Without Docker for the harness:
`uv run python prototypes/emhass_gateway/emhass_gateway.py --ids DS1` (EMHASS at `localhost:5001`, Ollama at
`OLLAMA_HOST`). App answers go to `out/gateway/app/<model>/<plan>.json`.

On a real Raspberry Pi 5 (64-bit OS, Docker): the same compose file, with `COMPANION` set to the laptop's address;
on the laptop Ollama must listen on the network (`OLLAMA_HOST=0.0.0.0`) and the firewall must allow port 11434.
Check that the pinned EMHASS image has an arm64 build.

## Runs (17 Nov 2026, Gemma 4 E4B, 14 dev plans, gateway containers limited to 4 cores / 8 GB)

**Current: heat pump as an EMHASS thermal load** (`out/gateway/dev.jsonl`). The twin's house model maps exactly onto
EMHASS's `thermal_config` room model (see the docstring of `emhass_gateway.py`); the comfort band EMHASS gets is
clipped to what the heat pump can reach, and the gateway checks EMHASS's predicted temperature against the band the
household asked for.

- 14 of 14 decisions match the answer key; items 16 right, 0 extra, 0 missed. Every committed plan meets its
  requirements on EMHASS's schedule, except the two the design allows: a car charge due after the last published
  price (DA1, planned when the prices are out) and one the charger cannot complete in time (DX1, charged as far as
  possible with a warning).
- EMHASS solved all 12 problems with status Optimal, median 0.6 s, at most 2.4 s; message to app answer median 6.6 s,
  at most 12.9 s, almost all of it model time on the laptop GPU.
- DX2 ("on holiday till Friday 6pm, away mode, but keep it at 22"): the predicted temperature misses the 22 C band,
  so the gateway asks (as with the thesis MPC). The model's answer carried no question text in this run.
- DS3 (21-22 C from 6 to 8): the band is held at 21.0-21.4 C; the heat pump uses 14.5 kWh over the horizon.

**First run: heat pump as a fixed load** (`out/gateway/dev_v1_heatpump_fixed.jsonl`): 13 of 14 decisions, the same
13 as the agent with the thesis MPC. DX2 was committed, because the indoor temperature was reported as held in any
requested band, so the conflict was not exposed.

**Companion offline** (`COMPANION` pointing at a closed port): the gateway answers at once that the message was not
read and the home keeps the last confirmed plan; EMHASS is not called.

Limitations: one COP per request (the forecast mean) instead of one per 15 min; the car charge is rounded up to
whole 15-min steps at 3.7 kW (DS1: 18.5 kWh planned for 18.0 needed); EMHASS needs an end state of charge for the
battery (set to the charge now), where the thesis MPC values the energy left; one run on the development plans only.
Not comparable with the thesis results.
