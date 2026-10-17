"""Tell model behaviour apart from provider/network failures, and recover from the former.

Some providers (e.g. Groq with gpt-oss) reject a whole turn with HTTP 400 when the model answers in prose
although a tool call is required ("tool_use_failed") or emits output the provider cannot parse
("output_parse_failed"). ``invoke_with_recovery`` resumes the agent from its last checkpoint, shows the
model its own rejected text and asks it to call the output tool, at most ``MAX_RECOVERIES`` times. The
same rule applies to every model, and also when a provider that does not enforce tool choice lets the
prose reply end the agent loop without a structured result; recoveries are counted and reported.
Failures that persist count as a failed run, not as an infrastructure error.
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

MODEL_OUTPUT_FAILURE_CODES = ("tool_use_failed", "output_parse_failed")
DAILY_QUOTA_MARKERS = ("tokens per day", "requests per day", "(TPD)", "(RPD)")
MAX_RECOVERIES = 2


def _error_body(exc: BaseException) -> dict:
    body = getattr(exc, "body", None)
    return body.get("error", {}) if isinstance(body, dict) else {}


def model_output_failure(exc: BaseException) -> str | None:
    """Short description if ``exc`` means the model produced unusable output, else None."""
    code = _error_body(exc).get("code")
    if code in MODEL_OUTPUT_FAILURE_CODES:
        return f"model output rejected by provider ({code})"
    for marker in MODEL_OUTPUT_FAILURE_CODES:
        if marker in str(exc):
            return f"model output rejected by provider ({marker})"
    return None


def daily_quota_exhausted(exc: BaseException) -> bool:
    text = str(exc)
    return "rate_limit" in text and any(marker in text for marker in DAILY_QUOTA_MARKERS)


def invoke_with_recovery(
    agent: Any, message: str | list[BaseMessage], schema_name: str, config: dict[str, Any], limit: int
) -> tuple[dict[str, Any], int]:
    """Invoke a create_agent graph (compiled with a checkpointer); returns (final state, recoveries).

    ``message`` is the user message, or a whole conversation to continue (the single agent's feedback round).
    Raises the last model-output failure if it persists after MAX_RECOVERIES nudges.
    """
    run_config = {**config, "recursion_limit": limit}
    run_config["configurable"] = {**config.get("configurable", {}), "thread_id": str(uuid.uuid4())}
    payload: dict[str, Any] = {"messages": [HumanMessage(message)] if isinstance(message, str) else list(message)}
    nudge = HumanMessage(
        f"Your last reply could not be used because it did not call a tool. "
        f"Call the {schema_name} tool now with your final answer."
    )
    result: dict[str, Any] = {}
    for attempt in range(MAX_RECOVERIES + 1):
        try:
            result = agent.invoke(payload, config=run_config)
        except Exception as exc:
            # Provider-enforced tool choice (e.g. Groq): the prose reply arrives as an HTTP 400.
            if model_output_failure(exc) is None or attempt == MAX_RECOVERIES:
                raise
            rejected = _error_body(exc).get("failed_generation") or ""
            payload = {"messages": ([AIMessage(rejected)] if rejected.strip() else []) + [nudge]}
        else:
            # Providers that do not enforce tool choice (e.g. Ollama): the prose reply ends the loop
            # without a structured result. It is already in the checkpointed history.
            if result.get("structured_response") is not None or attempt == MAX_RECOVERIES:
                return result, attempt
            payload = {"messages": [nudge]}
        run_config.pop("run_id", None)  # a trace run id may only be used once
    return result, MAX_RECOVERIES
