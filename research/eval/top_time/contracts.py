"""Explicit, versioned contracts; session indices always refer to one calendar."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

VERSION = "top_time_evaluator_v1_dev"


@dataclass(frozen=True)
class Protocol:
    """Research defaults, not frozen product parameters or fitted optima."""

    short_left: int = 10
    short_right: int = 10
    stage_left: int = 63
    stage_right: int = 42
    merge_gap: int = 5
    trough_left: int = 21
    trough_right: int = 21
    rise_min: int = 21
    rise_max: int = 126
    require_stage_rise: bool = True
    horizon: int = 63
    minimum_lead: int = 5
    maximum_width: int = 10
    require_entire_window_lead: bool = True
    price_field: str = "close"
    parameter_status: str = "RESEARCH_DEFAULT_NOT_FROZEN"

    def __post_init__(self) -> None:
        names = ("short_left", "short_right", "stage_left", "stage_right", "merge_gap",
                 "trough_left", "trough_right", "rise_min", "rise_max", "horizon",
                 "minimum_lead", "maximum_width")
        for name in names:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.stage_left < self.short_left or self.stage_right < self.short_right:
            raise ValueError("stage context must contain short context")
        if self.merge_gap > min(self.short_left, self.short_right,
                                self.trough_left, self.trough_right):
            raise ValueError("merge_gap must not exceed the smaller context")
        if self.rise_min > self.rise_max:
            raise ValueError("rise_min must not exceed rise_max")
        if self.price_field not in {"close", "high"}:
            raise ValueError("price_field must be close or high; never switch per event")
        for name in ("require_stage_rise", "require_entire_window_lead"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {"evaluator_version": VERSION, **asdict(self)}


@dataclass
class TopEvent:
    event_id: str
    symbol: str
    scale: str
    peak_session: int
    end_session: int
    candidate_sessions: tuple[int, ...]
    price: str
    support_start: int
    support_end: int
    available_session: int
    family_id: str = ""
    family_ambiguous: bool = False
    rise_start: int | None = None


@dataclass
class LabelBook:
    """known[scale][i] says event-anchor presence/absence at i is resolved.

    False is unknown, including immature tails and missing inputs. It is never
    a negative label. events contains only mature, eligible events.
    """

    symbol: str
    sessions: tuple[str, ...]
    asof_session: int
    events: list[TopEvent]
    known: dict[str, tuple[bool, ...]]
    pending: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Forecast:
    prediction_id: str
    episode_id: str
    symbol: str
    scope: str  # short / stage / both / uncertain
    interval_start: int
    interval_end: int
    data_cutoff_session: int
    published_session: int
    published_at: str  # timezone-aware ISO timestamp, supplied by source ledger
    action_session: int | None
    actionability: str = "unknown"  # verified / theoretical / unknown
    on_time: bool = True
    run_id: str | None = None
    parent_claim_id: str | None = None


@dataclass(frozen=True)
class ScheduledRun:
    run_id: str
    symbol: str
    cutoff_session: int
    status: str


@dataclass
class Evaluation:
    claims: list[dict[str, Any]]
    events: list[dict[str, Any]]
    metrics: dict[str, Any]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
