"""Synthetic raw-byte fixtures only; no live sampling or provider verification."""

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import pytest

from research.data.market_source_candidate import inspect_market_source_candidate

DAY = "2026-11-06"
NOW = "2026-11-06T08:00:00Z"
_EM = ("getTopicZTPool", "getTopicZBPool", "getTopicDTPool", "getYesterdayZTPool")


def record(endpoint, payload, *, page=1, limit=200):
    if endpoint == "ths":
        source = "ths_limit_up_pool"
        url = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?" + urlencode(
            {"date": DAY.replace("-", ""), "page": page, "limit": limit, "filter": "HS,GEM2STAR"})
    else:
        source = "eastmoney_yesterday_zt_pool" if endpoint == _EM[3] else "eastmoney_limit_pools"
        url = f"https://push2ex.eastmoney.com/{endpoint}?" + urlencode(
            {"date": DAY.replace("-", ""), "Pageindex": 0, "pagesize": 10000})
    body = json.dumps(payload, ensure_ascii=False).encode()
    return {"source_id": source, "url": url, "http_status": 200, "fetched_at": NOW,
            "body_sha256": hashlib.sha256(body).hexdigest(), "body": body}


def em(codes=("600519", "000001"), *, source_day=DAY):
    return {"rc": 0, "synthetic": True,
            "data": {"date": source_day, "total": len(codes), "pool": [{"c": code} for code in codes]}}


def row(code="600519", *, source_day=DAY):
    timestamp = datetime.fromisoformat(source_day).replace(hour=9, tzinfo=ZoneInfo("Asia/Shanghai"))
    return {"code": code, "first_limit_up_time": int(timestamp.timestamp()),
            "reason_type": "Synthetic 题材甲+Synthetic 题材乙"}


def ths(rows=None, *, total=2):
    return {"status_code": 0, "synthetic": True,
            "data": {"info": [row(), row("000001")] if rows is None else rows,
                     "page": {"total": total}}}


def records():
    return [*[record(endpoint, em()) for endpoint in _EM], record("ths", ths())]


def inspect(items=None, **kwargs):
    return inspect_market_source_candidate(records() if items is None else items,
                                           asof=DAY, checked_at=kwargs.pop("checked_at", NOW), **kwargs)


def replace_payload(item, payload):
    item["body"] = json.dumps(payload, ensure_ascii=False).encode()
    item["body_sha256"] = hashlib.sha256(item["body"]).hexdigest()


def query(item, **changes):
    parts = urlsplit(item["url"])
    params = dict(parse_qsl(parts.query))
    for key, value in changes.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value
    item["url"] = urlunsplit(parts._replace(query=urlencode(params)))


def test_complete_private_candidate_preserves_source_and_never_promotes():
    items = records()
    before = deepcopy(items)
    result = inspect(items)
    assert items == before
    assert result["status"] == "research_candidate"
    assert result["research_candidate_complete"] and result["local_body_hashes_verified"]
    assert set(result["sources"]) == {"zt", "zb", "dt", "yesterday", "ths"}
    assert result["records"][4]["body_text"] == items[4]["body"].decode()
    assert result["sources"]["ths"]["inspection"]["rows"][0]["source_reason_raw"] == row()["reason_type"]
    assert result["sources"]["ths"]["inspection"]["coverage"]["full_market_denominator"] == 2
    for key in ("publication_eligible", "model_input_eligible", "source_authenticity_verified",
                "source_network_verified", "exchange_calendar_verified", "session_finality_verified",
                "production_snapshot_created", "public_repository_eligible"):
        assert result[key] is False
    assert result["contains_private_source_material"]
    assert result["first_public_visible_at"] is None
    json.dumps(result)  # No bytes escape into the JSON report.


def test_all_five_source_groups_required_including_yesterday():
    result = inspect(records()[:3] + records()[4:])
    assert result["status"] == "partial"
    assert "yesterday:response_missing" in result["missing"]


def test_hash_mismatch_rejects_before_decoding():
    items = records()
    items[0]["body"] += b" "
    result = inspect(items)
    assert result["status"] == "rejected" and not result["local_body_hashes_verified"]
    assert result["records"][0]["decoded_payload"] is None
    assert "body_sha256_mismatch" in result["records"][0]["errors"]


@pytest.mark.parametrize("url", [
    "http://push2ex.eastmoney.com/getTopicZTPool",
    "https://user@push2ex.eastmoney.com/getTopicZTPool",
    "https://push2ex.eastmoney.com/getTopicZTPool#fragment",
    "https://push2ex.eastmoney.com:444/getTopicZTPool",
    "https://push2ex.eastmoney.com.example.org/getTopicZTPool",
    "https://push2ex.eastmoney.com/other",
])
def test_only_exact_reviewed_https_endpoint_is_accepted(url):
    items = records()
    items[0]["url"] = url
    assert inspect(items)["status"] == "rejected"


def test_source_id_cannot_impersonate_another_endpoint():
    items = records()
    items[3]["source_id"] = "eastmoney_limit_pools"
    result = inspect(items)
    assert result["status"] == "rejected"
    assert "source_id_url_mismatch" in result["records"][3]["errors"]


@pytest.mark.parametrize("status", [302, 403, 429])
def test_non_success_http_retains_body_but_is_not_a_candidate(status):
    items = records()
    items[0]["http_status"] = status
    result = inspect(items)
    assert result["status"] == "rejected"
    assert result["records"][0]["decoded_payload"]["synthetic"] is True


@pytest.mark.parametrize("body", [b"<html>synthetic error</html>", b"[]", b"not-json",
                                  b'{"rc":1,"rc":0,"synthetic":true}',
                                  b'{"rc":0,"synthetic":true,"data":NaN}'])
def test_html_and_non_object_json_never_become_empty_success(body):
    items = records()
    items[0].update(body=body, body_sha256=hashlib.sha256(body).hexdigest())
    result = inspect(items)
    assert result["status"] == "rejected"
    assert "body_is_not_a_json_object" in result["records"][0]["errors"]


@pytest.mark.parametrize("index,field", [(0, "rc"), (4, "status_code")])
def test_business_error_is_rejected_despite_http_success(index, field):
    items = records()
    payload = json.loads(items[index]["body"])
    payload[field] = 1
    replace_payload(items[index], payload)
    assert inspect(items)["status"] == "rejected"


def test_request_date_and_qdate_do_not_prove_historical_response_date():
    items = records()
    payload = em()
    del payload["data"]["date"]
    payload["data"]["qdate"] = DAY
    replace_payload(items[0], payload)
    result = inspect(items)
    assert result["status"] == "partial"
    assert result["sources"]["zt"]["inspection"]["date_evidence"] == "NOT_ESTABLISHED"
    assert result["records"][0]["request_date_is_response_date_proof"] is False
    assert "verified_full_zt_denominator_missing" in result["sources"]["ths"]["missing"]


@pytest.mark.parametrize("source_day", ["2026-11-05", "2026-11-07"])
def test_wrong_or_future_provider_day_is_not_qualified(source_day):
    items = records()
    replace_payload(items[0], em(source_day=source_day))
    assert inspect(items)["status"] == "partial"


def test_ths_pages_are_sorted_for_inspection_but_keep_input_hash_binding():
    items = records()[:4] + [record("ths", ths([row("000001")]), page=2, limit=1),
                             record("ths", ths([row()]), page=1, limit=1)]
    result = inspect(items)
    assert result["status"] == "research_candidate"
    assert result["sources"]["ths"]["record_ordinals"] == [4, 5]
    assert result["sources"]["ths"]["inspection_record_ordinals"] == [5, 4]
    assert result["sources"]["ths"]["body_sha256s"] == [r["body_sha256"] for r in items[4:]]
    assert result["sources"]["ths"]["inspection"]["rows"][0]["code"] == "600519"
    reversed_result = inspect(items[:4] + list(reversed(items[4:])))
    assert result["record_binding_sha256"] != reversed_result["record_binding_sha256"]


@pytest.mark.parametrize("second_page", [1, 3])
def test_duplicate_or_noncontiguous_pages_fail_even_if_unique_row_counts_match(second_page):
    items = records()[:4] + [record("ths", ths([row()]), page=1, limit=1),
                             record("ths", ths([row("000001")]), page=second_page, limit=1)]
    assert inspect(items)["status"] == "rejected"


def test_duplicate_query_parameters_cannot_hide_ambiguous_page():
    items = records()
    items[4]["url"] += "&page=2"
    assert inspect(items)["status"] == "rejected"


@pytest.mark.parametrize("index,name", [(0, "Pageindex"), (4, "page")])
def test_missing_page_is_partial_and_never_assumed(index, name):
    items = records()
    query(items[index], **{name: None})
    result = inspect(items)
    assert result["status"] == "partial"
    assert result["records"][index]["page"] is None


def test_total_drift_and_millisecond_timestamps_use_existing_schema_checks():
    items = records()[:4] + [record("ths", ths([row()]), page=1, limit=1),
                             record("ths", ths([row("000001")], total=3), page=2, limit=1)]
    result = inspect(items)
    assert result["status"] == "partial"
    assert "total_changed_between_pages" in result["sources"]["ths"]["missing"]
    changed = ths()
    changed["data"]["info"][0]["first_limit_up_time"] *= 1000
    items = records()
    replace_payload(items[4], changed)
    assert inspect(items)["status"] == "partial"


def test_empty_pool_requires_response_date_not_the_request():
    items = [record(endpoint, em(())) for endpoint in _EM] + [record("ths", ths([], total=0))]
    assert inspect(items)["status"] == "partial"
    empty = ths([], total=0)
    empty["data"]["date"] = DAY
    replace_payload(items[4], empty)
    assert inspect(items)["status"] == "research_candidate"


def test_bse_gap_preserves_full_market_denominator():
    items = records()
    replace_payload(items[0], em(("600519", "000001", "920007")))
    result = inspect(items)
    observed = result["sources"]["ths"]["inspection"]
    assert result["status"] == "partial"
    assert observed["coverage"]["full_market_denominator"] == 3
    assert observed["coverage"]["reference_scope_denominator"] == 2
    assert observed["coverage"]["full_market_missing_codes"] == ["920007"]


def test_explicit_age_limit_rejects_expired_records_without_relabelling_history():
    items = records()
    later = "2026-11-08T08:00:00Z"
    assert inspect(items, checked_at=later)["status"] == "research_candidate"
    expired = inspect(items, checked_at=later, max_record_age_seconds=3600)
    assert expired["status"] == "rejected"
    for item in items:
        item["fetched_at"] = later
    result = inspect(items, checked_at=later)
    assert result["records"][0]["vintage_status"] == "retrieved_after_asof"
    assert result["first_public_visible_at"] is None


@pytest.mark.parametrize("fetched", ["2026-11-06T08:01:00Z", "2026-11-05T08:00:00Z", "2026-11-06T08:00:00"])
def test_impossible_or_timezone_naive_fetch_time_rejected(fetched):
    items = records()
    items[0]["fetched_at"] = fetched
    assert inspect(items)["status"] == "rejected"


def test_invalid_audit_controls_raise_before_inspection():
    with pytest.raises(ValueError, match="timezone"):
        inspect(checked_at="2026-11-06T08:00:00")
    with pytest.raises(ValueError, match="positive"):
        inspect(max_record_age_seconds=float("nan"))
    with pytest.raises(ValueError, match="canonical"):
        inspect_market_source_candidate([], asof="20261106", checked_at=NOW)


def test_assessment_hash_separates_inputs_from_cutoff_and_age_policy():
    baseline = inspect(max_record_age_seconds=3600)
    different_cutoff = inspect(checked_at="2026-11-06T08:01:00Z", max_record_age_seconds=3600)
    different_age = inspect(max_record_age_seconds=7200)
    unlimited = inspect()
    reports = [baseline, different_cutoff, different_age, unlimited]
    assert len({r["record_binding_sha256"] for r in reports}) == 1
    assert len({r["assessment_sha256"] for r in reports}) == 4
    assert all(r["status"] == "research_candidate" for r in reports)
    equivalent = inspect(checked_at="2026-11-06T16:00:00+08:00", max_record_age_seconds=3600.0)
    assert equivalent["assessment_sha256"] == baseline["assessment_sha256"]


@pytest.mark.parametrize("fetched", [
    "0001-01-01T00:00:00+23:59",  # Normalizing to UTC would precede year 1.
    "9999-12-31T23:59:00-23:59",  # Normalizing to UTC would exceed year 9999.
    "9999-12-31T16:00:00Z",       # UTC is valid, but conversion to Shanghai overflows.
])
def test_extreme_record_time_is_rejected_without_aborting_other_records(fetched):
    items = records()
    items[0]["fetched_at"] = fetched
    result = inspect(items)
    assert result["status"] == "rejected"
    assert result["records"][0]["vintage_status"] == "NOT_ESTABLISHED"
    assert result["records"][0]["errors"]
    assert result["sources"]["yesterday"]["status"] == "research_candidate"
    assert len(result["assessment_sha256"]) == 64


@pytest.mark.parametrize("checked", [
    "0001-01-01T00:00:00+23:59",
    "9999-12-31T23:59:00-23:59",
    "9999-12-31T16:00:00Z",
])
def test_extreme_audit_cutoff_has_clear_value_error(checked):
    with pytest.raises(ValueError, match="checked_at"):
        inspect(checked_at=checked)


def test_arbitrarily_large_age_limit_has_clear_value_error():
    with pytest.raises(ValueError, match="max_record_age_seconds"):
        inspect(max_record_age_seconds=10**1000)
