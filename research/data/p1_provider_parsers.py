"""Pure, original parsers for three descriptive P1 provider responses.

No fetch, storage, LLM, forecast, or availability-time claims occur here. ``asof``
is the requested observation date, not the date a response became knowable.
The archive must separately bind raw bytes, retrieval and first-available times.
An accepted historical row is never evidence of a point-in-time prediction.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

SOURCE_IDS = frozenset({
    "eastmoney_fund_flow_history", "eastmoney_dragon_tiger", "eastmoney_lockup_expiry",
})
_NUMERIC = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
_MISSING = (None, "", "-", "--")
_FUND_FIELDS = (
    "main_net", "small_net", "medium_net", "large_net", "super_net",
    "main_pct", "small_pct", "medium_pct", "large_pct", "super_pct", "close", "pct_chg",
)
_DRAGON_FIELDS = {
    "BILLBOARD_NET_AMT": "net_buy", "BILLBOARD_BUY_AMT": "buy_amount",
    "BILLBOARD_SELL_AMT": "sell_amount", "TURNOVERRATE": "turnover_pct",
}


def _day(value: Any, *, provider: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("date must be an ISO date string")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value).isoformat()
    if provider and re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]00:00:00", value):
        return datetime.fromisoformat(value).date().isoformat()
    raise ValueError("date must be YYYY-MM-DD (provider midnight allowed)")


def _symbol(code: Any) -> str:
    """Map a six-digit A-share code without discarding its exchange."""
    if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
        raise ValueError("provider SECURITY_CODE must be a six-digit string")
    if code.startswith("6"):
        return "sh" + code
    if code.startswith(("0", "3")):
        return "sz" + code
    if code.startswith(("4", "8", "92")):
        return "bj" + code
    raise ValueError("unsupported A-share security code")


def _subject(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"(?:sh|sz|bj)\d{6}", value):
        raise ValueError("subject must be canonical, e.g. sh600519")
    if _symbol(value[2:]) != value:
        raise ValueError("subject exchange and A-share code disagree")
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        raise ValueError("boolean is not a financial number")
    if value in _MISSING:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value in _MISSING:
            return None
        if not _NUMERIC.fullmatch(value):
            raise ValueError("invalid financial number")
    elif not isinstance(value, (int, float)):
        raise ValueError("financial number has invalid type")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("financial number overflow") from exc
    if not math.isfinite(result):
        raise ValueError("non-finite financial number")
    return result


def _text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("text field has invalid type")
    return value


def _section(source_id: str, asof: str, subject: str | None) -> dict[str, Any]:
    windows = {
        "eastmoney_fund_flow_history": "up_to_asof",
        "eastmoney_dragon_tiger": "asof",
        "eastmoney_lockup_expiry": "asof_to_plus_90_calendar_days",
    }
    return {
        "status": "fresh", "valid": True, "asof": asof,
        "window": windows[source_id], "rows": [], "stale_reason": None,
        "evidence": "descriptive", "source_id": source_id,
        "metadata": {
            "subject": subject, "pit_status": "NOT_ESTABLISHED",
            "historical_replay_eligible": False, "source_reported_asof": None,
            "asof_semantics": "requested_observation_date_not_availability_time",
            "fresh_semantics": "accepted_payload_not_verified_currentness",
            "coverage_status": "NOT_ESTABLISHED", "is_complete": False,
            "input_rows": 0, "rejected_rows": 0, "filtered_rows": 0,
            "row_errors": [], "empty_response": False, "units": {},
        },
    }


def _fail(section: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    section.update(status=status, valid=False, stale_reason=reason)
    return section


def _partial(section: dict[str, Any], reason: str) -> None:
    section["status"] = "partial"
    reasons = (section["stale_reason"] or "").split("; ")
    if reason not in reasons:
        section["stale_reason"] = "; ".join([r for r in reasons if r] + [reason])


def _provider_error(payload: Mapping[str, Any]) -> str | None:
    for key in ("rc", "code"):
        if key in payload:
            value = payload[key]
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                return "malformed_provider_status"
            if value not in (0, "0"):
                return "provider_reported_error"
    if "success" in payload:
        if not isinstance(payload["success"], bool):
            return "malformed_provider_status"
        if payload["success"] is False:
            return "provider_reported_error"
    return None


def _pagination(section: dict[str, Any], result: Mapping[str, Any], count: int) -> None:
    meta = section["metadata"]
    meta["pagination"] = {k: result.get(k) for k in ("pages", "count")}
    for key in ("pageNumber", "pageSize"):
        if key in result:
            meta["pagination"][key] = result[key]
            if type(result[key]) is not int or result[key] < 1:
                _fail(section, "schema_changed", "malformed_pagination")
                return
    pages, total = result.get("pages"), result.get("count")
    for value in (pages, total):
        if value is not None and (type(value) is not int or value < 0):
            _fail(section, "schema_changed", "malformed_pagination")
            return
    if pages is None or total is None:
        _partial(section, "pagination_metadata_missing")
    elif total < count or (pages == 0 and total != 0) or (pages > 1 and total == 0):
        _fail(section, "schema_changed", "inconsistent_pagination")
    elif pages > 1 or total > count:
        _partial(section, "pagination_incomplete")
    else:
        meta["is_complete"] = True


def _fund_rows(section: dict[str, Any], data: Mapping[str, Any], subject: str) -> None:
    meta, asof = section["metadata"], section["asof"]
    meta["date_capability"] = "rolling_source_history_filtered_at_asof"
    meta["units"] = {
        **{k: "CNY" for k in _FUND_FIELDS[:5]},
        **{k: "percent" for k in _FUND_FIELDS[5:10]},
        "close": "CNY_per_share", "pct_chg": "percent",
    }
    meta["percent_convention"] = "1.0 means 1 percent; not a 0-to-1 fraction"
    if "code" in data and data["code"] != subject[2:]:
        _fail(section, "schema_changed", "payload_subject_mismatch")
        return
    if "code" not in data:
        _partial(section, "payload_subject_not_confirmed")
    if "klines" not in data:
        _fail(section, "schema_changed", "klines_missing")
        return
    raw = data["klines"]
    if raw is None:
        _fail(section, "not_available", "klines_null")
        return
    if not isinstance(raw, list):
        _fail(section, "schema_changed", "klines_not_array")
        return
    meta.update(input_rows=len(raw), empty_response=not raw)
    seen: set[str] = set()
    for index, item in enumerate(raw):
        try:
            if not isinstance(item, str):
                raise ValueError("kline_not_csv_string")
            cells = item.split(",")
            # The accepted layouts are f51..f57, f51..f63 and f51..f65.
            # f64/f65 are retained as opaque fields, never interpreted.
            if len(cells) not in (7, 13, 15):
                raise ValueError("unsupported_kline_column_count")
            row_date = _day(cells[0])
            values = {key: _number(cells[i + 1]) if i + 1 < min(len(cells), 13) else None
                      for i, key in enumerate(_FUND_FIELDS)}
            if row_date > asof:
                meta["filtered_rows"] += 1
                continue
            if row_date in seen:
                raise ValueError("duplicate_fund_date")
            seen.add(row_date)
            row = {"date": row_date, "symbol": subject, **values}
            if len(cells) == 15:
                row["uninterpreted_provider_fields"] = {"f64": cells[13], "f65": cells[14]}
            section["rows"].append(row)
            if values["main_net"] is None:
                _partial(section, "main_net_missing")
        except ValueError as exc:
            meta["rejected_rows"] += 1
            meta["row_errors"].append({"index": index, "reason": str(exc)})
    section["rows"].sort(key=lambda row: row["date"])
    meta["is_complete"] = meta["rejected_rows"] == 0
    meta["coverage_status"] = "returned_rolling_window_only"
    if section["rows"]:
        meta["observed_start"] = section["rows"][0]["date"]
        meta["observed_end"] = section["rows"][-1]["date"]
        if meta["observed_end"] < asof:
            _partial(section, "last_observation_before_asof_calendar_unverified")
    elif raw and not meta["rejected_rows"]:
        _fail(section, "not_available", "no_rows_on_or_before_asof")


def _table_rows(section: dict[str, Any], result: Mapping[str, Any], subject: str | None) -> None:
    if "data" not in result:
        _fail(section, "schema_changed", "result_data_missing")
        return
    raw = result["data"]
    if raw is None:
        _fail(section, "not_available", "result_data_null")
        return
    if not isinstance(raw, list):
        _fail(section, "schema_changed", "result_data_not_array")
        return
    meta, asof = section["metadata"], section["asof"]
    meta.update(input_rows=len(raw), empty_response=not raw)
    _pagination(section, result, len(raw))
    if not section["valid"]:
        return
    lockup = section["source_id"] == "eastmoney_lockup_expiry"
    end = (date.fromisoformat(asof) + timedelta(days=90)).isoformat() if lockup else asof
    meta["date_capability"] = "current_schedule_future_events" if lockup else "historical_event_date"
    meta["event_date_is_knowledge_date"] = False
    meta["units"] = ({"provider_reported_fields": "unverified_preserve_raw"} if lockup else {
        "net_buy": "CNY", "buy_amount": "CNY", "sell_amount": "CNY",
        "turnover_pct": "percent",
    })
    if lockup:
        meta["future_event_horizon_end"] = end
        meta["historical_snapshot_requires_archive_gate"] = True
    for index, item in enumerate(raw):
        try:
            if not isinstance(item, Mapping):
                raise ValueError("row_not_object")
            event_date = _day(item.get("FREE_DATE" if lockup else "TRADE_DATE"), provider=True)
            symbol = _symbol(item.get("SECURITY_CODE"))
            name = _text(item.get("SECURITY_NAME_ABBR"))
            if subject is not None and symbol != subject:
                meta["filtered_rows"] += 1
                continue
            if (lockup and not asof <= event_date <= end) or (not lockup and event_date != asof):
                meta["filtered_rows"] += 1
                continue
            row = {"event_date": event_date, "date": event_date, "symbol": symbol, "name": name}
            if lockup:
                row["snapshot_asof"] = asof
                row["type"] = _text(item.get("FREE_SHARES_TYPE")) or _text(item.get("LIMITED_STOCK_TYPE"))
                # Upstream readers disagree on quantity/ratio fields and units.
                # Preserve source strings; never guess conversions or denominators.
                row["provider_reported_fields"] = {
                    key: item.get(key) for key in (
                        "FREE_SHARES_NUM", "FREE_SHARES", "ABLE_FREE_SHARES", "FREE_RATIO", "CURRENT_FREE_SHARES",
                        "TOTAL_RATIO", "FREE_MARKET_CAP",
                    )
                }
                for value in row["provider_reported_fields"].values():
                    if isinstance(value, bool) or not isinstance(value, (str, int, float, type(None))):
                        raise ValueError("invalid_lockup_raw_field_type")
                    if isinstance(value, (int, float)):
                        _number(value)
                    if isinstance(value, str) and value.strip().lower() in ("nan", "inf", "infinity", "-inf", "+inf"):
                        raise ValueError("non_finite_lockup_raw_field")
                    if isinstance(value, str) and _NUMERIC.fullmatch(value.strip()):
                        _number(value)
                if all(value in _MISSING for value in row["provider_reported_fields"].values()):
                    _partial(section, "lockup_metrics_missing")
            else:
                row["reason"] = _text(item.get("EXPLANATION"))
                row.update({target: _number(item.get(source)) for source, target in _DRAGON_FIELDS.items()})
                if row["net_buy"] is None:
                    _partial(section, "net_buy_missing")
                if row["reason"] is None:
                    _partial(section, "listing_reason_missing")
            section["rows"].append(row)
        except ValueError as exc:
            meta["rejected_rows"] += 1
            meta["row_errors"].append({"index": index, "reason": str(exc)})
    section["rows"].sort(key=lambda row: (row["event_date"], row["symbol"]))


def parse_provider_payload(
    source_id: str, payload: Any, *, asof: str, subject: str | None = None,
) -> dict[str, Any]:
    """Parse an already obtained JSON object without trusting its freshness.

    Invalid caller arguments raise ValueError; provider failures are returned as
    non-fresh sections. ``valid`` means a usable schema, not complete coverage.
    A page with ``pages > 1`` remains partial even when supplied rows look valid.
    Histories retrieved now must pass the separate archive availability gate.
    """
    if not isinstance(source_id, str) or source_id not in SOURCE_IDS:
        raise ValueError("unsupported P1 source_id")
    asof, subject = _day(asof), _subject(subject)
    if source_id == "eastmoney_lockup_expiry" and date.fromisoformat(asof) > date.max - timedelta(days=90):
        raise ValueError("asof leaves insufficient date range for 90-day horizon")
    if source_id == "eastmoney_fund_flow_history" and subject is None:
        raise ValueError("fund-flow history requires a canonical subject")
    section = _section(source_id, asof, subject)
    if not isinstance(payload, Mapping):
        return _fail(section, "schema_changed", "payload_not_object")
    failure = _provider_error(payload)
    if failure:
        status = "schema_changed" if failure.startswith("malformed") else "error"
        return _fail(section, status, failure)
    key = "data" if source_id == "eastmoney_fund_flow_history" else "result"
    if key not in payload:
        return _fail(section, "schema_changed", f"{key}_missing")
    container = payload[key]
    if container is None:
        return _fail(section, "not_available", f"{key}_null")
    if not isinstance(container, Mapping):
        return _fail(section, "schema_changed", f"{key}_not_object")
    if source_id == "eastmoney_fund_flow_history":
        assert subject is not None
        _fund_rows(section, container, subject)
    else:
        _table_rows(section, container, subject)
    if section["metadata"]["rejected_rows"]:
        section["metadata"]["is_complete"] = False
        if section["rows"]:
            _partial(section, "malformed_rows_rejected")
        else:
            _fail(section, "schema_changed", "all_target_rows_malformed")
    return section
