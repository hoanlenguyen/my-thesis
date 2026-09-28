---
name: run-evaluation
description: Run pilot or full agent evaluations (hems run) across models, keep results comparable after code changes, and summarise gaps/feasibility/recoveries. Use when asked to run a pilot, the full evaluation, a model comparison, or to show evaluation results.
---

# Run and report agent evaluations

## Before running

1. `uv run pytest -q` passes.
2. Keys in `.env` (OpenAI, Groq, LangSmith with EU endpoint). Never print key values.
3. For `gpt-oss-20b` (local): Ollama server up — `curl -s http://127.0.0.1:11434/api/version`; if not,
   start `"/c/Users/Admin/AppData/Local/Programs/Ollama/ollama.exe" serve` in the background.
4. **Comparability:** results are only comparable when produced by the same code. If agents, prompts,
   tools, recovery or scoring changed since rows in the output file were written, archive first and
   drop the affected rows (keep `milp`/`naive` reference rows — they depend only on the scenarios):
   ```bash
   cp results/pilot_real.jsonl results/pilot_real_vN.jsonl   # next unused N
   uv run python -c "import json; rows=[json.loads(l) for l in open('results/pilot_real.jsonl')]; open('results/pilot_real.jsonl','w').writelines(json.dumps(r)+'\n' for r in rows if r['system'] in ('milp','naive'))"
   ```
   The runner skips keys already present, so stale rows would otherwise silently survive.

## Running

- Pilot (one scenario per type): `--ids A01 B03 C02 D01 E01 F04 --runs 1`.
- Full: all 48 scenarios, `--runs 3`, `--models gpt-4o-mini gpt-oss-20b` (the evaluation's two models).
  The local gpt-oss-20b runs take ~1–10 min each, so the full local part runs for many hours: start it
  in the background and let the resumable runner continue after any interruption.
- Run long jobs with `run_in_background`, writing output to a log file in the scratchpad rather than
  long pipes (a Git Bash fork failure killed an earlier batch), then grep the log for
  `^\[|jobs|FAILED|quota`.
- `gpt-oss-120b` (Groq) is pilot-only. If it is ever run, use a **separate** batch: on its daily quota
  the runner stops the whole batch; rerun the same command after the quota resets to resume.
- `FAILED (not recorded)` = provider/network error → rerun later. `INFEASIBLE` = recorded agent failure.

## Reporting

Summarise per scenario and model: gap vs MILP `(cost - milp)/milp`, feasible, `recoveries`,
latency, tokens, and `agent_errors`/`violations` for failures. Distinguish model behaviour
(no structured output, step limit, dropped appliance) from infrastructure (quota, DNS). Compare with
earlier archived runs only when the code was the same.
