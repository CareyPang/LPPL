"""Offline synthetic pipeline tests; never fetch market data or run models."""

import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import requests

from research.data import market_eod_pipeline as pipeline
from research.data.market_eod_archive import EODArchive, digest
from research.data.market_p1 import THS_LIMIT_UP_URL
from tests.test_market_source_validation import rewrite_bundle, write_policy_fixture

DAY = "2026-11-06"
PRIOR = "2026-11-05"
NOW = "2026-11-06T08:00:00Z"  # 16:00 China, after the 15:30 gate.


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("test attempted a real network request")
    monkeypatch.setattr(requests.Session, "request", forbidden)


@pytest.fixture
def archive(tmp_path):
    return EODArchive(tmp_path / "archive.sqlite")


@pytest.fixture
def calendar_path(tmp_path):
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps({"dates": ["2026-11-04", PRIOR, DAY, "2026-11-09", "2026-11-10"],
        "version": "synthetic-exchange-v1", "source_url": "https://example.test/calendar",
        "source_sha256": "b" * 64, "verification_status": "exchange_verified",
        "coverage_start": "2026-11-01", "coverage_end": "2026-11-10"}), encoding="utf-8")
    return path


@pytest.fixture
def policy_path(tmp_path):
    return write_policy_fixture(tmp_path / "source-policy")


def fake_collector(day, archive, run_id, policy):
    """Produce normalized synthetic rows plus the exact corresponding raw bytes."""
    fetched = f"{day}T07:30:00Z"
    rows = [{"code": "000001", "streak": 2 if day == DAY else 1}, {"code": "600519", "streak": 1}]
    records = []
    for kind, endpoint, _ in pipeline.LIMIT_POOLS:
        members = rows if kind == "zt" else []
        raw = json.dumps({"rc": 0, "data": {"date": day.replace("-", ""), "total": len(members),
                        "pool": [{"c": row["code"], "lbc": row["streak"]} for row in members]}}, sort_keys=True).encode()
        url = "https://push2ex.eastmoney.com/" + endpoint + "?date=" + day.replace("-", "") + "&Pageindex=0&pagesize=10000"
        sha = archive.response(run_id, source_id="eastmoney_limit_pools", url=url, raw=raw, http_status=200, fetched_at=fetched)
        records.append({"source_id": "eastmoney_limit_pools", "url": url, "raw": raw, "raw_sha256": sha,
                        "http_status": 200, "fetched_at": fetched})
    yesterday_rows = [{"code": row["code"], "name": "Synthetic", "pct": 0.0,
                       "turnover": 1.25, "amplitude": 3.0, "speed": -0.2,
                       "y_first_seal": 93000, "y_limit_days": 1, "industry": "Synthetic industry",
                       "zt_stat": {"days": 1, "count": 1}} for row in rows]
    raw_yesterday = json.dumps({"rc": 0, "data": {"date": day.replace("-", ""), "total": len(yesterday_rows),
        "pool": [{"c": row["code"], "n": "Synthetic", "zdp": 0.0, "hs": 1.25, "zf": 3.0, "zs": -0.2,
                  "yfbt": 93000, "ylbc": 1, "hybk": "Synthetic industry", "zttj": {"days": 1, "ct": 1}}
                 for row in yesterday_rows]}}).encode()
    yesterday_url = "https://push2ex.eastmoney.com/getYesterdayZTPool?date=" + day.replace("-", "") + "&Pageindex=0&pagesize=10000"
    sha_yesterday = archive.response(run_id, source_id=pipeline.YESTERDAY_SOURCE, url=yesterday_url,
                                     raw=raw_yesterday, http_status=200, fetched_at=fetched)
    records.append({"source_id": pipeline.YESTERDAY_SOURCE, "url": yesterday_url, "raw": raw_yesterday,
                    "raw_sha256": sha_yesterday, "http_status": 200, "fetched_at": fetched})
    proof = pipeline.pool_source_proof(records, day)
    raw_ths = json.dumps({"data": {"date": day, "info": [{"code": row["code"], "reason_type": "Synthetic"} for row in rows]}}).encode()
    sha_ths = archive.response(run_id, source_id="ths_limit_up_pool", url=THS_LIMIT_UP_URL,
                               raw=raw_ths, http_status=200, fetched_at=fetched)
    ths_source = {"source_id": "ths_limit_up_pool", "source_url": THS_LIMIT_UP_URL,
                  "asof": day, "asof_status": "source_verified", "status": "fresh", "ok": True,
                  "fetched_at": fetched, "raw_sha256": sha_ths}
    return {"asof": day, "generated_at": fetched, "sources": {"ths_limit_up_pool": ths_source},
            "limit_pools": {"date": day, "zt": len(rows), "zb": 0, "dt": 0,
                "pool_rows": {"zt": rows, "zb": [], "dt": []},
                "pool_sources": proof,
                "yesterday_performance": {"asof": day, "window": "t-1_to_t", "status": "fresh",
                    "declared_count": len(yesterday_rows), "rows": yesterday_rows,
                    "source": deepcopy(proof[pipeline.YESTERDAY_POOL])},
                "reasons": {"asof": day, "status": "fresh", "source": deepcopy(ths_source),
                            "rows": [{"code": row["code"], "reason": "Synthetic"} for row in rows]},
                "topics": {"asof": day, "status": "fresh", "source": deepcopy(ths_source),
                           "rows": [{"code": row["code"], "topic_label": "Synthetic"} for row in rows]}}}


def run(archive, calendar_path, policy_path=None, **kwargs):
    args = {"archive": archive, "calendar_path": calendar_path, "policy_path": policy_path,
            "asof": DAY, "now": NOW, "run_id": "synthetic_run_001", "collector": fake_collector}
    args.update(kwargs)
    return pipeline.run_eod(**args)


def test_first_capture_preserves_exact_raw_bytes_but_requires_prior_for_sealing(archive, calendar_path, policy_path):
    receipt = run(archive, calendar_path, policy_path)
    assert receipt["status"] == "partial"
    assert archive.report()["raw_response_count"] == 5
    value = archive.best(DAY)["snapshot"]
    assert value["daily_capture"]["quality"]["core_complete"] is True
    assert value["daily_capture"]["quality"]["four_pool_complete"] is False
    assert value["daily_capture"]["raw_verification"] == {"zt": True, "zb": True, "dt": True,
                                                         "yesterday_performance": True, "reasons_topics": True}
    assert value["publication_eligible"] is False and value["model_input_eligible"] is False
    assert value["daily_capture"]["first_public_visible_at"] is None
    assert value["history"]["progression"]["status"] == "not_available"


def test_offline_import_does_not_call_collector_or_network(archive, calendar_path, tmp_path):
    item = {"asof": DAY, "sources": {}, "limit_pools": {}, "history": {"progression": {"status": "fresh", "rows": [{"rate": 1}]}}}
    path = tmp_path / "preserved.json"
    raw = json.dumps(item).encode()
    path.write_bytes(raw)
    def forbidden(*args):
        raise AssertionError("offline import invoked collector")
    receipt = run(archive, calendar_path, input_path=path, collector=forbidden)
    assert receipt["status"] == "partial" and receipt["mode"] == "historical_import"
    assert archive.report()["raw_response_count"] == 0
    stored = archive.best(DAY)["snapshot"]
    assert stored["run_mode"] == "research_import"
    assert stored["daily_capture"]["import_provenance"]["input_file_sha256"] == digest(raw)
    assert stored["daily_capture"]["legacy_progression"] == item["history"]["progression"]
    assert stored["history"]["progression"]["status"] == "not_available"
    assert path.read_bytes() == raw


def test_policy_is_required_before_any_capture(archive, calendar_path):
    def forbidden(*args):
        raise AssertionError("collector must not run without policy")
    result = run(archive, calendar_path, collector=forbidden)
    assert result["status"] == "failed" and result["detail"]["reason"] == "SOURCE_VALIDATION_BLOCKED"
    assert {item["reason"] for item in result["detail"]["source_validation"]["missing"]} >= {"SOURCE_POLICY_REQUIRED"}
    assert archive.report()["raw_response_count"] == 0 and not archive.report()["revisions"]


@pytest.mark.parametrize("change", [{"fetch_enabled": False}, {"min_interval_seconds": True}, {"min_interval_seconds": 0}])
def test_unreviewed_policy_is_a_durable_failure(archive, calendar_path, policy_path, change):
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["sources"]["eastmoney_limit_pools"].update(change)
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    result = run(archive, calendar_path, policy_path)
    assert result["status"] == "failed"
    assert archive.report()["runs"][0] == result and not archive.report()["revisions"]


@pytest.mark.parametrize("claim", ["automated_access", "raw_retention", "frequency", "mainland_network"])
def test_each_unverified_source_review_prevents_even_a_custom_collector(
    archive, calendar_path, policy_path, claim,
):
    rewrite_bundle(policy_path, lambda bundle: bundle["sources"]["eastmoney_limit_pools"][claim].update({"status": "pending"}))
    def forbidden(*args):
        raise AssertionError("collector ran before source review completed")
    result = run(archive, calendar_path, policy_path, collector=forbidden)
    assert result["status"] == "failed"
    report = result["detail"]["source_validation"]
    assert report["allowed"] is False and report["sources"]["eastmoney_limit_pools"]["blocked"]
    assert archive.report()["raw_response_count"] == 0 and not archive.report()["revisions"]


def test_verified_strings_without_bundle_do_not_reach_capture(archive, calendar_path, tmp_path):
    policy = tmp_path / "old-policy.json"
    policy.write_text(json.dumps({"schema_version": "market-eod-fetch-policy.v1", "sources": {
        key: {"fetch_enabled": True, "research_access_review": "verified", "evidence_refs": ["verified"],
              "min_interval_seconds": 1} for key in pipeline.REQUIRED_FETCH_SOURCES}}), encoding="utf-8")
    result = run(archive, calendar_path, policy)
    assert result["status"] == "failed" and result["detail"]["source_validation"]["allowed"] is False
    assert archive.report()["raw_response_count"] == 0


def test_checked_in_policy_blocks_real_capture_before_any_collector(archive, calendar_path):
    policy_path = Path(__file__).resolve().parents[1] / "research/data/market_eod_fetch_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    bundle = json.loads((policy_path.parent / policy["validation_bundle"]["path"]).read_text(encoding="utf-8"))
    def forbidden(*args):
        raise AssertionError("real checked-in policy permitted a collector")
    result = run(archive, calendar_path, policy_path, collector=forbidden, now=bundle["reviewed_at"])
    assert result["status"] == "failed" and result["detail"]["source_validation"]["allowed"] is False
    assert archive.report()["raw_response_count"] == 0


@pytest.mark.parametrize("change,expected", [
    ({"verification_status": "NOT_ESTABLISHED"}, "verification_status"),
    ({"source_sha256": "bad"}, "source_sha256"),
    ({"coverage_end": "2026-11-05"}, "CALENDAR_COVERAGE"),
    ({"coverage_start": "2026-11-09"}, "CALENDAR_COVERAGE"),
])
def test_calendar_failure_is_recorded_before_collection(archive, calendar_path, policy_path, change, expected):
    calendar = json.loads(calendar_path.read_text(encoding="utf-8"))
    calendar.update(change)
    calendar_path.write_text(json.dumps(calendar), encoding="utf-8")
    result = run(archive, calendar_path, policy_path)
    assert result["status"] == "failed" and expected in result["detail"]["reason"]
    assert archive.report()["raw_response_count"] == 0


@pytest.mark.parametrize("asof,now,reason", [
    ("2026-11-07", "2026-11-07T08:00:00Z", "NOT_A_VERIFIED_TRADING_DAY"),
    (DAY, "2026-11-06T07:29:59Z", "EOD_NOT_CLOSED"),
    ("2026-11-09", NOW, "EOD_NOT_CLOSED"),
])
def test_holiday_preclose_and_future_dates_skip_without_collection(archive, calendar_path, policy_path, asof, now, reason):
    result = run(archive, calendar_path, policy_path, asof=asof, now=now)
    assert result["status"] == "skipped" and result["detail"]["reason"] == reason
    assert archive.report()["raw_response_count"] == 0 and not archive.report()["revisions"]


def test_exact_1530_china_boundary_is_closed(archive, calendar_path, policy_path):
    assert run(archive, calendar_path, policy_path, now="2026-11-06T07:30:00Z")["status"] == "partial"
    assert archive.report()["raw_response_count"] == 5


def test_payload_source_date_mismatch_has_failure_receipt(archive, calendar_path, policy_path):
    def mismatched(day, journal, run_id, policy):
        result = fake_collector(day, journal, run_id, policy)
        result["asof"] = PRIOR
        return result
    result = run(archive, calendar_path, policy_path, collector=mismatched)
    assert result["status"] == "failed" and result["detail"]["reason"] == "SOURCE_ASOF_MISMATCH"
    assert archive.report()["raw_response_count"] == 5
    assert not archive.report()["revisions"]


def record(data, *, request_day=DAY, code=200):
    raw = json.dumps({"data": data}).encode()
    endpoint = pipeline.LIMIT_POOLS[0][1]
    return {"url": f"https://push2ex.eastmoney.com/{endpoint}?date={request_day.replace('-', '')}",
            "raw": raw, "raw_sha256": digest(raw), "http_status": code, "fetched_at": NOW}


def test_request_date_and_row_length_cannot_establish_provider_completeness():
    proof = pipeline.pool_source_proof([record({"pool": [{"c": "000001"}]})], DAY)["zt"]
    assert proof["asof_status"] == "NOT_ESTABLISHED"
    assert proof["coverage"]["status"] == "NOT_ESTABLISHED"
    assert proof["coverage"]["declared_total"] is None
    wrong_day = pipeline.pool_source_proof([record({"date": "20261105", "total": 1, "pool": [{}]})], DAY)["zt"]
    assert wrong_day["asof"] == PRIOR and wrong_day["asof_status"] != "source_verified"
    truncated = pipeline.pool_source_proof([record({"date": "20261106", "total": 3, "pool": [{}]})], DAY)["zt"]
    assert truncated["coverage"]["status"] != "complete"


def test_pool_proof_rejects_error_status_and_ambiguous_count():
    assert pipeline.pool_source_proof([record({"date": "20261106", "total": 0, "pool": []}, code=403)], DAY) == {}
    proof = pipeline.pool_source_proof([record({"date": "20261106", "total": True, "pool": [{}]})], DAY)
    assert proof["zt"]["coverage"]["status"] != "complete"


def test_two_current_captures_can_score_but_imported_prior_cannot(archive, calendar_path, policy_path, tmp_path):
    prior = run(archive, calendar_path, policy_path, asof=PRIOR, now="2026-11-05T08:00:00Z", run_id="prior_captured_001")
    assert prior["status"] == "partial"
    assert run(archive, calendar_path, policy_path)["detail"]["progression_status"] == "fresh"
    imported_archive = EODArchive(tmp_path / "imported.sqlite")
    path = tmp_path / "prior.json"
    path.write_text(json.dumps(archive.best(PRIOR)["snapshot"]), encoding="utf-8")
    imported = run(imported_archive, calendar_path, asof=PRIOR, input_path=path,
                   now="2026-11-05T09:00:00Z", run_id="prior_imported_001")
    assert imported["status"] == "partial"
    result = run(imported_archive, calendar_path, policy_path, run_id="current_capture_001")
    assert result["status"] == "partial"
    assert result["detail"]["progression_status"] == "not_available"
    progression = imported_archive.best(DAY)["snapshot"]["history"]["progression"]
    assert progression["stale_reason"] == "prior_archive_core_not_verified"


def test_partial_or_failed_retry_never_replaces_verified_best(archive, calendar_path, policy_path):
    run(archive, calendar_path, policy_path)
    original = archive.best(DAY)
    def partial(day, journal, run_id, policy):
        result = fake_collector(day, journal, run_id, policy)
        result["limit_pools"]["pool_sources"]["zt"]["asof"] = PRIOR
        return result
    retry = run(archive, calendar_path, policy_path, collector=partial, run_id="partial_retry_002")
    assert retry["status"] == "partial"
    assert archive.best(DAY) == original
    def failed(*args):
        raise RuntimeError("synthetic upstream failed")
    failure = run(archive, calendar_path, policy_path, collector=failed, run_id="failed_retry_003")
    assert failure["status"] == "failed" and archive.best(DAY) == original
    assert len(archive.report()["runs"]) == 3 and len(archive.report()["revisions"]) == 2


def test_recording_session_archives_actual_http_body_before_parse(archive, policy_path, monkeypatch):
    archive.start("recording_run_001", asof=DAY, mode="fixture", now=NOW)
    body = b'{"malformed": this is not json}\n'
    response = requests.Response()
    response.status_code = 503
    response.url = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?date=20261106&token=never-store"
    response._content = body
    observed = []
    def mock_request(self, method, url, **kwargs):
        observed.append(kwargs)
        return response
    monkeypatch.setattr(requests.Session, "request", mock_request)
    with pipeline.RecordingSession(archive, "recording_run_001", pipeline.load_fetch_policy(policy_path, now=NOW)) as session:
        returned = session.get(THS_LIMIT_UP_URL, allow_redirects=True)
        assert returned is response
        with pytest.raises(requests.exceptions.JSONDecodeError):
            returned.json()
        assert session.records[0]["raw"] == body
        assert session.records[0]["http_status"] == 503
        assert "never-store" not in session.records[0]["url"]
    assert observed[0]["allow_redirects"] is False and observed[0]["timeout"] == 15
    with archive.connect() as db:
        stored = db.execute("SELECT body,raw_sha256,http_status,url FROM responses").fetchone()
    assert bytes(stored["body"]) == body and stored["raw_sha256"] == digest(body)
    assert stored["http_status"] == 503 and "never-store" not in stored["url"]


def test_recording_session_rejects_unreviewed_host_without_network(archive, policy_path):
    archive.start("recording_run_001", asof=DAY, mode="fixture", now=NOW)
    with pipeline.RecordingSession(archive, "recording_run_001", pipeline.load_fetch_policy(policy_path, now=NOW)) as session:
        with pytest.raises(ValueError, match="UNREVIEWED_SOURCE_HOST"):
            session.get("https://example.test/anything")
    assert archive.report()["raw_response_count"] == 0


def test_import_raw_downgrade_cannot_leave_quality_ready(archive, calendar_path, policy_path, tmp_path):
    run(archive, calendar_path, policy_path)
    path = tmp_path / "old.json"
    path.write_text(json.dumps(archive.best(DAY)["snapshot"]), encoding="utf-8")
    imported = EODArchive(tmp_path / "copy.sqlite")
    receipt = run(imported, calendar_path, input_path=path)
    assert receipt["status"] == "partial"
    quality = imported.best(DAY)["snapshot"]["daily_capture"]["quality"]
    assert not quality["core_complete"]
    assert quality["status"] != "ready"


def test_later_archived_prior_is_not_available_to_earlier_run(archive, calendar_path, policy_path):
    run(archive, calendar_path, policy_path, asof=PRIOR, now="2026-11-07T08:00:00Z", run_id="late_prior_001")
    result = run(archive, calendar_path, policy_path, now=NOW)
    assert result["detail"]["progression_status"] == "not_available"


def test_missing_reason_rows_keep_daily_snapshot_partial(archive, calendar_path, policy_path):
    def missing_labels(day, journal, run_id, policy):
        result = fake_collector(day, journal, run_id, policy)
        result["limit_pools"]["reasons"]["rows"] = []
        return result
    result = run(archive, calendar_path, policy_path, collector=missing_labels)
    assert result["status"] == "partial"
    assert archive.best(DAY)["snapshot"]["daily_capture"]["quality"]["labels"]["reasons"]["missing_count"] == 2


def install_capture_http_fixture(monkeypatch, ths_data, *, yesterday_data=None, yesterday_http_status=200, yesterday_rc=0):
    """Exercise real collectors/parsers/recording using synthetic HTTP bodies."""
    observed = []
    endpoints = {"/" + endpoint: kind for kind, endpoint, _ in pipeline.LIMIT_POOLS}
    zt_rows = [{"c": "000001", "n": "Synthetic A", "lbc": 2, "fbt": 93000},
               {"c": "600519", "n": "Synthetic B", "lbc": 1, "fbt": 100000}]

    def respond(self, method, url, **kwargs):
        path = urlsplit(url).path
        if url == THS_LIMIT_UP_URL:
            payload = {"data": ths_data}
        elif path in endpoints:
            rows = zt_rows if endpoints[path] == "zt" else []
            payload = {"rc": 0, "data": {"date": DAY.replace("-", ""), "total": len(rows), "pool": rows}}
        elif path == "/getYesterdayZTPool":
            payload = {"data": yesterday_data if yesterday_data is not None else
                       {"date": DAY.replace("-", ""), "total": 0, "pool": []}}
        else:
            raise AssertionError(f"unexpected request: {url}")
        if path == "/getYesterdayZTPool" and yesterday_rc != "missing":
            payload["rc"] = yesterday_rc
        response = requests.Response()
        response.status_code = yesterday_http_status if path == "/getYesterdayZTPool" else 200
        response.url = requests.Request(method, url, params=kwargs.get("params")).prepare().url
        response._content = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        observed.append({"url": response.url, "body": response.content, "kwargs": kwargs})
        return response

    # Only HTTP transport and waits are substituted. capture_core, legacy
    # provider parsers, evidence checks and the SQLite journal all remain real.
    original_client = pipeline.EMClient
    monkeypatch.setattr(pipeline, "EMClient", lambda session: original_client(
        session=session, sleep=lambda _: None, jitter=lambda _a, _b: 0))
    monkeypatch.setattr(pipeline.time, "sleep", lambda _: None)
    real_stamp = pipeline.stamp
    monkeypatch.setattr(pipeline, "stamp", lambda value=None: real_stamp(value or NOW))
    monkeypatch.setattr(requests.Session, "request", respond)
    return observed


def ths_http_payload():
    return {"date": DAY, "total": 2, "info": [
        {"code": "000001", "name": "Synthetic A", "reason_type": "Synthetic topic A"},
        {"code": "600519", "name": "Synthetic B", "reason_type": "Synthetic topic B"},
    ]}


@pytest.mark.parametrize("source_date", [DAY, DAY.replace("-", "")])
def test_actual_capture_core_uses_archived_ths_date_proof_and_still_requires_prior(
    archive, calendar_path, policy_path, monkeypatch, source_date,
):
    data = ths_http_payload()
    data["date"] = source_date
    requests_seen = install_capture_http_fixture(monkeypatch, data)

    receipt = run(archive, calendar_path, policy_path, collector=pipeline.capture_core)

    assert receipt["status"] == "partial"
    assert len(requests_seen) == archive.report()["raw_response_count"] == 5
    context = archive.best(DAY)["snapshot"]
    source = context["sources"]["ths_limit_up_pool"]
    ths_body = next(item["body"] for item in requests_seen if urlsplit(item["url"]).hostname == "data.10jqka.com.cn")
    assert source["asof"] == DAY and source["asof_status"] == "source_verified"
    assert source["coverage"] == {"status": "complete", "declared_total": 2, "pages_expected": 1, "pages_received": 1}
    assert source["raw_sha256"] == digest(ths_body)
    assert archive.raw_verified(receipt["run_id"], "ths_limit_up_pool", source["raw_sha256"])
    for label in ("reasons", "topics"):
        assert context["limit_pools"][label]["source"] == source
        checked = context["daily_capture"]["quality"]["labels"][label]
        assert checked["status"] == "fresh" and checked["source_date_status"] == "VERIFIED"
    assert all(item["kwargs"]["allow_redirects"] is False for item in requests_seen)
    assert context["publication_eligible"] is False and context["model_input_eligible"] is False


@pytest.mark.parametrize("change", [
    {"date": None}, {"date": PRIOR}, {"total": None}, {"total": True}, {"total": 3}, {"total": 200},
])
def test_actual_capture_core_never_promotes_missing_wrong_or_truncated_ths_proof(
    archive, calendar_path, policy_path, monkeypatch, change,
):
    data = ths_http_payload()
    data.update(change)
    install_capture_http_fixture(monkeypatch, data)

    receipt = run(archive, calendar_path, policy_path, collector=pipeline.capture_core)

    assert receipt["status"] == "partial"
    context = archive.best(DAY)["snapshot"]
    assert context["daily_capture"]["quality"]["core_complete"] is True
    assert context["daily_capture"]["raw_verification"]["reasons_topics"] is True
    for label in ("reasons", "topics"):
        assert context["limit_pools"][label]["status"] == "partial"
        assert context["daily_capture"]["quality"]["labels"][label]["status"] == "partial"
    source = context["sources"]["ths_limit_up_pool"]
    if "date" in change:
        assert source["asof_status"] == "NOT_ESTABLISHED"
    if "total" in change:
        assert source["coverage"]["status"] == "NOT_ESTABLISHED"


def yesterday_http_payload():
    return {"date": DAY.replace("-", ""), "total": 2,
            "pool": [{"c": "000001", "n": " Synthetic A ", "zdp": 0.0, "hs": 1.25, "zf": 3.0, "zs": -0.2,
                      "yfbt": 93000, "ylbc": 1, "hybk": " Synthetic industry ", "zttj": {"days": 1, "ct": 1}},
                     {"c": "600519", "n": "Synthetic B", "zdp": None}]}


def test_fourth_response_is_independently_bound_and_missing_quotes_keep_prior_members(
    archive, calendar_path, policy_path, monkeypatch,
):
    assert run(archive, calendar_path, policy_path, asof=PRIOR, now="2026-11-05T08:00:00Z",
               run_id="prior_captured_001")["status"] == "partial"
    seen = install_capture_http_fixture(monkeypatch, ths_http_payload(), yesterday_data=yesterday_http_payload())
    receipt = run(archive, calendar_path, policy_path, collector=pipeline.capture_core)
    assert receipt["status"] == "sealed"
    context = archive.best(DAY)["snapshot"]
    section = context["limit_pools"]["yesterday_performance"]
    checked = context["daily_capture"]["quality"]["pools"]["yesterday_performance"]
    body = next(row["body"] for row in seen if urlsplit(row["url"]).path == "/getYesterdayZTPool")
    assert section["source"]["source_id"] == pipeline.YESTERDAY_SOURCE
    assert section["source"]["raw_sha256"] == digest(body)
    assert section["source"]["asof"] == DAY and section["source"]["asof_status"] == "source_verified"
    assert section["declared_count"] == 2 and len(section["rows"]) == 2
    assert context["sources"][pipeline.YESTERDAY_SOURCE] == section["source"]
    assert checked["raw_response_check"] == {"verified": True, "raw_bytes_verified": True, "reasons": []}
    assert checked["prior_membership"]["status"] == "matched"
    assert checked["quote_unavailable_codes"] == ["600519"]
    assert context["history"]["progression"]["rows"][0]["eligible_count"] == 2
    assert context["limit_pools"].get("prior_day", {}).get("status") != "fresh"


@pytest.mark.parametrize("change", [
    {"date": None}, {"date": PRIOR}, {"total": None}, {"total": True}, {"total": 3},
    {"pool": [{"c": "000001"}, {"c": "000001"}]}, {"pool": [{"c": "000001"}, {"c": "sh600519"}]},
    {"pool": None},
])
def test_actual_fourth_pool_missing_wrong_date_counts_or_rows_never_seals(
    archive, calendar_path, policy_path, monkeypatch, change,
):
    data = yesterday_http_payload()
    data.update(change)
    install_capture_http_fixture(monkeypatch, ths_http_payload(), yesterday_data=data)
    receipt = run(archive, calendar_path, policy_path, collector=pipeline.capture_core)
    assert receipt["status"] == "partial"
    quality = archive.best(DAY)["snapshot"]["daily_capture"]["quality"]
    assert quality["core_complete"] and not quality["four_pool_complete"]
    assert not quality["pools"]["yesterday_performance"]["verified_complete"]


def test_fourth_http_failure_cannot_seal_despite_complete_other_sources(
    archive, calendar_path, policy_path, monkeypatch,
):
    install_capture_http_fixture(monkeypatch, ths_http_payload(), yesterday_data=yesterday_http_payload(),
                                 yesterday_http_status=503)
    receipt = run(archive, calendar_path, policy_path, collector=pipeline.capture_core)
    assert receipt["status"] == "partial"
    context = archive.best(DAY)["snapshot"]
    assert context["daily_capture"]["raw_verification"]["yesterday_performance"] is False
    assert context["limit_pools"]["yesterday_performance"]["status"] == "error"


@pytest.mark.parametrize("mutation", ["missing", "error", "wrong_source", "no_raw", "other_pool_raw", "altered_members"])
def test_fourth_envelope_or_receipt_failure_never_seals(archive, calendar_path, policy_path, mutation):
    def changed(day, journal, run_id, policy):
        result = fake_collector(day, journal, run_id, policy)
        section = result["limit_pools"]["yesterday_performance"]
        if mutation == "missing":
            result["limit_pools"].pop("yesterday_performance")
        elif mutation == "error":
            section["status"] = "error"
        elif mutation == "wrong_source":
            section["source"]["source_id"] = "eastmoney_limit_pools"
        elif mutation == "no_raw":
            section["source"]["raw_sha256"] = "a" * 64
        elif mutation == "other_pool_raw":
            section["source"]["raw_sha256"] = result["limit_pools"]["pool_sources"]["zt"]["raw_sha256"]
        else:
            section["rows"][1]["code"] = "000002"
        return result
    receipt = run(archive, calendar_path, policy_path, collector=changed)
    assert receipt["status"] == "partial"
    checked = archive.best(DAY)["snapshot"]["daily_capture"]["quality"]
    assert checked["core_complete"] and not checked["four_pool_complete"]
    assert not checked["pools"]["yesterday_performance"]["verified_complete"]


def test_request_date_cannot_be_forged_into_fourth_response_proof(
    archive, calendar_path, policy_path, monkeypatch,
):
    data = yesterday_http_payload()
    data.pop("date")
    install_capture_http_fixture(monkeypatch, ths_http_payload(), yesterday_data=data)
    def forged(day, journal, run_id, policy):
        result = pipeline.capture_core(day, journal, run_id, policy)
        section = result["limit_pools"]["yesterday_performance"]
        section["status"] = "fresh"
        section["source"].update({"asof": day, "asof_status": "source_verified"})
        return result
    receipt = run(archive, calendar_path, policy_path, collector=forged)
    assert receipt["status"] == "partial"
    fourth = archive.best(DAY)["snapshot"]["daily_capture"]["quality"]["pools"]["yesterday_performance"]
    assert fourth["raw_bytes_verified"]
    assert not fourth["raw_response_check"]["verified"]
    assert "yesterday_raw_response_date_not_verified" in fourth["reasons"]
    assert "yesterday_source_receipt_differs_from_raw_response" in fourth["reasons"]


def test_fourth_complete_provider_view_still_reports_member_missing_from_prior_archive(
    archive, calendar_path, policy_path, monkeypatch,
):
    run(archive, calendar_path, policy_path, asof=PRIOR, now="2026-11-05T08:00:00Z", run_id="prior_captured_001")
    data = yesterday_http_payload()
    data.update({"total": 1, "pool": data["pool"][:1]})
    install_capture_http_fixture(monkeypatch, ths_http_payload(), yesterday_data=data)
    receipt = run(archive, calendar_path, policy_path, collector=pipeline.capture_core)
    assert receipt["status"] == "partial"
    context = archive.best(DAY)["snapshot"]
    fourth = context["daily_capture"]["quality"]["pools"]["yesterday_performance"]
    assert fourth["raw_response_check"]["verified"]
    assert fourth["prior_membership"]["missing_codes"] == ["600519"]
    assert context["history"]["progression"]["status"] == "fresh"
    assert context["history"]["progression"]["rows"][0]["eligible_count"] == 2
    assert context["history"]["progression"]["rows"][0]["rate"] == 0.5


def test_historical_import_retains_old_fourth_values_without_certifying_them(archive, calendar_path, tmp_path):
    old_view = {"status": "fresh", "asof": DAY, "rows": [{"code": "000001", "pct": 1.25}],
                "source": {"source_id": pipeline.YESTERDAY_SOURCE}}
    item = {"asof": DAY, "limit_pools": {"yesterday_performance": old_view},
            "history": {"progression": {"status": "fresh", "rows": [{"rate": 0.99}]}}}
    path = tmp_path / "legacy_fourth.json"
    raw = json.dumps(item).encode()
    path.write_bytes(raw)
    receipt = run(archive, calendar_path, input_path=path)
    assert receipt["status"] == "partial" and path.read_bytes() == raw
    context = archive.best(DAY)["snapshot"]
    assert context["limit_pools"]["yesterday_performance"] == old_view
    assert context["daily_capture"]["legacy_progression"] == item["history"]["progression"]
    assert not context["daily_capture"]["quality"]["core_complete"]


@pytest.mark.parametrize("return_code", ["missing", None, False, True, "0", 1, -1])
def test_fourth_provider_requires_explicit_integer_zero_return_code(
    archive, calendar_path, policy_path, monkeypatch, return_code,
):
    install_capture_http_fixture(monkeypatch, ths_http_payload(), yesterday_data=yesterday_http_payload(),
                                 yesterday_rc=return_code)
    receipt = run(archive, calendar_path, policy_path, collector=pipeline.capture_core)
    assert receipt["status"] == "partial"
    fourth = archive.best(DAY)["snapshot"]["daily_capture"]["quality"]["pools"]["yesterday_performance"]
    assert not fourth["raw_response_check"]["verified"]
    assert "yesterday_raw_provider_return_code_not_success" in fourth["reasons"]


@pytest.mark.parametrize("field", ["name", "pct", "turnover", "amplitude", "speed", "y_first_seal", "y_limit_days", "industry", "zt_stat"])
def test_all_normalized_display_fields_are_bound_to_fourth_raw_body(archive, calendar_path, policy_path, field):
    def changed(day, journal, run_id, policy):
        result = fake_collector(day, journal, run_id, policy)
        result["limit_pools"]["yesterday_performance"]["rows"][0][field] = "fabricated display value"
        return result
    receipt = run(archive, calendar_path, policy_path, collector=changed)
    assert receipt["status"] == "partial"
    fourth = archive.best(DAY)["snapshot"]["daily_capture"]["quality"]["pools"]["yesterday_performance"]
    assert fourth["raw_bytes_verified"] and not fourth["raw_response_check"]["verified"]
    assert "yesterday_normalized_fields_differ_from_raw_response" in fourth["reasons"]


@pytest.mark.parametrize("query", [
    "date=20261105&Pageindex=0&pagesize=10000", "date=20261109&Pageindex=0&pagesize=10000",
    "date=20261106&Pageindex=1&pagesize=10000", "date=20261106&Pageindex=0&pagesize=10",
    "date=20261106&date=20261106&Pageindex=0&pagesize=10000", "date=20261106",
])
def test_fourth_raw_request_identity_is_not_inferred_from_response_date(
    archive, calendar_path, policy_path, monkeypatch, query,
):
    original_response = archive.response
    url = "https://push2ex.eastmoney.com/getYesterdayZTPool?" + query
    def record_changed(run_id, **kwargs):
        if kwargs["source_id"] == pipeline.YESTERDAY_SOURCE:
            kwargs["url"] = url
        return original_response(run_id, **kwargs)
    monkeypatch.setattr(archive, "response", record_changed)
    def changed(day, journal, run_id, policy):
        result = fake_collector(day, journal, run_id, policy)
        result["limit_pools"]["yesterday_performance"]["source"]["source_url"] = url
        return result
    receipt = run(archive, calendar_path, policy_path, collector=changed)
    assert receipt["status"] == "partial"
    fourth = archive.best(DAY)["snapshot"]["daily_capture"]["quality"]["pools"]["yesterday_performance"]
    assert "yesterday_raw_request_date_or_pagination_mismatch" in fourth["reasons"]
    assert not fourth["raw_response_check"]["verified"]


@pytest.mark.parametrize("actual,reported,reason", [
    ("2026-11-06T07:30:00Z", "2026-11-06T08:00:00Z", "yesterday_fetched_at_differs_from_raw_response"),
    ("2026-11-06T09:00:00Z", "2026-11-06T09:00:00Z", "yesterday_raw_fetched_at_is_future"),
    ("2026-11-06T07:29:59Z", "2026-11-06T07:29:59Z", "yesterday_raw_response_precedes_asof_close"),
    ("2026-11-05T08:00:00Z", "2026-11-05T08:00:00Z", "yesterday_raw_response_precedes_asof_close"),
])
def test_fourth_uses_archived_fetched_time_and_rejects_future_or_before_close(
    archive, calendar_path, policy_path, monkeypatch, actual, reported, reason,
):
    original_response = archive.response
    def record_changed(run_id, **kwargs):
        if kwargs["source_id"] == pipeline.YESTERDAY_SOURCE:
            kwargs["fetched_at"] = actual
        return original_response(run_id, **kwargs)
    monkeypatch.setattr(archive, "response", record_changed)
    def changed(day, journal, run_id, policy):
        result = fake_collector(day, journal, run_id, policy)
        result["limit_pools"]["yesterday_performance"]["source"]["fetched_at"] = reported
        return result
    receipt = run(archive, calendar_path, policy_path, collector=changed)
    assert receipt["status"] == "partial"
    fourth = archive.best(DAY)["snapshot"]["daily_capture"]["quality"]["pools"]["yesterday_performance"]
    assert reason in fourth["reasons"] and not fourth["raw_response_check"]["verified"]


def test_prior_self_reported_raw_flags_cannot_substitute_for_actual_archive_bytes(
    archive, calendar_path, policy_path, monkeypatch,
):
    run_id = "synthetic_prior_claim_001"
    archive.start(run_id, asof=PRIOR, mode="fixture", now="2026-11-05T08:00:00Z")
    original_response = archive.response
    def record_wrong_source(run_id, **kwargs):
        if kwargs["source_id"] == "eastmoney_limit_pools":
            kwargs["source_id"] = "synthetic_unverified_source"
        return original_response(run_id, **kwargs)
    with monkeypatch.context() as scoped:
        scoped.setattr(archive, "response", record_wrong_source)
        prior = fake_collector(PRIOR, archive, run_id, {})
    prior["calendar"] = pipeline.resolve_sessions(asof=PRIOR, prior_asof=None,
                                                  calendar=pipeline.load_calendar(calendar_path), today=PRIOR)
    prior["publication_eligible"] = False
    prior["daily_capture"] = {"run_id": run_id, "quality": {"core_complete": True}, "raw_verification": {"zt": True}}
    archive.finish(run_id, status="partial", detail={"evidence": "synthetic forged flags regression"},
                    snapshot=prior, now="2026-11-05T08:00:00Z")
    receipt = run(archive, calendar_path, policy_path)
    assert receipt["status"] == "partial"
    quality = archive.best(DAY)["snapshot"]["daily_capture"]["quality"]
    assert quality["core_complete"] and not quality["four_pool_complete"]
    membership = quality["pools"]["yesterday_performance"]["prior_membership"]
    assert membership["status"] == "not_available" and not membership["raw_bytes_verified"]
    assert "prior_zt_archive_raw_not_verified" in membership["reasons"]


@pytest.mark.parametrize("mutation,reason", [
    ("dt_raw", "prior_zt_raw_endpoint_mismatch"),
    ("streak", "prior_zt_normalized_codes_or_streaks_differ_from_raw_response"),
    ("code", "prior_zt_normalized_codes_or_streaks_differ_from_raw_response"),
])
def test_four_pool_denominator_must_match_specific_prior_zt_raw(archive, calendar_path, policy_path, mutation, reason):
    run_id = "synthetic_prior_binding_001"
    archive.start(run_id, asof=PRIOR, mode="fixture", now="2026-11-05T08:00:00Z")
    prior = fake_collector(PRIOR, archive, run_id, {})
    if mutation == "dt_raw":
        source = prior["limit_pools"]["pool_sources"]
        source["zt"].update({key: source["dt"][key] for key in ("raw_sha256", "source_url")})
    elif mutation == "streak":
        prior["limit_pools"]["pool_rows"]["zt"][0]["streak"] = 9
    else:
        prior["limit_pools"]["pool_rows"]["zt"][0]["code"] = "000002"
    prior["calendar"] = pipeline.resolve_sessions(asof=PRIOR, prior_asof=None,
                                                  calendar=pipeline.load_calendar(calendar_path), today=PRIOR)
    prior["publication_eligible"] = False
    prior["daily_capture"] = {"run_id": run_id, "quality": {"core_complete": True}, "raw_verification": {"zt": True}}
    archive.finish(run_id, status="partial", detail={"evidence": "synthetic altered denominator regression"},
                    snapshot=prior, now="2026-11-05T08:00:00Z")
    receipt = run(archive, calendar_path, policy_path)
    assert receipt["status"] == "partial"
    quality = archive.best(DAY)["snapshot"]["daily_capture"]["quality"]
    assert quality["core_complete"] and not quality["four_pool_complete"]
    check = quality["pools"]["yesterday_performance"]["prior_membership"]["raw_response_check"]
    assert not check["verified"] and reason in check["reasons"]


def test_prior_raw_cannot_be_fetched_after_its_already_recorded_revision(
    archive, calendar_path, policy_path, monkeypatch,
):
    run_id = "synthetic_prior_future_fetch_001"
    archive.start(run_id, asof=PRIOR, mode="fixture", now="2026-11-05T08:00:00Z")
    original_response = archive.response
    future_fetch = "2026-11-05T09:00:00Z"
    def record_future(run_id, **kwargs):
        if urlsplit(kwargs["url"]).path == "/getTopicZTPool":
            kwargs["fetched_at"] = future_fetch
        return original_response(run_id, **kwargs)
    with monkeypatch.context() as scoped:
        scoped.setattr(archive, "response", record_future)
        prior = fake_collector(PRIOR, archive, run_id, {})
    prior["limit_pools"]["pool_sources"]["zt"]["fetched_at"] = future_fetch
    prior["calendar"] = pipeline.resolve_sessions(asof=PRIOR, prior_asof=None,
                                                  calendar=pipeline.load_calendar(calendar_path), today=PRIOR)
    prior["publication_eligible"] = False
    prior["daily_capture"] = {"run_id": run_id, "quality": {"core_complete": True}, "raw_verification": {"zt": True}}
    archive.finish(run_id, status="partial", detail={"evidence": "synthetic future-fetch/early-archive regression"},
                    snapshot=prior, now="2026-11-05T08:00:00Z")
    receipt = run(archive, calendar_path, policy_path)
    assert receipt["status"] == "partial"
    quality = archive.best(DAY)["snapshot"]["daily_capture"]["quality"]
    assert quality["core_complete"] and not quality["four_pool_complete"]
    check = quality["pools"]["yesterday_performance"]["prior_membership"]["raw_response_check"]
    assert not check["verified"] and "prior_zt_fetched_after_archive_or_run_start" in check["reasons"]
