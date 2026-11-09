#!/usr/bin/env python3
"""Fetch and seal one descriptive A-share EOD market-context snapshot.

The command is intentionally artifact-first.  It never updates LPPLS inputs,
the Pages bundle, or a production Worker.  A prior snapshot is used only when
the caller supplies that dated file; current data cannot be substituted for a
missing historical day.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from research.data.market_base import fetch_market, write_snapshot
from research.data.market_calendar import load_calendar, resolve_sessions
from research.data.market_context import build_snapshot
from research.data.market_p1 import (
    EM_YESTERDAY_POOL_URL,
    THS_LIMIT_UP_URL,
    attach_snapshot_extensions,
    attach_source_adapters,
    fetch_ths_reasons_topics,
    fetch_yesterday_pool,
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _read_calendar(path: Path | None) -> list[str] | None:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    dates = value.get("dates") if isinstance(value, dict) else value
    if not isinstance(dates, list) or any(not isinstance(item, str) for item in dates):
        raise ValueError("trading calendar must be a JSON list or {\"dates\": [...]}")
    return dates


def _prior_path(out: Path, prior_asof: str | None) -> Path | None:
    if not prior_asof:
        return None
    path = out / f"market_{prior_asof}.json"
    return path if path.exists() else None


def _manifest_entry(context: dict[str, Any], *, run_mode: str) -> dict[str, Any]:
    source_hashes = sorted(
        str(meta["raw_sha256"])
        for meta in (context.get("sources") or {}).values()
        if isinstance(meta, dict) and meta.get("raw_sha256")
    )
    return {
        "asof": context.get("asof"),
        "generated_at": context.get("generated_at"),
        "fetched_at": context.get("source", {}).get("fetched_at"),
        "status": context.get("status"),
        "run_mode": run_mode,
        "source_hashes": source_hashes,
        "snapshot_sha256": context.get("snapshot_sha256"),
        "evidence": context.get("evidence"),
    }


def _rehash(context: dict[str, Any]) -> None:
    context.pop("snapshot_sha256", None)
    raw = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    context["snapshot_sha256"] = hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _assert_dated_payload_immutable(path: Path, payload: dict[str, Any]) -> None:
    if not path.exists():
        return
    existing = _load_json(path)
    if _canonical(existing) != _canonical(payload):
        raise ValueError(f"dated market payload is immutable: {path.name}")


def _assert_dated_context_immutable(path: Path, text: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") != text:
        raise ValueError(f"dated market context is immutable: {path.name}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    calendar = load_calendar(getattr(args, "trading_calendar", None))
    sessions = resolve_sessions(
        asof=args.asof,
        prior_asof=args.prior_asof,
        calendar=calendar,
        today=getattr(args, "today", None),
    )
    asof = sessions["asof"]
    base_snapshot = getattr(args, "base_snapshot", None)
    payload = _load_json(Path(base_snapshot)) if base_snapshot else fetch_market(asof)
    asof = payload.get("asof", asof)

    # These sources are independent of the existing market_latest contract.
    # A failure remains explicit and cannot be converted to an empty success.
    try:
        reasons, topics, ths_source = fetch_ths_reasons_topics(asof)
        topic_by_code = {row.get("code"): row for row in topics.get("rows", [])}
        ths_rows = [
            {
                "code": row.get("code"),
                "name": row.get("name"),
                "reason": row.get("reason"),
                "topic_label": (topic_by_code.get(row.get("code")) or {}).get("topic_label"),
            }
            for row in reasons.get("rows", [])
        ]
        ths_pool = {"status": reasons.get("status"), "asof": asof, "rows": ths_rows, "stale_reason": reasons.get("stale_reason"), "source": ths_source}
    except Exception as exc:  # noqa: BLE001 — preserve partial snapshot with a stable reason
        ths_pool = {
            "status": "error", "asof": asof, "rows": [],
            "stale_reason": f"{type(exc).__name__}: {exc}",
            "source": {"source_id": "ths_limit_up_pool", "source_url": THS_LIMIT_UP_URL, "status": "error", "ok": False, "stale_reason": f"{type(exc).__name__}: {exc}", "raw_sha256": None, "license_tier": "public_endpoint_unverified_terms"},
        }
    try:
        yesterday_pool = fetch_yesterday_pool(asof)
    except Exception as exc:  # noqa: BLE001 — preserve partial snapshot with a stable reason
        yesterday_pool = {
            "status": "error", "asof": asof, "rows": [],
            "stale_reason": f"{type(exc).__name__}: {exc}",
            "source": {"source_id": "eastmoney_yesterday_zt_pool", "source_url": f"{EM_YESTERDAY_POOL_URL}getYesterdayZTPool", "status": "error", "ok": False, "stale_reason": f"{type(exc).__name__}: {exc}", "raw_sha256": None, "license_tier": "public_endpoint_unverified_terms"},
        }

    payload = attach_source_adapters(payload, yesterday_pool=yesterday_pool, ths_pool=ths_pool)
    _assert_dated_payload_immutable(out / f"market_{asof}.json", payload)
    prior_asof = sessions["prior_asof"]
    prior = None
    if prior_asof:
        path = _prior_path(out, prior_asof)
        if path is not None:
            prior = _load_json(path)
    payload = attach_snapshot_extensions(
        payload,
        prior,
        trading_dates=_read_calendar(Path(args.trading_calendar) if args.trading_calendar else None),
    )
    write_snapshot(payload, out, board_dir=out / "board_flow")

    context = build_snapshot(
        payload,
        source_url=args.source_url,
        requested_at=args.requested_at,
        fetched_at=payload.get("generated_at"),
    )
    context["run_mode"] = args.run_mode
    context["calendar"] = sessions
    context["history"]["progression"] = payload.get("history", {}).get("progression", context["history"]["progression"])
    _rehash(context)
    text = json.dumps(context, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    dated_context = out / f"market_context_{asof}.json"
    _assert_dated_context_immutable(dated_context, text)
    if not dated_context.exists():
        dated_context.write_text(text, encoding="utf-8")
    latest_context = out / "market_context_latest.json"
    if latest_context.exists():
        existing_latest = _load_json(latest_context)
        existing_asof = str(existing_latest.get("asof") or "")
        if existing_asof > asof:
            pass
        elif existing_asof == asof:
            _assert_dated_context_immutable(latest_context, text)
        else:
            latest_context.write_text(text, encoding="utf-8")
    else:
        latest_context.write_text(text, encoding="utf-8")

    manifest_path = out / "market_context_manifest.json"
    manifest = _load_json(manifest_path) if manifest_path.exists() else {"schema_version": "market-context-manifest.v1", "snapshots": []}
    entry = _manifest_entry(context, run_mode=args.run_mode)
    entry.update({"prior_asof": sessions["prior_asof"], "calendar_status": sessions["calendar_status"], "calendar_version": sessions["calendar_version"]})
    existing_entry = next((item for item in manifest.get("snapshots", []) if item.get("asof") == asof), None)
    if existing_entry and existing_entry.get("snapshot_sha256") != entry.get("snapshot_sha256"):
        raise ValueError(f"dated manifest entry is immutable: {asof}")
    entries = [item for item in manifest.get("snapshots", []) if item.get("asof") != asof]
    entries.append(entry)
    entries.sort(key=lambda entry: str(entry.get("asof")))
    manifest.update({"generated_at": context.get("generated_at"), "snapshots": entries, "real_snapshot_count": sum(1 for entry in entries if entry.get("run_mode") == "live" and entry.get("status") in {"fresh", "partial"} and entry.get("source_hashes"))})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"asof": asof, "prior_asof": sessions["prior_asof"], "calendar_status": sessions["calendar_status"], "status": context.get("status"), "progression": context["history"]["progression"].get("status"), "real_snapshot_count": manifest["real_snapshot_count"], "output": str(out)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asof", help="EOD date YYYY-MM-DD")
    parser.add_argument("--prior-asof", help="explicit prior trading date; missing file stays unavailable")
    parser.add_argument("--trading-calendar", help="JSON list of verified trading dates")
    parser.add_argument("--today", help="Override today for deterministic calendar resolution")
    parser.add_argument("--out", default="out/market-context")
    parser.add_argument("--base-snapshot", help="Use an already fetched dated market payload; still refreshes P1 adapters")
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--requested-at", default=None)
    parser.add_argument("--run-mode", choices=("live", "fixture"), default="live")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
