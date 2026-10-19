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
    reasoning_effort: str | None = None  # OpenAI reasoning models: "none" = answer without a reasoning phase


MODELS: dict[str, ModelSpec] = {
    # Model of the redesigned evaluation (since 19 Oct 2026). OpenAI publishes no dated snapshot of gpt-6-luna, so
    # the model id is all that can be pinned. It accepts temperature 0 only with reasoning effort "none", which also
    # keeps every call fast; the solver tool does the search, so the agents need no reasoning phase.
    "gpt-6-luna": ModelSpec("openai", "gpt-6-luna", 0.10, 0.50, reasoning_effort="none"),
    # Model of design iterations 1-11, the registered Q2 confirmation and every result recorded before 19 Oct 2026.
    "gpt-4o-mini": ModelSpec("openai", "gpt-4o-mini-2024-07-18", 0.15, 0.60),
    # Earlier evaluation models: gpt-4o-mini (commercial API) and gpt-oss-20b (open weights, local).
    # Llama-3.3-70B was planned but Groq moved Llama to enterprise-only access on 26 Aug 2026.
    # gpt-oss-120b (Groq, evaluated by El Makroum et al. 2026) is pilot-only: the free tier's ~200k
    # tokens/day cannot cover the full evaluation and the paid tier was unavailable.
    "gpt-oss-120b": ModelSpec("groq", "openai/gpt-oss-120b", 0.15, 0.60),
    # gpt-oss-20b runs locally with Ollama (same open weights, no API cost or rate limit); the Groq-hosted
    # variant is kept for comparison.
    "gpt-oss-20b": ModelSpec("ollama", "gpt-oss:20b", 0.0, 0.0),
    "gpt-oss-20b-groq": ModelSpec("groq", "openai/gpt-oss-20b", 0.075, 0.30),
}

# The model new runs use unless another is named (CLI, LangGraph Studio, demo)
DEFAULT_MODEL = "gpt-6-luna"

# Local inference settings: the agents' conversations exceed Ollama's default context window, and
# "medium" reasoning effort matches the gpt-oss default on hosted providers.
OLLAMA_NUM_CTX = 32768
OLLAMA_REASONING = "medium"


def make_model(name: str, temperature: float = 0.0, seed: int | None = None) -> BaseChatModel:
    spec = MODELS[name]
    if spec.provider == "openai":
        from langchain_openai import ChatOpenAI

        extra = {"reasoning_effort": spec.reasoning_effort} if spec.reasoning_effort else {}
        return ChatOpenAI(model=spec.model_id, temperature=temperature, seed=seed, max_retries=6, **extra)
    if spec.provider == "groq":
        from langchain_groq import ChatGroq

        kwargs = {"model_kwargs": {"seed": seed}} if seed is not None else {}
        return ChatGroq(model=spec.model_id, temperature=temperature, max_retries=6, **kwargs)
    if spec.provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=spec.model_id, temperature=temperature, seed=seed, num_ctx=OLLAMA_NUM_CTX,
            reasoning=OLLAMA_REASONING, keep_alive="30m",
        )  # fmt: skip
    raise ValueError(f"unknown provider {spec.provider}")


def usage_cost_usd(usage: dict[str, dict], name: str) -> tuple[int, int, float]:
    """Sum token usage from get_usage_metadata_callback() and price it."""
    spec = MODELS[name]
    tokens_in = sum(u.get("input_tokens", 0) for u in usage.values())
    tokens_out = sum(u.get("output_tokens", 0) for u in usage.values())
    cost = tokens_in / 1e6 * spec.usd_per_m_input + tokens_out / 1e6 * spec.usd_per_m_output
    return tokens_in, tokens_out, cost
