"""Offline contract tests for P2/P3 source normalizers."""

from __future__ import annotations

import pytest

from research.data.global_context import (
    GLOBAL_SCHEMA_VERSION,
    PROBABILITY_SCHEMA_VERSION,
    build_global_context,
    build_probability_context,
    build_probability_snapshot,
    json_sha256,
    parse_bls_series,
    parse_eia_series,
    parse_ny_fed_observations,
    parse_treasury_curve,
    source_unavailable_market,
)

ASOF = "2026-11-06"
FETCHED = "2026-11-07T00:30:00+00:00"


def test_treasury_parser_keeps_source_provenance_and_missing_values() -> None:
    payload = {
        "data": [
            {"record_date": ASOF, "1 Mo": "4.20", "3 Mo": "4.10", "10 Yr": "4.25"},
        ]
    }
    result = parse_treasury_curve(
        payload,
        asof=ASOF,
        fetched_at=FETCHED,
        source_url="https://home.treasury.gov/resource-center/data-chart-center/interest-rates",
        raw_sha256="raw-treasury",
        license_tier="official_public",
    )

    assert result["status"] == "ok"
    assert result["source"] == "us_treasury"
    assert result["source_url"].startswith("https://home.treasury.gov/")
    assert result["fetched_at"] == FETCHED
    assert result["raw_sha256"] == "raw-treasury"
    assert result["license_tier"] == "official_public"
    assert result["rows"] == [{"asof": ASOF, "tenors": {"1m": "4.20", "3m": "4.10", "10y": "4.25"}}]
    assert "0" not in result["rows"][0]["tenors"]


def test_official_response_parsers_are_offline_and_shape_explicit() -> None:
    nyfed = parse_ny_fed_observations(
        {"observations": [{"effectiveDate": ASOF, "percentRate": 4.5}]},
        asof=ASOF,
        fetched_at=FETCHED,
        source_url="https://markets.newyorkfed.org/api/rates/secured/sofr/search.json",
        raw_sha256="raw-nyfed",
    )
    bls = parse_bls_series(
        {"Results": {"series": [{"data": [{"year": "2026", "period": "M10", "value": "3.1"}]}]}},
        asof=ASOF,
        fetched_at=FETCHED,
        source_url="https://api.bls.gov/publicAPI/v2/timeseries/data/",
        raw_sha256="raw-bls",
    )
    eia = parse_eia_series(
        {"response": {"data": [{"period": "2026-11-06", "value": 72.0}]}},
        asof=ASOF,
        fetched_at=FETCHED,
        source_url="https://api.eia.gov/v2/",
        raw_sha256="raw-eia",
    )

    assert nyfed["source"] == "ny_fed"
    assert nyfed["rows"] == [{"asof": ASOF, "value": 4.5}]
    assert bls["rows"][0]["period"] == "M10"
    assert bls["rows"][0]["value"] == "3.1"
    assert eia["rows"] == [{"period": "2026-11-06", "value": 72.0}]


def test_source_unavailable_market_does_not_fill_zero() -> None:
    result = source_unavailable_market(
        "vix",
        asof=ASOF,
        fetched_at=FETCHED,
        reason="licensed market feed is not connected",
    )

    assert result["status"] == "source_unavailable"
    assert result["stale_reason"] == "licensed market feed is not connected"
    assert result["value"] is None


def test_probability_snapshot_is_descriptive_and_preserves_liquidity_and_stale() -> None:
    item = build_probability_snapshot(
        venue="polymarket",
        market_id="fed-cut-dec-2026",
        question="Will the target range be lower at the December meeting?",
        outcome="Yes",
        implied_probability=0.62,
        asof="2026-11-06T09:00:00Z",
        fetched_at=FETCHED,
        source_url="https://polymarket.com/event/example",
        liquidity={"volume_24h": 12000, "open_interest": 90000},
        status="stale",
        stale_reason="source_unavailable",
    )
    snapshot = build_probability_context([item], asof=ASOF, generated_at=FETCHED)

    assert item["schema_version"] == PROBABILITY_SCHEMA_VERSION
    assert item["probability_type"] == "forecast_market_implied_probability"
    assert item["official_fedwatch"] is False
    assert item["liquidity"]["volume_24h"] == 12000
    assert item["volume_24h"] == 12000
    assert item["open_interest"] == 90000
    assert item["asof"] == "2026-11-06T09:00:00Z"
    assert snapshot["status"] == "stale"
    assert snapshot["items"][0]["stale_reason"] == "source_unavailable"


def test_probability_range_is_validated_and_missing_probability_stays_none() -> None:
    with pytest.raises(ValueError):
        build_probability_snapshot(
            venue="kalshi",
            market_id="example",
            question="Example",
            outcome="Yes",
            implied_probability=1.1,
            asof=ASOF,
            fetched_at=FETCHED,
            source_url=None,
        )

    item = build_probability_snapshot(
        venue="kalshi",
        market_id="unavailable",
        question="Example",
        outcome="Yes",
        implied_probability=None,
        asof=ASOF,
        fetched_at=FETCHED,
        source_url=None,
        status="source_unavailable",
        stale_reason="network unavailable",
    )
    assert item["implied_probability"] is None


def test_global_context_is_stable_and_keeps_p2_p3_separate() -> None:
    treasury = parse_treasury_curve(
        [{"record_date": ASOF, "10 Yr": "4.25"}],
        asof=ASOF,
        fetched_at=FETCHED,
        source_url="https://home.treasury.gov/",
        raw_sha256="raw-treasury",
    )
    unavailable = source_unavailable_market(
        "dxy",
        asof=ASOF,
        fetched_at=FETCHED,
        reason="source not connected",
    )
    probability = build_probability_context(
        [
            build_probability_snapshot(
                venue="kalshi",
                market_id="m1",
                question="Example",
                outcome="Yes",
                implied_probability=0.4,
                asof=ASOF,
                fetched_at=FETCHED,
                source_url="https://kalshi.com/markets/m1",
            )
        ],
        asof=ASOF,
        generated_at=FETCHED,
    )
    args = {
        "asof": ASOF,
        "generated_at": FETCHED,
        "run_id": "run-1",
        "sources": {"us_treasury": treasury, "dxy": unavailable},
        "rates": {"treasury_curve": treasury},
        "markets": {"dxy": unavailable, "vix": source_unavailable_market("vix", asof=ASOF, fetched_at=FETCHED, reason="not connected")},
        "probability": probability,
    }
    left = build_global_context(**args)
    right = build_global_context(**args)

    assert left["schema_version"] == GLOBAL_SCHEMA_VERSION
    assert left["status"] == "partial"
    assert left["sources"]["us_treasury"]["raw_sha256"] == "raw-treasury"
    assert left["markets"]["dxy"]["value"] is None
    assert left["probability"]["schema_version"] == PROBABILITY_SCHEMA_VERSION
    assert left["probability"]["official_fedwatch"] is False
    assert left["snapshot_sha256"] == right["snapshot_sha256"]
    assert left["snapshot_sha256"] == json_sha256({key: value for key, value in left.items() if key != "snapshot_sha256"})
