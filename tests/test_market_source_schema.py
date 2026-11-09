"""Synthetic decoded HTTP fixtures only; no live provider verification."""

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from research.data.market_source_schema import inspect_em_pool, inspect_ths_pages

DAY = "2026-11-06"
TZ = ZoneInfo("Asia/Shanghai")


def row(code="600519", *, day=DAY, reason="Synthetic A+Synthetic B", hour=9):
    return {"code": code, "reason_type": reason,
            "first_limit_up_time": str(int(datetime.fromisoformat(day).replace(hour=hour, tzinfo=TZ).timestamp()))}


def page(rows=None, *, total=None, date=None):
    rows = [row()] if rows is None else rows
    value = {"status_code": 0, "data": {"info": rows, "page": {"total": len(rows) if total is None else total}}}
    if date is not None:
        value["data"]["date"] = date
    return value


def inspect(pages=None, **kwargs):
    return inspect_ths_pages([page()] if pages is None else pages, asof=DAY, **kwargs)


def test_complete_synthetic_pages_are_offline_only_and_non_mutating():
    value = [page([row()], total=2), page([row("000001")], total=2)]
    before = deepcopy(value)
    result = inspect(value, expected_codes=["600519", "000001"])
    assert value == before
    assert result["schema_complete"] and result["pagination"]["counts_complete"]
    assert result["pages"][0]["date_evidence"] == "row_first_limit_up_time"
    assert result["rows"][0]["source_reason_raw"] == "Synthetic A+Synthetic B"
    assert result["rows"][0]["derived_tags"] == ["Synthetic A", "Synthetic B"]
    assert result["coverage"]["full_market_ratio"] == 1
    for key in ("publication_eligible", "model_input_eligible", "raw_bytes_verified", "source_network_verified", "exchange_calendar_verified"):
        assert result[key] is False


@pytest.mark.parametrize("stamp_day", ["2026-11-05", "2026-11-07"])
def test_mixed_past_or_future_row_date_cannot_be_overridden_by_declared_date(stamp_day):
    result = inspect([page([row(), row("000001", day=stamp_day)], date=DAY)])
    assert result["status"] == "partial" and not result["date_evidence_complete"]
    assert "row_date_mismatch" in result["reasons"]


def test_timestamp_date_uses_shanghai_not_utc():
    result = inspect([page([row(hour=0)])])
    assert result["schema_complete"]  # UTC date is the previous day.


def test_milliseconds_require_explicit_unit_and_are_not_guessed():
    value = page()
    value["data"]["info"][0]["first_limit_up_time"] = int(value["data"]["info"][0]["first_limit_up_time"]) * 1000
    assert not inspect([value])["schema_complete"]
    assert inspect([value], timestamp_unit="milliseconds")["schema_complete"]
    assert not inspect(timestamp_unit="milliseconds")["schema_complete"]
    with pytest.raises(ValueError, match="timestamp_unit"):
        inspect(timestamp_unit="auto")


@pytest.mark.parametrize("bad", [None, True, "nan", "inf", "bad", -1, 10**30])
def test_bad_timestamp_keeps_result_partial_even_with_declared_date(bad):
    value = page(date=DAY)
    value["data"]["info"][0]["first_limit_up_time"] = bad
    assert not inspect([value])["schema_complete"]


def test_empty_pool_needs_independent_response_date():
    assert not inspect([page([])])["date_evidence_complete"]
    assert inspect([page([], date=DAY)])["schema_complete"]
    assert inspect([page([], date="20261106")])["schema_complete"]
    assert not inspect([page([], date="2026-11-07")])["schema_complete"]


@pytest.mark.parametrize("totals", [(2, 3), (1, 1), (3, 3)])
def test_cross_page_total_drift_underflow_or_truncation_is_partial(totals):
    result = inspect([page([row()], total=totals[0]), page([row("000001")], total=totals[1])])
    assert result["status"] == "partial" and not result["pagination"]["counts_complete"]


def test_duplicate_codes_across_pages_do_not_match_declared_unique_total():
    result = inspect([page(total=2), page(total=2)])
    assert result["pagination"]["duplicate_codes"] == ["600519"]
    assert not result["pagination"]["counts_complete"]


@pytest.mark.parametrize("total", [None, "1", True, -1])
def test_total_is_observed_not_invented_from_row_count(total):
    value = page()
    value["data"]["page"]["total"] = total
    result = inspect([value])
    assert result["pagination"]["declared_total"] is None
    assert not result["schema_complete"]


def test_legacy_top_level_total_does_not_replace_observed_page_total():
    value = page()
    value["data"].pop("page")
    value["data"]["total"] = 1
    assert not inspect([value])["schema_complete"]


@pytest.mark.parametrize("status", [None, "0", True, 1])
def test_business_status_is_strict(status):
    value = page()
    value["status_code"] = status
    result = inspect([value])
    assert not result["schema_complete"]
    assert result["status"] == ("error" if type(status) is int and status != 0 else "partial")


def test_full_market_denominator_preserves_bse_exclusion_and_extra_rows():
    result = inspect([page([row(), row("000001")])], expected_codes=["600519", "920007"])
    assert result["coverage"]["full_market_denominator"] == 2
    assert result["coverage"]["full_market_ratio"] == 0.5
    assert result["coverage"]["reference_scope_denominator"] == 1
    assert result["coverage"]["reference_scope_matched"] == 1
    assert result["coverage"]["full_market_missing_codes"] == ["920007"]
    assert result["coverage"]["extra_source_codes"] == ["000001"]
    assert result["scope"]["expected_outside_reference_codes"] == ["920007"]
    assert result["scope"]["observed_source_filters"] == []
    assert not result["scope"]["reference_scope_is_source_declaration"]
    assert result["status"] == "partial"


def test_observed_scope_conflict_and_unexpected_bse_are_visible():
    value = page([row("920007")])
    value["data"]["filter"] = "BSE"
    result = inspect([value])
    assert result["scope"]["observed_source_filters"] == ["BSE"]
    assert result["scope"]["observed_outside_reference_codes"] == ["920007"]
    assert not result["schema_complete"]


@pytest.mark.parametrize("reason", [None, "", "-", "暂无", "NaN"])
def test_missing_reasons_do_not_get_filled_from_industry(reason):
    value = page([row(reason=reason)])
    value["data"]["info"][0]["industry"] = "Synthetic industry"
    result = inspect([value], expected_codes=["600519"])
    assert result["coverage"]["source_reason_codes"] == 0
    assert result["rows"][0]["derived_tags"] == []
    assert not result["schema_complete"]


def test_delimiters_alone_are_not_topic_labels():
    result = inspect([page([row(reason=" + + ")])], expected_codes=["600519"])
    assert result["coverage"]["source_topic_codes"] == 0
    assert result["coverage"]["full_market_missing_topic_codes"] == ["600519"]
    assert result["rows"][0]["source_reason_raw"] == " + + "
    assert not result["schema_complete"]


@pytest.mark.parametrize("codes", [["600519", "600519"], ["abc"], [600519]])
def test_invalid_expected_pool_is_error(codes):
    assert inspect(expected_codes=codes)["status"] == "error"


@pytest.mark.parametrize("value", [None, {}, {"status_code": 0, "data": None}, {"status_code": 0, "data": {"info": None}}])
def test_malformed_ths_payload_is_not_empty_success(value):
    assert inspect([value])["status"] == "error"


def em(**data):
    return {"rc": 0, "data": {"pool": [{"c": "600519"}], "total": 1, **data}}


def test_em_latest_quote_day_is_never_history_proof():
    for quote_day in (DAY, "20261109"):
        result = inspect_em_pool(em(qdate=quote_day), asof=DAY)
        assert result["date_evidence"] == "NOT_ESTABLISHED"
        assert result["qdate_is_requested_date_proof"] is False
        assert result["status"] == "partial"


def test_em_source_date_and_explicit_total_support_schema_only():
    value = em(date="20261106", qdate="20261109")
    before = deepcopy(value)
    result = inspect_em_pool(value, asof=DAY)
    assert value == before and result["schema_complete"]
    assert result["latest_quote_day"] == "2026-11-09"
    assert result["raw_bytes_verified"] is False
    assert result["scope"]["scope_verified"] is False


@pytest.mark.parametrize("changes", [{"total": None}, {"total": 2}, {"pool": [{"c": "600519"}, {"c": "600519"}], "total": 2}, {"pool": [{"c": 600519}]}])
def test_em_total_truncation_duplicate_and_code_validation(changes):
    assert not inspect_em_pool(em(date=DAY, **changes), asof=DAY)["schema_complete"]


def test_em_empty_pool_needs_date_and_total_and_business_success():
    assert inspect_em_pool(em(date=DAY, pool=[], total=0), asof=DAY)["schema_complete"]
    assert not inspect_em_pool(em(pool=[], total=0), asof=DAY)["schema_complete"]
    value = em(date=DAY, pool=[], total=0)
    value["rc"] = 102
    assert inspect_em_pool(value, asof=DAY)["status"] == "error"


@pytest.mark.parametrize("asof", ["20261106", "2026-02-30", None])
def test_requested_date_requires_canonical_real_calendar_date(asof):
    with pytest.raises(ValueError):
        inspect_em_pool(em(), asof=asof)
    with pytest.raises(ValueError):
        inspect_ths_pages([page()], asof=asof)
