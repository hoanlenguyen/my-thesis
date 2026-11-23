# Edge kit: measuring the gateway on a household device (22 Nov 2026)

One command per device measures what SQ3 and H5 need on the hardware a household could own: the Raspberry Pi 5
with 16 GB and the Ryzen mini PC. Built and tested on the laptop (dry run, compose check, the power logger against a
simulated plug, the energy analysis on synthetic logs with known answers, the benchmark on two plans); not yet run
on either device. This is the last step of the plan: it waits for the devices and a power meter.

| What | How | Feeds |
|---|---|---|
| Time per plan, structured call (22 pilot plans) | `edge_bench/bench.py` against the device's Ollama | Table 5.7 (edge benchmark) |
| Time per MPC solve | `edge_bench/mpc_time.py` on the device | Table 5.7 |
| The Household Assistant with EMHASS on the same cores, and the background work meanwhile | the one-device test (`emhass_gateway`), unprioritised and prioritised, DS1-DS4 | Section 5.4.2 on the device; H5 (p95 per plan, limit 15 min) |
| Idle power without and with the model loaded; energy per plan above idle | power log + `edge_energy.py` | `heldout/year_balance.py` (H5 energy balance) |

## Before the run (once per device)

1. **Operating system:** Raspberry Pi OS Lite 64-bit (Pi 5) or Ubuntu Server 24.04 (mini PC), no desktop, on an SSD
   if possible. Pi 5: the official 27 W power supply and the active cooler, so it does not throttle.
2. **Docker** with the compose plugin, the user in the `docker` group, and `git` and `python3` (both come with the
   systems above).
3. **The code:** clone the repository and check out `new-thesis/home-gateway`.
4. **The raw data** (about 130 MB) into one folder on the device, with these names:
   - `opsd_household/household_data_15min_singleindex.csv` (58 MB)
   - `dwd_konstanz/` (67 MB)
   - `when2heat_de_2015_2018.csv`
   - `prices_de_energycharts_2015_2019.csv`
5. **The power meter** between the wall and the device's power supply, and nothing else on it. A Shelly plug (Plus
   Plug S or Plug S) on the home Wi-Fi is logged automatically; note its address. Any other meter works with manual
   readings (below).
6. Leave the device otherwise idle during the run, in a room at normal temperature.

## The run

```
DEVICE=pi5-16gb RAW_DIR=$HOME/raw SHELLY=192.168.1.50 bash prototypes/edge_kit/run_device.sh
```

`DEVICE` labels the results (`pi5-16gb`, `ryzen-minipc`). The setup step pulls `gemma4:e4b` (about 7 GB), builds
the Python environment and checks that the solver runs on the device's processor; it stops there if it does not.
Then, in order: 5 min idle without the model, 5 min with the model loaded, the 22-plan benchmark, the MPC timing,
the one-device test twice (with all cores, then one core fewer at low weight; 2 min baseline each), 2 min idle.
Expected time: about 3 to 5 hours on the Pi 5, 1 to 2 hours on the mini PC. `DRY_RUN=1` prints the commands;
`ONLY="bench mpc"` runs only those phases (also `idle`, `onedevice`).

Results go to `prototypes/edge_kit/out/<DEVICE>/`: `device.txt`, `events.jsonl` (phase windows), `power.jsonl`,
the benchmark's rows and summary, the MPC timing, the one-device plans and probe samples. Copy the folder back to
the laptop, then:

```
uv run python prototypes/edge_kit/edge_energy.py --dir prototypes/edge_kit/out/pi5-16gb
uv run python prototypes/emhass_gateway/onedevice_summary.py --dir prototypes/edge_kit/out/pi5-16gb
```

`edge_energy.py` writes `energy.json` and prints the `year_balance.py` command for the device.

## Manual readings (a meter without a network interface)

Without `SHELLY`, read the meter's power during each phase (the script prints each phase as it starts) and write
the averages, in W, into `out/<DEVICE>/manual.json`:

```json
{"idle_no_model_w": 0, "idle_model_w": 0, "bench_w": 0,
 "probe_idle_unprioritised_w": 0, "onedevice_unprioritised_w": 0,
 "probe_idle_prioritised_w": 0, "onedevice_prioritised_w": 0}
```

`bench_w` and `onedevice_*_w` are the power while the model answers; the energy per plan is then (that power minus
the phase's baseline) times the time per plan. A logged meter is better: it integrates the power over each plan.

## Known limits

- One device of each kind, one run per setting, as on the laptop; the thesis reports this.
- The Configurator's energy per call is estimated from the benchmark's structured call (similar size), not measured.
- On the Pi, Ollama, EMHASS and the harness are the arm64 builds of the same versions; a slower or failed step there
  is a result, not something to tune.
