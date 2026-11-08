"""Deterministic P1 market-context summaries.

These helpers only summarize fields that are already present in dated source
snapshots.  They never infer a topic, fill a missing rate with zero, or turn a
descriptive count into a trading signal.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import date
from typing import Any

EVIDENCE = "descriptive"
BOARD_KINDS = ("industry", "concept", "region")
DISCLOSURE_KINDS = ("announcements", "research", "f10", "shareholders", "unlock")


def _asof(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("asof must be YYYY-MM-DD")
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("asof must be YYYY-MM-DD")
    return value


def unavailable(asof: str, reason: str, *, window: str | None = None) -> dict[str, Any]:
    return {
        "status": "not_available",
        "asof": _asof(asof),
        "window": window,
        "rows": [],
        "stale_reason": reason,
        "evidence": EVIDENCE,
    }


def board_heatmaps(board_flow: Mapping[str, Any] | None, asof: str) -> dict[str, Any]:
    """Return source-labelled heatmap rows for all three board classes."""

    asof = _asof(asof)
    board_flow = board_flow if isinstance(board_flow, Mapping) else {}
    provider = board_flow.get("provider") if isinstance(board_flow.get("provider"), Mapping) else {}
    result: dict[str, Any] = {}
    for kind in BOARD_KINDS:
        rows = board_flow.get(kind)
        if not isinstance(rows, list) or not rows:
            result[kind] = unavailable(asof, f"{kind} board source returned no dated rows", window="eod")
            continue
        clean = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            name = row.get("name")
            if name is None:
                continue
            item = {"name": str(name), "code": row.get("code")}
            for field in ("pct_chg", "main_net", "main_pct", "pct_5d", "main_net_5d", "pct_10d", "main_net_10d"):
                if field in row and row[field] is not None:
                    item[field] = row[field]
            clean.append(item)
        if not clean:
            result[kind] = unavailable(asof, f"{kind} board rows lack displayable names", window="eod")
            continue
        result[kind] = {
            "status": "fresh",
            "asof": asof,
            "window": "eod",
            "provider": provider.get(kind),
            "rows": clean,
            "stale_reason": None,
            "evidence": EVIDENCE,
        }
    return result


def topic_heat(limit_pools: Mapping[str, Any] | None, asof: str) -> dict[str, Any]:
    """Count only explicit topic labels from a dated limit-pool snapshot."""

    asof = _asof(asof)
    limit_pools = limit_pools if isinstance(limit_pools, Mapping) else {}
    section = limit_pools.get("topics")
    rows = section.get("rows") if isinstance(section, Mapping) else None
    if not isinstance(rows, list) or not rows:
        return unavailable(asof, "dated topic labels are unavailable", window="eod")
    counts = Counter(str(row["topic_label"]).strip() for row in rows if isinstance(row, Mapping) and row.get("topic_label"))
    if not counts:
        return unavailable(asof, "topic rows contain no non-empty labels", window="eod")
    return {
        "status": "fresh" if section.get("status") == "fresh" else "partial",
        "asof": asof,
        "window": "eod",
        "rows": [{"topic_label": key, "count": value} for key, value in counts.most_common()],
        "stale_reason": section.get("stale_reason"),
        "evidence": EVIDENCE,
    }


def limit_pool_stats(limit_pools: Mapping[str, Any] | None, asof: str) -> dict[str, Any]:
    """Expose dated counts and a broken-board ratio when both counts exist."""

    asof = _asof(asof)
    limit_pools = limit_pools if isinstance(limit_pools, Mapping) else {}
    values = {name: limit_pools.get(name) for name in ("zt", "zb", "dt")}
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values.values()):
        return unavailable(asof, "limit-up/broken/down counts are incomplete", window="eod")
    zt, zb, dt = (float(values[name]) for name in ("zt", "zb", "dt"))
    denominator = zt + zb
    return {
        "status": "fresh",
        "asof": asof,
        "window": "eod",
        "rows": [{"zt": values["zt"], "zb": values["zb"], "dt": values["dt"], "broken_rate": zb / denominator if denominator else None}],
        "stale_reason": None,
        "evidence": EVIDENCE,
    }


def funding_percentile(history: list[Mapping[str, Any]] | None, *, asof: str, value_key: str = "main_net", lookback: int = 60, min_rows: int = 20) -> dict[str, Any]:
    """Compute an empirical percentile only from dated history at or before asof."""

    asof = _asof(asof)
    rows = []
    for row in history or []:
        if not isinstance(row, Mapping) or not isinstance(row.get("date"), str):
            continue
        try:
            row_date = _asof(row["date"])
        except (TypeError, ValueError):
            continue
        value = row.get(value_key)
        if row_date <= asof and isinstance(value, (int, float)) and not isinstance(value, bool):
            rows.append((row_date, float(value)))
    rows = sorted({row_date: value for row_date, value in rows}.items())[-lookback:]
    if len(rows) < min_rows:
        return unavailable(asof, f"funding history has {len(rows)} rows; {min_rows} required", window=f"{lookback}d")
    latest_date, latest = rows[-1]
    values = [value for _, value in rows]
    percentile = sum(value <= latest for value in values) / len(values)
    return {
        "status": "fresh",
        "asof": asof,
        "window": f"{lookback}d",
        "rows": [{"date": latest_date, "value": latest, "percentile": percentile, "sample_size": len(values), "value_key": value_key}],
        "stale_reason": None,
        "evidence": EVIDENCE,
    }


def disclosure_sections(asof: str, sections: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Normalize announcement/F10/shareholder placeholders without backfilling."""

    asof = _asof(asof)
    supplied = sections if isinstance(sections, Mapping) else {}
    result = {}
    for kind in DISCLOSURE_KINDS:
        value = supplied.get(kind)
        if isinstance(value, Mapping) and value.get("status") in {"fresh", "partial", "stale", "not_available"}:
            result[kind] = dict(value)
        else:
            result[kind] = unavailable(asof, f"{kind} source adapter is not connected", window="eod")
    return result


def attach_p1_extensions(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Attach P1 descriptive modules while preserving the original payload."""

    result = dict(payload)
    asof = _asof(result.get("asof"))
    result["p1"] = {
        "heatmaps": board_heatmaps(result.get("board_flow"), asof),
        "topic_heat": topic_heat(result.get("limit_pools"), asof),
        "limit_pool_stats": limit_pool_stats(result.get("limit_pools"), asof),
        "funding_percentiles": funding_percentile(result.get("funding_history"), asof=asof),
        "disclosures": disclosure_sections(asof, result.get("disclosures")),
        "evidence": EVIDENCE,
        "notes": ["P1 modules are descriptive and never enter LPPLS."],
    }
    return result
