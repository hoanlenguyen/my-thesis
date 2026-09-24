from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentRun:
    """What a scheduling system returns; scoring happens later in core.evaluate."""

    assignments: dict[str, str] | None  # appliance_id -> "HH:MM"; None if the system failed
    explanation: str = ""
    errors: list[str] = field(default_factory=list)
    tool_calls: int = 0
    iterations: int = 0
