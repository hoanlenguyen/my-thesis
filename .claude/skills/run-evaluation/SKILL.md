---
name: run-evaluation
description: Run the gateway thesis's pilots and evaluations (plan pilot, ReAct Household Assistant, Configurator, EMHASS gateway, edge benchmark, the held-out runner), keep results comparable after code changes, and summarise them. Use when asked to run a pilot, a model comparison, the registered evaluation, or to show results.
---

# Run and report the gateway evaluations

No held-out plans are written (author's decision, 26 Nov 2026): SQ1 runs on the 22 test and 14 development plans
and stays exploratory. H4 (Configurator, held-out weeks) and H5 (hardware) are registered before their run. The 22
test plans are never used for tuning (develop on `plans_dev.json`).

## Before running

1. `uv run pytest -q` passes (the prototypes import the `hems` package in `src/hems/`).
2. `.env` has the keys (OpenAI for GPT-6 Luna); `LANGSMITH_TRACING=false`. Never print key values.
3. Local models: the Ollama server is up (`curl -s http://127.0.0.1:11434/api/version`); if not, start
   `"/c/Users/Admin/AppData/Local/Programs/Ollama/ollama.exe" serve` in the background.
4. EMHASS runs (Sections 5.4.1, 5.4.2 and the registered run): Docker Desktop running and the container from
   `prototypes/emhass_gateway/docker-compose.yml` up (EMHASS 0.18.4, pinned by digest, no Home Assistant).
5. Data in `data/raw/` of the main checkout (`--raw-dir D:/Study/my-thesis/data/raw` from a worktree).
6. **Comparability:** results are comparable only when produced by the same prompt, tools, checker and
   optimiser. Before rerunning after such a change, move the old output to the folder's `out/archive/` (or
   `archive/`) and say so; never mix rows of two versions in one file.

## Running (from the repository root)

| What | Command | Output |
|---|---|---|
| Plan pilot (Table 5.3) | `uv run python prototypes/plan_pilot/pilot.py --models gemma4-e4b gpt-6-luna --plans prototypes/plan_pilot/plans_dev.json --out <file>` | JSONL per model and plan |
| Household Assistant, ReAct (Section 5.2) | `uv run python prototypes/react_gateway/agent.py --raw-dir <raw> --models gemma4-e4b --plans prototypes/plan_pilot/plans_dev.json --loop` | `react_gateway/out/results.jsonl`, app views in `out/app/<model>/` |
| Its summary | `uv run python prototypes/react_gateway/summary.py --plans prototypes/plan_pilot/plans_dev.json` | decisions, recall, met |
| Configurator (SQ2, Tables 5.4 and 5.6) | `uv run python prototypes/configurator_pilot/configurator.py --raw-dir <raw> --models gemma4-e4b gpt-6-luna --start 2016-10-03 --weeks 8 --tune-start 2016-06-06 --site DE_KN_residential4 --resume` | `configurator_pilot/out/` |
| Household Assistant with EMHASS (Section 5.4.1) | `uv run python prototypes/emhass_gateway/emhass_gateway.py --raw-dir <raw> --model gemma4-e4b` | `emhass_gateway/out/results.jsonl` |
| One-device test (Section 5.4.2) | `prototypes/emhass_gateway/run_onedevice.ps1`, then `onedevice_summary.py` | `emhass_gateway/out/onedevice/` |
| Edge benchmark (SQ3) | `uv run python prototypes/edge_bench/bench.py --device laptop-gpu --model gemma4-e4b`; on a device, `prototypes/edge_kit/run_device.sh` | `edge_bench/out/` |
| Plan runs, three repeats (SQ1, descriptive) | `uv run python prototypes/heldout/run_heldout.py --raw-dir <raw> --plans prototypes/plan_pilot/plans.json --emhass http://localhost:5001 --runs 3 --out <file>` | four set-ups x models |
| Registered run (after registration only) | Configurator held-out weeks and the year simulation; `confirm_heldout.py` tests H4 and H5 | H4, H5 report |

- The 22 test plans are `prototypes/plan_pilot/plans.json`; use them only for the reported test runs, never to
  change a prompt, a tool or a rule.
- Run long jobs with `run_in_background`, writing output to a log in the scratchpad, and resume with the same
  command (`--resume` where the runner has it). On CPU, Ollama needs `--num-thread` equal to its cores.
- A provider or network error is not a result: rerun it, never record it as a failed answer.

## Reporting

Per model and plan: constraint precision and recall against the answer key, decision right (commit or ask),
requirements met in the closed loop, latency (mean and p95), tokens and USD; for the Configurator, saving
against the default MPC in EUR and the share of the rules-to-perfect-foresight gap closed. Separate model
behaviour (wrong reading, asks when it should commit, invalid output) from infrastructure (Ollama, EMHASS,
network). Compare with archived runs only when the prompt, tools and optimiser were the same. Numbers that go into
`gateway_body.tex` must match the output files; then rebuild and compile with the `compile-thesis` skill.
