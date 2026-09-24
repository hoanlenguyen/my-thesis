"""Model registry. Pin exact model versions so every run is reproducible and logged."""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model_id: str
    usd_per_m_input: float  # check current provider pricing before the final evaluation
    usd_per_m_output: float


MODELS: dict[str, ModelSpec] = {
    "gpt-4o-mini": ModelSpec("openai", "gpt-4o-mini-2024-07-18", 0.15, 0.60),
    "llama-3.3-70b": ModelSpec("groq", "llama-3.3-70b-versatile", 0.59, 0.79),
    "llama-3.1-8b": ModelSpec("groq", "llama-3.1-8b-instant", 0.05, 0.08),
}


def make_model(name: str, temperature: float = 0.0, seed: int | None = None) -> BaseChatModel:
    spec = MODELS[name]
    if spec.provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=spec.model_id, temperature=temperature, seed=seed, max_retries=6)
    if spec.provider == "groq":
        from langchain_groq import ChatGroq

        kwargs = {"model_kwargs": {"seed": seed}} if seed is not None else {}
        return ChatGroq(model=spec.model_id, temperature=temperature, max_retries=6, **kwargs)
    raise ValueError(f"unknown provider {spec.provider}")


def usage_cost_usd(usage: dict[str, dict], name: str) -> tuple[int, int, float]:
    """Sum token usage from get_usage_metadata_callback() and price it."""
    spec = MODELS[name]
    tokens_in = sum(u.get("input_tokens", 0) for u in usage.values())
    tokens_out = sum(u.get("output_tokens", 0) for u in usage.values())
    cost = tokens_in / 1e6 * spec.usd_per_m_input + tokens_out / 1e6 * spec.usd_per_m_output
    return tokens_in, tokens_out, cost
