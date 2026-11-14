# Archived plan-pilot results

Superseded runs, kept for the record (the protocol log in `docs/protocol_home_gateway.md` describes each).
`../results.jsonl` holds the current results (one prompt, the settings and models in `pilot.py`).

| File | What |
|---|---|
| `results_pilot_v1.jsonl` | first pilot version (before plans were bound to dates) |
| `results_prompt1.jsonl` | first prompt (no explicit commit-or-ask rules), all models, 32k context (thesis Tables 5.2, 5.3) |
| `results_prompt2_ctx32k.jsonl` | prompt with commit-or-ask rules and examples, 32k context (thesis Table 5.4, 13 Nov 2026) |
| `results_prompt2_partial.jsonl` | same prompt, plan-sized context, stopped when the model set changed |
| `results_dev_prompt1_and_2.jsonl` | the 14 development plans, both prompts |
| `results_speed.jsonl` | speed pilot on the development plans (context window, reasoning settings) |
| `results_retry_bug.jsonl`, `results_qwen30b_oom.jsonl`, `results_qwen3_4b_think_false_ignored.jsonl` | failed or invalid runs |
| `rescore_checker_prompt1.json` | checker and fallback rescoring of `results_prompt1.jsonl` |

Model labels in these files carry the old settings (`/function_calling+retry2`, `+p3` = second prompt).
Closed-loop results of the same runs: `../../closed_loop/out/archive/`.
