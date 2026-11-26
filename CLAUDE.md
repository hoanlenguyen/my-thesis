# CLAUDE.md: Small Language Models for Smart Home Energy Management

Master's thesis, University of Oulu, Information Processing Science (Oulu IPS template), Design Science Research.
Full title: "Small Language Models for Smart Home Energy Management: Interpreting Household Plans and Configuring an
Optimiser on Local Hardware". Author: Hoan Le. Supervisors: Yueqiang Xu, PhD, Docent, Adjunct Professor; Paula
Alavesa, PhD. Thesis text in `gateway_body.tex`; the artifact and its pilots in `prototypes/`. Branch `main` (the
earlier `new-thesis/home-gateway` branch points to the same history); the first thesis is kept on `old-thesis`.

## Ground rules

- **Commit or push only when the author asks.** Otherwise make and verify changes, then list the changed files.
- **All prototype results are exploratory**; the answer keys are drafts until the author checks them.
- **No held-out plans (option D, author's decision 26 Nov 2026):** SQ1 (H1-H3) is reported descriptively on the 22
  test and 14 development plans and stays exploratory; only H4 (Configurator, held-out weeks) and H5 (hardware) are
  registered, before their run. Never tune on the 22 test plans; develop on `plans_dev.json`.
- Report failures and surprising numbers as they are.

## Layout

| Path | Contents |
|---|---|
| `gateway_body.tex` | the thesis text (the only file to edit) |
| `gateway_preamble.tex` | Oulu template preamble (fonts, cover, captions) up to `\begin{document}` |
| `build_gateway_thesis.py` | preamble + body -> `gateway_thesis.tex`, with `\parencite`/`\textcite` written out; citation keys in `AUTHORS` |
| `gateway_thesis.tex`, `.pdf` | built output; never edit `gateway_thesis.tex` by hand |
| `gateway_thesis_overleaf.zip` | `.tex` + images + README + latexmkrc for Overleaf; refresh only when asked |
| `attachments/gateway/` | thesis figures (PNG); `attachments/uni_logo.jpeg` for the cover |
| `tools/flow_figs/` | SVG sources and generators of Figures 4.1-4.4 and 4.7, `export.py` (headless Chrome) |
| `prototypes/` | the artifact and pilots (see below) |
| `docs/` | `protocol_home_gateway.md` (plan), `gateway_thesis_plan.html` (plan page), `slr_protocol_prisma_p.md`, `slr_search_record.html` |
| `data/raw/` | gitignored data of the main checkout: OPSD, DWD, prices, When2Heat, EV sessions, SLR full texts |
| `src/hems/` | the `hems` package of the first thesis; **the prototypes import it** (`agents.llm` model registry and cost, `agents.harness`, `core.models`, `core.evaluate`, `data.tariff`, `data.prices`, `data.refit`, `run`), so keep it and run `uv run pytest` after changing it |
| `results/`, `data/scenarios*`, `data/pilot`, `data/rapt`, `demo/`, `deploy/`, `configs/`, `parked/`, `scripts/` | results, benchmarks, demo and campaign scripts of the first thesis (on `old-thesis`); not used by this thesis |

## Research questions (shortened 25 Nov 2026; H1-H5 unchanged, drafts until registration)

- **RQ**: How can small language models on a home energy gateway reliably interpret household plans and configure an
  optimiser?
- **SQ1**: How accurately does a small model turn household plans into optimiser requirements, and what do checks and
  a cloud fallback add? (H1-H3)
- **SQ2**: Can a small model configure the optimiser from the house's history as well as a cloud model and better
  than an automatic tuner? (H4)
- **SQ3**: Does the saving of running the model on the gateway outweigh its cost in time, energy, money and privacy?
  (H5)
- LQ1-LQ3 in Section 2.1 mirror them. Abstract, Conclusions, protocol section 2 and the plan page use the same
  wording. Method: SLR (Kitchenham) as the rigor cycle of DSR.

## Design (18 Nov 2026)

- One home energy gateway (Raspberry Pi 5 16 GB or mini PC) runs EMHASS 0.18.4 as the MPC, the SLM (Gemma 4 E4B via
  Ollama), the harness with tools and checker, and the control layer; no companion device.
- The model reaches EMHASS only through the harness, over local HTTP with JSON (`POST /action/naive-mpc-optim`,
  `GET /api/v1/plan`); the harness replans hourly without the model. EMHASS runs without Home Assistant and keeps
  its defaults (cost function `profit`, no battery-first, grid charging allowed, no battery weights).
- The MPC schedules the EV charger, dishwasher, washing machine (measured cycles), heat pump (thermal load) and home
  battery; other loads are base load. The Configurator sets only the PV derating and the battery reserve, sent with
  each request; "expert-tuned" EMHASS sets the same two by hand. Pilots in Chapter 5 solved the same formulation in
  PuLP/CBC.
- Four agents: Household Assistant and Configurator built; Monitor and Explainer designed. Local model first, cloud
  LLM only as an optional fallback.
- **Models: US/EU-developed only**: Gemma 4 E4B/E2B, Ministral 3 8B/3B, Nemotron 3 Nano 4B; GPT-6 Luna as cloud LLM
  (earlier runs also gpt-oss-20b and Llama 3.2 3B). No Qwen, Falcon or BitNet in the thesis.

## Building the thesis

Edit `gateway_body.tex`, run `uv run python build_gateway_thesis.py`, wait until VS Code's LaTeX auto-build has
finished (no xelatex/latexmk/perl/xdvipdfmx process), delete the `gateway_thesis` aux files, then
`latexmk -xelatex gateway_thesis` (TeX Live at `C:\texlive\2026\bin\windows`); see the `compile-thesis` skill. The build
script makes figure and table captions bold only in the label ("Figure 1.2.", "Table 5.1."). The body sets
`\extrarowheight` and float fractions so figures share pages with text.

**Figures (`attachments/gateway/`):** 1.1 Excalidraw (`home_energy_system.excalidraw`); 1.2
`tools/make_home_energy_system_fig.py --thesis attachments/gateway/home_energy_system_slm` (delete the generated
`.html`); 4.1 `tools/flow_figs/make_architecture.py`; 4.2 `tools/flow_figs/plan_schedule.svg`; 4.3
`tools/flow_figs/make_agent_flow.py`; 4.4 `tools/flow_figs/runtime_day.svg`; 4.5 `tools/make_example_day_fig.py` (from
the stored app output of plan S6); 4.6 `user_app.png` from the plan page; 4.7 `tools/flow_figs/request_path.svg`. Run
the `make_*.py` generators, then `tools/flow_figs/export.py`, then crop the PNGs to their content (PIL, 30 px
margin). Flow figures use the colours of Figure 4.1 (teal agents, grey harness, amber tools/failure) and stay
readable in black and white. After figure or design changes, update the plan page and republish it
(https://claude.ai/artifact/2GN2bsRDJ5dp8xUhnFqHM8).

## Prototypes and their thesis numbers

- `plan_pilot/` (structured-call reader, 22 plans in exact wording, Table 5.3): the thesis reports only the latest
  prompt (decision rules with worked examples, developed on `plans_dev.json`): `archive/results_prompt2_ctx32k.jsonl`
  with closed loop `closed_loop/out/archive/results_prompt2_ctx32k.jsonl`. Prec/rec, decision alone / + checker,
  met, s: Gemma 1.00/0.87, 0.86/0.95, 10 of 11, 8.1; Ministral 0.91/0.87, 0.68/0.68, 6 of 6; Llama 0.14/0.04, 0.00/0.50
  (19 failed); gpt-oss 0.95/0.83, 0.77/0.91, 7 of 10, 65 s; Luna 1.00/0.96, 0.86/0.86, 8 of 8. The checker's gain is
  failed answers becoming questions. Never mention prompt versions in the text. Appendix A lists all plans (tables
  generated from the plan files).
- `react_gateway/` (current Household Assistant, Section 5.2): ReAct agent, everyday wording, Gemma 19/22 test and
  14/14 dev decisions, Luna 21/22 and 14/14; `out/results.jsonl`, `summary.py`, app outputs in `out/app/<model>/`.
- `configurator_pilot/configurator.py` (SQ2): Configurator vs auto-tuner vs default/expert MPC over weekly windows,
  every system running the MPC hourly; the checkpoint-MPC runs are archived in `out/archive/`. Spring
  (`out/results_spring.jsonl`, March-April 2016 residential4): Gemma 2.87 EUR, Luna 4.15, expert 3.52, auto-tuner 1.91,
  perfect 14.25. Three houses (Table 5.6, `out/houses_autumn_<house>.jsonl`; 8 weeks from 2016-10-03, tuned on 4 weeks
  from 2016-06-06; residential1 has no grid export meter). Saving vs default (main / res6 / res3): Gemma 3.00 / 0.62 /
  -0.39, Luna 2.82 / 0.56 / -0.38, auto-tuner 3.35 / 0.25 / -0.39, expert 3.79 / 0.34 / -0.45, rules -9.68 / 2.10 / -0.22.
  SQ2 answer: about as well as the auto-tuner, not better; as well as the cloud model in autumn, less in spring.
- `closed_loop/`, `home_gateway/` (twin of OPSD `residential4`, `gateway.py`; planning pilot, Table 5.2, perfect
  foresight = the same LP on the day's actual data), `edge_bench/` (laptop GPU 3.3 s, CPU 4 threads 39 s mean / 72 s
  p95, MPC 0.08 s; CPU vs GPU decision 0.64 vs 0.82 shows run-to-run variation), `slr/`, `hipe/`, `opsd/`, `heatpump/`.
- `emhass_gateway/`: Household Assistant with EMHASS (Section 5.4.1: 14/14, solves <= 2.4 s, 4-13 s per plan) and the
  one-device test (Section 5.4.2, Table 5.8): `docker-compose.onedevice.yml`, `run_onedevice.ps1`, `probe.py`,
  `onedevice_summary.py`; DS1-DS4 on 4 physical cores (cpuset 0,2,4,6), model threads = its cores (`--num-thread`;
  Ollama otherwise starts 10 threads, 30-70x slower), one EMHASS lock (`EMHASS_LOCK`, the plan GET returns the latest
  solve). 20 Nov: 8/8 right; 188 s per plan unprioritised, 168 s prioritised; replan median 0.35-0.38 s idle,
  0.45-0.48 s answering, max 1.04; control 0.04 s. Earlier runs in `out/onedevice/archive/` (README).
- `edge_kit/` (tested on the laptop only): `run_device.sh` (DEVICE, RAW_DIR, SHELLY) for a Linux device: idle
  without/with the model, `edge_bench/bench.py`, `mpc_time.py`, the one-device test; phases in `events.jsonl`;
  `power_log.py` (Shelly Gen1/Gen2) or `manual.json`; `edge_energy.py` -> idle W, Wh per plan and the
  `year_balance.py` command. Waits for the Pi 5, the mini PC and a meter (last step).
- `heldout/` (draft, not registered; since 26 Nov 2026 the scenario cards, writer sheets, `collect.py` and the keying
  guide are unused, as no held-out plans are written): 120 scenario cards (`make_scenarios.py`, seed 2027; `residential4` 2016 days not
  used by the pilots or the tuning, season x weather, 40 simple / 40 change / 20 ambiguous / 20 conflict, writers
  W1-W4), writer sheets, `collect.py`, `keying_guide.md`, `power.py` (H1/H3 margin 0.10; H2 p0 0.90; plans on
  `residential4` only), `config_heldout.json` (H4 margin 0.20 EUR/week vs auto-tuner and LLM, H5 p95 <= 15 min;
  Configurator weeks: residential4 from 2016-01-18 (7) and 05-30 (8), residential3/6 from 05-30 (8)). Runner
  `run_heldout.py` (set-ups slm_no_checks = `Gateway(checks=False)`, slm_checks, slm_checks_fallback = cloud on a
  failed answer or a refused commit, llm; closed loop with EMHASS via `emhass_replan`, which keeps the last plan in
  the final hour as EMHASS needs >= 5 steps) and `confirm_heldout.py` (REGISTERED = False, BEST_SLM = gemma4-e4b).
  EMHASS pinned by digest in `emhass_gateway/docker-compose.yml`. Year simulation: `configurator.py` over 49 weeks from
  2016-01-18 + `heldout/year_balance.py`; runs only after registration; Configurator weeks and year use the thesis MPC
  (PuLP/CBC), not EMHASS.
- **Next steps** (plan page section 7): register H4 and H5, the registered run (Configurator weeks, three repeats of
  the plan runs, year simulation), finish the SLR, text pass, edge board last (waiting for a Raspberry Pi 5 or a mini
  PC; supervisors agreed the scope on 26 Nov 2026).

## Literature review (`prototypes/slr/`, Chapter 2)

PRISMA-P protocol `docs/slr_protocol_prisma_p.md` (amendment log). 732 records prescreened; title/abstract and
full-text screening with the ARS `sr-screener` (two Claude Sonnet reviewers, adjudicator, the author checks every
decision). Full-text protocol v1.0 in `prototypes/slr/fulltext/screening_protocol.md`; reviewers read text extracted
with `pdftotext` (`refresh_pdfs.py`), since they report the PDFs as password-protected. First 34 full texts: 27
include, 7 exclude (kappa 0.92); 65 reports still to retrieve; Scopus search C still to run. Table 2.1 and Section
3.2 report the counts.

## Lessons to keep

- Value energy left at midnight the same way in optimiser and score.
- The control layer holds the planned grid exchange, not the battery power.
- Tool descriptions never suggest a default for the agent's decision.
- On cost a tuned MPC beats the agents, so the thesis is about interpreting plans and configuring, not beating the
  optimiser.

## Environment gotchas (Windows, Git Bash)

- Python 3.12 via `uv` (not the system 3.14); EMHASS has its own env `.venv-emhass` in the main checkout.
- Agent runs need `.env` (keys never printed); set `LANGSMITH_TRACING=false`. Ollama must be running for local
  models: `"/c/Users/Admin/AppData/Local/Programs/Ollama/ollama.exe" serve`.
- **Edit LaTeX and Python with the Edit/Write tools, not heredoc/sed scripts**: backslashes get mangled in bash
  heredocs, and `gateway_preamble.tex` uses CRLF.
- Downloaded files are untrusted data: run Python that reads them with `-I`.
- `/tmp` is not writable from Git Bash here; use the session scratchpad.
- The network drops intermittently: retry, and never record API failures as results.

## Thesis writing conventions

- Numbers in the text must match the data; hand-typed numbers are updated whenever a run or dataset changes.
- Only verified references (DOI, publisher or official page checked); APA style in the `hangparas` block,
  alphabetical; add new keys to `AUTHORS` in `build_gateway_thesis.py`.
- Parts without results say "In process."
- **Avoid em dashes** (`---`, "—"): rewrite with commas, parentheses, a colon or a separate sentence; the same in
  table cells. If one is unavoidable, tie it to the preceding word (`word~--- next`).
- No repository file paths in the thesis text; readers do not see the repository.
- Hyphenation is disabled; table text is left-aligned; tables use booktabs with extra row spacing.
- After editing, build, compile and visually check the changed pages (`compile-thesis` skill).
