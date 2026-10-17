# A Hierarchical ReAct Multi-Agent Pipeline for Residential Appliance Load Scheduling

Master's thesis (University of Oulu, Information Processing Science) — thesis text in `main.tex`,
DSR artifact in `src/hems/`.

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
| `model` | `gpt-4o-mini` | any name in `agents/llm.py` (e.g. `gpt-oss-20b` with Ollama running) |

Each run calls the language model (GPT-4o-mini: about USD 0.001 per run).

## Workflow

```bash
# 0. development / pilots without real data (flagged synthetic, never thesis results)
uv run hems synth --out data/pilot
uv run hems demo data/pilot/SYN-D01.json --system multi_duo --model gpt-4o-mini
uv run hems demo data/pilot/SYN-D01.json --system multi_duo --review     # human-in-the-loop approval

# 1. benchmark from real data (see data/README.md)
uv run hems refit-inspect --refit data/raw/refit
uv run hems build --refit data/raw/refit --prices data/raw/prices_fi.csv --out data/scenarios

# 2. evaluation (resumable; rerun the same command after an interruption)
uv run hems run --scenarios data/scenarios --systems milp naive single multi_duo \
                --models gpt-4o-mini gpt-oss-20b --runs 3 --out results/runs.jsonl

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
- **Peak limit** default 3.5 kW for the benchmark (raised per scenario only if infeasible; recorded in `notes`).
- **REFIT houses**: all except 12 (no flexible appliances) and 19 (washing machine shows no heating phase);
  see `EXCLUDED_HOUSES` in `data/refit.py`.
- **Types C–F** use repeated cycles of the three REFIT appliance kinds to reach 4–5 loads.
