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
    fetched = f"{day}T08:00:00Z"
    rows = [{"code": "000001", "streak": 2 if day == DAY else 1}, {"code": "600519", "streak": 1}]
    records = []
    for kind, endpoint, _ in pipeline.LIMIT_POOLS:
        members = rows if kind == "zt" else []
        raw = json.dumps({"data": {"date": day.replace("-", ""), "total": len(members),
                        "pool": [{"c": row["code"], "lbc": row["streak"]} for row in members]}}, sort_keys=True).encode()
        url = "https://push2ex.eastmoney.com/" + endpoint + "?date=" + day.replace("-", "")
        sha = archive.response(run_id, source_id="eastmoney_limit_pools", url=url, raw=raw, http_status=200, fetched_at=fetched)
        records.append({"source_id": "eastmoney_limit_pools", "url": url, "raw": raw, "raw_sha256": sha,
                        "http_status": 200, "fetched_at": fetched})
    raw_ths = json.dumps({"data": {"date": day, "info": [{"code": row["code"], "reason_type": "Synthetic"} for row in rows]}}).encode()
    sha_ths = archive.response(run_id, source_id="ths_limit_up_pool", url=THS_LIMIT_UP_URL,
                               raw=raw_ths, http_status=200, fetched_at=fetched)
    ths_source = {"source_id": "ths_limit_up_pool", "source_url": THS_LIMIT_UP_URL,
                  "asof": day, "asof_status": "source_verified", "status": "fresh", "ok": True,
                  "fetched_at": fetched, "raw_sha256": sha_ths}
    return {"asof": day, "generated_at": fetched, "sources": {"ths_limit_up_pool": ths_source},
            "limit_pools": {"date": day, "zt": len(rows), "zb": 0, "dt": 0,
                "pool_rows": {"zt": rows, "zb": [], "dt": []},
                "pool_sources": pipeline.pool_source_proof(records, day),
                "reasons": {"asof": day, "status": "fresh", "source": deepcopy(ths_source),
                            "rows": [{"code": row["code"], "reason": "Synthetic"} for row in rows]},
                "topics": {"asof": day, "status": "fresh", "source": deepcopy(ths_source),
                           "rows": [{"code": row["code"], "topic_label": "Synthetic"} for row in rows]}}}


def run(archive, calendar_path, policy_path=None, **kwargs):
    args = {"archive": archive, "calendar_path": calendar_path, "policy_path": policy_path,
            "asof": DAY, "now": NOW, "run_id": "synthetic_run_001", "collector": fake_collector}
    args.update(kwargs)
    return pipeline.run_eod(**args)


def test_capture_seals_exact_raw_bytes_with_no_network_or_publication(archive, calendar_path, policy_path):
    receipt = run(archive, calendar_path, policy_path)
    assert receipt["status"] == "sealed"
    assert archive.report()["raw_response_count"] == 4
    value = archive.best(DAY)["snapshot"]
    assert value["daily_capture"]["quality"]["core_complete"] is True
    assert value["daily_capture"]["raw_verification"] == {"zt": True, "zb": True, "dt": True, "reasons_topics": True}
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
    assert run(archive, calendar_path, policy_path, now="2026-11-06T07:30:00Z")["status"] == "sealed"


def test_payload_source_date_mismatch_has_failure_receipt(archive, calendar_path, policy_path):
    def mismatched(day, journal, run_id, policy):
        result = fake_collector(day, journal, run_id, policy)
        result["asof"] = PRIOR
        return result
    result = run(archive, calendar_path, policy_path, collector=mismatched)
    assert result["status"] == "failed" and result["detail"]["reason"] == "SOURCE_ASOF_MISMATCH"
    assert archive.report()["raw_response_count"] == 4
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
    assert prior["status"] == "sealed"
    assert run(archive, calendar_path, policy_path)["detail"]["progression_status"] == "fresh"
    imported_archive = EODArchive(tmp_path / "imported.sqlite")
    path = tmp_path / "prior.json"
    path.write_text(json.dumps(archive.best(PRIOR)["snapshot"]), encoding="utf-8")
    imported = run(imported_archive, calendar_path, asof=PRIOR, input_path=path,
                   now="2026-11-05T09:00:00Z", run_id="prior_imported_001")
    assert imported["status"] == "partial"
    result = run(imported_archive, calendar_path, policy_path, run_id="current_capture_001")
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


def install_capture_http_fixture(monkeypatch, ths_data):
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
            payload = {"data": {"date": DAY.replace("-", ""), "total": len(rows), "pool": rows}}
        elif path == "/getYesterdayZTPool":
            payload = {"data": {"date": DAY.replace("-", ""), "total": 0, "pool": []}}
        else:
            raise AssertionError(f"unexpected request: {url}")
        response = requests.Response()
        response.status_code = 200
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
    monkeypatch.setattr(requests.Session, "request", respond)
    return observed


def ths_http_payload():
    return {"date": DAY, "total": 2, "info": [
        {"code": "000001", "name": "Synthetic A", "reason_type": "Synthetic topic A"},
        {"code": "600519", "name": "Synthetic B", "reason_type": "Synthetic topic B"},
    ]}


@pytest.mark.parametrize("source_date", [DAY, DAY.replace("-", "")])
def test_actual_capture_core_uses_archived_ths_date_proof_and_can_seal(
    archive, calendar_path, policy_path, monkeypatch, source_date,
):
    data = ths_http_payload()
    data["date"] = source_date
    requests_seen = install_capture_http_fixture(monkeypatch, data)

    receipt = run(archive, calendar_path, policy_path, collector=pipeline.capture_core)

    assert receipt["status"] == "sealed"
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
