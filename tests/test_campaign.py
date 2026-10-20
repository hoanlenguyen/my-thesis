"""Resumability of evaluation campaigns (no LLM calls: reference systems only)."""

from __future__ import annotations

import json
import os

import pytest

from hems import campaign
from hems.data.synthetic import generate
from hems.run import plan_jobs, read_records, repair_tail


def test_repair_tail_drops_a_cut_off_line(tmp_path) -> None:
    path = tmp_path / "runs.jsonl"
    path.write_bytes(b'{"key": "a"}\n{"key": "b"}\n{"key": "c", "cost')
    assert repair_tail(path)
    assert [r["key"] for r in read_records(path)] == ["a", "b"]
    assert not repair_tail(path)  # already clean


def test_read_records_skips_malformed_lines(tmp_path) -> None:
    path = tmp_path / "runs.jsonl"
    path.write_text('{"key": "a"}\nnot json\n{"key": "b"}\n', encoding="utf-8")
    assert [r["key"] for r in read_records(path)] == ["a", "b"]


def test_model_order_runs_references_then_models_in_plan_order(tmp_path) -> None:
    scenarios = generate(tmp_path / "s", per_type=1, seed=2)
    jobs = plan_jobs(scenarios, ["milp", "single"], ["gpt-4o-mini", "gpt-oss-20b"], runs=2, order="model")
    models = [j[2] for j in jobs]
    assert models == sorted(models, key=["-", "gpt-4o-mini", "gpt-oss-20b"].index)
    assert len(jobs) == len(scenarios) * (1 + 2 * 2)


def test_stale_lock_is_replaced_and_live_lock_blocks(tmp_path) -> None:
    out = tmp_path / "runs.jsonl"
    lock = out.with_suffix(".jsonl.lock")
    lock.write_text("999999")  # no such process
    with campaign.single_instance(out):
        assert lock.read_text() == str(os.getpid())
    assert not lock.exists()
    lock.write_text(str(os.getppid()))  # a live process (our parent) owns it
    with pytest.raises(SystemExit):
        with campaign.single_instance(out):
            pass


def test_campaign_resumes_after_interruption(tmp_path) -> None:
    generate(tmp_path / "s", per_type=1, seed=4)
    plan_path = tmp_path / "plan.json"
    out = tmp_path / "runs.jsonl"
    plan_path.write_text(json.dumps({
        "name": "t", "scenarios": str(tmp_path / "s"), "systems": ["milp", "naive"],
        "models": ["gpt-4o-mini"], "runs": 1, "out": str(out),
    }))  # fmt: skip
    plan = campaign.Plan.load(plan_path)
    assert campaign.run(plan) == "done"
    first = out.read_text(encoding="utf-8").splitlines()
    assert len(first) == 12  # 6 scenarios x (milp, naive)

    # simulate a hard power-off: lose two records and leave a half-written line
    out.write_text("\n".join(first[:-2]) + '\n{"key": "milp|-|x', encoding="utf-8")
    assert campaign.run(plan) == "done"
    assert sorted(r["key"] for r in read_records(out)) == sorted(json.loads(l)["key"] for l in first)
    assert "total 12/12 jobs (100%)" in campaign.status(plan)


def test_campaigns_skip_the_household_message_unless_the_plan_asks() -> None:
    import json
    from pathlib import Path

    from hems.campaign import Plan

    assert Plan(name="x", scenarios="s", systems=["multi_duo"], models=["gpt-6-luna"], runs=1, out="o").message is False
    earlier = ("baselines", "confirmation", "confirmation_q2", "full_evaluation", "iteration9", "iteration10",
               "iteration11", "main_v2", "pilot", "rapt_ch", "uk2015")  # plans run before 19 Oct 2026, with the message
    for name in earlier:
        assert json.loads(Path(f"configs/{name}.json").read_text(encoding="utf-8"))["message"] is True, name
    assert json.loads(Path("configs/luna_v2.json").read_text(encoding="utf-8"))["message"] is False  # new runs skip it
