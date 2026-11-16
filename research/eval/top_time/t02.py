"""Frozen T02 label, claim-lifecycle, interval, and scoring contracts."""
from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from types import MappingProxyType
from typing import Any

from .contracts import LABEL_VERSION, SCORING_CONTRACT_VERSION, LabelBook, LabelState

CLAIM_KINDS = frozenset({"observation", "formal", "revision", "new"})
SCOPES = ("short", "stage")
PRIMARY_CAUSE_PRIORITY = (
    "data_not_evaluable",
    "no_alert",
    "reversed_non_future_beyond_H",
    "too_wide",
    "early_late",
    "insufficient_lead",
    "success",
)


def action_session_after_close(sessions: Sequence[str], published_session: int) -> int:
    """A full-close delivery is actionable only on the next calendar session."""
    if isinstance(published_session, bool) or not isinstance(published_session, int):
        raise ValueError("published_session must be an integer calendar index")
    if not 0 <= published_session < len(sessions) - 1:
        raise ValueError("a next session is required after the full-close delivery")
    return published_session + 1


def formal_interval_gate(
    action_session: int,
    interval_start: int,
    interval_end: int,
    *,
    horizon: int = 63,
    minimum_lead: int = 5,
    maximum_width: int = 10,
) -> dict[str, Any]:
    """Apply the same untrimmed, inclusive geometry gate to every arm."""
    values = (action_session, interval_start, interval_end, horizon, minimum_lead, maximum_width)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ValueError("interval geometry uses integer session indices")
    if horizon < 1 or minimum_lead < 1 or maximum_width < 1:
        raise ValueError("geometry limits must be positive")
    if interval_end < interval_start:
        return {
            "formal": False,
            "inclusive_width": interval_end - interval_start + 1,
            "window_lead": interval_start - action_session,
            "reasons": ["reversed"],
            "interval_start": interval_start,
            "interval_end": interval_end,
        }
    width = interval_end - interval_start + 1
    reasons = []
    if interval_start <= action_session:
        reasons.append("not_future")
    if width > maximum_width:
        reasons.append("too_wide")
    if interval_start - action_session < minimum_lead:
        reasons.append("insufficient_lead")
    if interval_end > action_session + horizon:
        reasons.append("beyond_H")
    return {
        "formal": not reasons,
        "inclusive_width": width,
        "window_lead": interval_start - action_session,
        "reasons": reasons,
        "interval_start": interval_start,
        "interval_end": interval_end,
    }


class AppendOnlyClaimLedger:
    """Append-only claim records; scoring results are not accepted as inputs."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []
        self._by_id: dict[str, dict[str, Any]] = {}
        self._last_by_episode_scope: dict[tuple[str, str], dict[str, Any]] = {}
        self._first_formal_by_episode_scope: dict[tuple[str, str], dict[str, Any]] = {}

    def append(self, claim: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(claim, Mapping):
            raise TypeError("claim must be a mapping")
        row = copy.deepcopy(dict(claim))
        required = {
            "claim_id", "parent_claim_id", "episode_id", "kind", "scope",
            "interval_start", "interval_end", "first_clock_session",
            "fixed_expiry_session", "action_session", "mode",
        }
        missing = required - row.keys()
        if missing:
            raise ValueError(f"claim missing fields: {sorted(missing)}")
        if row["kind"] not in CLAIM_KINDS:
            raise ValueError("unknown claim kind")
        if row["scope"] not in SCOPES:
            raise ValueError("scope must be short or stage")
        if row["mode"] not in {"historical_replay", "forward"}:
            raise ValueError("mode must be historical_replay or forward")
        for name in (
            "interval_start", "interval_end", "first_clock_session",
            "fixed_expiry_session", "action_session",
        ):
            value = row[name]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        if row["interval_end"] < row["interval_start"]:
            raise ValueError("interval_end must not precede interval_start")
        if row["fixed_expiry_session"] < row["first_clock_session"]:
            raise ValueError("fixed expiry cannot precede the first clock")
        supplied_first_fields = {
            field for field in (
                "first_interval_start", "first_interval_end",
                "first_clock_session", "fixed_expiry_session",
            ) if field in row
        }
        row.setdefault("first_interval_start", row["interval_start"])
        row.setdefault("first_interval_end", row["interval_end"])
        if (
            isinstance(row["first_interval_start"], bool)
            or not isinstance(row["first_interval_start"], int)
            or isinstance(row["first_interval_end"], bool)
            or not isinstance(row["first_interval_end"], int)
            or row["first_interval_end"] < row["first_interval_start"]
        ):
            raise ValueError("first interval must be an ordered integer pair")
        if not isinstance(row["claim_id"], str) or not row["claim_id"]:
            raise ValueError("claim_id must be nonempty")
        if not isinstance(row["episode_id"], str) or not row["episode_id"]:
            raise ValueError("episode_id must be nonempty")
        if row["claim_id"] in self._by_id:
            raise ValueError("claim_id already exists; ledger rows cannot be replaced")

        key = (row["episode_id"], row["scope"])
        previous = self._last_by_episode_scope.get(key)
        first_formal = self._first_formal_by_episode_scope.get(key)
        parent_id = row["parent_claim_id"]
        if parent_id is not None:
            if not isinstance(parent_id, str) or not parent_id:
                raise ValueError("parent_claim_id must be a nonempty string or null")
            parent = self._by_id.get(parent_id)
            if parent is None or (parent["episode_id"], parent["scope"]) != key:
                raise ValueError("parent claim must already exist in the same scope episode")
        if previous is not None and row["action_session"] < previous["action_session"]:
            raise ValueError("claim action sessions must be append-only and nondecreasing")
        if row["kind"] == "revision":
            if (
                first_formal is None or previous is None
                or row["parent_claim_id"] != previous["claim_id"]
            ):
                raise ValueError("a revision must append to the latest claim in its scope episode")
            if row["action_session"] > first_formal["fixed_expiry_session"]:
                raise ValueError("a revision cannot extend a fixed-expiry episode")
            for field in (
                "first_interval_start", "first_interval_end",
                "first_clock_session", "fixed_expiry_session",
            ):
                if row[field] != first_formal[field]:
                    raise ValueError(f"revision cannot change sealed {field}")
        elif row["kind"] in {"formal", "new"} and first_formal is not None:
            raise ValueError("an existing episode must use a revision, not a new first claim")
        elif row["kind"] in {"formal", "new"} and row["first_clock_session"] != row["action_session"]:
            raise ValueError("a scope episode clock starts at its own first action session")
        elif row["kind"] == "observation" and first_formal is not None:
            for field in (
                "first_interval_start", "first_interval_end",
                "first_clock_session", "fixed_expiry_session",
            ):
                if field not in supplied_first_fields:
                    row[field] = first_formal[field]
                elif row[field] != first_formal[field]:
                    raise ValueError(f"observation cannot change sealed {field}")

        if row["mode"] == "historical_replay":
            if row.get("first_visible_at") is not None:
                raise ValueError("historical replay cannot invent first_visible_at")
            for field in ("simulated_available_at", "simulated_action_session", "delay_assumption"):
                if row.get(field) in (None, ""):
                    raise ValueError(f"historical replay requires {field}")
            if row["simulated_action_session"] != row["action_session"]:
                raise ValueError("action_session must match simulated_action_session")
            if not row.get("pit_evidence"):
                row["vintage_status"] = "HISTORICAL_VINTAGE_NOT_ESTABLISHED"
        else:
            visible = row.get("first_visible_at")
            if not isinstance(visible, str) or not visible:
                raise ValueError("forward claims require delivery-backed first_visible_at")
            try:
                stamp = datetime.fromisoformat(visible.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("first_visible_at must be an ISO timestamp") from exc
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("first_visible_at must be timezone-aware")
            if not row.get("delivery_evidence"):
                raise ValueError("forward claims require delivery evidence")
            if row.get("full_close_data", False):
                published = row.get("published_session")
                if isinstance(published, bool) or not isinstance(published, int):
                    raise ValueError("full-close claims require published_session")
                close_at = row.get("published_session_close_at")
                if not isinstance(close_at, str) or not close_at:
                    raise ValueError("full-close claims require the fixed session close timestamp")
                try:
                    close_stamp = datetime.fromisoformat(close_at.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise ValueError("published_session_close_at must be an ISO timestamp") from exc
                if close_stamp.tzinfo is None or close_stamp.utcoffset() is None:
                    raise ValueError("published_session_close_at must be timezone-aware")
                if stamp < close_stamp:
                    raise ValueError("full-close data cannot be visible before the session close")
                if row["action_session"] != published + 1:
                    raise ValueError("full-close data is actionable only next session")
        if row["kind"] in {"formal", "revision", "new"}:
            gate = formal_interval_gate(
                row["action_session"], row["interval_start"], row["interval_end"]
            )
            if not gate["formal"]:
                raise ValueError(f"formal claim fails geometry gate: {gate['reasons']}")

        self._rows.append(row)
        self._by_id[row["claim_id"]] = row
        self._last_by_episode_scope[key] = row
        if row["kind"] in {"formal", "new"}:
            self._first_formal_by_episode_scope[key] = row
        return MappingProxyType(copy.deepcopy(row))

    @property
    def rows(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(MappingProxyType(copy.deepcopy(row)) for row in self._rows)

    def to_list(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._rows)

    def update(self, *_: Any, **__: Any) -> None:
        raise TypeError("claim ledger is append-only")

    def delete(self, *_: Any, **__: Any) -> None:
        raise TypeError("claim ledger is append-only")


def _state(book: LabelBook, scale: str, session: int) -> LabelState:
    value = book.state_at(scale, session)
    return value if isinstance(value, LabelState) else LabelState(value)


def _next_target(
    book: LabelBook,
    event_by_anchor: Mapping[tuple[str, int], Any],
    scope: str,
    action_session: int,
    horizon: int,
) -> tuple[str, Any | None, int | None]:
    if action_session < 0 or action_session >= book.asof_session:
        return "pending", None, action_session
    limit = min(action_session + horizon, book.asof_session)
    for session in range(action_session + 1, limit + 1):
        state = _state(book, scope, session)
        if state in {LabelState.UNKNOWN, LabelState.PENDING}:
            return "pending", None, session
        if state is LabelState.MATURE_EVENT:
            event = event_by_anchor.get((scope, session))
            if event is None:
                return "pending", None, session
            return "event", event, None
    if action_session + horizon > book.asof_session:
        return "pending", None, book.asof_session + 1
    return "no_event", None, None


def _rows(claims: Any) -> list[dict[str, Any]]:
    if isinstance(claims, AppendOnlyClaimLedger):
        return claims.to_list()
    if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)):
        raise TypeError("claims must be a sequence or AppendOnlyClaimLedger")
    if any(not isinstance(row, Mapping) for row in claims):
        raise TypeError("each claim must be a mapping")
    return [copy.deepcopy(dict(row)) for row in claims]


def score_t02(
    book: LabelBook,
    claims: Sequence[Mapping[str, Any]] | AppendOnlyClaimLedger,
    *,
    data_evaluable_event_ids: set[str] | None = None,
    horizon: int = 63,
    minimum_lead: int = 5,
    maximum_width: int = 10,
    start_session: int = 0,
    end_session: int | None = None,
) -> dict[str, Any]:
    """Score first formal claims by the next same-scope label, never by interval."""
    source = _rows(claims)
    if horizon < 1:
        raise ValueError("horizon must be positive")
    range_end = book.asof_session if end_session is None else end_session
    if (
        isinstance(start_session, bool) or not isinstance(start_session, int)
        or isinstance(range_end, bool) or not isinstance(range_end, int)
        or start_session < 0 or start_session > range_end or range_end > book.asof_session
    ):
        raise ValueError("scoring range must be inside the label book asof")
    events_by_scope = {
        scope: sorted((event for event in book.events if event.scale == scope),
                      key=lambda event: (event.peak_session, event.event_id))
        for scope in SCOPES
    }
    event_by_anchor: dict[tuple[str, int], Any] = {}
    for event in sorted(book.events, key=lambda item: (item.scale, item.peak_session, item.event_id)):
        event_by_anchor.setdefault((event.scale, event.peak_session), event)
    output: dict[str, Any] = {
        "scoring_contract_version": SCORING_CONTRACT_VERSION,
        "label_version": book.metadata.get("label_version", LABEL_VERSION),
        "tie_break": "first_clock_session, action_session, claim_id; event anchors by session then event_id",
        "scopes": {},
    }

    for scope in SCOPES:
        scope_rows = [
            row for row in source
            if row.get("scope") == scope and row.get("kind") in CLAIM_KINDS
        ]
        episode_rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in scope_rows:
            episode_rows[(str(row.get("episode_id", "")), scope)].append(row)
        first_rows: list[dict[str, Any]] = []
        for group in episode_rows.values():
            base = [
                row for row in group
                if row.get("kind") in {"new", "formal"}
            ]
            if not base:
                continue
            base.sort(key=lambda row: (
                row.get("first_clock_session", row.get("action_session", -1)),
                row.get("action_session", -1),
                str(row.get("claim_id", "")),
            ))
            first_rows.append(base[0])
        first_rows.sort(key=lambda row: (
            row.get("first_clock_session", row.get("action_session", -1)),
            row.get("action_session", -1),
            str(row.get("claim_id", "")),
        ))

        claim_results: list[dict[str, Any]] = []
        primary_by_event: dict[str, dict[str, Any]] = {}
        for row in first_rows:
            start = row.get("first_interval_start", row.get("interval_start"))
            end = row.get("first_interval_end", row.get("interval_end"))
            action = row.get("action_session")
            if any(isinstance(value, bool) or not isinstance(value, int) for value in (start, end)):
                gate = {"formal": False, "reasons": ["invalid_interval"], "inclusive_width": None}
            elif isinstance(action, bool) or not isinstance(action, int):
                gate = {"formal": False, "reasons": ["missing_action_session"], "inclusive_width": end - start + 1}
            else:
                gate = formal_interval_gate(
                    action, start, end, horizon=horizon,
                    minimum_lead=minimum_lead, maximum_width=maximum_width,
                )
            claim_result = {
                "claim_id": row.get("claim_id"),
                "episode_id": row.get("episode_id"),
                "scope": scope,
                "action_session": action,
                "interval_start": start,
                "interval_end": end,
                "formal": gate["formal"],
                "geometry_reasons": gate["reasons"],
                "target_status": "not_formal",
                "target_event_id": None,
                "unknown_blocker_session": None,
                "primary": False,
                "duplicate": False,
                "first_window_covered": False,
                "lead": None,
                "strict_success": False,
            }
            if not gate["formal"]:
                claim_results.append(claim_result)
                continue
            target_status, target_event, blocker = _next_target(
                book, event_by_anchor, scope, action, horizon
            )
            claim_result["target_status"] = target_status
            claim_result["unknown_blocker_session"] = blocker
            if target_status == "event" and target_event is not None:
                claim_result["target_event_id"] = target_event.event_id
                if target_event.event_id in primary_by_event:
                    claim_result["duplicate"] = True
                else:
                    claim_result["primary"] = True
                    primary_by_event[target_event.event_id] = claim_result
                lead = target_event.peak_session - action
                covered = start <= target_event.peak_session <= end
                claim_result["lead"] = lead
                claim_result["first_window_covered"] = covered
                claim_result["strict_success"] = bool(
                    claim_result["primary"]
                    and covered
                    and lead >= minimum_lead
                    and gate["inclusive_width"] <= maximum_width
                    and start - action >= minimum_lead
                    and end <= action + horizon
                )
            claim_results.append(claim_result)

        event_results = []
        for event in events_by_scope[scope]:
            if not start_session <= event.peak_session <= range_end:
                continue
            first = primary_by_event.get(event.event_id)
            event_results.append({
                "event_id": event.event_id,
                "symbol": event.symbol,
                "scope": scope,
                "peak_session": event.peak_session,
                "support_end": event.support_end,
                "label_available_session": event.label_available_session,
                "label_version": event.label_version,
                "data_evaluable": (
                    None if data_evaluable_event_ids is None
                    else event.event_id in data_evaluable_event_ids
                ),
                "first_formal_claim_id": first["claim_id"] if first else None,
                "first_window_covered": bool(first and first["first_window_covered"]),
                "qualified_recall5": bool(
                    first and first["first_window_covered"] and first["lead"] >= minimum_lead
                ),
                "strict_success": bool(first and first["strict_success"]),
            })

        E = len(event_results)
        event_ids_in_range = {row["event_id"] for row in event_results}
        no_alert = sum(row["first_formal_claim_id"] is None for row in event_results)
        covered = sum(row["first_window_covered"] for row in event_results)
        recall5 = sum(row["qualified_recall5"] for row in event_results)
        strict = sum(row["strict_success"] for row in event_results)
        resolved_claims = [
            row for row in claim_results
            if row["formal"]
            and row["target_status"] in {"event", "no_event"}
            and (
                start_session <= row["action_session"] <= range_end
                or row["target_event_id"] in event_ids_in_range
            )
        ]
        precision_hits = sum(row["strict_success"] for row in resolved_claims)
        revisions = sum(
            row.get("kind") == "revision"
            and isinstance(row.get("action_session"), int)
            and start_session <= row["action_session"] <= range_end
            for row in scope_rows
        )
        duplicate_notices = sum(
            row["duplicate"] and row["target_event_id"] in event_ids_in_range
            for row in claim_results
        )
        notice_rows = [
            row for row in source
            if row.get("scope") == scope and row.get("kind") in CLAIM_KINDS
            and isinstance(row.get("action_session"), int)
            and start_session <= row["action_session"] <= range_end
        ]
        formal_notice_rows = [
            row for row in notice_rows
            if row.get("kind") in {"new", "formal", "revision"}
        ]
        occupied: set[int] = set()
        formal_occupied: set[int] = set()
        for row in notice_rows:
            start, end = row.get("interval_start"), row.get("interval_end")
            if (
                isinstance(start, int) and not isinstance(start, bool)
                and isinstance(end, int) and not isinstance(end, bool)
                and end >= start
            ):
                occupied.update(range(
                    max(start_session, 0, start),
                    min(range_end, len(book.sessions) - 1, end) + 1,
                ))
                if row.get("kind") in {"new", "formal", "revision"}:
                    formal_occupied.update(range(
                        max(start_session, 0, start),
                        min(range_end, len(book.sessions) - 1, end) + 1,
                    ))
        asset_years = _asset_years(book.sessions, start_session, range_end)
        metrics = {
            "E": E,
            "no_formal_alert_rate": no_alert / E if E else None,
            "first_window_coverage": covered / E if E else None,
            "resolved_claim_precision": (
                precision_hits / len(resolved_claims) if resolved_claims else None
            ),
            "resolved_claims_denominator": len(resolved_claims),
            "strict_success_count": precision_hits,
            "resolved_false_positive_count": len(resolved_claims) - precision_hits,
            "missed_event_count": E - strict,
            "duplicate_notices": duplicate_notices,
            "pending_claims": sum(
                row["target_status"] == "pending"
                and isinstance(row["action_session"], int)
                and start_session <= row["action_session"] <= range_end
                for row in claim_results
            ),
            "revisions": revisions,
            "formal_alerts": len(formal_notice_rows),
            "claim_notices": len(notice_rows),
            "observation_notices": sum(
                row.get("kind") == "observation" for row in notice_rows
            ),
            "alerts_per_asset_year": (
                len(notice_rows) / asset_years if asset_years else None
            ),
            "alarm_occupied_days": len(occupied),
            "formal_alarm_occupied_days": len(formal_occupied),
            "asset_years": asset_years,
            "data_evaluable_subset": _subset_metrics(
                event_results, data_evaluable_event_ids, claim_results, scope
            ),
        }
        recall_key = "QualifiedStageRecall5" if scope == "stage" else "QualifiedShortRecall5"
        strict_key = "StrictStageRecall5W10" if scope == "stage" else "StrictShortRecall5W10"
        miss_key = "strict_stage_miss_rate" if scope == "stage" else "strict_short_miss_rate"
        metrics[recall_key] = recall5 / E if E else None
        metrics[strict_key] = strict / E if E else None
        metrics[miss_key] = 1 - strict / E if E else None
        output["scopes"][scope] = {
            "metrics": metrics,
            "events": event_results,
            "claims": claim_results,
        }
    return output


def _asset_years(sessions: Sequence[str], start_session: int, end_session: int) -> float:
    if not sessions or end_session < start_session:
        return 0.0
    first, last = sessions[start_session], sessions[end_session]
    try:
        days = (datetime.fromisoformat(last) - datetime.fromisoformat(first)).days
    except ValueError:
        days = end_session - start_session
    return max(days / 365.2425, 1 / 252)


def _subset_metrics(
    events: Sequence[Mapping[str, Any]],
    evaluable_ids: set[str] | None,
    claims: Sequence[Mapping[str, Any]],
    scope: str,
) -> dict[str, Any]:
    strict_key = "StrictStageRecall5W10" if scope == "stage" else "StrictShortRecall5W10"
    if evaluable_ids is None:
        return {
            "status": "NOT_ESTABLISHED",
            "E": None,
            strict_key: None,
            "resolved_claim_precision": None,
        }
    subset = [event for event in events if event["event_id"] in evaluable_ids]
    denominator = len(subset)
    successes = sum(event["strict_success"] for event in subset)
    subset_claim_ids = {event["first_formal_claim_id"] for event in subset}
    resolved = [
        claim for claim in claims
        if claim["claim_id"] in subset_claim_ids
        and claim["formal"]
        and claim["target_status"] in {"event", "no_event"}
    ]
    hits = sum(claim["strict_success"] for claim in resolved)
    return {
        "status": "ESTABLISHED_FROM_EXPLICIT_EVENT_IDS",
        "E": denominator,
        strict_key: successes / denominator if denominator else None,
        "resolved_claim_precision": hits / len(resolved) if resolved else None,
        "resolved_claims_denominator": len(resolved),
    }


def unknown_label_rows(book: LabelBook) -> list[dict[str, Any]]:
    """List unresolved anchors without representing them as mature events."""
    rows = []
    for scale in SCOPES:
        for session, state in enumerate(book.states[scale]):
            state = state if isinstance(state, LabelState) else LabelState(state)
            if state in {LabelState.UNKNOWN, LabelState.PENDING}:
                rows.append({
                    "symbol": book.symbol,
                    "scope": scale,
                    "session": session,
                    "date": book.sessions[session],
                    "label_state": state.value,
                })
    return rows
