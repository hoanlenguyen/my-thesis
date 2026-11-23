# Archived Configurator results

`*_prompt_with_location.jsonl`: runs before 19 Nov 2026. Two things differ from the current pilot:

- the prompt began "You are the Configurator of a home energy gateway in Konstanz, Germany.";
- every system ran the checkpoint MPC (00, 06, 12, 18 h and each EV plug-in), and the prompt said so.

On 19 Nov 2026 the location was removed and the MPC switched to hourly replanning (as on the gateway, after a
review pointed out the mismatch); the pilots were then rerun (`../results_spring.jsonl`,
`../houses_autumn_<house>.jsonl`).
