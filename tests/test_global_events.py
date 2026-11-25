"""Point-in-time information boundaries and bounded metadata-only refresh."""
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
import requests

from research.data import global_events as events

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)


def news_payload(published=None):
    return {"news": [{"title": "MRVL market update", "publisher": "Fixture publisher",
                      "providerPublishTime": int((published or NOW - timedelta(hours=1)).timestamp()),
                      "link": "https://example.org/article", "body": "NEVER SAVE ARTICLE BODY",
                      "thumbnail": {"url": "https://example.org/image"}}]}


def snapshot(root, fetched, published=None):
    items, _ = events._normalise_news(news_payload(published or fetched - timedelta(hours=1)), fetched)
    value = {"symbol": "US_MRVL", "status": "ok", "items": items,
             "fetched_at": fetched.isoformat(), "source": events.SOURCE}
    events._archive(root / "events" / "US_MRVL", value)
    return value


def corporate(root, fetched):
    folder = root / "source" / "US_MRVL"
    folder.mkdir(parents=True)
    payload = {"chart": {"result": [{"meta": {"symbol": "MRVL"},
               "events": {"dividends": {"one": {"date": int(datetime(2026, 10, 2, 14, tzinfo=UTC).timestamp()),
                                                    "amount": 0.06}}}}]}}
    raw = json.dumps(payload).encode()
    (folder / "prices.raw.json").write_bytes(raw)
    (folder / "vintage.metadata.json").write_text(json.dumps({"id": "US_MRVL",
        "fetched_at": fetched.isoformat(), "raw_file": "prices.raw.json",
        "raw_sha256": hashlib.sha256(raw).hexdigest()}))


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(events, "_now", lambda: NOW)


def test_historical_request_never_fetches_or_backfills_later_knowledge(tmp_path, monkeypatch):
    snapshot(tmp_path, NOW, datetime(2026, 11, 19, 12, tzinfo=UTC))
    corporate(tmp_path, NOW)
    monkeypatch.setattr(events.requests, "get", lambda *a, **k: pytest.fail("historical network access"))
    result = events.collect_market_events("US_MRVL", tmp_path, "2026-11-20", refresh=True)
    assert result["status"] == "unavailable"
    assert result["stale_reason"] == "historical_news_not_archived"
    assert result["items"] == []


def test_historical_asof_cutoff_is_exchange_close_not_utc_midnight(tmp_path):
    before = datetime(2026, 11, 20, 20, 59, tzinfo=UTC)
    snapshot(tmp_path, before)
    snapshot(tmp_path, datetime(2026, 11, 20, 21, 1, tzinfo=UTC))
    result = events.collect_market_events("US_MRVL", tmp_path, "2026-11-20")
    assert result["fetched_at"] == before.isoformat()
    assert all(not row["after_model_asof"] for row in result["items"])
    assert all(row["knowledge_scope"] == "archived_asof" for row in result["items"])


def test_current_refresh_keeps_only_metadata_and_labels_later_context(tmp_path, monkeypatch):
    class Response:
        status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return news_payload()
    monkeypatch.setattr(events.requests, "get", lambda *a, **k: Response())
    result = events.collect_market_events("US_MRVL", tmp_path, "2026-11-20", True, mode="current")
    assert result["status"] == "ok"
    assert result["model_asof"] == "2026-11-20"
    assert result["items"][0]["after_model_asof"] is True
    assert result["model_input"] is False
    assert result["source"]["public_redistribution"] == "NOT_ESTABLISHED"
    files = list((tmp_path / "events" / "US_MRVL").glob("*.json"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "NEVER SAVE" not in text and "thumbnail" not in text


def test_six_hour_reuse_avoids_repeat_requests(tmp_path, monkeypatch):
    snapshot(tmp_path, NOW - timedelta(hours=1))
    monkeypatch.setattr(events.requests, "get", lambda *a, **k: pytest.fail("refetched too soon"))
    assert events.collect_market_events("US_MRVL", tmp_path, "2026-11-20", True, mode="current")["status"] == "ok"


def test_naver_prices_do_not_block_independent_news_or_fabricate_actions(tmp_path, monkeypatch):
    folder = tmp_path / "source" / "KR_KOSDAQ"
    folder.mkdir(parents=True)
    raw = b"[['date', 'close'], ['20261123', 700.0]]"
    (folder / "prices.raw.json").write_bytes(raw)
    (folder / "vintage.metadata.json").write_text(json.dumps({"id": "KR_KOSDAQ",
        "provider": "naver", "fetched_at": NOW.isoformat(), "raw_file": "prices.raw.json",
        "raw_sha256": hashlib.sha256(raw).hexdigest()}), encoding="utf-8")
    items, _ = events._normalise_news(news_payload(), NOW)
    events._archive(tmp_path / "events" / "KR_KOSDAQ", {"symbol": "KR_KOSDAQ", "status": "ok",
        "items": items, "fetched_at": NOW.isoformat(), "source": events.SOURCE})
    monkeypatch.setattr(events.requests, "get", lambda *a, **k: pytest.fail("unrequested network"))
    result = events.collect_market_events("KR_KOSDAQ", tmp_path, "2026-11-23", mode="current")
    assert result["status"] == "ok"
    assert len(result["items"]) == 1 and result["items"][0]["type"] == "news"
    assert result["components"]["corporate_actions"]["status"] == "unavailable"
    assert result["components"]["corporate_actions"]["source"] == "naver"
    (folder / "prices.raw.json").write_bytes(raw + b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        events.collect_market_events("KR_KOSDAQ", tmp_path, "2026-11-23", mode="current")


def test_denied_refresh_preserves_usable_cache_and_records_failure(tmp_path, monkeypatch):
    old = snapshot(tmp_path, NOW - timedelta(hours=7))
    class Denied:
        status_code = 429
        def raise_for_status(self):
            raise requests.HTTPError("429")
    monkeypatch.setattr(events.requests, "get", lambda *a, **k: Denied())
    result = events.collect_market_events("US_MRVL", tmp_path, "2026-11-20", True, mode="current")
    assert result["status"] == "stale"
    assert result["stale_reason"] == "source_access_denied"
    assert result["items"][0]["hash"] == old["items"][0]["hash"]
    assert len(list((tmp_path / "events" / "US_MRVL").glob("*.json"))) == 2


def test_corporate_action_effective_date_is_not_published_time(tmp_path):
    corporate(tmp_path, NOW)
    result = events.collect_market_events("US_MRVL", tmp_path, "2026-11-20", mode="current")
    item = result["items"][0]
    assert item["type"] == "dividend" and item["published_at"] is None
    assert item["event_at"].startswith("2026-10-02")
    assert item["known_at"] == NOW.isoformat() and item["after_model_asof"] is True
    assert item["time_basis"] == "effective_date_not_announcement"


def test_headlines_reject_future_time_and_unsafe_url():
    data = news_payload(NOW + timedelta(hours=1))
    assert events._normalise_news(data, NOW) == ([], 1)
    data = news_payload()
    data["news"][0]["link"] = "javascript:alert(1)"
    assert events._normalise_news(data, NOW) == ([], 1)


def test_news_checksum_and_corporate_raw_checksum_are_verified(tmp_path):
    snapshot(tmp_path, NOW)
    path = next((tmp_path / "events" / "US_MRVL").glob("*.json"))
    value = json.loads(path.read_text())
    value["items"][0]["title"] = "changed"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="checksum"):
        events.collect_market_events("US_MRVL", tmp_path, "2026-11-20", mode="current")
    other = tmp_path / "corporate"
    corporate(other, NOW)
    (other / "source" / "US_MRVL" / "prices.raw.json").write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        events.collect_market_events("US_MRVL", other, "2026-11-20", mode="current")


def test_all_terminal_assets_have_explicit_queries():
    assert set(events.QUERIES) == set(events.ASSETS)


def test_refetched_headline_keeps_earliest_archived_knowledge_time(tmp_path):
    before = datetime(2026, 11, 20, 20, tzinfo=UTC)
    published = before - timedelta(hours=1)
    snapshot(tmp_path, before, published)
    snapshot(tmp_path, NOW, published)
    result = events.collect_market_events("US_MRVL", tmp_path, "2026-11-20", mode="current")
    assert result["news_asof"] == NOW.isoformat()
    assert result["items"][0]["known_at"] == before.isoformat()
    assert result["items"][0]["after_model_asof"] is False
