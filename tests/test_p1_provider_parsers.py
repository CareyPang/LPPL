"""Synthetic contract fixtures; these are not real market snapshots."""

import copy
import math

import pytest

from research.data.p1_provider_parsers import parse_provider_payload

ASOF = "2026-11-09"


def test_unlock_preserves_vibe_documented_fields_without_guessing_units():
    response = {"success": True, "result": {"pages": 1, "count": 1, "data": [{
        "SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "示例", "FREE_DATE": "2026-12-01",
        "FREE_SHARES_TYPE": "限售股份", "ABLE_FREE_SHARES": "123.5", "TOTAL_RATIO": "0.02",
    }]}}
    section = parse_provider_payload("eastmoney_lockup_expiry", response, asof=ASOF)
    assert section["rows"][0]["type"] == "限售股份"
    assert section["rows"][0]["provider_reported_fields"]["ABLE_FREE_SHARES"] == "123.5"
    assert section["metadata"]["units"]["provider_reported_fields"] == "unverified_preserve_raw"
FUND = "eastmoney_fund_flow_history"
DRAGON = "eastmoney_dragon_tiger"
LOCKUP = "eastmoney_lockup_expiry"


def fund(*rows):
    return {"rc": 0, "data": {"code": "600519", "klines": list(rows)}}


def table(*rows, pages=1, count=None):
    return {"success": True, "code": 0, "result": {
        "data": list(rows), "pages": pages,
        "count": len(rows) if count is None else count,
    }}


def dragon(**overrides):
    return {"TRADE_DATE": ASOF + " 00:00:00", "SECURITY_CODE": "600519",
            "SECURITY_NAME_ABBR": "Synthetic", "BILLBOARD_NET_AMT": "123.5",
            "TURNOVERRATE": "2.5", "EXPLANATION": "Synthetic reason", **overrides}


def lockup(**overrides):
    return {"FREE_DATE": "2026-12-01 00:00:00", "SECURITY_CODE": "600519",
            "SECURITY_NAME_ABBR": "Synthetic", "FREE_SHARES_NUM": "10万股",
            "FREE_RATIO": "2.5%", **overrides}


def test_fund_fields_units_missing_and_no_mutation():
    payload = fund(f"{ASOF},100,-20,-30,40,60,1.5")
    before = copy.deepcopy(payload)
    result = parse_provider_payload(FUND, payload, asof=ASOF, subject="sh600519")
    assert payload == before
    assert result["valid"] and result["status"] == "fresh"
    row = result["rows"][0]
    assert row["main_net"] == 100 and row["small_net"] == -20
    assert row["large_net"] == 40 and row["super_net"] == 60
    assert row["main_pct"] == 1.5 and row["close"] is None
    assert result["metadata"]["units"]["main_net"] == "CNY"
    assert result["metadata"]["units"]["main_pct"] == "percent"
    assert result["metadata"]["pit_status"] == "NOT_ESTABLISHED"


def test_extended_fund_layout_is_explicit():
    result = parse_provider_payload(FUND, fund(f"{ASOF},1,2,3,4,5,6,7,8,9,10,11,12,opaque,last"),
                                    asof=ASOF, subject="sh600519")
    row = result["rows"][0]
    assert row["close"] == 11 and row["pct_chg"] == 12
    assert row["uninterpreted_provider_fields"] == {"f64": "opaque", "f65": "last"}


def test_future_fund_rows_never_enter_requested_history():
    result = parse_provider_payload(FUND, fund("2026-11-10,100,2,3,4,5,6", f"{ASOF},7,2,3,4,5,6"),
                                    asof=ASOF, subject="sh600519")
    assert [r["date"] for r in result["rows"]] == [ASOF]
    assert result["metadata"]["filtered_rows"] == 1
    assert result["metadata"]["rejected_rows"] == 0


def test_missing_history_does_not_imply_zero_or_complete_coverage():
    result = parse_provider_payload(FUND, fund(f"{ASOF},-,2,3,4,5,--"), asof=ASOF, subject="sh600519")
    assert result["rows"][0]["main_net"] is None
    assert result["status"] == "partial"
    assert result["metadata"]["coverage_status"] == "returned_rolling_window_only"
    future = parse_provider_payload(FUND, fund("2026-11-10,1,2,3,4,5,6"), asof=ASOF, subject="sh600519")
    assert future["status"] == "not_available" and not future["valid"]
    assert not future["metadata"]["empty_response"]


@pytest.mark.parametrize("subject", [None, "600519", "SH600519", "sz600519", "sh000001", "sh60051", True, "xx600519"])
def test_fund_subject_is_required_canonical_a_share(subject):
    with pytest.raises(ValueError):
        parse_provider_payload(FUND, fund(), asof=ASOF, subject=subject)


@pytest.mark.parametrize("asof", [None, True, "20261109", "2026-02-30", "2026-1-01", "2026-11-09T00:00:00"])
def test_invalid_caller_dates_raise(asof):
    with pytest.raises(ValueError):
        parse_provider_payload(DRAGON, table(), asof=asof)


@pytest.mark.parametrize("payload,status", [(None, "schema_changed"), ({}, "schema_changed"),
    ({"result": None}, "not_available"), ({"result": {}}, "schema_changed"),
    ({"result": {"data": None}}, "not_available"), ({"result": {"data": {}}}, "schema_changed"),
    ({"success": False}, "error"), ({"code": 403}, "error"), ({"code": False}, "schema_changed"),
    ({"success": "true"}, "schema_changed")])
def test_missing_malformed_and_provider_errors_are_not_empty_success(payload, status):
    result = parse_provider_payload(DRAGON, payload, asof=ASOF)
    assert result["status"] == status and result["valid"] is False
    assert result["rows"] == []


def test_known_empty_preserves_distinction_from_missing():
    result = parse_provider_payload(DRAGON, table(), asof=ASOF)
    assert result["status"] == "fresh" and result["valid"]
    assert result["metadata"]["empty_response"] and result["metadata"]["is_complete"]


def test_dragon_only_target_day_and_subject_no_dedup_of_distinct_reasons():
    result = parse_provider_payload(DRAGON, table(
        dragon(), dragon(EXPLANATION="Second reason"), dragon(TRADE_DATE="2026-11-08"),
        dragon(TRADE_DATE="2026-11-10"), dragon(SECURITY_CODE="000001")),
        asof=ASOF, subject="sh600519")
    assert len(result["rows"]) == 2
    assert result["metadata"]["filtered_rows"] == 3
    assert result["rows"][0]["net_buy"] == 123.5
    assert result["rows"][0]["buy_amount"] is None
    assert result["rows"][0]["turnover_pct"] == 2.5


@pytest.mark.parametrize("value", [True, False, "NaN", "Infinity", float("inf"), math.nan, {}, [], "1,000", "2%", "1e9999"])
def test_financial_numbers_are_strict(value):
    result = parse_provider_payload(DRAGON, table(dragon(BILLBOARD_NET_AMT=value)), asof=ASOF)
    assert not result["valid"] and result["status"] == "schema_changed"
    assert result["metadata"]["rejected_rows"] == 1


@pytest.mark.parametrize("code", [600519, True, "60051", "600519.SH", "100001"])
def test_provider_security_code_not_coerced(code):
    result = parse_provider_payload(DRAGON, table(dragon(SECURITY_CODE=code)), asof=ASOF)
    assert not result["valid"]


def test_bj_and_sz_exchange_preserved():
    result = parse_provider_payload(DRAGON, table(dragon(SECURITY_CODE="920001"), dragon(SECURITY_CODE="300001")), asof=ASOF)
    assert {r["symbol"] for r in result["rows"]} == {"bj920001", "sz300001"}


def test_partial_page_is_not_complete_or_no_events_claim():
    result = parse_provider_payload(DRAGON, table(dragon(), pages=3, count=50), asof=ASOF)
    assert result["status"] == "partial" and result["valid"]
    assert result["metadata"]["pagination"] == {"pages": 3, "count": 50}
    assert not result["metadata"]["is_complete"]
    empty = parse_provider_payload(DRAGON, table(pages=2, count=10), asof=ASOF)
    assert empty["status"] == "partial"


@pytest.mark.parametrize("pages,count", [(True, 1), (1, False), (-1, 1), (1, "1"), (0, 1), (1, 0)])
def test_malformed_pagination_is_explicit(pages, count):
    result = parse_provider_payload(DRAGON, table(dragon(), pages=pages, count=count), asof=ASOF)
    assert result["status"] == "schema_changed" and not result["valid"]


def test_pagination_metadata_missing_is_partial():
    result = parse_provider_payload(DRAGON, {"result": {"data": [dragon()]}}, asof=ASOF)
    assert result["status"] == "partial"
    assert result["stale_reason"] == "pagination_metadata_missing"


def test_valid_rows_survive_malformed_row_but_not_as_fresh():
    result = parse_provider_payload(DRAGON, table(dragon(), "unexpected"), asof=ASOF)
    assert result["status"] == "partial" and result["valid"]
    assert len(result["rows"]) == 1 and not result["metadata"]["is_complete"]


def test_lockup_event_date_distinct_from_snapshot_and_no_pit_claim():
    result = parse_provider_payload(LOCKUP, table(lockup()), asof=ASOF)
    row = result["rows"][0]
    assert row["event_date"] == "2026-12-01" and row["snapshot_asof"] == ASOF
    assert row["provider_reported_fields"]["FREE_SHARES_NUM"] == "10万股"
    assert row["provider_reported_fields"]["FREE_RATIO"] == "2.5%"
    assert row["provider_reported_fields"]["CURRENT_FREE_SHARES"] is None
    assert not result["metadata"]["event_date_is_knowledge_date"]
    assert not result["metadata"]["historical_replay_eligible"]
    assert result["metadata"]["source_reported_asof"] is None
    assert result["metadata"]["historical_snapshot_requires_archive_gate"]


def test_lockup_horizon_is_inclusive_calendar_days_and_excludes_past():
    result = parse_provider_payload(LOCKUP, table(lockup(FREE_DATE="2026-11-08"), lockup(FREE_DATE=ASOF),
        lockup(FREE_DATE="2027-02-07"), lockup(FREE_DATE="2027-02-08")), asof=ASOF)
    assert [r["event_date"] for r in result["rows"]] == [ASOF, "2027-02-07"]
    assert result["metadata"]["filtered_rows"] == 2


@pytest.mark.parametrize("value", [True, float("nan"), "NaN", "Inf", "1e9999", {}, []])
def test_lockup_unverified_fields_still_reject_invalid_types(value):
    result = parse_provider_payload(LOCKUP, table(lockup(FREE_RATIO=value)), asof=ASOF)
    assert not result["valid"]


def test_fund_unknown_layout_duplicates_mismatch_and_stale_cutoff():
    bad = parse_provider_payload(FUND, fund(f"{ASOF},1,2"), asof=ASOF, subject="sh600519")
    assert not bad["valid"]
    dup = parse_provider_payload(FUND, fund(f"{ASOF},1,2,3,4,5,6", f"{ASOF},2,2,3,4,5,6"),
                                 asof=ASOF, subject="sh600519")
    assert dup["status"] == "partial" and len(dup["rows"]) == 1
    mismatch = parse_provider_payload(FUND, fund(), asof=ASOF, subject="sz000001")
    assert not mismatch["valid"]
    stale = parse_provider_payload(FUND, fund("2026-11-06,1,2,3,4,5,6"), asof=ASOF, subject="sh600519")
    assert stale["status"] == "partial"
    assert "calendar_unverified" in stale["stale_reason"]


def test_unknown_source_rejected():
    with pytest.raises(ValueError):
        parse_provider_payload("random", {}, asof=ASOF)


def test_missing_subject_in_payload_is_not_confirmed():
    result = parse_provider_payload(FUND, {"data": {"klines": [f"{ASOF},1,2,3,4,5,6"]}},
                                    asof=ASOF, subject="sh600519")
    assert result["status"] == "partial"
    assert "payload_subject_not_confirmed" in result["stale_reason"]


def test_extreme_date_does_not_overflow():
    with pytest.raises(ValueError):
        parse_provider_payload(LOCKUP, table(), asof="9999-12-31")
    assert parse_provider_payload(DRAGON, table(), asof="9999-12-31")["valid"]


def test_optional_pagination_metadata_is_preserved_and_validated():
    payload = table(dragon())
    payload["result"].update(pageNumber=1, pageSize=50)
    result = parse_provider_payload(DRAGON, payload, asof=ASOF)
    assert result["metadata"]["pagination"]["pageNumber"] == 1
    payload["result"]["pageNumber"] = True
    assert not parse_provider_payload(DRAGON, payload, asof=ASOF)["valid"]
