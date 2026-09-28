"""Scripted chat models for exercising agent wiring without API calls."""

from __future__ import annotations

from itertools import count
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

_ids = count()


def call(name: str, **args: Any) -> AIMessage:
    """An AI turn that calls one tool (or a structured-output schema)."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{next(_ids)}", "type": "tool_call"}])


class ProviderRejection(Exception):
    """Mimics Groq's HTTP 400 when the model answers in prose although a tool call is required."""

    def __init__(self, text: str = "I think the schedule is fine.") -> None:
        super().__init__("Error code: 400 - tool_use_failed")
        self.body = {"error": {"code": "tool_use_failed", "failed_generation": text}}


class ScriptedModel(GenericFakeChatModel):
    """Replays a fixed list of AI messages (an Exception item is raised instead); accepts bind_tools."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        item = next(self.messages)
        if isinstance(item, Exception):
            raise item
        return ChatResult(generations=[ChatGeneration(message=item)])


def scripted(*messages: AIMessage | str | Exception) -> ScriptedModel:
    items = [AIMessage(content=m) if isinstance(m, str) else m for m in messages]
    return ScriptedModel(messages=iter(items))
