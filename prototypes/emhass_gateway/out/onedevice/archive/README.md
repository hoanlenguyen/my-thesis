# Archived one-device runs (18-20 Nov 2026)

`*_oversubscribed.jsonl` and `app_oversubscribed/`: the first unprioritised and prioritised runs on DS1-DS4.
Ollama counts the host's cores (20), not the container's, and started 10 threads on the 4 pinned cores (3 in the
prioritised run). A check on 20 Nov 2026 with the same image and cores: 0.5-0.7 prompt tokens/s and 0.1 generated
tokens/s with 10 threads, 37-39 and 3-4 with 4 or 3 threads. The plan times (1-3.4 h per plan) therefore measure
the oversubscription, not the hardware. All 8 decisions were right, and the background work kept its times
(replan median 0.39-0.42 s, control step 0.04 s, idle or answering).

Probe samples to leave out of the prioritised run are listed in `onedevice_summary.EXCLUDE` (a lost DS2 attempt,
a lost DS4 attempt when the laptop stopped, LaTeX compiles). The run was rerun with `--num-thread` set to the
model's cores (`../plans_<run>.jsonl`, `../probe_<run>.jsonl`).

`*_2cores_smt.jsonl` and `app_2cores_smt/` (20 Nov 2026, 14:09-14:48): the rerun with matched threads, but on cpuset
0-3, which in the Docker VM are two physical cores with two threads each. All 8 decisions right; 103-260 s per
plan (mean 193 s unprioritised, 174 s prioritised); EMHASS replan median 0.39 s idle vs 0.45 s answering, control
step 0.03-0.04 s. Rerun on four physical cores (cpuset 0,2,4,6).
