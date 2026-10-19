"""The Multi-Agent Pipeline as a LangGraph Studio graph (langgraph.json -> make_graph). Not used by the evaluation.

    uv run --extra studio langgraph dev        # opens LangGraph Studio for the local server

Studio calls ``make_graph`` for every run with the assistant's configuration. Its ``configurable`` fields choose the
household-day and the pipeline variant; the graph is then built exactly as the system registry builds it
(src/hems/systems.py), so a Studio run is the same pipeline as an evaluation run of that system.

    scenario  path to a scenario JSON, relative to the thesis root (default: a held-out Q2 day)
    variant   "multi_duo" (the two-agent pipeline, design iteration 10) or "multi_duo_thoughts" (with an explicit
              Thought in every tool call, design iteration 11)
    model     a model name from hems.agents.llm.MODELS (default "gpt-6-luna"; needs OPENAI_API_KEY in .env)

The run's input is the household's request: {"request": "<the scenario's user_request>"}. Leave it empty to use
the request stored in the scenario file.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from hems.core.models import Scenario

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO = "data/scenarios_q2/Q2-PH03-35.json"

# Pipeline variants as registered in src/hems/systems.py: keyword arguments of build_pipeline
VARIANTS: dict[str, dict[str, Any]] = {
    "multi_duo": {"retriever": True},
    "multi_duo_thoughts": {"retriever": True, "thoughts": True},
}


def build(scenario_path: str = DEFAULT_SCENARIO, variant: str = "multi_duo", model: str = "gpt-6-luna",
          models: Any = None):  # type: ignore[no-untyped-def]
    """The compiled pipeline for one household-day. ``models`` (a role -> chat model function) replaces the
    named model, for tests."""
    from hems.agents.llm import make_model
    from hems.agents.multi_agent import build_pipeline

    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; choose one of {sorted(VARIANTS)}")
    scenario = Scenario.load(ROOT / scenario_path)
    kwargs = dict(VARIANTS[variant])
    if kwargs.pop("retriever", False):
        from hems.rag import default_retriever

        kwargs["retriever"] = default_retriever()
    if models is None:
        chat = make_model(model)
        models = lambda _role: chat  # noqa: E731 - one model for every agent, as in the evaluation
    return scenario, build_pipeline(scenario, models, **kwargs)


async def make_graph(config: RunnableConfig):  # type: ignore[no-untyped-def]
    """Graph factory for LangGraph Studio: the pipeline for the configured scenario and variant. An empty request
    is replaced by the one stored in the scenario. Async, with the file reads (scenario, case library) in a worker
    thread, because the LangGraph server does not allow blocking calls in its event loop."""
    cfg = (config or {}).get("configurable", {}) or {}
    scenario, pipeline = await asyncio.to_thread(
        build, cfg.get("scenario", DEFAULT_SCENARIO), cfg.get("variant", "multi_duo"), cfg.get("model", "gpt-6-luna")
    )

    def household_request(state: dict[str, Any]) -> dict[str, Any]:
        return {"request": state.get("request") or scenario.user_request}

    # A one-step wrapper so that Studio can start a run without typing the request; the pipeline itself is the
    # unchanged subgraph "pipeline", which Studio shows node by node.
    from hems.agents.multi_agent import PipelineState

    graph = StateGraph(PipelineState)
    graph.add_node("household_request", household_request)
    graph.add_node("pipeline", pipeline)
    graph.add_edge(START, "household_request")
    graph.add_edge("household_request", "pipeline")
    graph.add_edge("pipeline", END)
    return graph.compile()
