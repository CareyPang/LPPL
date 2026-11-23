"""Local headline and corporate-action context, independent of LPPLS inputs.

Historical views only use snapshots actually fetched before the exchange close.
Current context is opt-in and always exposes its later knowledge timestamp.
"""
from __future__ import annotations

import hashlib
import html
import json
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import requests

from ..pipeline.stock_jobs import atomic_json
from .global_terminal import ASSETS

ENDPOINT = "https://query2.finance.yahoo.com/v1/finance/search"
QUERIES = {
    "US_SPX": "S&P 500", "US_IXIC": "Nasdaq Composite", "US_NDX": "Nasdaq 100",
    "US_DJI": "Dow Jones", "JP_N225": "Nikkei 225", "KR_KOSPI": "KOSPI",
    "KR_KOSDAQ": "KOSDAQ", "US_MRVL": "MRVL",
}
TTL = timedelta(hours=6)
SOURCE = {
    "name": "Yahoo Finance search headline metadata",
    "url": ENDPOINT,
    "license_status": "NOT_ESTABLISHED",
    "public_redistribution": "NOT_ESTABLISHED",
    "usage": "local_research",
    "terms_url": "https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
    "terms_note": "global-stock-data flags prior-permission restrictions on automated collection; no redistribution permission is established by this adapter.",
    "refresh_interval_hours": 6,
    "rate_limit_status": "provider_quota_not_established",
    "network_scope": "local_host_only",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(value: str) -> datetime:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return instant.astimezone(UTC)


def _hash(value: dict) -> str:
    content = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(content.encode()).hexdigest()


def _cutoff(asset_id: str, asof: str) -> datetime:
    day = datetime.strptime(asof, "%Y-%m-%d").date()
    asset = ASSETS[asset_id]
    close = time(16) if asset["market"] == "us" else time(15, 30)
    return datetime.combine(day, close, ZoneInfo(asset["timezone"])).astimezone(UTC)


def _url(value) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    return value if parsed.scheme in ("http", "https") and parsed.netloc else None


def _item(title, source, published_at, url, kind, known_at, **extra):
    value = {"title": html.unescape(str(title)).strip(), "source": str(source),
             "published_at": published_at, "url": url, "type": kind, **extra}
    digest = _hash(value)
    return {"id": digest[:24], **value, "hash": digest, "known_at": known_at}


def _normalise_news(payload: dict, fetched_at: datetime) -> tuple[list[dict], int]:
    rows = payload.get("news")
    if not isinstance(rows, list):
        raise ValueError("Yahoo news array missing")
    items, rejected = {}, 0
    for row in rows:
        try:
            timestamp = datetime.fromtimestamp(float(row["providerPublishTime"]), UTC)
            url = _url(row.get("link"))
            if timestamp > fetched_at or not url or not row.get("title") or not row.get("publisher"):
                raise ValueError("Incomplete or future headline")
            item = _item(row["title"], row["publisher"], timestamp.isoformat(), url,
                         "news", fetched_at.isoformat())
            items[item["hash"]] = item
        except (KeyError, TypeError, ValueError, OverflowError):
            rejected += 1
    return sorted(items.values(), key=lambda item: item["published_at"], reverse=True), rejected


def _archive(folder: Path, snapshot: dict) -> None:
    """Content-addressed append-only metadata. Never persist article bodies."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (_hash(snapshot) + ".json")
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != snapshot:
            raise ValueError("Immutable news snapshot mismatch")
        return
    atomic_json(path, snapshot)


def _news_snapshots(folder: Path, asset_id: str, cutoff: datetime) -> list[dict]:
    snapshots = []
    for path in folder.glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if _hash(value) != path.stem or value.get("symbol") != asset_id:
            raise ValueError("News snapshot checksum or asset identity mismatch")
        if _stamp(value["fetched_at"]) <= cutoff:
            snapshots.append(value)
    return sorted(snapshots, key=lambda item: item["fetched_at"])


def _fetch_news(asset_id: str, folder: Path) -> dict:
    snapshot = {"symbol": asset_id, "query": QUERIES[asset_id], "source": SOURCE,
                "items": [], "status": "unavailable", "stale_reason": None}
    try:
        response = requests.get(ENDPOINT, params={"q": QUERIES[asset_id], "quotesCount": 0,
                                "newsCount": 12}, headers={"User-Agent": "Mozilla/5.0"},
                                timeout=(10, 20))
        snapshot["http_status"] = response.status_code
        response.raise_for_status()
        fetched = _now()
        items, rejected = _normalise_news(response.json(), fetched)
        snapshot.update(items=items, rejected_rows=rejected,
                        status="ok" if items else "empty", fetched_at=fetched.isoformat())
    except (requests.RequestException, ValueError) as error:
        snapshot.update(fetched_at=_now().isoformat(),
                        stale_reason="source_access_denied" if snapshot.get("http_status") in (401, 403, 429, 999)
                        else "source_fetch_failed", error_type=type(error).__name__)
    _archive(folder, snapshot)
    return snapshot


def _corporate_actions(asset_id: str, root: Path, cutoff: datetime) -> dict:
    folder = root / "source" / asset_id
    snapshots = []
    for path in folder.glob("*.metadata.json"):
        meta = json.loads(path.read_text(encoding="utf-8"))
        if meta.get("id") == asset_id and _stamp(meta["fetched_at"]) <= cutoff:
            snapshots.append(meta)
    if not snapshots:
        return {"status": "unavailable", "items": [], "stale_reason": "corporate_actions_not_archived"}
    meta = max(snapshots, key=lambda item: _stamp(item["fetched_at"]))
    filename = meta["raw_file"]
    if Path(filename).name != filename:
        raise ValueError("Unsafe corporate-action archive path")
    raw = (folder / filename).read_bytes()
    if hashlib.sha256(raw).hexdigest() != meta["raw_sha256"]:
        raise ValueError("Corporate-action source checksum mismatch")
    if meta.get("provider", "yahoo") != "yahoo":
        # Naver's index table contains prices, not Yahoo's events envelope.
        # Its presence must not prevent independently archived news rendering.
        return {"status": "unavailable", "items": [], "fetched_at": meta["fetched_at"],
                "stale_reason": "corporate_actions_not_supported_by_source",
                "source": meta.get("provider"), "raw_source_hash": meta["raw_sha256"]}
    result = json.loads(raw)["chart"]["result"][0]
    if result["meta"].get("symbol") != ASSETS[asset_id]["ticker"]:
        raise ValueError("Corporate-action asset mismatch")
    items = []
    for key, kind, label in (("dividends", "dividend", "股息生效"), ("splits", "split", "拆股生效")):
        for row in (result.get("events") or {}).get(key, {}).values():
            event = datetime.fromtimestamp(row["date"], UTC)
            event_day = event.astimezone(ZoneInfo(ASSETS[asset_id]["timezone"])).date()
            title = f"{ASSETS[asset_id]['name']} · {label}日 {event_day}"
            items.append(_item(title, "Yahoo Finance chart corporate actions", None,
                               "https://finance.yahoo.com/quote/" + quote(ASSETS[asset_id]["ticker"], safe="") + "/history/",
                               kind, meta["fetched_at"], event_at=event.isoformat(),
                               time_basis="effective_date_not_announcement", raw_source_hash=meta["raw_sha256"]))
    items.sort(key=lambda item: item["event_at"], reverse=True)
    return {"status": "ok" if items else "empty", "items": items, "fetched_at": meta["fetched_at"],
            "stale_reason": None, "source": "previously_cached_Yahoo_chart", "raw_source_hash": meta["raw_sha256"]}


def collect_market_events(asset_id: str, root: Path, asof: str, refresh: bool = False,
                          *, mode: str = "historical") -> dict:
    """Return archived as-of knowledge, or explicitly labelled current context.

    ``refresh`` only fetches in current mode, at most once per six hours. Failed
    refreshes retain previously readable headlines and expose the failure.
    """
    if asset_id not in ASSETS or mode not in ("historical", "current"):
        raise ValueError("Unsupported event asset or mode")
    root = Path(root)
    model_cutoff = _cutoff(asset_id, asof)
    now = _now()
    cutoff = min(now, model_cutoff) if mode == "historical" else now
    folder = root / "events" / asset_id
    snapshots = _news_snapshots(folder, asset_id, cutoff)
    latest = snapshots[-1] if snapshots else None
    if mode == "current" and refresh and (latest is None or now - _stamp(latest["fetched_at"]) >= TTL):
        latest = _fetch_news(asset_id, folder)
        snapshots.append(latest)
        now = _now()
    usable = [item for item in snapshots if item["status"] in ("ok", "empty")]
    news = usable[-1] if usable else None
    reason = None
    if mode == "historical" and news is None:
        reason = "historical_news_not_archived"
    elif latest and latest["status"] == "unavailable":
        reason = latest["stale_reason"]
    elif news is None:
        reason = "news_not_fetched"
    elif now - _stamp(news["fetched_at"]) >= TTL and mode == "current":
        reason = "news_refresh_due"
    corporate = _corporate_actions(asset_id, root, cutoff)
    first_seen = {}
    for snapshot in usable:
        for item in snapshot["items"]:
            first_seen.setdefault(item["hash"], item["known_at"])
    items = [{**item, "known_at": first_seen[item["hash"]]} for item in news["items"]] if news else []
    items += corporate["items"]
    items = [{**item, "after_model_asof": _stamp(item["known_at"]) > model_cutoff,
              "knowledge_scope": "current_context" if mode == "current" else "archived_asof"} for item in items]
    status = ("stale" if news else "partial" if items else "unavailable") if reason else "ok" if items else "empty"
    fetched_at = news["fetched_at"] if news else corporate.get("fetched_at")
    return {"schema_version": "global_events_v1", "symbol": asset_id, "asof": asof,
            "model_asof": asof, "mode": mode, "status": status, "items": items,
            "source": SOURCE, "fetched_at": fetched_at, "queried_at": now.isoformat(),
            "news_asof": news["fetched_at"] if news else None, "stale_reason": reason,
            "last_attempt_at": latest["fetched_at"] if latest else None,
            "components": {"news": {"status": news["status"] if news else "unavailable",
                                     "stale_reason": reason},
                           "corporate_actions": {k: v for k, v in corporate.items() if k != "items"}},
            "information_only": True, "model_input": False,
            "known_at_definition": "News: earliest retained observation. Corporate actions: source snapshot retrieval; announcement time is unknown.",
            "note": "当前资讯与模型截止日分别展示；历史页只读当时已取得的档案。股息/拆股日期是生效日，公告时间未知。"}
