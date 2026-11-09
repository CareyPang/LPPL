"""Synthetic contract fixtures only; no live news or market data is fetched."""

import copy

import pytest

from research.data.investor_context import (
    SECTIONS,
    _hash,
    build_investor_context,
    validate_public_context,
)

DAY = "2026-11-06"
TIME = "2026-11-06T10:00:00Z"
CUTOFF = "2026-11-06T12:00:00Z"
SYMBOL = "sh600519"


def source(permitted=True):
    return {"source_id": "synthetic_source", "source_url": "https://example.test/source",
            "raw_sha256": "a" * 64, "available_at": TIME,
            "publication": {"status": "verified" if permitted else "NOT_ESTABLISHED",
                            "evidence_refs": ["synthetic-review-for-test"] if permitted else []}}


def attachment(rows, *, symbol=None, permitted=True, **extra):
    return {"asof": DAY, "status": "fresh", "rows": rows, "source": source(permitted),
            "symbol": symbol, "coverage_status": "complete", **extra}


def headline(**extra):
    return {"title": "Synthetic title", "source": "Synthetic publisher", "published_at": "2026-11-06T09:00:00Z",
            "url": "https://example.test/story", "body": "Must never survive", "prompt": "Must never survive", **extra}


def build(attachments=None, **kwargs):
    return build_investor_context(asof=DAY, available_at_cutoff=CUTOFF, attachments=attachments, **kwargs)


def test_no_source_has_honest_individual_empty_states():
    value = build()
    assert set(value["sections"]) == set(SECTIONS)
    assert all(section["status"] == "not_available" and not section["rows"] for section in value["sections"].values())
    assert not value["publication_eligible"] and not value["model_input_eligible"]
    assert value["pit_status"] == "NOT_ESTABLISHED"


def test_news_is_only_a_safe_index_and_does_not_mutate_input():
    inputs = {"news": attachment([headline()])}
    before = copy.deepcopy(inputs)
    value = build(inputs)
    assert inputs == before
    row = value["sections"]["news"]["rows"][0]
    assert set(row) == {"title", "source", "published_at", "url", "hash", "known_at", "available_at"}
    assert len(row["hash"]) == 64
    assert value["sections"]["news"]["source"]["raw_sha256"] == "a" * 64


def test_permission_block_is_independent_of_research_ingestion():
    inputs = {"news": attachment([headline()], permitted=False)}
    assert build(inputs)["sections"]["news"]["rows"]
    public = build(inputs, purpose="publish")
    assert public["sections"]["news"]["status"] == "blocked"
    assert public["sections"]["news"]["rows"] == []
    assert public["sections"]["news"]["publication_eligible"] is False


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://example.test/a", "data:text/plain,x",
                                "https://u:p@example.test/a", "https://example.test:bad/a", "https://example.test/\nattack"])
def test_unsafe_links_cannot_survive(url):
    result = build({"news": attachment([headline(url=url)])})
    assert result["sections"]["news"]["status"] == "error"
    assert result["sections"]["news"]["rows"] == []


@pytest.mark.parametrize("timestamp", ["2026-11-06", "2026-11-06T09:00:00", "2026-02-30T09:00:00Z", "20261106T090000Z", True])
def test_publication_timestamps_must_be_real_and_timezone_aware(timestamp):
    section = build({"news": attachment([headline(published_at=timestamp)])})["sections"]["news"]
    assert section["status"] == "error" and not section["rows"]


def test_future_publication_is_not_shown_in_old_review():
    inputs = {"news": attachment([headline(published_at="2026-11-07T01:00:00Z", available_at="2026-11-07T02:00:00Z")])}
    result = build(inputs)["sections"]["news"]
    assert result["status"] == "not_available" and not result["rows"]


def test_source_capture_bounds_even_an_earlier_row_time():
    item = attachment([headline(available_at="2026-11-06T09:30:00Z")])
    item["source"]["available_at"] = "2026-11-06T13:00:00Z"
    result = build({"news": item})["sections"]["news"]
    assert result["stale_reason"] == "source_not_available_at_cutoff"
    assert not result["rows"]


def test_future_event_date_is_allowed_if_known_by_cutoff():
    event = {"title": "Synthetic future event", "event_date": "2027-01-01", "url": "https://example.test/event"}
    result = build({"events": attachment([event])})["sections"]["events"]
    assert result["rows"][0]["event_date"] == "2027-01-01"
    future = {**event, "known_at": "2026-11-06T13:00:00Z", "available_at": "2026-11-06T14:00:00Z"}
    assert not build({"events": attachment([future])})["sections"]["events"]["rows"]


@pytest.mark.parametrize("field", ["source_id", "source_url", "raw_sha256", "available_at"])
def test_attachment_requires_source_provenance(field):
    item = attachment([headline()])
    del item["source"][field]
    section = build({"news": item})["sections"]["news"]
    assert section["status"] == "error" and not section["rows"]


def test_incorrect_asof_and_unknown_section_are_not_silently_used():
    item = attachment([headline()], asof="2026-11-05")
    assert build({"news": item})["sections"]["news"]["status"] == "error"
    with pytest.raises(ValueError, match="unknown"):
        build({"unregistered": item})


def test_profile_is_symbol_bound_and_excludes_unspecified_fields():
    item = attachment([{"symbol": SYMBOL, "name": "Synthetic", "industry": "Test", "description": "A profile fact",
                        "website": "https://example.test/", "secret": "discard"}], symbol=SYMBOL)
    value = build({"profile": item}, symbol=SYMBOL)
    assert value["sections"]["profile"]["rows"][0]["name"] == "Synthetic"
    assert "secret" not in value["sections"]["profile"]["rows"][0]
    assert not build({"profile": item}, symbol="sz000001")["sections"]["profile"]["rows"]
    assert not build({"profile": item})["sections"]["profile"]["rows"]


def test_stock_news_requires_explicit_row_asset():
    item = attachment([headline()])
    assert not build({"news": item}, symbol=SYMBOL)["sections"]["news"]["rows"]
    item["rows"][0]["symbol"] = SYMBOL
    assert build({"news": item}, symbol=SYMBOL)["sections"]["news"]["rows"]


@pytest.mark.parametrize("value", [True, "5", float("nan"), float("inf")])
def test_financial_numbers_remain_typed_and_finite(value):
    item = attachment([{"symbol": SYMBOL, "metric": "Revenue", "value": value, "unit": "CNY",
                        "report_period": "2026-09-30", "published_at": "2026-11-06T09:00:00Z"}], symbol=SYMBOL)
    assert not build({"financials": item}, symbol=SYMBOL)["sections"]["financials"]["rows"]


def test_missing_financial_value_is_null_not_zero():
    item = attachment([{"symbol": SYMBOL, "metric": "Revenue", "unit": "CNY",
                        "report_period": "2026-09-30", "published_at": "2026-11-06T09:00:00Z"}], symbol=SYMBOL)
    row = build({"financials": item}, symbol=SYMBOL)["sections"]["financials"]["rows"][0]
    assert row["value"] is None


def test_progression_must_have_matching_counts_and_never_invents_rate():
    valid = {"from_streak": 1, "to_streak": 2, "eligible_count": 4, "advanced_count": 1, "rate": 0.25}
    assert build({"progression": attachment([valid])})["sections"]["progression"]["rows"]
    bad = {**valid, "rate": 0.75}
    assert not build({"progression": attachment([bad])})["sections"]["progression"]["rows"]
    missing = {**valid, "rate": None}
    assert build({"progression": attachment([missing])})["sections"]["progression"]["rows"][0]["rate"] is None


def test_stale_and_partial_coverage_are_preserved():
    item = attachment([headline()], status="stale", stale_reason="source unavailable")
    assert build({"news": item})["sections"]["news"]["status"] == "stale"
    item = attachment([headline()], coverage_status="partial")
    assert build({"news": item})["sections"]["news"]["status"] == "partial"
    del item["coverage_status"]
    assert build({"news": item})["sections"]["news"]["status"] == "partial"


def test_public_validator_checks_sections_not_just_top_level_boolean():
    good = build({"news": attachment([headline()])}, purpose="publish")
    validate_public_context(good, asof=DAY, symbol=None, available_at_cutoff=CUTOFF)
    research = build({"news": attachment([headline()], permitted=False)})
    research.update(purpose="publish", publication_eligible=True)
    research["snapshot_sha256"] = _hash({k: v for k, v in research.items() if k != "snapshot_sha256"})
    with pytest.raises(ValueError, match="section publication"):
        validate_public_context(research, asof=DAY, symbol=None, available_at_cutoff=CUTOFF)


def test_public_validator_detects_tamper_and_date_or_symbol_leak():
    value = build({"news": attachment([headline()])}, purpose="publish")
    with pytest.raises(ValueError, match="date or symbol"):
        validate_public_context(value, asof="2026-11-05", symbol=None, available_at_cutoff=CUTOFF)
    with pytest.raises(ValueError, match="cutoff"):
        validate_public_context(value, asof=DAY, symbol=None, available_at_cutoff=TIME)
    value["sections"]["news"]["rows"][0]["title"] = "changed"
    with pytest.raises(ValueError, match="hash"):
        validate_public_context(value, asof=DAY, symbol=None, available_at_cutoff=CUTOFF)


def test_unknown_symbol_future_snapshot_and_date_only_cutoff_are_rejected():
    with pytest.raises(ValueError):
        build(symbol="600519")
    with pytest.raises(ValueError):
        build_investor_context(asof="2026-11-07", available_at_cutoff=CUTOFF)
    with pytest.raises(ValueError):
        build_investor_context(asof=DAY, available_at_cutoff=DAY)


def test_current_profile_cannot_be_pasted_into_an_older_snapshot():
    item = attachment([{"symbol": SYMBOL, "name": "Synthetic"}], symbol=SYMBOL)
    item["source"]["available_at"] = "2026-11-09T02:00:00Z"
    value = build_investor_context(asof=DAY, available_at_cutoff="2026-11-09T03:00:00Z",
                                   symbol=SYMBOL, attachments={"profile": item}, purpose="publish")
    assert not value["sections"]["profile"]["rows"]
    assert value["sections"]["profile"]["stale_reason"] == "current_profile_cannot_backfill_historical_snapshot"


@pytest.mark.parametrize("marker", [{"origin": "fixture"}, {"run_mode": "research_import"},
                                  {"publication_eligible": False}, {"evidence_import": {}}])
def test_explicit_unpublished_source_markers_cannot_be_overruled_by_review_boolean(marker):
    item = attachment([headline()])
    item["source"].update(marker)
    result = build({"news": item}, purpose="publish")
    assert result["sections"]["news"]["status"] == "blocked"
    assert not result["sections"]["news"]["rows"]
