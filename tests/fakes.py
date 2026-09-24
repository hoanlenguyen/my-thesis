"""Scripted chat models for exercising agent wiring without API calls."""

from __future__ import annotations

from itertools import count
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

_ids = count()


def call(name: str, **args: Any) -> AIMessage:
    """An AI turn that calls one tool (or a structured-output schema)."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{next(_ids)}", "type": "tool_call"}])


class ScriptedModel(GenericFakeChatModel):
    """Replays a fixed list of AI messages; accepts bind_tools so create_agent can use it."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:
        return self


def scripted(*messages: AIMessage | str) -> ScriptedModel:
    return ScriptedModel(messages=iter([AIMessage(content=m) if isinstance(m, str) else m for m in messages]))
