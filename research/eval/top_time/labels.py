"""Calendar-preserving, retrospective labels; no forecast or model inputs.

An unresolved anchor is never a negative example.  ``available_session`` is a
data-dependency bound, not evidence that a label was actually published then.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .contracts import VERSION, LabelBook, Protocol, TopEvent

_DEFAULT_PROTOCOL = Protocol()


@dataclass
class _Inputs:
    sessions: tuple[str, ...]
    prices: tuple[Decimal | None, ...]
    available: tuple[int | None, ...]
    asof: int

    def reason(self, start: int, end: int) -> str | None:
        if start < 0:
            return "LEFT_TRUNCATED"
        if end > self.asof or end >= len(self.sessions):
            return "UNMATURED_RIGHT_CONTEXT"
        for i in range(start, end + 1):
            if self.available[i] is None:
                return "UNKNOWN_DATA_AVAILABILITY"
            if self.available[i] > self.asof:
                return "DELAYED_DATA"
            if self.prices[i] is None:
                return "MISSING_PRICE"
        return None

    def values(self, start: int, end: int) -> tuple[Decimal, ...]:
        values = self.prices[start : end + 1]
        if any(value is None for value in values):
            raise AssertionError("attempted to use an unresolved price")
        return tuple(value for value in values if value is not None)

    def available_at(self, start: int, end: int) -> int:
        if self.reason(start, end) is not None:
            raise AssertionError("attempted to publish unresolved dependencies")
        return max(value for value in self.available[start : end + 1] if value is not None)


@dataclass
class _Scan:
    events: list[TopEvent]
    known: list[bool]
    endpoint_known: list[bool]
    dependencies: list[tuple[int, int] | None]
    pending: list[dict[str, Any]]
    excluded: list[dict[str, Any]]


def _price(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a price")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid numeric price: {value!r}") from exc
    return result if result.is_finite() else None


def _canonical(value: Decimal) -> str:
    # Fixed decimal output avoids epsilon comparisons and floating-point casts.
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _prepare(
    sessions: Sequence[str],
    prices: Sequence[Any],
    asof_session: int | None,
    available_sessions: Sequence[int | None] | None,
) -> _Inputs:
    calendar = tuple(sessions)
    if len(calendar) != len(prices):
        raise ValueError("sessions and prices must have equal length; retain missing sessions")
    for session in calendar:
        if not isinstance(session, str) or date.fromisoformat(session).isoformat() != session:
            raise ValueError("sessions must be canonical ISO calendar dates")
    if any(a >= b for a, b in zip(calendar, calendar[1:], strict=False)):
        raise ValueError("sessions must be unique and strictly increasing")
    asof = len(calendar) - 1 if asof_session is None else asof_session
    if isinstance(asof, bool) or not isinstance(asof, int) or not -1 <= asof < len(calendar):
        raise ValueError("asof_session must be a calendar index, or -1 before the first session")
    if available_sessions is not None and len(available_sessions) != len(calendar):
        raise ValueError("available_sessions must have one entry per calendar session")
    availability: list[int | None] = []
    normalized: list[Decimal | None] = []
    for i in range(len(calendar)):
        if i > asof:
            # Even malformed future values must not affect a historical cutoff.
            availability.append(None)
            normalized.append(None)
            continue
        available = i if available_sessions is None else available_sessions[i]
        if available is not None and (
            isinstance(available, bool) or not isinstance(available, int) or available < i
        ):
            raise ValueError("data availability must be None or an integer no earlier than its row")
        availability.append(available)
        normalized.append(
            _price(prices[i]) if available is not None and available <= asof else None
        )
    return _Inputs(calendar, tuple(normalized), tuple(availability), asof)


def _unknown_ranges(scale: str, reasons: list[str | None]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    start = 0
    while start < len(reasons):
        reason = reasons[start]
        end = start
        while end + 1 < len(reasons) and reasons[end + 1] == reason:
            end += 1
        if reason is not None:
            result.append(
                {
                    "scale": scale,
                    "kind": "unresolved_anchor_range",
                    "start_session": start,
                    "end_session": end,
                    "reason": reason,
                }
            )
        start = end + 1
    return result


def _scan_extrema(
    symbol: str, data: _Inputs, scale: str, left: int, right: int, gap: int, *, trough: bool = False
) -> _Scan:
    n = len(data.sessions)
    candidates: list[bool | None] = [None] * n
    known = [False] * n
    endpoint_known = [False] * n
    dependencies: list[tuple[int, int] | None] = [None] * n
    reasons: list[str | None] = [None] * n
    extreme = min if trough else max
    for i in range(n):
        point_reason = data.reason(i - left, i + right)
        complete_reason = data.reason(i - left, i + right + gap)
        reasons[i] = point_reason or complete_reason
        if point_reason is None:
            candidates[i] = data.prices[i] == extreme(data.values(i - left, i + right))
        if complete_reason is None and candidates[i] is False:
            known[i] = endpoint_known[i] = True
            dependencies[i] = (i - left, i + right + gap)
        elif candidates[i] is True:
            reasons[i] = reasons[i] or "PENDING_GROUP_CLOSURE"

    groups: list[list[int]] = []
    for i, candidate in enumerate(candidates):
        if candidate is not True:
            continue
        if groups:
            previous = groups[-1][-1]
            if (
                i - previous <= gap
                and data.prices[i] == data.prices[previous]
                and extreme(data.values(previous, i)) == data.prices[i]
            ):
                groups[-1].append(i)
                continue
        groups.append([i])

    events: list[TopEvent] = []
    pending: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for group in groups:
        u, v = group[0], group[-1]
        start, end = u - left, v + gap + right
        reason = data.reason(start, end)
        # A delayed or left-truncated same-price predecessor may change the
        # representative u.  Its candidate test is an actual dependency too.
        for j in range(max(0, u - gap), u):
            if data.prices[j] != data.prices[u]:
                continue
            start = min(start, j - left)
            if candidates[j] is None:
                reason = "UNRESOLVED_SAME_PRICE_PREDECESSOR"
        reason = reason or data.reason(start, end)
        record = {
            "scale": scale,
            "peak_session": u,
            "end_session": v,
            "candidate_sessions": tuple(group),
            "support_start": start,
            "support_end": end,
        }
        if reason is not None:
            pending.append({**record, "reason": reason})
            for i in range(u, v + 1):
                known[i] = endpoint_known[i] = False
                dependencies[i] = None
                reasons[i] = reason
            continue

        record["available_session"] = data.available_at(start, end)
        value = data.prices[u]
        assert value is not None
        left_values = data.values(u - left, u - 1)
        right_values = data.values(v + 1, v + right)
        has_left_turn = any(p > value if trough else p < value for p in left_values)
        has_right_turn = any(p > value if trough else p < value for p in right_values)
        for i in range(u, v + 1):
            known[i] = endpoint_known[i] = True
            dependencies[i] = (start, end)
            reasons[i] = None
        if not has_left_turn or not has_right_turn:
            excluded.append(
                {
                    **record,
                    "reason": "NO_TWO_SIDED_TURN",
                    "left_strict_turn": has_left_turn,
                    "right_strict_turn": has_right_turn,
                }
            )
            continue
        events.append(
            TopEvent(
                event_id=f"{symbol}:{scale}:{data.sessions[u]}:{data.sessions[v]}",
                symbol=symbol,
                scale=scale,
                peak_session=u,
                end_session=v,
                candidate_sessions=tuple(group),
                price=_canonical(value),
                support_start=start,
                support_end=end,
                available_session=data.available_at(start, end),
            )
        )
    pending.extend(_unknown_ranges(scale, reasons))
    return _Scan(events, known, endpoint_known, dependencies, pending, excluded)


def _rise(
    event: TopEvent, troughs: _Scan, data: _Inputs, config: Protocol
) -> tuple[bool | None, dict[str, Any], tuple[int, int] | None]:
    u = event.peak_session
    low, high = u - config.rise_max, u - config.rise_min
    audit: dict[str, Any] = {
        "scale": "stage",
        "event_id": event.event_id,
        "peak_session": u,
        "trough_endpoint_search": (low, high),
        "rule": "RETROSPECTIVE_FIXED_RANGE_NEAREST_CLOSED_TROUGH",
        "required_minimum_support_start": min(
            event.support_start, low - config.trough_left
        ),
        "required_minimum_support_end": max(
            event.support_end, high + config.trough_right + config.merge_gap
        ),
    }
    if low < 0:
        return None, {**audit, "reason": "RISE_SEARCH_LEFT_TRUNCATED"}, None
    unresolved = [i for i in range(low, high + 1) if not troughs.endpoint_known[i]]
    if unresolved:
        return (
            None,
            {**audit, "reason": "RISE_SEARCH_UNRESOLVED", "unresolved_sessions": tuple(unresolved)},
            None,
        )
    ranges = [troughs.dependencies[i] for i in range(low, high + 1)]
    assert all(item is not None for item in ranges)
    start = min(event.support_start, *(item[0] for item in ranges if item is not None))
    end = max(event.support_end, *(item[1] for item in ranges if item is not None))
    eligible = [item for item in troughs.events if low <= item.end_session <= high]
    audit["eligible_trough_ids"] = tuple(item.event_id for item in eligible)
    audit.update(support_start=start, support_end=end)
    reason = data.reason(start, end)
    if reason is not None:
        return None, {**audit, "reason": f"RISE_{reason}"}, None
    audit["available_session"] = data.available_at(start, end)
    if not eligible:
        return False, {**audit, "reason": "NO_ELIGIBLE_TROUGH"}, (start, end)
    # Selection happens before direction or path validation.  Never fall back
    # to an older, more convenient trough after rejecting the nearest one.
    selected = max(eligible, key=lambda item: item.end_session)
    a = selected.end_session
    start = min(start, selected.support_start, a)
    end = max(end, selected.support_end)
    audit.update(
        selected_trough_id=selected.event_id,
        rise_start=a,
        rise_duration=u - a,
        trough_price=selected.price,
        trough_available_session=selected.available_session,
        support_start=start,
        support_end=end,
    )
    reason = data.reason(start, end)
    if reason is not None:
        return None, {**audit, "reason": f"RISE_{reason}"}, None
    audit["available_session"] = data.available_at(start, end)
    valley = data.prices[a]
    peak = data.prices[u]
    assert valley is not None and peak is not None
    if peak <= valley:
        return False, {**audit, "reason": "RISE_NOT_NET_UP"}, (start, end)
    breaches = tuple(i for i in range(a + 1, u + 1) if data.prices[i] < valley)
    if breaches:
        return (
            False,
            {**audit, "reason": "RISE_TROUGH_BREACHED", "breach_sessions": breaches},
            (start, end),
        )
    return True, {**audit, "reason": "RISE_CONFIRMED"}, (start, end)


def _assign_families(events: list[TopEvent]) -> list[dict[str, str]]:
    """Keep all cross-layer links, including many-to-one ambiguity."""
    links: list[dict[str, str]] = []
    adjacency: dict[str, set[str]] = {event.event_id: set() for event in events}
    by_id = {event.event_id: event for event in events}
    short = [event for event in events if event.scale == "short"]
    stage = [event for event in events if event.scale == "stage"]
    for first in short:
        for second in stage:
            if Decimal(first.price) != Decimal(second.price):
                continue
            if not set(first.candidate_sessions).intersection(second.candidate_sessions):
                continue
            adjacency[first.event_id].add(second.event_id)
            adjacency[second.event_id].add(first.event_id)
            links.append({"short_event_id": first.event_id, "stage_event_id": second.event_id})
    visited: set[str] = set()
    for event in events:
        if event.event_id in visited:
            continue
        component: set[str] = set()
        stack = [event.event_id]
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(adjacency[current] - component)
        visited.update(component)
        family = "family:" + min(component)
        ambiguous = any(len(adjacency[item]) > 1 for item in component)
        for item in component:
            by_id[item].family_id = family
            by_id[item].family_ambiguous = ambiguous
    return links


def build_labels(
    symbol: str,
    sessions: Sequence[str],
    prices: Sequence[Any],
    *,
    config: Protocol = _DEFAULT_PROTOCOL,
    asof_session: int | None = None,
    available_sessions: Sequence[int | None] | None = None,
    input_status: str = "UNVERIFIED",
) -> LabelBook:
    """Build only mature labels from an explicit, uncompressed session calendar.

    Missing/NaN prices stay missing.  Inputs after the cutoff, including prices
    delivered later than the cutoff, are never used.  The optional availability
    sequence contains first-available calendar indices (None means unknown).
    Defaults assume same-session availability and do not establish PIT history.
    """
    data = _prepare(sessions, prices, asof_session, available_sessions)
    short = _scan_extrema(
        symbol, data, "short", config.short_left, config.short_right, config.merge_gap
    )
    stage = _scan_extrema(
        symbol, data, "stage", config.stage_left, config.stage_right, config.merge_gap
    )
    troughs = _scan_extrema(
        symbol,
        data,
        "trough",
        config.trough_left,
        config.trough_right,
        config.merge_gap,
        trough=True,
    )
    structure_audit = [asdict(event) for event in stage.events]
    selected_stage: list[TopEvent] = []
    pending = short.pending + stage.pending
    excluded = short.excluded + stage.excluded
    rise_audit: list[dict[str, Any]] = []
    for event in stage.events:
        if not config.require_stage_rise:
            selected_stage.append(event)
            continue
        decision, audit, support = _rise(event, troughs, data, config)
        rise_audit.append(audit)
        if decision is None:
            stage.known[event.peak_session] = False
            stage.dependencies[event.peak_session] = None
            pending.append(audit)
            continue
        assert support is not None
        stage.dependencies[event.peak_session] = support
        if not decision:
            excluded.append(audit)
            continue
        event.rise_start = audit["rise_start"]
        event.support_start, event.support_end = support
        event.available_session = data.available_at(*support)
        selected_stage.append(event)
    events = sorted(short.events + selected_stage, key=lambda item: (item.peak_session, item.scale))
    links = _assign_families(events)
    known_support: dict[str, list[dict[str, int] | None]] = {}
    for name, scan in (("short", short), ("stage", stage)):
        known_support[name] = [
            {
                "support_start": support[0],
                "support_end": support[1],
                "available_session": data.available_at(*support),
            }
            if known and support is not None
            else None
            for known, support in zip(scan.known, scan.dependencies, strict=True)
        ]
    metadata = {
        "evaluator_version": VERSION,
        "config": config.to_dict(),
        "stage_target": "STAGE_RISE" if config.require_stage_rise else "STAGE_STRUCTURE",
        "rise_search_policy": "ENTIRE_FIXED_ENDPOINT_RANGE_RESOLVED_NO_FALLBACK",
        "provenance": {
            "input_status": input_status,
            "calendar_basis": "CALLER_SUPPLIED_EXPLICIT_SESSIONS_UNVERIFIED",
            "availability_basis": (
                "ASSUMED_SAME_SESSION_NON_PIT"
                if available_sessions is None
                else "CALLER_SUPPLIED_AVAILABLE_SESSIONS_UNVERIFIED"
            ),
            "price_field": config.price_field,
            "price_encoding": "DECIMAL_FROM_INPUT_STRING_NO_EPSILON",
            "historical_publication": "NOT_ESTABLISHED",
            "asof_session": data.asof,
        },
        "known_support": known_support,
        "stage_structure_events": structure_audit,
        "trough_events": [asdict(event) for event in troughs.events],
        "trough_pending": troughs.pending,
        "rise_audit": rise_audit,
        "family_links": links,
    }
    return LabelBook(
        symbol=symbol,
        sessions=data.sessions,
        asof_session=data.asof,
        events=events,
        known={"short": tuple(short.known), "stage": tuple(stage.known)},
        pending=pending,
        excluded=excluded,
        metadata=metadata,
    )
