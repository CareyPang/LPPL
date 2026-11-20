"""Score immutable, scoped first claims against an already matured label ledger.

This module neither discovers peaks nor fits a model. Unknown anchors are not
negative labels, and a later claim never repairs the first claim for an event.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime
from statistics import median
from typing import Any

from .contracts import Evaluation, Forecast, LabelBook, Protocol, ScheduledRun, TopEvent

SCALES = ("stage", "short")
SCOPES = {"stage", "short", "both", "uncertain"}
DEFAULT_PROTOCOL = Protocol()


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _timestamp(value: Any) -> datetime:
    _text(value, "published_at")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("published_at must be an ISO timestamp") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("published_at must be timezone-aware")
    return stamp.astimezone(UTC)


def _distribution(values: Sequence[int]) -> dict[str, Any]:
    ordered = sorted(values)
    return {"n": len(ordered), "values": ordered,
            "min": ordered[0] if ordered else None,
            "median": median(ordered) if ordered else None,
            "max": ordered[-1] if ordered else None}


def _validate(book: LabelBook, forecasts: Sequence[Forecast], runs: Sequence[ScheduledRun],
              config: Protocol) -> tuple[dict[str, tuple[bool, ...]], dict[str, datetime]]:
    if not isinstance(book, LabelBook) or not isinstance(config, Protocol):
        raise ValueError("book/config must use the evaluator contracts")
    _text(book.symbol, "book.symbol")
    if not book.sessions or any(not isinstance(s, str) for s in book.sessions):
        raise ValueError("sessions must contain calendar labels")
    if len(set(book.sessions)) != len(book.sessions):
        raise ValueError("session labels must be unique")
    n = len(book.sessions)
    if _integer(book.asof_session, "asof_session") >= n:
        raise ValueError("asof_session is outside the calendar")
    if not isinstance(book.known, dict) or not isinstance(book.events, (list, tuple)):
        raise ValueError("invalid label ledger types")
    known = {}
    for scale in SCALES:
        values = book.known.get(scale, (False,) * n)
        if not isinstance(values, (list, tuple)) or len(values) != n:
            raise ValueError(f"known[{scale}] must match the calendar")
        if any(type(v) is not bool for v in values):
            raise ValueError("known entries must be booleans, not numeric proxies")
        if any(values[book.asof_session + 1:]):
            raise ValueError("known masks cannot resolve anchors after book asof")
        known[scale] = tuple(values)
    if not isinstance(book.pending, (list, tuple)) or any(not isinstance(p, dict) for p in book.pending):
        raise ValueError("pending must contain label-audit dictionaries")
    ids, anchors = set(), set()
    for event in book.events:
        if not isinstance(event, TopEvent) or event.symbol != book.symbol:
            raise ValueError("events must be TopEvent records for the book symbol")
        if event.scale not in SCALES:
            raise ValueError("invalid event scale")
        _text(event.event_id, "event_id")
        if event.event_id in ids:
            raise ValueError("duplicate event_id")
        ids.add(event.event_id)
        for name in ("peak_session", "end_session", "support_start", "support_end", "available_session"):
            _integer(getattr(event, name), name)
        if not (event.support_start <= event.peak_session <= event.end_session <= event.support_end
                <= event.available_session <= book.asof_session):
            raise ValueError("event must have complete causal support and be mature at book asof")
        if not known[event.scale][event.peak_session]:
            raise ValueError("a mature event anchor cannot be marked unknown")
        if (event.scale, event.peak_session) in anchors:
            raise ValueError("duplicate scale/anchor event")
        anchors.add((event.scale, event.peak_session))
        if not isinstance(event.family_id, str) or type(event.family_ambiguous) is not bool:
            raise ValueError("invalid event family fields")
    if isinstance(forecasts, (str, bytes)) or not isinstance(forecasts, Sequence):
        raise ValueError("forecasts must be a sequence of Forecast records")
    stamps, forecast_ids = {}, set()
    for f in forecasts:
        if not isinstance(f, Forecast) or f.symbol != book.symbol:
            raise ValueError("forecasts must be Forecast records for the book symbol")
        for name in ("prediction_id", "episode_id", "symbol"):
            _text(getattr(f, name), name)
        if f.prediction_id in forecast_ids:
            raise ValueError("duplicate prediction_id")
        forecast_ids.add(f.prediction_id)
        if f.scope not in SCOPES or f.actionability not in {"verified", "theoretical", "unknown"}:
            raise ValueError("invalid forecast scope/actionability")
        if type(f.on_time) is not bool:
            raise ValueError("on_time must be a boolean")
        # Invalid or past intervals are scored failures, not discarded inputs.
        for name in ("interval_start", "interval_end"):
            value = getattr(f, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        for name in ("data_cutoff_session", "published_session"):
            if _integer(getattr(f, name), name) >= n:
                raise ValueError(f"{name} is outside the calendar")
        if f.data_cutoff_session > f.published_session:
            raise ValueError("forecast data cutoff is after publication")
        if f.action_session is not None:
            _integer(f.action_session, "action_session")
            if f.action_session < f.published_session:
                raise ValueError("action_session cannot precede publication")
        for name in ("run_id", "parent_claim_id"):
            if getattr(f, name) is not None:
                _text(getattr(f, name), name)
        stamps[f.prediction_id] = _timestamp(f.published_at)
        try:
            session_date = date.fromisoformat(book.sessions[f.published_session])
        except ValueError:
            session_date = None  # Abstract T-session fixtures have no civil date.
        if session_date is not None and datetime.fromisoformat(f.published_at.replace("Z", "+00:00")).date() != session_date:
            raise ValueError("published_at local date does not match published_session")
    run_ids = set()
    for run in runs:
        if not isinstance(run, ScheduledRun) or run.symbol != book.symbol:
            raise ValueError("runs must be ScheduledRun records for the book symbol")
        _text(run.run_id, "run_id")
        _text(run.status, "run.status")
        if run.run_id in run_ids:
            raise ValueError("duplicate run_id")
        run_ids.add(run.run_id)
        if _integer(run.cutoff_session, "run.cutoff_session") >= n:
            raise ValueError("run cutoff is outside the calendar")
    runs_by_id = {r.run_id: r for r in runs}
    for f in forecasts:
        if f.run_id is not None and runs:
            if f.run_id not in runs_by_id:
                raise ValueError("forecast run_id is missing from the supplied schedule")
            if runs_by_id[f.run_id].cutoff_session != f.data_cutoff_session:
                raise ValueError("forecast cutoff differs from its scheduled run")
            status = runs_by_id[f.run_id].status.upper()
            if status not in {"INTERVAL", "ON_TIME_INTERVAL", "COMPLETED", "ON_TIME", "LATE", "LATE_RESULT"}:
                raise ValueError("a non-output or failed scheduled run cannot supply a forecast")
            if status in {"LATE", "LATE_RESULT"} and f.on_time:
                raise ValueError("late run status contradicts forecast.on_time")
            if status in {"ON_TIME", "ON_TIME_INTERVAL"} and not f.on_time:
                raise ValueError("on-time run status contradicts forecast.on_time")
    return known, stamps


def evaluate(book: LabelBook, forecasts: Sequence[Forecast], runs=(), *,
             config: Protocol = DEFAULT_PROTOCOL, mode: str = "strict", start_session: int = 0,
             end_session: int | None = None) -> Evaluation:
    """Evaluate one symbol; labels, calendar and actionability are supplied evidence.

    Event denominators use anchors in the inclusive evaluation range. A claim
    targeting such an event participates even if published before the range.
    Mature no-event claims participate when their action session is in range;
    their entire H must be known, including any required data outside the range.
    """
    if mode not in {"strict", "diagnostic"}:
        raise ValueError("mode must be strict or diagnostic")
    if not isinstance(runs, Sequence) or isinstance(runs, (str, bytes)):
        raise ValueError("runs must be a sequence")
    known, stamps = _validate(book, forecasts, runs, config)
    start = _integer(start_session, "start_session")
    end = book.asof_session if end_session is None else _integer(end_session, "end_session")
    if start > end or end > book.asof_session:
        raise ValueError("evaluation range must be inside book asof")
    events = {s: sorted((e for e in book.events if e.scale == s),
                       key=lambda e: (e.peak_session, e.event_id)) for s in SCALES}
    by_anchor = {s: {e.peak_session: e for e in events[s]} for s in SCALES}
    by_family = defaultdict(list)
    for event in book.events:
        if event.family_id:
            by_family[event.family_id].append(event)

    def resolve(scale: str, action: int | None) -> tuple[str, TopEvent | None, int | None]:
        if action is None:
            return "pending_action", None, None
        for i in range(action + 1, action + config.horizon + 1):
            if i >= len(book.sessions) or i > book.asof_session or not known[scale][i]:
                return "pending_labels", None, i
            if i in by_anchor[scale]:
                return "event", by_anchor[scale][i], None
        return "no_event", None, None

    def affiliated(stage_result):
        status, target, blocker = stage_result
        if status != "event":
            return status, None, blocker
        matches = [e for e in by_family.get(target.family_id, ()) if e.scale == "short"]
        if target.family_ambiguous or len(matches) != 1 or matches[0].family_ambiguous:
            return "pending_family_link", None, None
        return "event", matches[0], None

    def measure(f: Forecast, scale: str, resolution, kind: str) -> dict[str, Any]:
        status, target, blocker = resolution
        a = f.action_session
        width = f.interval_end - f.interval_start + 1
        lead = target.peak_session - a if target is not None and a is not None else None
        reference = a if a is not None else f.published_session
        in_scope = (start <= target.peak_session <= end if target is not None else
                    start <= reference <= end if status == "no_event" else
                    reference <= end and reference + config.horizon >= start)
        reasons = []
        if width < 1 or f.interval_start < 0:
            reasons.append("invalid_interval")
        if a is not None:
            if a <= f.data_cutoff_session:
                reasons.append("same_session_daily_data_action")
            if f.interval_start <= a or f.interval_start <= f.data_cutoff_session:
                reasons.append("not_future")
            if f.interval_end > a + config.horizon:
                reasons.append("beyond_horizon")
        evidence_failures = []
        if f.actionability != "verified":
            evidence_failures.append("actionability_not_verified")
        if not f.on_time:
            evidence_failures.append("late_publication")
        if mode == "strict":
            reasons.extend(evidence_failures)
        elif f.actionability == "unknown":
            reasons.append("actionability_unknown")
        if status.startswith("pending"):
            reasons.append(status)
        if status == "no_event":
            reasons.append("no_event_in_horizon")
        if target is not None and not (f.interval_start <= target.peak_session <= f.interval_end):
            reasons.append("wrong_interval")
        width_pass = 1 <= width <= config.maximum_width
        lead_pass = lead is not None and lead >= config.minimum_lead
        entire_pass = a is not None and f.interval_start - a >= config.minimum_lead
        if not width_pass:
            reasons.append("width_exceeded" if width > config.maximum_width else "invalid_width")
        if target is not None and not lead_pass:
            reasons.append("insufficient_event_lead")
        basic_hit = target is not None and not reasons and lead_pass
        strict_hit = basic_hit and (entire_pass or not config.require_entire_window_lead)
        if basic_hit and not entire_pass and config.require_entire_window_lead:
            reasons.append("insufficient_window_lead")
        return {"prediction_id": f.prediction_id, "episode_id": f.episode_id,
                "scope": scale, "kind": kind, "target_event_id": target.event_id if target else None,
                "target_family_id": target.family_id if target else None,
                "target_session": target.peak_session if target else None,
                "status": status if in_scope else "boundary_excluded", "pending": status.startswith("pending"),
                "unknown_blocker_session": blocker, "boundary_excluded": not in_scope,
                "failure_reasons": sorted(set(reasons)), "strict_evidence_failures": evidence_failures,
                "lead": lead, "width": width, "width_pass": width_pass,
                "event_lead_pass": lead_pass, "entire_window_lead_pass": entire_pass,
                "strict_hit": strict_hit and in_scope, "event_only_hit": basic_hit and in_scope,
                "raw_strict_hit": strict_hit and in_scope, "raw_event_only_hit": basic_hit and in_scope,
                "revision_hit": False, "is_first": False, "is_revision": False,
                "first_prediction_id": None, "first_alert_id": None, "duplicate_event": False,
                "overstatement": False, "action_session": a, "published_session": f.published_session}

    ordered = sorted(forecasts, key=lambda f: (stamps[f.prediction_id], f.prediction_id))
    rows, units, affiliates = [], [], []
    forecasts_by_id = {f.prediction_id: f for f in forecasts}
    for f in ordered:
        scope = "stage" if f.scope in {"stage", "both"} else f.scope
        if f.published_session > book.asof_session:
            rows.append({"prediction_id": f.prediction_id, "episode_id": f.episode_id, "scope": scope,
                         "status": "not_yet_published", "is_first": False, "is_revision": False,
                         "strict_hit": False, "event_only_hit": False, "revision_hit": False,
                         "pending": False, "boundary_excluded": True, "failure_reasons": ["not_yet_published"],
                         "short_affiliate": None})
            continue
        resolution = resolve(scope, f.action_session) if scope in SCALES else resolve("short", f.action_session)
        row = measure(f, scope, resolution, "explicit")
        row["original_scope"] = f.scope
        row["short_affiliate"] = None
        rows.append(row)
        if scope in SCALES:
            units.append(row)
        else:
            row["is_first"] = True
            row["strict_hit"] = row["event_only_hit"] = False
            row["failure_reasons"].append("scale_uncertain")
        if scope == "stage":
            affiliate = measure(f, "short", affiliated(resolution),
                                "explicit_both" if f.scope == "both" else "stage_affiliate")
            row["short_affiliate"] = affiliate
            affiliates.append(affiliate)
            if f.scope == "both":
                units.append(affiliate)
            # Overstatement is a separate, mature short-event diagnostic.
            short_status, short_event, _ = resolve("short", f.action_session)
            if short_status == "event" and short_event is not None:
                has_stage = any(e.scale == "stage" for e in by_family.get(short_event.family_id, ()))
                stage_status, stage_target, _ = resolution
                stage_time_matches = (stage_target is not None
                                      and f.interval_start <= stage_target.peak_session <= f.interval_end)
                row["overstatement"] = (stage_status in {"event", "no_event"} and not stage_time_matches
                                         and known["stage"][short_event.peak_session] and not has_stage
                                         and f.interval_start <= short_event.peak_session <= f.interval_end)

    # First claim is independent for each scope. both supplies a same-family
    # short subclaim, while a stage-only upgrade never adds a short denominator.
    groups = defaultdict(list)
    for unit in units:
        groups[(book.symbol, unit["episode_id"], unit["scope"])].append(unit)
    first_units = []
    for group in groups.values():
        group.sort(key=lambda u: (stamps[u["prediction_id"]], u["prediction_id"]))
        first = group[0]
        first["is_first"] = True
        first_units.append(first)
        for unit in group:
            unit["first_prediction_id"] = first["prediction_id"]
        for revision in group[1:]:
            revision["is_revision"] = True
            revision["revision_hit"] = bool(revision["raw_strict_hit"]
                                             and revision["target_event_id"] == first["target_event_id"])
            first["revision_hit"] |= revision["revision_hit"]
            revision["strict_hit"] = revision["event_only_hit"] = False

    targeted = defaultdict(list)
    for unit in first_units:
        if unit["target_event_id"] and not unit["pending"] and not unit["boundary_excluded"]:
            targeted[unit["target_event_id"]].append(unit)
    first_for_event = {}
    for event_id, group in targeted.items():
        group.sort(key=lambda u: (stamps[u["prediction_id"]], u["prediction_id"]))
        first_for_event[event_id] = group[0]
        for unit in group:
            unit["first_alert_id"] = group[0]["prediction_id"]
        for duplicate in group[1:]:
            duplicate["duplicate_event"] = True
            duplicate["strict_hit"] = duplicate["event_only_hit"] = False
            duplicate["failure_reasons"].append("duplicate_event_claim")

    event_rows = []
    for event in sorted(book.events, key=lambda e: (e.peak_session, e.scale, e.event_id)):
        if not start <= event.peak_session <= end:
            continue
        first = first_for_event.get(event.event_id)
        event_rows.append({"event_id": event.event_id, "scope": event.scale, "scale": event.scale,
                           "peak_session": event.peak_session, "family_id": event.family_id,
                           "first_prediction_id": first["prediction_id"] if first else None,
                           "strict_hit": bool(first and first["strict_hit"]),
                           "event_only_hit": bool(first and first["event_only_hit"]),
                           "failure_reasons": first["failure_reasons"][:] if first else ["no_claim"]})

    metrics: dict[str, Any] = {}
    for scale in SCALES:
        scoped = [u for u in first_units if u["scope"] == scale and not u["boundary_excluded"]]
        mature = [u for u in scoped if not u["pending"]]
        scoped_events = [e for e in event_rows if e["scale"] == scale]
        E, P = len(scoped_events), len(mature)
        TP = sum(bool(u["strict_hit"]) for u in mature)
        event_tp = sum(bool(u["event_only_hit"]) for u in mature)
        pending_events = sum(1 for e in book.pending if e.get("scale") == scale
                             and type(e.get("peak_session")) is int
                             and start <= e["peak_session"] <= end)
        pending_regions = sum(1 for e in book.pending if e.get("scale") == scale
                              and e.get("kind") == "unresolved_anchor_range"
                              and type(e.get("start_session")) is int
                              and type(e.get("end_session")) is int
                              and e["start_session"] <= end and e["end_session"] >= start)
        known_anchors = sum(known[scale][start:end + 1])
        unknown_anchors = end - start + 1 - known_anchors
        failures = Counter(reason for u in mature if not u["strict_hit"] for reason in u["failure_reasons"])
        missed_events = Counter(reason for e in scoped_events if not e["strict_hit"] for reason in e["failure_reasons"])
        metrics[scale] = {"E": E, "P": P, "TP": TP, "FP": P - TP, "FN": E - TP,
                          "recall": TP / E if E else None, "precision": TP / P if P else None,
                          "event_only": {"E": E, "P": P, "TP": event_tp, "FP": P-event_tp,
                                         "FN": E-event_tp, "recall": event_tp/E if E else None,
                                         "precision": event_tp/P if P else None},
                          "issued_claims": len(scoped), "pending_claims": sum(u["pending"] for u in scoped),
                          "pending_events": pending_events, "pending_label_regions": pending_regions,
                          "known_anchors": known_anchors, "unknown_anchors": unknown_anchors,
                          "known_anchor_fraction": known_anchors / (end-start+1),
                          "complete_recall_denominator_established": not (unknown_anchors or pending_events or pending_regions),
                          "failure_counts": dict(failures),
                          "missed_event_reasons": dict(missed_events),
                          "lead_distribution": _distribution([u["lead"] for u in scoped if u["lead"] is not None]),
                          "width_distribution": _distribution([u["width"] for u in scoped if u["width"] >= 1]),
                          "successful_lead_distribution": _distribution([u["lead"] for u in mature if u["strict_hit"]]),
                          "successful_width_distribution": _distribution([u["width"] for u in mature if u["strict_hit"]])}

    available_rows = [r for r in rows if r["status"] != "not_yet_published"]
    relevant_first = [u for u in first_units if not u["boundary_excluded"]]
    uncertain_groups = {(r["episode_id"], r["scope"]) for r in available_rows if r["scope"] == "uncertain"}
    metrics["diagnostics"] = {
        "pending_claims": sum(u["pending"] for u in relevant_first),
        "pending_action": sum(u["status"] == "pending_action" for u in relevant_first),
        "revision_hit_count": sum(bool(u["revision_hit"]) for u in relevant_first),
        "duplicate_claims": sum(bool(u["duplicate_event"]) for u in relevant_first),
        "uncertain_claims": len(uncertain_groups),
        "overstatement_count": sum(bool(u["overstatement"]) for u in relevant_first if u["scope"] == "stage"),
        "total_notifications": len(available_rows),
        "input_records": len(rows), "not_yet_published_records": len(rows)-len(available_rows),
        "boundary_excluded_claims": sum(u["boundary_excluded"] for u in first_units),
        "actionability_not_verified": sum(forecasts_by_id[u["prediction_id"]].actionability != "verified"
                                           for u in relevant_first),
    }
    in_range_runs = [r for r in runs if start <= r.cutoff_session <= end and r.status.upper() != "OUT_OF_SCOPE"]
    status_counts = Counter(r.status.upper() for r in in_range_runs)
    on_time = {"NO_SIGNAL", "ABSTAIN", "INTERVAL", "COMPLETED", "ON_TIME",
               "ON_TIME_INTERVAL", "ON_TIME_NO_SIGNAL", "ON_TIME_ABSTAIN"}
    completed = on_time | {"LATE", "LATE_RESULT"}
    failed = {"FAILED", "COMPUTE_FAILED", "MISSED_RUN", "TIMED_OUT", "DATA_INVALID", "DATA_LATE"}
    metrics["operational"] = {
        "scheduled_runs": len(in_range_runs),
        "on_time_runs": sum(status_counts[s] for s in on_time),
        "completed_runs": sum(status_counts[s] for s in completed),
        "missing_or_failed_runs": sum(status_counts[s] for s in failed),
        "status_counts": dict(status_counts),
        "on_time_fraction": sum(status_counts[s] for s in on_time)/len(in_range_runs) if in_range_runs else None,
        "total_notifications": len(available_rows),
        "notifications_published_in_range": sum(start <= r.get("published_session", -1) <= end for r in available_rows),
        "unrecognized_status_runs": sum(v for k, v in status_counts.items() if k not in completed | failed),
    }
    # Diagnostic affiliates do not secretly become explicit short claims.
    affiliate_first = [r["short_affiliate"] for r in available_rows
                       if r["scope"] == "stage" and r["is_first"] and r["short_affiliate"] is not None]
    affiliate_hits = {u["target_event_id"] for u in affiliate_first if u["raw_strict_hit"]}
    strict_families = {e["family_id"] or e["event_id"] for e in event_rows if e["strict_hit"]}
    event_only_families = {e["family_id"] or e["event_id"] for e in event_rows if e["event_only_hit"]}
    metrics["short_affiliate"] = {"diagnostic_records": len(affiliate_first),
                                  "strict_covered_events": len(affiliate_hits),
                                  "event_ids": sorted(affiliate_hits), "adds_to_short_P": False,
                                  "explicit_both_subclaims_are_in_short_metrics": True}
    metrics["family"] = {
        "event_families": len({e["family_id"] or e["event_id"] for e in event_rows}),
        "successful_families_strict": len(strict_families),
        "successful_families_event_only": len(event_only_families),
        "strict_family_ids": sorted(strict_families),
        "ambiguous_events": sum(e.family_ambiguous for e in book.events if start <= e.peak_session <= end),
    }
    claims_incomplete = bool(metrics["diagnostics"]["pending_claims"])
    recall_incomplete = any(not metrics[s]["complete_recall_denominator_established"] for s in SCALES)
    incomplete = claims_incomplete or recall_incomplete
    metadata = {
        "protocol": config.to_dict(), "mode": mode, "symbol": book.symbol,
        "start_session": start, "end_session": end, "asof_session": book.asof_session,
        "evidence_status": "CONDITIONAL_DIAGNOSTIC_NOT_PROSPECTIVE" if mode == "diagnostic" else
                           "SUPPLIED_LEDGER_STRICT_SCORE_NOT_PUBLICATION_AUTHENTICATION",
        "scored_claim_ledger_closed": not claims_incomplete,
        "precision_defined_by_scale": {s: metrics[s]["P"] > 0 for s in SCALES},
        "complete_recall_denominator_established": not recall_incomplete,
        "complete_strict_precision_established": mode == "strict" and not claims_incomplete
                                               and any(metrics[s]["P"] > 0 for s in SCALES),
        "incomplete_scoring": incomplete,
        "boundary_policy": "E: in-range event anchors; P: in-range targets regardless of publication boundary; "
                           "no-event P: action in range with all H known; unresolved overlapping horizons pending",
        "short_policy": "explicit short and explicit both same-family subclaims; same episode shares short first claim; "
                        "stage-only affiliates diagnostic, never added to short P",
        "first_policy": "UTC published_at then prediction_id; first per symbol/episode/scope; "
                        "first event alert across episodes cannot be repaired",
        "publication_calendar_policy": "for ISO-date sessions, published_at's declared local-offset date must "
                                       "equal the calendar date; callers must normalize timestamps to the "
                                       "calendar/venue timezone before evaluation; abstract T labels skip this check",
        "notification_policy": "each available supplied Forecast is one published notification; revisions count; "
                               "no inferred hidden deliveries",
        "unknown_policy": "never scan past an unknown anchor; action=None pending, not a no-event observation",
        "label_generation_performed": False,
    }
    # Raw flags are implementation detail; retain evaluated outcome diagnostics.
    for unit in units + affiliates:
        unit.pop("raw_strict_hit", None)
        unit.pop("raw_event_only_hit", None)
    return Evaluation(rows, event_rows, metrics, metadata)
