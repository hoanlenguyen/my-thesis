"""Scenario data model shared by every system (MILP, naive, single-agent, multi-agent).

Time is discretised into 15-minute slots. A scenario covers exactly 96 slots
(24 hours) starting at ``start_time``; because the horizon is 24 h, an "HH:MM"
clock time maps to exactly one slot, which is the representation the LLM
agents read and write.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from collections.abc import Sequence

from pydantic import BaseModel, Field, model_serializer, model_validator

SLOT_MINUTES = 15
SLOTS_PER_DAY = 96
SLOT_HOURS = SLOT_MINUTES / 60

# "A".."F": the six types of the first benchmarks (data/scenarios, data/scenarios_15min).
# "<regime>-<load>-<limit>", e.g. "volatile-heavy-strict": the factorial design (hems.data.factorial).
ScenarioType = str
# The benchmarks use the three REFIT kinds; the demo's "Try it" view also offers constant-power loads
# from the Low-carbon-alerts appliance catalog (EV charger, sauna, hot tub, electric oven).
FlexibleKind = Literal["washing_machine", "dishwasher", "tumble_dryer", "ev_charger", "sauna", "hot_tub", "electric_oven"]


class FlexibleAppliance(BaseModel):
    """A shiftable appliance cycle the household wants run within a window."""

    id: str
    kind: FlexibleKind
    profile_kw: list[float] = Field(description="Mean power per 15-min slot over one cycle")
    earliest_slot: int = Field(ge=0, lt=SLOTS_PER_DAY)
    deadline_slot: int = Field(gt=0, le=SLOTS_PER_DAY, description="Cycle must end at or before this slot boundary")
    default_start_slot: int = Field(ge=0, lt=SLOTS_PER_DAY, description="Start time without scheduling (naive baseline)")
    # Optional allowed periods [start, end) in slot boundaries, sorted and disjoint, e.g. 06:00-09:00 and
    # 18:00-22:00; a cycle must start and finish inside one of them. Used only by the demo's "Try it" view:
    # None (every benchmark scenario) means the single window earliest_slot..deadline_slot, which then spans
    # the periods. Left out of serialised output when None, so saved scenarios are unchanged.
    windows: list[tuple[int, int]] | None = None

    @property
    def duration_slots(self) -> int:
        return len(self.profile_kw)

    @property
    def energy_kwh(self) -> float:
        return sum(self.profile_kw) * SLOT_HOURS

    @property
    def peak_kw(self) -> float:
        return max(self.profile_kw)

    @property
    def latest_start_slot(self) -> int:
        return self.deadline_slot - self.duration_slots

    def valid_starts(self) -> Sequence[int]:
        if self.windows is None:
            return range(self.earliest_slot, self.latest_start_slot + 1)
        return [s for start, end in self.windows for s in range(start, end - self.duration_slots + 1)]

    def window_periods(self) -> list[tuple[int, int]]:
        """The allowed periods [start, end): the single window unless several periods are given."""
        return list(self.windows) if self.windows is not None else [(self.earliest_slot, self.deadline_slot)]

    @model_validator(mode="after")
    def _check_window(self) -> FlexibleAppliance:
        if not self.profile_kw:
            raise ValueError(f"{self.id}: empty profile")
        if self.windows is not None:
            if not self.windows:
                raise ValueError(f"{self.id}: empty list of periods")
            for (s0, e0), (s1, _) in zip(self.windows, self.windows[1:], strict=False):
                if s1 < e0:
                    raise ValueError(f"{self.id}: periods must be sorted and must not overlap")
            if any(not (0 <= s < e <= SLOTS_PER_DAY) for s, e in self.windows):
                raise ValueError(f"{self.id}: period outside the day")
            if (self.earliest_slot, self.deadline_slot) != (self.windows[0][0], self.windows[-1][1]):
                raise ValueError(f"{self.id}: earliest_slot and deadline_slot must span the periods")
            if not self.valid_starts():
                raise ValueError(f"{self.id}: every period is shorter than the cycle")
        elif self.latest_start_slot < self.earliest_slot:
            raise ValueError(f"{self.id}: window shorter than cycle")
        if self.default_start_slot not in self.valid_starts():
            raise ValueError(f"{self.id}: default start outside window")
        return self

    @model_serializer(mode="wrap")
    def _drop_unset_windows(self, handler):  # type: ignore[no-untyped-def]
        data = handler(self)
        if self.windows is None:
            data.pop("windows", None)
        return data


class FixedAppliance(BaseModel):
    """A non-shiftable load (fridge, microwave, ...). Its consumption is in base_load_kw."""

    id: str
    kind: str
    typical_power_kw: float


class Scenario(BaseModel):
    id: str
    type: ScenarioType
    date: str
    start_time: datetime = Field(description="Local time of slot 0 (Europe/Helsinki)")
    spot_eur_per_kwh: list[float] = Field(description="Nord Pool FI day-ahead spot price per slot")
    price_eur_per_kwh: list[float] = Field(description="Consumer price per slot used for cost (see data.tariff)")
    base_load_kw: list[float] = Field(description="Non-shiftable household load per slot")
    peak_limit_kw: float = Field(gt=0, description="Household load must never exceed this")
    appliances: list[FlexibleAppliance]
    fixed_appliances: list[FixedAppliance] = []
    user_request: str
    synthetic: bool = Field(default=False, description="True for generated dev/pilot data, never for thesis results")
    notes: str = ""

    @model_validator(mode="after")
    def _check_lengths(self) -> Scenario:
        for name in ("spot_eur_per_kwh", "price_eur_per_kwh", "base_load_kw"):
            if len(getattr(self, name)) != SLOTS_PER_DAY:
                raise ValueError(f"{name} must have {SLOTS_PER_DAY} slots")
        ids = [a.id for a in self.appliances]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate appliance ids")
        return self

    def appliance(self, appliance_id: str) -> FlexibleAppliance:
        for a in self.appliances:
            if a.id == appliance_id:
                return a
        known = ", ".join(a.id for a in self.appliances)
        raise ValueError(f"unknown appliance {appliance_id!r}; schedulable appliances: {known}")

    # ── clock-time helpers (the agents' vocabulary) ──────────────────────────
    def slot_to_time(self, slot: int) -> str:
        minutes = (self.start_time.hour * 60 + self.start_time.minute + slot * SLOT_MINUTES) % 1440
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    def boundary_to_time(self, slot: int) -> str:
        """Clock time of a slot boundary; the end of the horizon is "24:00" (or "HH:MM next day")."""
        if slot < SLOTS_PER_DAY:
            return self.slot_to_time(slot)
        clock = self.slot_to_time(slot % SLOTS_PER_DAY)
        return "24:00" if clock == "00:00" else f"{clock} next day"

    def time_to_slot(self, clock: str) -> int:
        """Parse "HH:MM" into a slot index. Off-grid minutes are floored to the slot."""
        hh, mm = clock.strip().split(":")[:2]
        minutes = int(hh) * 60 + int(mm)
        if not (0 <= minutes < 1440):
            raise ValueError(f"invalid clock time {clock!r}")
        offset = (minutes - (self.start_time.hour * 60 + self.start_time.minute)) % 1440
        return offset // SLOT_MINUTES

    # ── persistence ──────────────────────────────────────────────────────────
    @classmethod
    def load(cls, path: str | Path) -> Scenario:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.model_dump(mode="json"), indent=1), encoding="utf-8")


def load_scenarios(directory: str | Path) -> list[Scenario]:
    return [Scenario.load(p) for p in sorted(Path(directory).glob("*.json")) if p.name != "manifest.json"]


Schedule = dict[str, int]
"""Appliance id -> start slot."""
