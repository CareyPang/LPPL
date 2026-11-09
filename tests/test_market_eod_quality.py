"""Synthetic EOD quality fixtures, never real market snapshots."""

from copy import deepcopy

import pytest

from research.data.market_eod_quality import assess_eod_payload

DAY = "2026-11-06"
PRIOR = "2026-11-05"


def receipt(day, total):
    return {"status": "fresh", "asof": day, "asof_status": "source_verified", "raw_sha256": "a" * 64,
            "coverage": {"status": "complete", "declared_total": total, "pages_expected": 1, "pages_received": 1}}


def payload(day=DAY, *, prior=PRIOR):
    rows = [{"code": "000001", "streak": 2 if day == DAY else 1}, {"code": "600519", "streak": 1}]
    return {"asof": day,
            "calendar": {"calendar_status": "provided", "asof_status": "exchange_verified", "prior_status": "exchange_verified",
                         "prior_asof": prior, "calendar_source_sha256": "b" * 64},
            "limit_pools": {"date": day.replace("-", ""), "zt": 2, "zb": 0, "dt": 0,
                "pool_rows": {"zt": rows, "zb": [], "dt": []},
                "pool_sources": {key: receipt(day, 2 if key == "zt" else 0) for key in ("zt", "zb", "dt")},
                "reasons": {"status": "fresh", "asof": day, "source": receipt(day, 2),
                            "rows": [{"code": row["code"], "reason": "Synthetic reason"} for row in rows]},
                "topics": {"status": "fresh", "asof": day, "source": receipt(day, 2),
                           "rows": [{"code": row["code"], "topic_label": "Synthetic topic"} for row in rows]}}}


def assess(value=None, **kwargs):
    return assess_eod_payload(payload() if value is None else value, asof=DAY, **kwargs)


def test_complete_receipts_separate_structure_evidence_and_no_mutation():
    value = payload()
    before = deepcopy(value)
    result = assess(value)
    assert value == before
    assert result["status"] == "ready" and result["core_complete"]
    assert result["pools"]["zt"]["structurally_complete"] and result["pools"]["zt"]["verified_complete"]
    assert not result["pools"]["zt"]["raw_bytes_verified"]
    assert not result["publication_eligible"] and not result["model_input_eligible"]
    assert result["labels"]["reasons"]["matched_count"] == 2


def test_legacy_real_shape_can_be_structurally_complete_without_source_proof():
    value = payload()
    del value["limit_pools"]["pool_sources"]
    value["sources"] = {"limit_pools": {"ok": True, "url_host": "push2ex.eastmoney.com", "fetched_at": "2026-11-07T17:00:00Z"}}
    result = assess(value)
    assert result["structurally_complete"] and not result["core_complete"]
    assert result["pools"]["zt"]["source_date_status"] == "NOT_ESTABLISHED"
    assert result["pools"]["zt"]["coverage_status"] == "NOT_ESTABLISHED"
    assert result["status"] == "partial"


def test_top20_is_never_full_pool():
    value = payload()
    value["limit_pools"]["top20"] = value["limit_pools"].pop("pool_rows")
    result = assess(value)
    assert not result["structurally_complete"]
    assert "full_pool_rows_missing_top20_is_not_complete" in result["pools"]["zt"]["reasons"]


@pytest.mark.parametrize("total", [1, 3, -1, True, "2", None, 2.0])
def test_declared_totals_must_equal_complete_rows_as_integers(total):
    value = payload()
    value["limit_pools"]["zt"] = total
    result = assess(value)
    assert not result["pools"]["zt"]["structurally_complete"]


def test_duplicate_and_invalid_codes_do_not_enter_population():
    value = payload()
    value["limit_pools"]["pool_rows"]["zt"][1]["code"] = "000001"
    result = assess(value)
    assert result["pools"]["zt"]["duplicate_codes"] == ["000001"]
    assert not result["pools"]["zt"]["verified_complete"]
    for code in (1, "sh600519", "60051", "100001", True):
        value["limit_pools"]["pool_rows"]["zt"][1]["code"] = code
        assert not assess(value)["pools"]["zt"]["structurally_complete"]


@pytest.mark.parametrize("streak", [None, 0, -1, 2.0, "2", True])
def test_limit_streak_requires_positive_integer(streak):
    value = payload()
    value["limit_pools"]["pool_rows"]["zt"][0]["streak"] = streak
    assert not assess(value)["pools"]["zt"]["structurally_complete"]


def test_zero_total_is_known_empty_only_with_date_and_coverage_receipts():
    value = payload()
    value["limit_pools"]["zt"] = 0
    value["limit_pools"]["pool_rows"]["zt"] = []
    value["limit_pools"]["pool_sources"]["zt"] = receipt(DAY, 0)
    for key in ("reasons", "topics"):
        value["limit_pools"][key]["rows"] = []
    result = assess(value)
    assert result["pools"]["zt"]["verified_complete"]
    assert result["labels"]["reasons"]["known_empty"]
    assert result["labels"]["reasons"]["coverage_ratio"] is None
    del value["limit_pools"]["pool_sources"]["zt"]["coverage"]
    assert assess(value)["pools"]["zt"]["status"] == "partial"


def test_cross_day_snapshot_pool_source_and_row_are_detected_separately():
    value = payload()
    value["asof"] = PRIOR
    assert assess(value)["status"] == "error"
    value = payload()
    value["limit_pools"]["date"] = "20261105"
    assert not assess(value)["pools"]["zt"]["structurally_complete"]
    value = payload()
    value["limit_pools"]["pool_sources"]["zt"]["asof"] = PRIOR
    result = assess(value)["pools"]["zt"]
    assert result["structurally_complete"] and result["source_date_status"] == "MISMATCH"
    value = payload()
    value["limit_pools"]["pool_rows"]["zt"][0]["date"] = PRIOR
    assert not assess(value)["pools"]["zt"]["structurally_complete"]


def test_request_date_alone_is_not_verified_provider_date():
    value = payload()
    value["limit_pools"]["pool_sources"]["zt"].pop("asof_status")
    result = assess(value)["pools"]["zt"]
    assert result["source_date_status"] == "NOT_ESTABLISHED"
    assert not result["verified_complete"]


@pytest.mark.parametrize("change", [{"pages_received": 0}, {"pages_received": True}, {"pages_expected": 0},
    {"declared_total": 999}, {"status": "partial"}, {"pages_received": 2}])
def test_pagination_and_reported_counts_are_not_assumed(change):
    value = payload()
    value["limit_pools"]["pool_sources"]["zt"]["coverage"].update(change)
    assert not assess(value)["pools"]["zt"]["verified_complete"]


def test_failed_source_cannot_be_complete_even_with_old_rows():
    value = payload()
    value["limit_pools"]["pool_sources"]["zt"]["status"] = "error"
    result = assess(value)["pools"]["zt"]
    assert result["structurally_complete"] and not result["verified_complete"]


def test_broken_board_zero_stat_is_not_a_positive_limit_up_streak():
    value = payload()
    value["limit_pools"]["zb"] = 1
    value["limit_pools"]["pool_rows"]["zb"] = [{"code": "000002", "streak": 0}]
    value["limit_pools"]["pool_sources"]["zb"] = receipt(DAY, 1)
    assert assess(value)["pools"]["zb"]["verified_complete"]


def test_contradictory_source_success_flags_never_certify_a_pool():
    value = payload()
    value["limit_pools"]["pool_sources"]["zt"]["ok"] = False
    result = assess(value)["pools"]["zt"]
    assert not result["verified_complete"]
    assert "contradictory_source_success_flags" in result["reasons"]


def test_missing_reasons_does_not_invalidate_complete_pool_but_remains_explicit():
    value = payload()
    value["limit_pools"].pop("reasons")
    value["limit_pools"]["topics"]["rows"] = [{"code": "000001", "topic_label": "Synthetic"}]
    result = assess(value)
    assert result["core_complete"] and result["status"] == "partial"
    assert result["labels"]["reasons"]["status"] == "not_available"
    assert result["labels"]["reasons"]["missing_count"] == 2
    assert result["labels"]["topics"]["matched_count"] == 1
    assert result["labels"]["topics"]["missing_codes"] == ["600519"]
    assert result["labels"]["topics"]["coverage_ratio"] == 0.5


def test_wrong_day_extra_and_duplicate_topic_rows_do_not_inflate_coverage():
    value = payload()
    value["limit_pools"]["reasons"]["asof"] = PRIOR
    value["limit_pools"]["topics"]["rows"] = [{"code": "000001", "topic_label": "A"}, {"code": "000001", "topic_label": "B"}, {"code": "000002", "topic_label": "C"}]
    result = assess(value)
    assert result["labels"]["reasons"]["matched_count"] == 0
    assert result["labels"]["topics"]["matched_count"] == 1
    assert result["labels"]["topics"]["extra_codes"] == ["000002"]


def test_progression_requires_verified_complete_pair_and_keeps_legacy_result():
    current, previous = payload(), payload(PRIOR, prior="2026-11-04")
    current["history"] = {"progression": {"status": "fresh", "rows": [{"rate": 0.99}]}}
    before = deepcopy(current)
    result = assess(current, prior_payload=previous, prior_asof=PRIOR)
    assert current == before
    assert result["progression"]["status"] == "fresh"
    assert result["progression"]["rows"][0]["eligible_count"] == 2
    assert result["progression"]["rows"][0]["advanced_count"] == 1
    assert result["progression"]["rows"][0]["rate"] == 0.5
    current["limit_pools"]["zt"] = 100
    assert assess(current, prior_payload=previous, prior_asof=PRIOR)["progression"]["status"] == "not_available"


@pytest.mark.parametrize("which,field,value", [
    ("current", "prior_status", "not_available"), ("current", "prior_asof", "2026-11-04"),
    ("current", "calendar_source_sha256", None), ("prior", "asof_status", "weekday_estimate"),
    ("prior", "calendar_source_sha256", "c" * 64)])
def test_progression_requires_caller_verified_adjacent_calendar(which, field, value):
    current, previous = payload(), payload(PRIOR)
    (current if which == "current" else previous)["calendar"][field] = value
    assert assess(current, prior_payload=previous, prior_asof=PRIOR)["progression"]["status"] == "not_available"


def test_legacy_source_without_proof_cannot_be_promoted_by_calendar():
    previous = payload(PRIOR)
    del previous["limit_pools"]["pool_sources"]
    result = assess(prior_payload=previous, prior_asof=PRIOR)
    assert result["progression"]["status"] == "not_available"
    assert "prior_zt_pool_not_verified_complete" in result["progression"]["reasons"]


def test_inconsistent_streak_jump_does_not_count_as_advance():
    current = payload()
    current["limit_pools"]["pool_rows"]["zt"][0]["streak"] = 5
    result = assess(current, prior_payload=payload(PRIOR), prior_asof=PRIOR)
    assert result["progression"]["status"] == "not_available" and not result["progression"]["rows"]


def test_invalid_inputs_and_empty_payload_remain_honest():
    for day in (None, True, "20261106", "2026-02-30"):
        with pytest.raises(ValueError):
            assess_eod_payload({}, asof=day)
    result = assess_eod_payload(None, asof=DAY)
    assert result["status"] == "error" and not result["core_complete"]


def test_malformed_label_status_is_reported_not_a_type_error():
    value = payload()
    value["limit_pools"]["topics"]["status"] = []
    result = assess(value)
    assert result["labels"]["topics"]["status"] == "not_available"
    assert result["labels"]["topics"]["matched_count"] == 0
