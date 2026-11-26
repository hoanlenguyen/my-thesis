# Small Language Models for Smart Home Energy Management: Interpreting Household Plans and Configuring an Optimiser on Local Hardware

Master's thesis, University of Oulu, Information Processing Science (Design Science Research).
Author: Hoan Le. Supervisors: Yueqiang Xu, PhD, Docent, Adjunct Professor; Paula Alavesa, PhD.

Thesis text in `gateway_body.tex` (built into `gateway_thesis.tex` and `gateway_thesis.pdf`); the artifact
and its pilots in `prototypes/`.

## Research questions

**RQ:** How can small language models on a home energy gateway reliably interpret household plans and
configure an optimiser?

- **SQ1** (interpreting household plans): how accurately does a small model turn household plans into
  optimiser requirements, and what do checks and a cloud fallback add?
- **SQ2** (configuring an optimiser): can a small model configure the optimiser from the house's history as
  well as a cloud model and better than an automatic tuner?
- **SQ3** (local hardware): does the saving of running the model on the gateway outweigh its cost in time,
  energy, money and privacy?

Method: a systematic literature review (Kitchenham; PRISMA-P protocol in `docs/slr_protocol_prisma_p.md`)
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

## Setup

```bash
uv sync                      # Python 3.12 + dependencies into .venv
cp .env.example .env         # add OPENAI_API_KEY (cloud LLM); set LANGSMITH_TRACING=false
```

Local models run through Ollama (`ollama serve`); EMHASS runs in Docker (`prototypes/emhass_gateway/
docker-compose.yml`, image pinned by digest). The prototypes read their data from `data/raw/` (gitignored:
OPSD household data, DWD weather, day-ahead prices, When2Heat, the EV sessions).

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

## Building the thesis

```bash
uv run python build_gateway_thesis.py     # gateway_preamble.tex + gateway_body.tex -> gateway_thesis.tex
latexmk -xelatex gateway_thesis           # after VS Code's LaTeX auto-build has finished
```

Edit only `gateway_body.tex` (`\parencite`/`\textcite`; citation keys in `build_gateway_thesis.py`), never
`gateway_thesis.tex`. `gateway_preamble.tex` holds the Oulu template (fonts, cover, captions). Delete the
`gateway_thesis` aux files before `latexmk` if VS Code built at the same time. TeX Live 2026 with XeLaTeX.
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

Chapters 1 to 7 are drafted; parts without results say "In process", and all prototype results are
exploratory. Still open: registering the hypotheses, collecting the 120 held-out plans and running the
registered evaluation, the full-text screening of the remaining reports and Scopus search C, and the
measurements on the Raspberry Pi 5 and the mini PC.
