"""P1 adapters for end-of-day limit-pool context.

The source payloads used by :mod:`market_base` are deliberately kept separate
from this module.  This module only adds fields that can be supported by the
saved responses and requires two dated snapshots before it reports a
next-day progression rate.  It never turns a missing source field into a
zero, and it never uses ``market_latest.json`` as a historical substitute.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import UTC, date, datetime
from typing import Any

import requests

EVIDENCE = "descriptive"
POOL_KINDS = ("zt", "zb", "dt")
EM_YESTERDAY_POOL_URL = "https://push2ex.eastmoney.com/"
THS_LIMIT_UP_URL = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
EM_LIMIT_UT = "7eea3edcaed734bea9cbfc24409ed989"
THS_LIMIT_FIELDS = (
    "199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004"
)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"


def _json_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _source_meta(
    url: str,
    *,
    fetched_at: str,
    raw_sha256: str,
    source_id: str | None = None,
    status: str = "fresh",
    error: str | None = None,
) -> dict[str, Any]:
    host = url.split("/", 3)[2] if "://" in url else None
    return {
        "source_id": source_id or host or "unknown",
        "source_url": url,
        "url_host": host,
        "fetched_at": fetched_at,
        "status": status,
        "raw_sha256": raw_sha256,
        "license_tier": None,
        "stale_reason": error,
        "error": error,
    }


def _get_json(session: Any, url: str, params: Mapping[str, Any], *, headers: Mapping[str, str] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    response = session.get(url, params=dict(params), headers=dict(headers or {}), timeout=15, allow_redirects=True)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("source response is not a JSON object")
    fetched_at = datetime.now(UTC).isoformat()
    raw = getattr(response, "content", None)
    if not isinstance(raw, (bytes, bytearray)):
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return payload, {
        "url": getattr(response, "url", None) or url,
        "fetched_at": fetched_at,
        "raw_sha256": hashlib.sha256(bytes(raw)).hexdigest(),
    }


def fetch_yesterday_pool(asof: str, *, session: Any | None = None) -> dict[str, Any]:
    """Fetch the explicit T-1 limit-up result returned on *asof*.

    Eastmoney labels this endpoint ``getYesterdayZTPool``.  The response is
    archived as descriptive evidence; it is not used to fill a missing prior
    snapshot or to infer a historical rate from today's data.
    """

    asof = _iso(asof, "asof")
    session = session or requests.Session()
    url = f"{EM_YESTERDAY_POOL_URL.rstrip('/')}/getYesterdayZTPool"
    params = {
        "ut": EM_LIMIT_UT,
        "dpt": "wz.ztzt",
        "Pageindex": 0,
        "pagesize": 10000,
        "sort": "zs:desc",
        "date": asof.replace("-", ""),
    }
    payload, meta = _get_json(session, url, params, headers={"Referer": "https://quote.eastmoney.com/"})
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("pool"), list):
        raise RuntimeError(f"Eastmoney yesterday limit-pool response lacks data.pool for {asof}")
    rows = []
    for item in data["pool"]:
        if not isinstance(item, dict) or _text(item.get("c")) is None:
            raise RuntimeError("Eastmoney yesterday limit-pool row lacks code")
        zttj = item.get("zttj") if isinstance(item.get("zttj"), Mapping) else {}
        rows.append({
            "code": _text(item.get("c")),
            "name": _text(item.get("n")),
            "pct": item.get("zdp"),
            "turnover": item.get("hs"),
            "amplitude": item.get("zf"),
            "speed": item.get("zs"),
            "y_first_seal": item.get("yfbt"),
            "y_limit_days": item.get("ylbc"),
            "industry": _text(item.get("hybk")),
            "zt_stat": {"days": zttj.get("days"), "count": zttj.get("ct")},
        })
    return {
        "status": "fresh",
        "asof": asof,
        "window": "t-1_to_t",
        "rows": rows,
        "stale_reason": None,
        "evidence": EVIDENCE,
        "source": _source_meta(
            meta["url"],
            source_id="eastmoney_yesterday_zt_pool",
            fetched_at=meta["fetched_at"],
            raw_sha256=meta["raw_sha256"],
        ),
    }


def fetch_ths_reasons_topics(asof: str, *, session: Any | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Fetch Tonghuashun's dated reason/topic rows and provenance."""

    asof = _iso(asof, "asof")
    session = session or requests.Session()
    params = {
        "page": 1,
        "limit": 200,
        "field": THS_LIMIT_FIELDS,
        "filter": "HS,GEM2STAR",
        "order_field": "330324",
        "order_type": "0",
        "date": asof.replace("-", ""),
    }
    payload, meta = _get_json(session, THS_LIMIT_UP_URL, params, headers={"User-Agent": UA})
    data = payload.get("data")
    info = data.get("info") if isinstance(data, dict) else None
    if not isinstance(info, list):
        raise RuntimeError(f"Tonghuashun response lacks data.info for {asof}")
    reason_rows: list[dict[str, Any]] = []
    topic_rows: list[dict[str, Any]] = []
    for item in info:
        if not isinstance(item, dict):
            raise RuntimeError("Tonghuashun reason row is not an object")
        code = _text(item.get("code"))
        if code is None:
            raise RuntimeError("Tonghuashun reason row lacks code")
        name = _text(item.get("name"))
        reason = _text(item.get("reason_type")) or _text(item.get("reason"))
        if reason is None:
            continue
        field = "reason_type" if _text(item.get("reason_type")) is not None else "reason"
        reason_rows.append({"code": code, "name": name, "reason": reason, "source_field": field})
        topic_rows.append({"code": code, "name": name, "topic_label": reason, "source_field": field})
    source = _source_meta(
        meta["url"],
        source_id="ths_limit_up_pool",
        fetched_at=meta["fetched_at"],
        raw_sha256=meta["raw_sha256"],
    )
    status = "fresh" if reason_rows else "not_available"
    stale_reason = None if reason_rows else "source returned no reason rows"
    common = {"status": status, "asof": asof, "window": "eod", "stale_reason": stale_reason, "evidence": EVIDENCE}
    return {**common, "rows": reason_rows}, {**common, "rows": topic_rows}, source


def _iso(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    try:
        normalized = date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD") from exc
    if normalized != value:
        raise ValueError(f"{field} must be YYYY-MM-DD")
    return value


def unavailable(asof: str, reason: str, *, window: str | None = None) -> dict[str, Any]:
    """Return a stable missing-data value for a P1 section."""

    return {
        "status": "not_available",
        "asof": _iso(asof, "asof"),
        "window": window,
        "rows": [],
        "stale_reason": reason,
        "evidence": EVIDENCE,
    }


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None



def attach_source_adapters(
    payload: Mapping[str, Any],
    *,
    yesterday_pool: Mapping[str, Any] | None = None,
    ths_pool: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge source envelopes into a dated market payload.

    ``yesterday_pool`` is retained as a separate prior-day section.  The
    Tonghuashun ``reason_type`` field is copied to both ``reason`` and
    ``topic_label`` with its source field preserved; no topic taxonomy is
    inferred.  This function does not calculate a progression rate: that
    requires two complete dated ``pool_rows`` snapshots and an explicit
    trading calendar, handled by :func:`attach_snapshot_extensions`.
    """

    result = deepcopy(dict(payload))
    asof = _iso(result.get("asof"), "payload.asof")
    limit = result.get("limit_pools")
    if not isinstance(limit, dict):
        limit = {}
        result["limit_pools"] = limit
    sources = result.setdefault("sources", {})
    if not isinstance(sources, dict):
        sources = {}
        result["sources"] = sources

    if yesterday_pool is not None:
        prior_asof = yesterday_pool.get("asof")
        if isinstance(prior_asof, str) and yesterday_pool.get("status") == "fresh":
            limit["prior_day"] = {
                "status": "fresh",
                "asof": prior_asof,
                "window": "t-1",
                "rows": list(yesterday_pool.get("rows") or []),
                "stale_reason": None,
                "evidence": EVIDENCE,
                "source": yesterday_pool.get("source"),
            }
        else:
            limit["prior_day"] = unavailable(
                asof,
                str(yesterday_pool.get("stale_reason") or "previous-day source unavailable"),
                window="t-1",
            )
        source = yesterday_pool.get("source")
        if isinstance(source, Mapping) and source.get("source_id"):
            sources[str(source["source_id"])] = dict(source)

    if ths_pool is not None:
        reason_rows = []
        topic_rows = []
        for row in ths_pool.get("rows") or []:
            if not isinstance(row, Mapping):
                continue
            if row.get("reason") is not None:
                reason_rows.append(
                    {
                        "code": row.get("code"),
                        "name": row.get("name"),
                        "pool": "zt",
                        "reason": row.get("reason"),
                        "source_field": "reason_type",
                    }
                )
            if row.get("topic_label") is not None:
                topic_rows.append(
                    {
                        "code": row.get("code"),
                        "name": row.get("name"),
                        "pool": "zt",
                        "topic_label": row.get("topic_label"),
                        "source_field": "reason_type",
                    }
                )
        ths_asof = ths_pool.get("asof") if isinstance(ths_pool.get("asof"), str) else asof
        source_status = ths_pool.get("status")
        if source_status == "fresh":
            limit["reasons"] = {
                "status": "fresh",
                "asof": ths_asof,
                "window": "eod",
                "rows": reason_rows,
                "stale_reason": None,
                "evidence": EVIDENCE,
                "source": ths_pool.get("source"),
            }
            limit["topics"] = {
                "status": "fresh",
                "asof": ths_asof,
                "window": "eod",
                "rows": topic_rows,
                "stale_reason": None,
                "evidence": EVIDENCE,
                "source": ths_pool.get("source"),
            }
        else:
            reason = str(ths_pool.get("stale_reason") or "topic/reason source unavailable")
            limit["reasons"] = unavailable(asof, reason, window="eod")
            limit["topics"] = unavailable(asof, reason, window="eod")
        source = ths_pool.get("source")
        if isinstance(source, Mapping) and source.get("source_id"):
            sources[str(source["source_id"])] = dict(source)
    return result


def _first_text(row: Mapping[str, Any], keys: Iterable[str]) -> tuple[str | None, str | None]:
    for key in keys:
        value = _text(row.get(key))
        if value is not None:
            return value, key
    return None, None


def _streak(row: Mapping[str, Any], pool: str) -> int | None:
    if pool == "zt":
        value = row.get("lbc")
    elif pool == "dt":
        value = row.get("days")
    else:
        zttj = row.get("zttj")
        value = zttj.get("ct") if isinstance(zttj, Mapping) else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _time(row: Mapping[str, Any], pool: str) -> str | None:
    value = row.get("lbt" if pool == "dt" else "fbt")
    if value is None:
        return None
    digits = str(value).zfill(6)
    if len(digits) != 6 or not digits.isdigit():
        return None
    return f"{digits[:2]}:{digits[2:4]}:{digits[4:]}"


def _display_row(row: Mapping[str, Any], pool: str) -> dict[str, Any]:
    """Create a compact, source-labelled row for archival use."""

    result: dict[str, Any] = {
        "code": _text(row.get("c")),
        "name": _text(row.get("n")),
        "streak": _streak(row, pool),
        "limit_time": _time(row, pool),
    }
    industry, industry_field = _first_text(row, ("hybk", "industry", "industry_name"))
    if industry is not None:
        result["industry_label"] = industry
        result["industry_source_field"] = industry_field
    return result


def _topic_rows(raw_pools: Mapping[str, list[Mapping[str, Any]]], asof: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for pool in POOL_KINDS:
        for row in raw_pools.get(pool, []):
            topic, field = _first_text(
                row,
                ("gnbk", "topic", "topic_name", "zttype", "zttypename"),
            )
            if topic is None:
                continue
            rows.append(
                {
                    "code": _text(row.get("c")),
                    "name": _text(row.get("n")),
                    "pool": pool,
                    "topic_label": topic,
                    "source_field": field,
                }
            )
    if not rows:
        return unavailable(asof, "source response contained no topic label field")
    return {
        "status": "fresh",
        "asof": asof,
        "window": "eod",
        "rows": rows,
        "stale_reason": None,
        "evidence": EVIDENCE,
    }


def _reason_rows(raw_pools: Mapping[str, list[Mapping[str, Any]]], asof: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    # These names cover the variants used by public limit-pool endpoints.  A
    # field is accepted only when it is present in the raw response; zttj and
    # hybk are intentionally not treated as a reason.
    reason_keys = ("reason", "reason_text", "zt_reason", "ztReason", "ztyy", "zttj_text")
    for pool in POOL_KINDS:
        for row in raw_pools.get(pool, []):
            reason, field = _first_text(row, reason_keys)
            if reason is None:
                continue
            rows.append(
                {
                    "code": _text(row.get("c")),
                    "name": _text(row.get("n")),
                    "pool": pool,
                    "reason": reason,
                    "source_field": field,
                }
            )
    if not rows:
        return unavailable(asof, "source response contained no limit-up reason field")
    return {
        "status": "fresh",
        "asof": asof,
        "window": "eod",
        "rows": rows,
        "stale_reason": None,
        "evidence": EVIDENCE,
    }


def enrich_limit_pools(summary: Mapping[str, Any], raw_pools: Mapping[str, list[Mapping[str, Any]]], asof: str) -> dict[str, Any]:
    """Add archival rows, topic labels and reason status to a pool summary.

    ``summary`` retains all existing keys.  ``pool_rows`` is intentionally
    separate from ``top20`` so a later progression calculation does not treat
    the top-20 display slice as the complete eligible population.
    """

    asof = _iso(asof, "asof")
    result = dict(summary)
    result["pool_rows"] = {
        pool: [_display_row(row, pool) for row in raw_pools.get(pool, [])]
        for pool in POOL_KINDS
    }
    result["reasons"] = _reason_rows(raw_pools, asof)
    result["topics"] = _topic_rows(raw_pools, asof)
    result["prior_day"] = unavailable(asof, "previous trading-day limit-pool snapshot was not supplied", window="t-1")
    result["progression"] = unavailable(asof, "prior trading-day limit-pool pair is not available", window="t+1")
    return result


def _rows_from_limit(payload: Mapping[str, Any]) -> Mapping[str, list[Mapping[str, Any]]] | None:
    section = payload.get("limit_pools")
    if not isinstance(section, Mapping):
        return None
    rows = section.get("pool_rows")
    if not isinstance(rows, Mapping):
        return None
    if any(not isinstance(rows.get(pool), list) for pool in POOL_KINDS):
        return None
    return rows  # type: ignore[return-value]


def _adjacent(prior_asof: str, asof: str, trading_dates: Iterable[str] | None) -> bool | None:
    if trading_dates is None:
        return None
    dates = [_iso(value, "trading_dates entry") for value in trading_dates]
    if prior_asof not in dates or asof not in dates:
        return False
    return dates.index(asof) == dates.index(prior_asof) + 1


def progression_from_snapshots(
    current_payload: Mapping[str, Any],
    prior_payload: Mapping[str, Any] | None = None,
    *,
    trading_dates: Iterable[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return previous-day rows and next-day advancement metrics.

    A trading calendar is required.  Weekday arithmetic is insufficient for
    Chinese exchange holidays, so absent/ambiguous calendars remain explicitly
    unavailable.
    """

    asof = _iso(current_payload.get("asof"), "current_payload.asof")
    if prior_payload is None:
        missing = unavailable(asof, "prior trading-day snapshot was not supplied", window="t-1")
        return missing, unavailable(asof, "prior trading-day snapshot was not supplied", window="t+1")
    prior_asof = _iso(prior_payload.get("asof"), "prior_payload.asof")
    prior_rows = _rows_from_limit(prior_payload)
    current_rows = _rows_from_limit(current_payload)
    if prior_rows is None or current_rows is None:
        reason = "complete pool_rows are required in both dated snapshots"
        return unavailable(prior_asof, reason, window="t-1"), unavailable(asof, reason, window="t+1")

    previous = {
        "status": "fresh",
        "asof": prior_asof,
        "window": "t-1",
        "rows": {pool: deepcopy(list(prior_rows[pool])) for pool in POOL_KINDS},
        "stale_reason": None,
        "evidence": EVIDENCE,
    }
    adjacent = _adjacent(prior_asof, asof, trading_dates)
    if adjacent is None:
        return previous, unavailable(asof, "explicit trading calendar is required to establish t+1", window="t+1")
    if adjacent is False:
        return previous, unavailable(asof, f"snapshots {prior_asof} and {asof} are not adjacent trading days", window="t+1")

    current_by_code = {
        row.get("code"): row
        for row in current_rows["zt"]
        if row.get("code") is not None
    }
    eligible: dict[int, int] = {}
    advanced: dict[int, int] = {}
    for row in prior_rows["zt"]:
        code = row.get("code")
        from_streak = row.get("streak")
        if code is None or not isinstance(from_streak, int) or from_streak < 1:
            continue
        eligible[from_streak] = eligible.get(from_streak, 0) + 1
        next_row = current_by_code.get(code)
        if isinstance(next_row, Mapping) and isinstance(next_row.get("streak"), int) and next_row["streak"] >= from_streak + 1:
            advanced[from_streak] = advanced.get(from_streak, 0) + 1

    rows: list[dict[str, Any]] = []
    for from_streak in sorted(eligible):
        eligible_count = eligible[from_streak]
        advanced_count = advanced.get(from_streak, 0)
        rows.append(
            {
                "from_streak": from_streak,
                "to_streak": from_streak + 1,
                "eligible_count": eligible_count,
                "advanced_count": advanced_count,
                "rate": advanced_count / eligible_count if eligible_count else None,
                "asof": asof,
                "window": "t+1",
            }
        )
    progression = {
        "status": "fresh" if rows else "not_available",
        "asof": asof,
        "prior_asof": prior_asof,
        "window": "t+1",
        "rows": rows,
        "stale_reason": None if rows else "no valid zt rows with streak values in prior snapshot",
        "evidence": EVIDENCE,
    }
    return previous, progression


def attach_snapshot_extensions(
    payload: Mapping[str, Any],
    prior_payload: Mapping[str, Any] | None = None,
    *,
    trading_dates: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Attach P1 fields while preserving the original payload contract."""

    result = deepcopy(dict(payload))
    asof = _iso(result.get("asof"), "payload.asof")
    previous, progression = progression_from_snapshots(
        result, prior_payload, trading_dates=trading_dates
    )
    limit = result.get("limit_pools")
    if not isinstance(limit, dict):
        limit = {}
        result["limit_pools"] = limit
    limit.setdefault("reasons", unavailable(asof, "source did not provide limit-up reason rows"))
    limit.setdefault("topics", unavailable(asof, "source did not provide topic labels"))
    limit["prior_day"] = previous
    result["history"] = {"progression": progression}
    return result

