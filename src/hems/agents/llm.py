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
    # Input tokens the provider read from its prompt cache (a repeated prompt start of at least 1,024 tokens) cost
    # less; None = no discount known, priced as ordinary input
    usd_per_m_cached_input: float | None = None
    # Ollama models: the ``think`` setting ("medium" for gpt-oss, True/False for models with an on/off reasoning
    # phase, None to leave the model's default); unused by the other providers
    ollama_think: bool | str | None = "medium"
    # Local models: cap on generated tokens per call (Ollama's ``num_predict``, llama.cpp's ``max_tokens``); None = no cap
    ollama_num_predict: int | None = None
    # Ollama models: layers placed on the GPU (``num_gpu``; 0 = CPU only); None = Ollama decides
    ollama_num_gpu: int | None = None
    # llama.cpp servers (provider "llamacpp"): OpenAI-compatible endpoint; the environment variable
    # ``LLAMACPP_BASE_URL`` overrides it (e.g. a companion device on the home network)
    base_url: str | None = None
    # LangChain structured-output method for this model (None = the caller's default, a tool call); servers without
    # tool calling use "json_schema", which constrains the answer to the schema with a grammar
    structured_method: str | None = None


MODELS: dict[str, ModelSpec] = {
    # Model of the redesigned evaluation (since 19 Oct 2026). OpenAI publishes no dated snapshot of gpt-6-luna, so
    # the model id is all that can be pinned. It accepts temperature 0 only with reasoning effort "none", which also
    # keeps every call fast; the solver tool does the search, so the agents need no reasoning phase.
    # Prices as on OpenAI's pricing page (standard tier, checked 21 Oct 2026): cached input USD 0.01. Cache writes
    # (USD 0.125 per 1M for 30 min, 0.25 for 12 h) are not priced here; thesis sec:stack gives the bound.
    "gpt-6-luna": ModelSpec("openai", "gpt-6-luna", 0.10, 0.50, reasoning_effort="none", usd_per_m_cached_input=0.01),
    # Model of design iterations 1-11, the registered Q2 confirmation and every result recorded before 19 Oct 2026.
    # Its recorded costs priced every input token in full; the cached rate applies from 19 Oct 2026.
    "gpt-4o-mini": ModelSpec("openai", "gpt-4o-mini-2024-07-18", 0.15, 0.60, usd_per_m_cached_input=0.075),
    # Earlier evaluation models: gpt-4o-mini (commercial API) and gpt-oss-20b (open weights, local).
    # Llama-3.3-70B was planned but Groq moved Llama to enterprise-only access on 26 Aug 2026.
    # gpt-oss-120b (Groq, evaluated by El Makroum et al. 2026) is pilot-only: the free tier's ~200k
    # tokens/day cannot cover the full evaluation and the paid tier was unavailable.
    "gpt-oss-120b": ModelSpec("groq", "openai/gpt-oss-120b", 0.15, 0.60),
    # gpt-oss-20b runs locally with Ollama (same open weights, no API cost or rate limit); the Groq-hosted
    # variant is kept for comparison.
    "gpt-oss-20b": ModelSpec("ollama", "gpt-oss:20b", 0.0, 0.0),
    "gpt-oss-20b-groq": ModelSpec("groq", "openai/gpt-oss-20b", 0.075, 0.30),
    # Local candidates for the follow-up thesis (exploratory; added 3 Nov 2026). Qwen3 runs with its reasoning
    # phase on, like gpt-oss; Gemma 4 keeps its default. Output is capped at 8,000 tokens per call (4 Nov 2026):
    # qwen3:8b looped in its reasoning phase for 37,000+ tokens on one plan; a capped call counts as a failed answer.
    "qwen3-8b": ModelSpec("ollama", "qwen3:8b", 0.0, 0.0, ollama_think=True, ollama_num_predict=8000),
    # qwen3:30b-a3b fails to start on the 8 GB laptop GPU (CUDA out of memory, even with 24 layers), so it runs on
    # the CPU only.
    "qwen3-30b-a3b": ModelSpec("ollama", "qwen3:30b-a3b", 0.0, 0.0, ollama_think=True, ollama_num_predict=8000,
                               ollama_num_gpu=0),  # fmt: skip
    "gemma4-e4b": ModelSpec("ollama", "gemma4:e4b", 0.0, 0.0, ollama_think=None, ollama_num_predict=8000),
    # Tiny models that fit a 4 GB gateway board (10 Nov 2026): same settings as their larger relatives.
    "qwen3-1.7b": ModelSpec("ollama", "qwen3:1.7b", 0.0, 0.0, ollama_think=True, ollama_num_predict=8000),
    "qwen3-4b": ModelSpec("ollama", "qwen3:4b", 0.0, 0.0, ollama_think=True, ollama_num_predict=8000),
    # qwen3:4b is the 2507 "thinking" build: with think=False it still reasons in its answer text (10 Nov 2026), so
    # the run without reasoning uses the instruct build.
    "qwen3-4b-instruct": ModelSpec("ollama", "qwen3:4b-instruct", 0.0, 0.0, ollama_think=None, ollama_num_predict=8000),
    "llama3.2-3b": ModelSpec("ollama", "llama3.2:3b", 0.0, 0.0, ollama_think=None, ollama_num_predict=8000),
    # Mistral's Ministral 3 8B (instruct, no reasoning phase), added 12 Nov 2026 as a third 8B-class family.
    "ministral-3-8b": ModelSpec("ollama", "ministral-3:8b", 0.0, 0.0, ollama_think=None, ollama_num_predict=8000),
    # Model set chosen by the author on 13 Nov 2026 (Gemma 4, Ministral 3, Phi-4, SmolLM3; Llama 4 dropped: its
    # smallest model, Scout, has 109B parameters, and its licence excludes EU-domiciled users of multimodal models).
    # Small tier for a 4 GB gateway board, default reasoning settings of each model.
    "gemma4-e2b": ModelSpec("ollama", "gemma4:e2b", 0.0, 0.0, ollama_think=None, ollama_num_predict=8000),
    "ministral-3-3b": ModelSpec("ollama", "ministral-3:3b", 0.0, 0.0, ollama_think=None, ollama_num_predict=8000),
    # NVIDIA Nemotron 3 Nano 4B (hybrid Mamba-Transformer, trained for tool calling; NVIDIA Open Model License),
    # added 13 Nov 2026; reasoning on, parsed by Ollama.
    "nemotron3-nano-4b": ModelSpec("ollama", "nemotron-3-nano:4b", 0.0, 0.0, ollama_think=True, ollama_num_predict=8000),
    # Phi-4-mini: dropped from the model set on 13 Nov 2026 (no usable tool calls); kept for its archived results.
    "phi4-mini": ModelSpec("ollama", "phi4-mini", 0.0, 0.0, ollama_think=None, ollama_num_predict=8000),
    # Same weights with a tool-calling template (react_gateway/phi4-mini-tools.Modelfile): the stock template made
    # no tool calls in the ReAct gateway (13 Nov 2026).
    "phi4-mini-tools": ModelSpec("ollama", "phi4-mini-tools", 0.0, 0.0, ollama_think=None, ollama_num_predict=8000),
    # No official Ollama build: the GGUF of ggml-org on Hugging Face (Q4_K_M); reasoning on by default (/think).
    "smollm3-3b": ModelSpec("ollama", "hf.co/ggml-org/SmolLM3-3B-GGUF:Q4_K_M", 0.0, 0.0, ollama_think=None,
                            ollama_num_predict=8000),  # fmt: skip
    # The GGUF's template never passes the tools to the model (it reads a variable Ollama does not set); this build
    # has a template in SmolLM3's documented tool format (react_gateway/smollm3-tools.Modelfile), reasoning on.
    # Dropped from the model set on 13 Nov 2026 (never planned a schedule); kept for its archived results.
    "smollm3-tools": ModelSpec("ollama", "smollm3-tools", 0.0, 0.0, ollama_think=True, ollama_num_predict=8000),
    # Microsoft BitNet b1.58 2B-4T (ternary weights, I2_S GGUF from microsoft/BitNet-b1.58-2B-4T-gguf), added
    # 17 Nov 2026. Runs in bitnet.cpp's llama-server, not Ollama: BitNet commit 1876a3e (Jan 2026; one const fix for
    # Clang 18) in WSL, since the July 2026 main branch (embedding fork of llama.cpp) gives incoherent text with this
    # model. That server rejects ``tools``, so the plan pilot uses JSON-schema output and the ReAct gateway (tool
    # calls) cannot run it. No reasoning phase; 4,000-token cap within the server's 8,192-token context.
    "bitnet-2b": ModelSpec("llamacpp", "bitnet-b1.58-2b-4t", 0.0, 0.0, ollama_think=None, ollama_num_predict=4000,
                           base_url="http://localhost:8089/v1", structured_method="json_schema"),  # fmt: skip
}

# The model new runs use unless another is named (CLI, LangGraph Studio, demo)
DEFAULT_MODEL = "gpt-6-luna"

# Local inference settings: the agents' conversations exceed Ollama's default context window. The reasoning
# setting is per model (``ModelSpec.ollama_think``); "medium" matches the gpt-oss default on hosted providers.
OLLAMA_NUM_CTX = 32768


def make_model(name: str, temperature: float = 0.0, seed: int | None = None, num_ctx: int | None = None) -> BaseChatModel:
    """``num_ctx``: Ollama context window for this call site (None = ``OLLAMA_NUM_CTX``, sized for the agents)."""
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
            model=spec.model_id, temperature=temperature, seed=seed, num_ctx=num_ctx or OLLAMA_NUM_CTX,
            reasoning=spec.ollama_think, num_predict=spec.ollama_num_predict, num_gpu=spec.ollama_num_gpu,
            keep_alive="30m",
        )  # fmt: skip
    if spec.provider == "llamacpp":
        import os

        from langchain_openai import ChatOpenAI

        base_url = os.environ.get("LLAMACPP_BASE_URL") or spec.base_url
        return ChatOpenAI(model=spec.model_id, base_url=base_url, api_key="not-needed", temperature=temperature,
                          seed=seed, max_tokens=spec.ollama_num_predict, max_retries=2)  # fmt: skip
    raise ValueError(f"unknown provider {spec.provider}")


def cached_tokens(usage: dict[str, dict]) -> int:
    """Input tokens the provider read from its prompt cache (included in input_tokens)."""
    return sum((u.get("input_token_details") or {}).get("cache_read", 0) or 0 for u in usage.values())


def usage_cost_usd(usage: dict[str, dict], name: str) -> tuple[int, int, float]:
    """Sum token usage from get_usage_metadata_callback() and price it; cached input tokens at the cached rate."""
    spec = MODELS[name]
    tokens_in = sum(u.get("input_tokens", 0) for u in usage.values())
    tokens_out = sum(u.get("output_tokens", 0) for u in usage.values())
    cached = min(cached_tokens(usage), tokens_in)
    cached_rate = spec.usd_per_m_cached_input if spec.usd_per_m_cached_input is not None else spec.usd_per_m_input
    cost = ((tokens_in - cached) * spec.usd_per_m_input + cached * cached_rate + tokens_out * spec.usd_per_m_output) / 1e6
    return tokens_in, tokens_out, cost
