"""Design iteration 7: case retrieval, worked examples and the optimiser tool."""

from __future__ import annotations

from typing import Any

from hems.agents.multi_agent import run_multi_agent
from hems.core.evaluate import evaluate
from hems.core.models import Scenario
from hems.rag import Case, Retriever, example_text, features, similarity
from hems.solvers.milp import solve_milp
from hems.tools import build_tools

from .conftest import make_scenario
from .fakes import ScriptedModel, call, scripted


def _case(scenario: Scenario, case_id: str) -> Case:
    return Case(case_id, scenario.type, f"2020-01-{len(case_id):02d}", features(scenario), example_text(scenario, solve_milp(scenario).schedule))


def test_features_and_similarity() -> None:
    sc = make_scenario("D", seed=3)
    f = features(sc)
    assert len(f["shape"]) == 24 and len(f["structure"]) == 6
    assert abs(similarity(f, f) - 1.0) < 1e-6
    assert similarity(f, features(make_scenario("A", seed=4))) < 1.0


def test_example_text_lists_every_appliance_at_its_optimal_start() -> None:
    sc = make_scenario("D", seed=3)
    optimal = solve_milp(sc).schedule
    text = example_text(sc, optimal)
    for a in sc.appliances:
        assert f"- {a.id} (" in text and f"): {sc.slot_to_time(optimal[a.id])}-" in text


def test_retriever_ranks_the_most_similar_case_first() -> None:
    query = make_scenario("D", seed=3)
    cases = [_case(make_scenario("A", seed=5), "L-A01"), _case(query, "L-D01x"), _case(make_scenario("B", seed=6), "L-B01")]
    retrieved = Retriever(cases, k=2).retrieve(query.model_copy(update={"date": "2099-01-01"}))
    assert retrieved[0][0].id == "L-D01x" and len(retrieved) == 2
    assert "Worked examples" in Retriever(cases, k=1)(query)


def test_optimize_schedule_tool_returns_the_milp_optimum() -> None:
    sc = make_scenario("D", seed=3)
    out = build_tools(sc)["optimize_schedule"].invoke({"appliance_ids": [a.id for a in sc.appliances]})
    assert f"Total cost EUR {evaluate(sc, solve_milp(sc).schedule).cost_eur:.4f}" in out
    assert build_tools(sc)["optimize_schedule"].invoke({"appliance_ids": ["nope"]}).startswith("ERROR")


class Recording(ScriptedModel):
    seen: list[str] = []

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any):
        self.seen.append("\n".join(str(m.content) for m in messages))
        return super()._generate(messages, stop, run_manager, **kwargs)


def test_pipeline_passes_examples_and_gives_the_scheduler_the_optimiser(scenario: Scenario) -> None:
    ids = [a.id for a in scenario.appliances]
    optimal = [{"appliance_id": k, "start_time": scenario.slot_to_time(v)} for k, v in solve_milp(scenario).schedule.items()]
    profiles = [
        {"appliance_id": a.id, "kind": a.kind, "flexible": True, "peak_kw": a.peak_kw, "duration_minutes": a.duration_slots * 15,
         "earliest_time": scenario.slot_to_time(a.earliest_slot), "deadline_time": scenario.boundary_to_time(a.deadline_slot)}
        for a in scenario.appliances
    ]  # fmt: skip
    scheduler = Recording(messages=iter([
        call("optimize_schedule", appliance_ids=ids),
        call("ScheduleOutput", assignments=optimal, total_cost_eur=1.0, explanation="solver"),
    ]))  # fmt: skip
    models = {
        "orchestrator": scripted(call("TaskBrief", appliance_ids=ids, notes=""), "Done."),
        "profiler": scripted(call("ProfileOutput", appliances=profiles)),
        "scheduler": scheduler,
        "resolver": scripted(call("ResolverOutput", assignments=optimal, conflicts_remaining=False, changes="none")),
    }
    run = run_multi_agent(scenario, lambda role: models[role], retriever=lambda _sc: "EXAMPLES-MARKER", optimizer=True)
    assert run.errors == [] and run.tool_calls >= 1
    assert "EXAMPLES-MARKER" in scheduler.seen[0] and "optimize_schedule" in scheduler.seen[0]
    assert "Optimal schedule" in scheduler.seen[1]  # the tool ran and its result reached the agent
    parsed = {k: scenario.time_to_slot(v) for k, v in run.assignments.items()}
    assert evaluate(scenario, parsed).cost_eur == evaluate(scenario, solve_milp(scenario).schedule).cost_eur
