"""Model registry: new runs use GPT-6 Luna without a reasoning phase; recorded runs keep GPT-4o-mini."""

from __future__ import annotations

import pytest

from hems.agents.llm import DEFAULT_MODEL, MODELS, make_model


def test_new_runs_use_gpt6_luna_without_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")  # the client is only built, never called
    assert DEFAULT_MODEL == "gpt-6-luna"
    model = make_model(DEFAULT_MODEL)
    assert model.model_name == "gpt-6-luna" and model.reasoning_effort == "none" and model.temperature == 0.0


def test_cached_input_tokens_are_priced_at_the_cached_rate() -> None:
    from hems.agents.llm import cached_tokens, usage_cost_usd

    usage = {"gpt-6-luna": {"input_tokens": 3000, "output_tokens": 100, "input_token_details": {"cache_read": 2000}}}
    tokens_in, tokens_out, usd = usage_cost_usd(usage, "gpt-6-luna")
    assert (tokens_in, tokens_out, cached_tokens(usage)) == (3000, 100, 2000)
    assert usd == pytest.approx((1000 * 0.10 + 2000 * 0.01 + 100 * 0.50) / 1e6)
    no_cache = {"gpt-6-luna": {"input_tokens": 3000, "output_tokens": 100}}
    assert usage_cost_usd(no_cache, "gpt-6-luna")[2] == pytest.approx((3000 * 0.10 + 100 * 0.50) / 1e6)


def test_recorded_runs_keep_their_pinned_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert MODELS["gpt-4o-mini"].model_id == "gpt-4o-mini-2024-07-18"
    assert make_model("gpt-4o-mini").reasoning_effort is None  # called exactly as before
