"""Explicit, versioned contracts; session indices always refer to one calendar."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

VERSION = "top_time_evaluator_v1_dev"
SCORING_CONTRACT_VERSION = "two_level_first_alert_v1"
LABEL_VERSION = "two_level_close_10_10_63_42_v1"


class LabelState(str, Enum):
    UNKNOWN = "unknown"
    PENDING = "pending"
    NO_EVENT = "no_event"
    MATURE_EVENT = "mature_event"


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
    label_available_session: int | None = None
    label_version: str = LABEL_VERSION

    def __post_init__(self) -> None:
        if self.label_available_session is None:
            self.label_available_session = self.available_session


@dataclass
class LabelBook:
    """Calendar-aligned label states; the legacy known mask remains derived."""

    symbol: str
    sessions: tuple[str, ...]
    asof_session: int
    events: list[TopEvent]
    known: dict[str, tuple[bool, ...]]
    pending: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    states: dict[str, tuple[LabelState, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.states:
            event_anchors = {(event.scale, event.peak_session) for event in self.events}
            pending_anchors: set[tuple[str, int]] = set()
            pending_ranges: dict[str, list[tuple[int, int]]] = {"short": [], "stage": []}
            for row in self.pending:
                scale = row.get("scale")
                peak = row.get("peak_session")
                reason = str(row.get("reason", ""))
                if scale in pending_ranges and type(peak) is int and reason in {
                    "PENDING_GROUP_CLOSURE", "UNMATURED_RIGHT_CONTEXT",
                    "RISE_SEARCH_UNRESOLVED", "RISE_UNMATURED_SUPPORT",
                }:
                    pending_anchors.add((scale, peak))
                if (
                    scale in pending_ranges
                    and row.get("kind") == "unresolved_anchor_range"
                    and reason in {"PENDING_GROUP_CLOSURE", "UNMATURED_RIGHT_CONTEXT"}
                    and type(row.get("start_session")) is int
                    and type(row.get("end_session")) is int
                ):
                    pending_ranges[scale].append((row["start_session"], row["end_session"]))
            derived: dict[str, tuple[LabelState, ...]] = {}
            for scale in ("short", "stage"):
                known = self.known.get(scale, (False,) * len(self.sessions))
                values = [
                    LabelState.NO_EVENT if resolved else LabelState.UNKNOWN
                    for resolved in known
                ]
                for start, end in pending_ranges[scale]:
                    for session in range(max(0, start), min(len(values) - 1, end) + 1):
                        if values[session] is LabelState.UNKNOWN:
                            values[session] = LabelState.PENDING
                for pending_scale, session in pending_anchors:
                    if pending_scale == scale and 0 <= session < len(values):
                        values[session] = LabelState.PENDING
                for event_scale, session in event_anchors:
                    if event_scale == scale and 0 <= session < len(values):
                        values[session] = LabelState.MATURE_EVENT
                derived[scale] = tuple(values)
            self.states = derived
        for scale in ("short", "stage"):
            values = self.states.get(scale)
            if not isinstance(values, (tuple, list)) or len(values) != len(self.sessions):
                raise ValueError(f"states[{scale}] must match the session calendar")
            if any(not isinstance(value, LabelState) for value in values):
                raise ValueError(f"states[{scale}] must use LabelState values")
            known = self.known.get(scale, (False,) * len(self.sessions))
            if len(known) != len(self.sessions):
                raise ValueError(f"known[{scale}] must match the session calendar")
            event_anchors = {
                event.peak_session for event in self.events if event.scale == scale
            }
            for session, (state, resolved) in enumerate(zip(values, known, strict=True)):
                if type(resolved) is not bool:
                    raise ValueError("known entries must be booleans")
                if (state in {LabelState.UNKNOWN, LabelState.PENDING}) == resolved:
                    raise ValueError("unresolved states and legacy known mask disagree")
                if (state is LabelState.MATURE_EVENT) != (session in event_anchors):
                    raise ValueError("mature-event states must match explicit event anchors")

    def state_at(self, scale: str, session: int) -> LabelState:
        return self.states[scale][session]


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
