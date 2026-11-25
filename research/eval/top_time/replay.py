"""Historical saved-interval replay; never reconstruct original publication.

The builder receives dates and saved as-of aggregates, not future prices or
labels. All timestamps passed to Forecast are explicitly hypothetical adapters.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .contracts import Forecast, Protocol, ScheduledRun

REPLAY_VERSION = "top_time_saved_interval_replay_v1"
REPLAY_STATUS = "HYPOTHETICAL_REPLAY_CLAIM_NOT_ORIGINAL"
BASELINE = "calendar_fixed_10"
DEFAULT_PROTOCOL = Protocol()


@dataclass
class ReplayBundle:
    daily: list[dict[str, Any]]
    forecasts: list[Forecast]
    runs: list[ScheduledRun]
    forecast_audit: list[dict[str, Any]]


def outward_interval(position: int, low: float, high: float) -> tuple[int, int]:
    """Preserve the entire saved continuous interval, including invalid domains."""
    if not math.isfinite(low) or not math.isfinite(high) or low > high:
        raise ValueError("an alarm must contain a finite ordered saved interval")
    return position + math.floor(low), position + math.ceil(high)


def build_replay(
    symbol: str,
    sessions: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    *,
    scheduled_dates: set[str],
    fit_dates: set[str],
    arm: str,
    scope: str,
    source_id: str,
    protocol_hash: str,
    generated_at: str,
    start_session: int,
    end_session: int,
    config: Protocol = DEFAULT_PROTOCOL,
) -> ReplayBundle:
    """One row per observation day, independent first claims per arm/scope.

    Unscheduled days are not runs or signals. Scheduled unavailable inputs are
    explicit failed adapter runs, not assertions that an historical job failed.
    """
    if scope not in {"stage", "short"}:
        raise ValueError("replay scope must be an explicit stage or short probe")
    stamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("generated_at must be a timezone-aware actual replay time")
    if not 0 <= start_session <= end_session < len(sessions)-1:
        raise ValueError("replay requires an available next observation for each cutoff")
    if len(set(sessions)) != len(sessions) or list(sessions) != sorted(sessions):
        raise ValueError("calendar must be unique and sorted")
    by_date = {}
    for row in rows:
        if row["symbol"] != symbol or row["arm"] != arm:
            raise ValueError("mixed symbols or strategy rows")
        date = str(row["date"])[:10]
        if date in by_date:
            raise ValueError("duplicate asof rows")
        for flag in ("own_evaluable", "own_alarm"):
            if type(row[flag]) is not bool:
                raise ValueError(f"{flag} must be an explicit boolean, never a string or NaN")
        if row["own_alarm"] and not row["own_evaluable"]:
            raise ValueError("unavailable source cannot report an evaluable alarm")
        if row["own_alarm"] and date not in fit_dates:
            raise ValueError("saved alarm contradicts missing raw fit at its cutoff")
        position = int(row["position"])
        if sessions[position] != date:
            raise ValueError("saved position differs from the input price calendar")
        by_date[date] = row

    daily, forecasts, runs, audit = [], [], [], []
    episode, expiry, last_result = None, -1, None
    for i in range(start_session, end_session+1):
        date = sessions[i]
        if i > expiry:
            episode = None
        scheduled = date in scheduled_dates
        source = by_date.get(date)
        entry = {
            "record_id": f"{REPLAY_VERSION}:{symbol}:{arm}:{scope}:{date}",
            "symbol": symbol, "arm": arm, "scope_probe": scope,
            "date": date, "session": i, "source_id": source_id,
            "protocol_sha256": protocol_hash, "rule_version": REPLAY_VERSION,
            "replay_generated_at": generated_at, "evidence_status": REPLAY_STATUS,
            "input_cutoff": date, "scheduled": scheduled,
            "status": "NOT_SCHEDULED", "reason": "NO_CACHED_FIT_FOR_CUTOFF",
            "has_saved_fit": date in fit_dates, "new_forecast_id": "",
            "claim_change": "", "episode_id": episode or "",
            "episode_original_expiry_session": expiry if episode else "",
            "last_cached_result_id": last_result or "",
            "original_published_at": "", "hypothetical_published_at": "",
            "hypothetical_action_date": "", "hypothetical_action_session": "",
            "interval_lo_saved": "", "interval_hi_saved": "",
            "interval_start": "", "interval_end": "", "width_inclusive": "",
        }
        if not scheduled:
            daily.append(entry)
            continue
        run_id = f"run:{symbol}:{arm}:{scope}:{date}"
        is_baseline = arm == BASELINE
        evaluable = is_baseline or (source is not None and bool(source["own_evaluable"]))
        alarm = evaluable and (is_baseline or bool(source["own_alarm"]))
        if not evaluable:
            entry["status"] = "NO_CACHED_FIT" if date not in fit_dates else "INPUT_UNAVAILABLE"
            entry["reason"] = str(source["status"]) if source is not None else "missing_saved_asof"
            runs.append(ScheduledRun(run_id, symbol, i, "FAILED"))
        elif not alarm:
            entry.update(status="NO_SIGNAL", reason="saved_rule_no_alarm")
            runs.append(ScheduledRun(run_id, symbol, i, "NO_SIGNAL"))
        else:
            action = i+1
            if is_baseline:
                lo, hi = config.minimum_lead+1, config.minimum_lead+config.maximum_width
            else:
                lo, hi = float(source["interval_lo"]), float(source["interval_hi"])
            left, right = outward_interval(i, lo, hi)
            change = "REVISION"
            if episode is None:
                episode = f"episode:{symbol}:{arm}:{scope}:{date}"
                expiry = max(i, min(right, i+config.horizon))
                change = "FIRST_CLAIM"
            prediction_id = f"prediction:{symbol}:{arm}:{scope}:{date}"
            published = f"{date}T17:00:00+08:00"
            forecast = Forecast(prediction_id, episode, symbol, scope, left, right, i, i,
                                published, action, "theoretical", True, run_id)
            forecasts.append(forecast)
            runs.append(ScheduledRun(run_id, symbol, i, "INTERVAL"))
            last_result = prediction_id
            entry.update(status="HYPOTHETICAL_INTERVAL", reason="fixed_calendar_baseline" if is_baseline else "saved_rule_alarm",
                         new_forecast_id=prediction_id, claim_change=change, episode_id=episode,
                         episode_original_expiry_session=expiry, last_cached_result_id=last_result,
                         hypothetical_published_at=published, hypothetical_action_date=sessions[action],
                         hypothetical_action_session=action, interval_lo_saved=lo, interval_hi_saved=hi,
                         interval_start=left, interval_end=right, width_inclusive=right-left+1)
            audit.append({**entry, "interval_start_date": sessions[left] if 0 <= left < len(sessions) else "OUTSIDE_CALENDAR",
                          "interval_end_date": sessions[right] if 0 <= right < len(sessions) else "OUTSIDE_CALENDAR",
                          "actionability": "theoretical", "original_scope": "NOT_ESTABLISHED",
                          "scope_basis": "UNIFORM_TARGET_PROBE_NOT_MODEL_SCALE_CLASSIFICATION"})
        daily.append(entry)
    return ReplayBundle(daily, forecasts, runs, audit)


def common_event_opportunity(
    peak_session: int,
    sessions: Sequence[str],
    *,
    scheduled_dates: set[str],
    common_evaluable_dates: set[str],
    first_schedule_session: int,
    horizon: int,
) -> tuple[bool, str, int]:
    """Fixed pre-peak H-day availability diagnostic, selected after scoring.

    This frozen lookback is not the exact action-adjusted set of all possible
    claims: next-session action shifts that range by one session. It must not
    be described as exhaustive actionable-opportunity coverage.
    """
    if peak_session-horizon < first_schedule_session:
        return False, "incomplete_history_of_scheduled_opportunities", 0
    opportunities = [d for d in sessions[peak_session-horizon:peak_session] if d in scheduled_dates]
    if not opportunities:
        return False, "no_scheduled_opportunities", 0
    missing = [d for d in opportunities if d not in common_evaluable_dates]
    return not missing, "ok" if not missing else "some_arm_input_unavailable", len(opportunities)
