# Language-model agents for home energy management: two Master's theses

University of Oulu, Information Processing Science, Design Science Research. Author: Hoan Le.
This repository holds two theses:

| Thesis | Text | Artifact |
|---|---|---|
| **Follow-up (current, this branch `new-thesis/home-gateway`):** *Small Language Models for Smart Home Energy Management: Interpreting Household Plans and Configuring an Optimiser on Local Hardware*. Supervisors: Yueqiang Xu, Paula Alavesa | `gateway_body.tex` → `gateway_thesis.tex` / `.pdf` | `prototypes/` |
| **First:** *A Hierarchical ReAct Multi-Agent Pipeline for Residential Appliance Load Scheduling*. Supervisor: Yueqiang Xu | `main.tex` | `src/hems/` |

The two are kept apart: prototype numbers are never cited in `main.tex`, and the prototypes share no code
with `src/hems/` apart from the unused `industrial_machine` appliance kind.

# Follow-up thesis: small language models on a home energy gateway

**RQ:** How can small language models on a home energy gateway reliably interpret household plans and
configure an optimiser?

- **SQ1** (interpreting household plans): how accurately does a small model turn household plans into
  optimiser requirements, and what do checks and a cloud fallback add?
- **SQ2** (configuring an optimiser): can a small model configure the optimiser from the house's history as
  well as a cloud model and better than an automatic tuner?
- **SQ3** (local hardware): does the saving of running the model on the gateway outweigh its cost in time,
  energy, money and privacy?

Method: a systematic literature review (Kitchenham, PRISMA-P protocol in `docs/slr_protocol_prisma_p.md`)
as the rigor cycle of the design science research. Plan: `docs/protocol_home_gateway.md` and the plan page
`docs/gateway_thesis_plan.html`.

## Design

One home energy gateway (Raspberry Pi 5 16 GB or a mini PC) runs everything locally:

- **EMHASS 0.18.4** as the MPC, in its own container without Home Assistant, called over local HTTP with
  JSON (`POST /action/naive-mpc-optim`, `GET /api/v1/plan`). It schedules the EV charger, the dishwasher,
  the washing machine, the heat pump (thermal load) and the home battery; EMHASS keeps its default
  settings (cost function `profit`, no battery-first or self-consumption rules).
- **The harness**: tools, the checker and the commit gate. The model reaches EMHASS only through the
  harness, and the harness replans every hour without the model.
- **The control layer**, every 15 minutes: holds the planned grid exchange and falls back to rules.
- **Four agents** on a local small model through Ollama: the Household Assistant (ReAct; reads a plan
  through `plan_schedule`, commits or asks) and the Configurator (weekly PV derating and battery reserve)
  are built; the Monitor and the Explainer are designed. A cloud LLM is an optional fallback.
- **Models** (US/EU-developed only): Gemma 4 E4B (main), Gemma 4 E2B, Ministral 3 8B and 3B, Nemotron 3
  Nano 4B; GPT-6 Luna as the cloud LLM.

## Prototypes (`prototypes/`, all exploratory)

| Folder | What it is |
|---|---|
| `plan_pilot/` | structured-call reader; the 22 test plans (`plans.json`, exact wording in `archive/`) and 14 development plans (`plans_dev.json`) |
| `react_gateway/` | the Household Assistant as a ReAct agent (`agent.py`, `plan_schedule`); app outputs in `out/app/` |
| `closed_loop/`, `home_gateway/` | planning pilot and closed loop on the digital twin of OPSD `residential4` |
| `configurator_pilot/` | Configurator vs auto-tuner, default and expert-tuned MPC over weekly windows (SQ2) |
| `emhass_gateway/` | the Household Assistant with EMHASS; the one-device test (EMHASS, harness and model on shared cores) |
| `edge_bench/`, `edge_kit/` | speed on local hardware; scripts for the Raspberry Pi 5, the mini PC and a power meter (SQ3) |
| `heldout/` | materials for the registered run: 120 scenario cards, keying guide, power analysis, `run_heldout.py`, `confirm_heldout.py` |
| `slr/` | literature search, title/abstract and full-text screening (`fulltext/`) |
| `designed_agents/` | prompts of the Monitor and the Explainer |
| `hipe/`, `opsd/`, `heatpump/` | data exploration |

Data of the prototypes is in `data/raw/` of the main checkout (gitignored). Agent runs need `.env`; set
`LANGSMITH_TRACING=false`.

## Building the thesis

```bash
uv run python build_gateway_thesis.py     # gateway_body.tex -> gateway_thesis.tex (citations written out)
latexmk -xelatex gateway_thesis           # after VS Code's LaTeX auto-build has finished
```

Edit only `gateway_body.tex` (`\parencite`/`\textcite`; citation keys in `build_gateway_thesis.py`), never
`gateway_thesis.tex`. Delete the `gateway_thesis` aux files before `latexmk` if VS Code built at the same time.
`gateway_thesis_overleaf.zip` holds the `.tex` and its images for Overleaf.

Figures (`attachments/gateway/`):

| Figure | Source |
|---|---|
| 1.1 | Excalidraw (`home_energy_system.excalidraw`) |
| 1.2 | `tools/make_home_energy_system_fig.py --thesis attachments/gateway/home_energy_system_slm` |
| 4.1 architecture | `tools/flow_figs/make_architecture.py` |
| 4.2 `plan_schedule` | `tools/flow_figs/plan_schedule.svg` |
| 4.3 how each agent decides | `tools/flow_figs/make_agent_flow.py` |
| 4.4 one day at runtime | `tools/flow_figs/runtime_day.svg` |
| 4.5 example plan | `tools/make_example_day_fig.py` (from the stored app output of plan S6) |
| 4.6 user app | the plan page |
| 4.7 request path | `tools/flow_figs/request_path.svg` |

`uv run python tools/flow_figs/export.py` turns the SVGs of Figures 4.1 to 4.4 and 4.7 into PNGs (headless
Chrome); run the `make_*.py` generators first. The PNGs are then cropped to their content.

## Status

Chapters 1 to 7 are drafted; parts without results say "In process", and all prototype results are exploratory. Still open: registering the hypotheses,
collecting the 120 held-out plans and running the registered evaluation, the full-text screening of the
remaining reports and Scopus search C, and the measurements on the Raspberry Pi 5 and the mini PC.

# First thesis: hierarchical ReAct multi-agent pipeline

Thesis text in `main.tex`, DSR artifact in `src/hems/`.

## Setup

```bash
uv sync                      # Python 3.12 + dependencies into .venv
cp .env.example .env         # add OPENAI_API_KEY / GROQ_API_KEY / LANGSMITH_API_KEY
uv run pytest                # offline test suite (no API calls)
```

Compile the thesis with XeLaTeX (`latexmk`; VS Code LaTeX Workshop is preconfigured).

## Pipeline

| System | Module | Role |
|---|---|---|
| `multi_duo` | `agents/multi_agent.py` | Multi-Agent Pipeline (LangGraph): Orchestrator agent → `profile_data()` → Scheduler agent → `verify_schedule()` → Orchestrator agent (summary); verification loops back to the Scheduler agent if problems remain (max 2 rounds). Two LLM agents; the two functions use no language model |
| `multi_duo_thoughts` | `agents/multi_agent.py` | the same pipeline with explicit Thoughts (a required `thought` argument on every tool call) |
| `single_harness`, `single_harness_thoughts` | `agents/harness_agent.py` | one agent in the same harness (`agents/harness.py`): `profile_data()` → agent → `verify_schedule()` (feedback in the same conversation, max 2 rounds) → the agent writes the household message. Same tools as the Scheduler agent; exploratory, for comparing one agent with two |
| `single` | `agents/single_agent.py` | one ReAct agent with all eight tools and the combined prompt |
| `milp` | `solvers/milp.py` | PuLP/CBC ground truth |
| `naive` | `solvers/naive.py` | every appliance starts at its default (earliest) time |

All systems are scored by one function, `core/evaluate.py`. The eight tools (`tools/__init__.py`)
are shared: the Scheduler agent gets the scheduling and load tools plus `optimize_schedule`, the
baseline gets all eight.

The four-agent designs evaluated earlier (`multi`, `multi_v3`, `multi_rag`, `multi_rag_opt`, `multi_lean`:
Orchestrator, Appliance Profiler, Price-Aware Scheduler, Conflict Resolver) were removed from the code on
16 October 2026; their recorded results stay in `results/` and the analysis still reads them.

### Watching the pipeline in LangGraph Studio

`langgraph.json` registers the pipeline as the graph `multi_agent_pipeline` (`src/hems/studio.py`),
built exactly as the system registry builds it. Not used by the evaluation.

```bash
PYTHONIOENCODING=utf-8 uv run --extra studio langgraph dev --port 2024
```

This opens LangGraph Studio (EU region: `https://eu.smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`;
a LangSmith login is needed). Start a run with an empty `request` to use the scenario's own request. The
assistant's configuration chooses what runs:

| Field | Default | Choices |
|---|---|---|
| `scenario` | `data/scenarios_q2/Q2-PH03-35.json` | any scenario JSON, relative to the thesis root |
| `variant` | `multi_duo` | `multi_duo_thoughts` (explicit Thoughts, the demo) |
| `model` | `gpt-6-luna` | any name in `agents/llm.py` (e.g. `gpt-4o-mini`, or `gpt-oss-20b` with Ollama running) |

Each run calls the language model (GPT-6 Luna: about USD 0.001 per run).

## Workflow

```bash
# 0. development / pilots without real data (flagged synthetic, never thesis results)
uv run hems synth --out data/pilot
uv run hems demo data/pilot/SYN-D01.json --system multi_duo --model gpt-6-luna
uv run hems demo data/pilot/SYN-D01.json --system multi_duo --review     # human-in-the-loop approval

# 1. benchmark from real data (see data/README.md)
uv run hems refit-inspect --refit data/raw/refit
uv run hems build --refit data/raw/refit --prices data/raw/prices_fi.csv --out data/scenarios

# 2. evaluation (resumable; rerun the same command after an interruption)
uv run hems run --scenarios data/scenarios --systems milp naive single multi_duo \
                --models gpt-6-luna --runs 3 --out results/runs.jsonl

# 3. Chapter 5 tables/figures -> results/tables/*.tex, results/figures/*.pdf
uv run hems analyze --runs results/runs.jsonl --scenarios data/scenarios --out results
```

## Methodological settings (state in Chapter 3)

- **Cost** = consumer price (spot + margin + transfer + electricity tax, + VAT; `data/tariff.py`) × flexible
  appliance energy. Keeps costs positive on negative-price days so the optimality gap is defined.
- **Infeasible agent schedules** (window/peak violation or no schedule) are scored at the naive cost;
  feasibility rate is reported separately.
- **Metrics**: optimality gap %, savings captured `(naive − agent)/(naive − MILP)`, conflict resolution
  rate over scenarios where independently cheapest starts overload the household, per-appliance saving
  vs naive, latency, tokens, USD.
- **Statistics**: Wilcoxon signed-rank on per-scenario means over 3 runs, `zero_method="pratt"`,
  effect size r = |Z|/√N; Spearman for appliance characteristics (SQ2).
- **Peak limit** 8 kW, the Energy Authority's power-charge threshold, as a hard limit per 15-min slot (raised per
  scenario only if infeasible; recorded in `notes`). The benchmarks built before 20 Oct 2026 also used a stylised
  3.5 kW level (the only level of the first benchmarks); it had no source and is not used for new runs.
- **REFIT houses**: all except 12 (no flexible appliances) and 19 (washing machine shows no heating phase);
  see `EXCLUDED_HOUSES` in `data/refit.py`.
- **Types C–F** use repeated cycles of the three REFIT appliance kinds to reach 4–5 loads.
