from research.data.market_p1 import (
    attach_snapshot_extensions,
    attach_source_adapters,
    enrich_limit_pools,
    progression_from_snapshots,
    unavailable,
)


def _pools(rows):
    return {"zt": rows, "zb": [], "dt": []}


def _payload(asof, rows):
    return {"asof": asof, "limit_pools": {"pool_rows": _pools(rows)}}


def _row(code, streak, topic=None):
    row = {"code": code, "name": code, "streak": streak, "limit_time": "09:25:00"}
    if topic is not None:
        row["topic_label"] = topic
    return row


def test_enrich_limit_pools_keeps_full_rows_and_does_not_invent_reason():
    raw = {
        "zt": [{"c": "000001", "n": "示例", "lbc": 2, "fbt": 92500, "hybk": "银行"}],
        "zb": [],
        "dt": [],
    }
    result = enrich_limit_pools({"zt": 1, "zb": 0, "dt": 0}, raw, "2026-11-02")

    assert result["pool_rows"]["zt"] == [
        {
            "code": "000001",
            "name": "示例",
            "streak": 2,
            "limit_time": "09:25:00",
            "industry_label": "银行",
            "industry_source_field": "hybk",
        }
    ]
    assert result["topics"]["status"] == "not_available"
    assert result["reasons"]["status"] == "not_available"
    assert result["reasons"]["rows"] == []


def test_progression_requires_explicit_trading_calendar():
    current = _payload("2026-11-03", [_row("000001", 3)])
    prior = _payload("2026-11-02", [_row("000001", 2), _row("000002", 1)])

    previous, progression = progression_from_snapshots(current, prior)

    assert previous["status"] == "fresh"
    assert progression["status"] == "not_available"
    assert "calendar" in progression["stale_reason"]


def test_progression_counts_only_next_day_advancement_and_preserves_missing_as_none():
    current = _payload(
        "2026-11-03",
        [_row("000001", 3), _row("000002", 1)],
    )
    prior = _payload(
        "2026-11-02",
        [_row("000001", 2), _row("000002", 1), _row("000003", 2)],
    )

    previous, progression = progression_from_snapshots(
        current,
        prior,
        trading_dates=["2026-11-02", "2026-11-03"],
    )

    assert previous["rows"]["zt"][0]["code"] == "000001"
    assert progression["status"] == "fresh"
    by_from = {row["from_streak"]: row for row in progression["rows"]}
    assert by_from[2] == {
        "from_streak": 2,
        "to_streak": 3,
        "eligible_count": 2,
        "advanced_count": 1,
        "rate": 0.5,
        "asof": "2026-11-03",
        "window": "t+1",
    }
    assert by_from[1]["eligible_count"] == 1
    assert by_from[1]["advanced_count"] == 0


def test_progression_rejects_non_adjacent_dates_without_faking_rate():
    current = _payload("2026-11-05", [_row("000001", 3)])
    prior = _payload("2026-11-02", [_row("000001", 2)])

    _, progression = progression_from_snapshots(
        current,
        prior,
        trading_dates=["2026-11-02", "2026-11-03", "2026-11-05"],
    )

    assert progression["status"] == "not_available"
    assert progression["rows"] == []


def test_attach_extensions_keeps_old_fields_and_adds_prior_day():
    current = _payload("2026-11-03", [_row("000001", 3)])
    prior = _payload("2026-11-02", [_row("000001", 2)])
    current["limit_pools"]["zt"] = 1

    result = attach_snapshot_extensions(
        current,
        prior,
        trading_dates=["2026-11-02", "2026-11-03"],
    )

    assert result["limit_pools"]["zt"] == 1
    assert result["limit_pools"]["prior_day"]["asof"] == "2026-11-02"
    assert result["history"]["progression"]["status"] == "fresh"


def test_unavailable_never_uses_zero_for_missing_count():
    value = unavailable("2026-11-03", "source did not return rows")
    assert value["status"] == "not_available"
    assert value["rows"] == []
    assert "count" not in value


def test_attach_source_adapters_preserves_provenance_and_keeps_missing_topics_explicit():
    payload = {"asof": "2026-11-03", "limit_pools": {"zt": 1}}
    yesterday = {
        "status": "fresh",
        "asof": "2026-11-02",
        "rows": [{"code": "000001", "pct": 3.2}],
        "source": {
            "source_id": "eastmoney_yesterday_zt_pool",
            "source_url": "https://push2ex.eastmoney.com/getYesterdayZTPool",
            "raw_sha256": "a" * 64,
            "status": "fresh",
        },
    }
    ths = {
        "status": "fresh",
        "asof": "2026-11-03",
        "rows": [{"code": "000001", "name": "示例", "reason": "算力", "topic_label": "算力"}],
        "source": {
            "source_id": "ths_limit_up_pool",
            "source_url": "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool",
            "raw_sha256": "b" * 64,
            "status": "fresh",
        },
    }

    result = attach_source_adapters(payload, yesterday_pool=yesterday, ths_pool=ths)

    assert result["limit_pools"]["prior_day"]["asof"] == "2026-11-02"
    assert result["limit_pools"]["reasons"]["rows"][0]["source_field"] == "reason_type"
    assert result["limit_pools"]["topics"]["rows"][0]["topic_label"] == "算力"
    assert set(result["sources"]) == {"eastmoney_yesterday_zt_pool", "ths_limit_up_pool"}
    assert result["sources"]["ths_limit_up_pool"]["raw_sha256"] == "b" * 64


def test_yesterday_pool_adapter_preserves_source_hash_and_dated_rows():
    from research.data.market_p1 import EM_YESTERDAY_POOL_URL, fetch_yesterday_pool

    payload = {"data": {"pool": [{"c": "000001", "n": "示例", "zdp": 3.2, "ylbc": 2, "hybk": "银行", "zttj": {"days": 3, "ct": 2}}]}}

    class Response:
        url = f"{EM_YESTERDAY_POOL_URL}getYesterdayZTPool"

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class Session:
        def __init__(self):
            self.calls = []

        def get(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return Response()

    session = Session()
    result = fetch_yesterday_pool("2026-11-03", session=session)
    assert result["status"] == "fresh"
    assert result["rows"][0]["code"] == "000001"
    assert result["source"]["raw_sha256"]
    assert session.calls[0][1]["params"]["date"] == "20261103"


def test_ths_reason_topic_adapter_does_not_treat_industry_as_reason():
    from research.data.market_p1 import THS_LIMIT_UP_URL, fetch_ths_reasons_topics

    payload = {"data": {"info": [{"code": "000001", "name": "示例", "reason_type": "算力"}, {"code": "000002", "name": "无原因", "industry": "银行"}]}}

    class Response:
        url = THS_LIMIT_UP_URL

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    reasons, topics, source = fetch_ths_reasons_topics("2026-11-03", session=Session())
    assert reasons["status"] == "fresh"
    assert reasons["rows"] == [{"code": "000001", "name": "示例", "reason": "算力", "source_field": "reason_type"}]
    assert topics["rows"][0]["topic_label"] == "算力"
    assert source["raw_sha256"]
