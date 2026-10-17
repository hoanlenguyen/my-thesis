"""Structured outputs the agents must return (enforced via tool-calling)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Assignment(BaseModel):
    appliance_id: str
    start_time: str = Field(description='Start time "HH:MM" on the 15-minute grid')


class ScheduleOutput(BaseModel):
    """Final daily schedule for the requested appliances."""

    assignments: list[Assignment]
    total_cost_eur: float = Field(description="Estimated total cost of the scheduled cycles in EUR")
    explanation: str = Field(description="One or two sentences on why these times were chosen")


class TaskBrief(BaseModel):
    """Orchestrator's parse of the household request."""

    appliance_ids: list[str] = Field(description="Ids of the appliances the user wants scheduled")
    notes: str = Field(description="Any constraints or preferences stated in the request")


class ApplianceProfile(BaseModel):
    appliance_id: str
    kind: str
    flexible: bool
    peak_kw: float
    duration_minutes: int
    earliest_time: str = Field(description='"HH:MM" the cycle may start')
    deadline_time: str = Field(description='"HH:MM" the cycle must be finished by')
    periods: list[str] | None = Field(
        default=None,
        description='Only with several allowed periods, e.g. ["06:00-09:00", "18:00-22:00"]: the cycle must start and '
        "finish inside one of them; earliest_time and deadline_time then span all of them",
    )


class ProfileOutput(BaseModel):
    """Appliance profiles for the requested appliances."""

    appliances: list[ApplianceProfile]


class ResolverOutput(BaseModel):
    """Conflict-free schedule after checking the household peak limit."""

    assignments: list[Assignment]
    conflicts_remaining: bool = Field(description="True if the peak limit is still exceeded")
    changes: str = Field(description="Which appliances were moved and why (or 'none')")


def assignments_to_dict(assignments: list[Assignment]) -> dict[str, str]:
    return {a.appliance_id: a.start_time for a in assignments}
