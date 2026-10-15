"""LangGraph Studio entry point (langgraph.json -> hems.studio.make_graph): builds the registered pipelines."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from hems import studio

from .fakes import ScriptedModel

ROOT = Path(__file__).resolve().parents[1]
NODES = {"orchestrator_plan", "profiler", "scheduler", "resolver", "orchestrator_finalize"}


def fake_models(_role: str) -> ScriptedModel:
    return ScriptedModel(messages=iter([]))  # never called: the tests only build the graphs


@pytest.mark.parametrize("variant", sorted(studio.VARIANTS))
def test_every_variant_builds_the_pipeline_graph(variant: str) -> None:
    scenario, graph = studio.build(variant=variant, models=fake_models)
    assert scenario.id == "Q2-PH03-35"
    assert NODES <= set(graph.get_graph().nodes)


def test_unknown_variant_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown variant"):
        studio.build(variant="single", models=fake_models)


def test_studio_graph_fills_in_the_request_of_the_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hems.agents.llm.make_model", lambda _name: ScriptedModel(messages=iter([])))
    graph = asyncio.run(studio.make_graph({"configurable": {"variant": "multi_lean"}}))
    assert {"household_request", "pipeline"} <= set(graph.get_graph().nodes)
    scenario, _ = studio.build(models=fake_models)
    step = graph.nodes["household_request"].bound
    assert step.invoke({"request": ""})["request"] == scenario.user_request
    assert step.invoke({"request": "my own plan"})["request"] == "my own plan"


def test_langgraph_json_points_at_the_factory() -> None:
    config = json.loads((ROOT / "langgraph.json").read_text(encoding="utf-8"))
    assert config["graphs"]["multi_agent_pipeline"] == "./src/hems/studio.py:make_graph"
    assert (ROOT / config["graphs"]["multi_agent_pipeline"].split(":")[0]).exists()
