"""Model registry: new runs use GPT-6 Luna without a reasoning phase; recorded runs keep GPT-4o-mini."""

from __future__ import annotations

import pytest

from hems.agents.llm import DEFAULT_MODEL, MODELS, make_model


def test_new_runs_use_gpt6_luna_without_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")  # the client is only built, never called
    assert DEFAULT_MODEL == "gpt-6-luna"
    model = make_model(DEFAULT_MODEL)
    assert model.model_name == "gpt-6-luna" and model.reasoning_effort == "none" and model.temperature == 0.0


def test_recorded_runs_keep_their_pinned_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert MODELS["gpt-4o-mini"].model_id == "gpt-4o-mini-2024-07-18"
    assert make_model("gpt-4o-mini").reasoning_effort is None  # called exactly as before
