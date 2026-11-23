#!/usr/bin/env bash
# Edge kit (22 Nov 2026): every measurement of the household device in one command. See README.md.
#
#   DEVICE=pi5-16gb RAW_DIR=$HOME/raw SHELLY=192.168.1.50 bash prototypes/edge_kit/run_device.sh
#
# Phases, in order (each start and end is logged to $OUT_DIR/events.jsonl, so the power log can be cut by phase):
#   setup            start EMHASS and Ollama, pull the model, build the Python environment
#   idle_no_model    5 min, gateway running, model not loaded: the gateway's own idle power
#   idle_model       5 min, model loaded: the extra idle power of keeping it in memory
#   bench            the 22 pilot plans through the edge benchmark (one structured call per plan)
#   mpc              the closed-loop pilot's hourly MPC, timed on the device
#   onedevice_*      the one-device test: the Household Assistant with EMHASS on DS1-DS4 while a probe times the
#                    gateway's background work; unprioritised (all cores) and prioritised (one core fewer, low weight)
#   idle_end         2 min
# DRY_RUN=1 prints the commands instead of running them. ONLY="bench mpc" runs only those phases (setup always runs).
set -euo pipefail

: "${DEVICE:?set DEVICE, e.g. pi5-16gb or ryzen-minipc}"
: "${RAW_DIR:?set RAW_DIR to the folder with the raw data (see README.md)}"
MODEL="${MODEL:-gemma4-e4b}"
OLLAMA_MODEL="${OLLAMA_MODEL:-gemma4:e4b}"
IDS="${IDS:-DS1 DS2 DS3 DS4}"
CORES="$(nproc)"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
export DEVICE RAW_DIR
export OUT_DIR="${OUT_DIR:-$HERE/out/$DEVICE}"
COMPOSE=(docker compose -f "$HERE/docker-compose.device.yml")
mkdir -p "$OUT_DIR"
EVENTS="$OUT_DIR/events.jsonl"

run() { if [[ "${DRY_RUN:-0}" == 1 ]]; then echo "+ $*"; else "$@"; fi; }
event() { echo "{\"t\": $(date +%s.%N | cut -c1-14), \"event\": \"$1\", \"phase\": \"$2\"}" >> "$EVENTS"; echo "== $1 $2 $(date -Is)"; }
wanted() { [[ -z "${ONLY:-}" || " $ONLY " == *" $1 "* ]]; }
pause() { if [[ "${DRY_RUN:-0}" == 1 ]]; then echo "+ sleep $1"; else sleep "$1"; fi; }

# the device, for the record
{
  echo "device: $DEVICE"; echo "date: $(date -Is)"; uname -a || true
  echo "cores: $CORES"; grep -m1 -iE 'model name|^Model' /proc/cpuinfo || true
  free -m 2>/dev/null | head -2 || true; docker version --format 'docker {{.Server.Version}}' 2>/dev/null || true
} > "$OUT_DIR/device.txt"

if [[ -n "${SHELLY:-}" ]]; then  # the power logger runs on the device's own Python for the whole session
  run python3 "$HERE/power_log.py" --shelly "$SHELLY" --out "$OUT_DIR/power.jsonl" &
  LOGGER=$!
  trap '[[ -n "${LOGGER:-}" ]] && kill "$LOGGER" 2>/dev/null || true' EXIT
else
  echo "no SHELLY set: read the meter by hand at each phase (README.md, 'Manual readings')"
fi

event start setup
export MODEL_CPUS="$CORES" MODEL_SHARES=1024 RUN=setup
run "${COMPOSE[@]}" up -d emhass ollama
pause 20
run "${COMPOSE[@]}" exec -T ollama ollama pull "$OLLAMA_MODEL"
# the Python environment, and a check that PuLP's CBC solver runs on this processor (fails here, not hours later)
run "${COMPOSE[@]}" run --rm tools -c "import hems, pulp; m = pulp.LpProblem('check'); x = pulp.LpVariable('x', 0, 1); m += x; m.solve(pulp.PULP_CBC_CMD(msg=False)); assert pulp.LpStatus[m.status] == 'Optimal'; print('python environment and CBC ready', pulp.__version__)"
run "${COMPOSE[@]}" exec -T ollama ollama stop "$OLLAMA_MODEL" || true
event end setup

if wanted idle; then
  event start idle_no_model; pause 300; event end idle_no_model
  run "${COMPOSE[@]}" exec -T ollama ollama run "$OLLAMA_MODEL" "Reply with OK." > /dev/null
  event start idle_model; pause 300; event end idle_model
fi

if wanted bench; then
  event start bench
  run "${COMPOSE[@]}" run --rm tools prototypes/edge_bench/bench.py --device "$DEVICE" --host http://ollama:11434 \
    --model "$MODEL" --threads "$CORES" --out-dir /out
  event end bench
fi

if wanted mpc; then
  event start mpc
  run "${COMPOSE[@]}" run --rm tools prototypes/edge_bench/mpc_time.py --device "$DEVICE" --raw-dir /data --out-dir /out
  event end mpc
fi

if wanted onedevice; then
  for spec in "unprioritised $CORES 1024" "prioritised $((CORES > 1 ? CORES - 1 : 1)) 128"; do
    read -r name cpus shares <<< "$spec"
    export RUN="$name" MODEL_CPUS="$cpus" MODEL_SHARES="$shares"
    event start "onedevice_$name"
    run "${COMPOSE[@]}" up -d --force-recreate ollama probe
    pause 20
    run "${COMPOSE[@]}" exec -T ollama ollama run "$OLLAMA_MODEL" "Reply with OK." > /dev/null
    event start "probe_idle_$name"; pause 120; event end "probe_idle_$name"  # baseline: probe on, model loaded, idle
    # shellcheck disable=SC2086
    run "${COMPOSE[@]}" run --rm assistant --model "$MODEL" --out "/out/plans_$name.jsonl" --ids $IDS
    pause 60
    run "${COMPOSE[@]}" stop probe
    event end "onedevice_$name"
  done
fi

event start idle_end; pause 120; event end idle_end
run "${COMPOSE[@]}" down
echo "done: $OUT_DIR. Then: uv run python prototypes/edge_kit/edge_energy.py --dir $OUT_DIR"
