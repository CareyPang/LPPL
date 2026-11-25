"""Scheduled refresh contracts; no real network, fitting, publication or timers."""
import json
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from research.pipeline import global_refresh as refresh


@pytest.fixture
def config(tmp_path):
    return {"source_root": str(tmp_path / "source"), "jobs_root": str(tmp_path / "jobs"),
            "state_root": str(tmp_path / "state"), "symbols": ["US_IXIC", "KR_KOSDAQ"],
            "minimum_rows": {"US_IXIC": 6700, "KR_KOSDAQ": 10}, "long_window_rows": 6700}


@pytest.fixture
def harness(config, monkeypatch):
    monkeypatch.setattr(refresh, "implementation_identity", lambda _: "implementation-v1")
    calls = {"fetch": [], "start": [], "results": {}, "jobs": {}, "shutdown": []}
    versions = {"US_IXIC": "prices-1", "KR_KOSDAQ": "prices-1"}
    failures = set()
    failed_jobs = set()

    def fetch(symbol, root, **kwargs):
        calls["fetch"].append((symbol, root, kwargs))
        if symbol in failures:
            raise OSError("source unavailable")
        rows = 6800 if symbol == "US_IXIC" else 6432
        frame = pd.DataFrame({"date": pd.bdate_range(end="2026-11-20", periods=rows),
                              "close": [100.] * rows})
        return frame, {"id": symbol, "asof": "2026-11-20", "normalized_sha256": versions[symbol],
                       "fetched_at": "2026-11-23T08:30:00+08:00"}

    class Executor:
        def shutdown(self, **kwargs):
            calls["shutdown"].append(kwargs)

    class Service:
        def __init__(self, *_):
            self.executor = Executor()

        def selected_result(self, symbol):
            return deepcopy(calls["results"].get(symbol))

        def start(self, body):
            calls["start"].append(dict(body))
            job_id = str(len(calls["start"]))
            symbol = body["symbol"]
            job = {"job_id": job_id, "status": "failed" if symbol in failed_jobs else "complete",
                   "symbol": symbol, "cache_reused": 27, "modules": {"lppls": "complete"}}
            if symbol in failed_jobs:
                job["error"] = "fit failed"
            else:
                calls["results"][symbol] = {"job_id": job_id, "symbol": symbol,
                    "asof": "2026-11-20", "data_version": versions[symbol],
                    "record_version": "result-" + job_id,
                    "fit_counts": {"completed": 27, "expected": 27}}
            calls["jobs"][job_id] = job
            return job

        def get(self, job_id):
            return deepcopy(calls["jobs"][job_id])

        def result(self, job_id):
            return deepcopy(calls["results"][calls["jobs"][job_id]["symbol"]])

    def run():
        return refresh.run_config(config, fetcher=fetch, job_factory=Service,
                                  sleeper=lambda _: pytest.fail("Finished fixture must not sleep"))

    return calls, versions, failures, failed_jobs, Service, fetch, run


def test_dry_run_does_not_create_fetch_fit_or_write(config, tmp_path):
    audit, code = refresh.run_config(config, dry_run=True,
        fetcher=lambda *_: pytest.fail("fetch"), job_factory=lambda *_: pytest.fail("job"))
    assert code == 0
    assert audit["status"] == "configuration_valid"
    assert audit["history_auto_run"] is False and audit["publication"] == "none"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("changes", [
    {"symbols": []}, {"symbols": ["US_IXIC", "US_IXIC"]}, {"symbols": ["UNKNOWN"]},
    {"symbols": [{}]}, {"symbols": "US_IXIC"}, {"source_root": "relative"},
    {"jobs_root": str(refresh.ROOT / "cache")}, {"minimum_rows": {"US_IXIC": True}},
    {"minimum_rows": {"KR_KOSPI": 6700}}, {"long_window_rows": 100},
])
def test_invalid_configuration_is_rejected(config, changes):
    with pytest.raises(ValueError):
        refresh.parse_config({**config, **changes})


def test_complete_refresh_is_single_latest_endpoint_and_records_short_coverage(config, harness):
    calls, _, _, _, _, _, run = harness
    audit, code = run()
    assert code == 0 and audit["status"] == "complete"
    assert audit["counts"] == {"expected": 2, "updated": 2, "unchanged": 0, "failed": 0}
    assert calls["start"] == [{"symbol": s, "asof": None, "refresh": False} for s in config["symbols"]]
    assert all(options["refresh"] and options["full_history"] for _, _, options in calls["fetch"])
    assert calls["fetch"][1][2]["minimum_rows"] == 10
    assert audit["assets"][1]["long_window_coverage"] == {
        "required_rows": 6700, "actual_rows": 6432, "status": "insufficient_data"}
    assert calls["shutdown"] == [{"wait": True, "cancel_futures": False}]
    stored = json.loads((Path(config["state_root"]) / "latest.json").read_text())
    assert stored == audit


def test_unchanged_full_input_skips_all_model_jobs_and_does_not_infer_holiday(harness):
    calls, _, _, _, _, _, run = harness
    run()
    audit, code = run()
    assert code == 0 and audit["counts"]["unchanged"] == 2
    assert len(calls["start"]) == 2  # Only first run enqueued jobs.
    assert len(calls["fetch"]) == 4  # Both runs still verify the actual source.
    assert all(r["reason"] == "no_new_completed_session_or_input_revision" for r in audit["assets"])


def test_same_day_data_revision_recomputes_only_that_asset(harness):
    calls, versions, _, _, _, _, run = harness
    run()
    versions["US_IXIC"] = "corrected-prices"
    audit, _ = run()
    assert audit["counts"]["updated"] == 1 and audit["counts"]["unchanged"] == 1
    assert calls["start"][-1]["symbol"] == "US_IXIC"
    assert len(calls["start"]) == 3


def test_changed_method_does_not_reuse_old_analysis(harness, monkeypatch):
    calls, _, _, _, _, _, run = harness
    run()
    monkeypatch.setattr(refresh, "implementation_identity", lambda _: "implementation-v2")
    audit, _ = run()
    assert audit["counts"]["updated"] == 2 and len(calls["start"]) == 4


def test_source_failure_retains_last_good_and_continues_other_asset(config, harness):
    calls, _, failures, _, _, _, run = harness
    run()
    path = Path(config["state_root"]) / "assets/US_IXIC.json"
    old = json.loads(path.read_text())["last_good"]
    failures.add("US_IXIC")
    audit, code = run()
    assert code == 1 and audit["status"] == "partial_failure"
    assert audit["counts"]["failed"] == 1 and audit["counts"]["unchanged"] == 1
    assert len(calls["start"]) == 2
    stored = json.loads(path.read_text())
    assert stored["last_good"] == old and stored["source_status"] == "stale"
    assert stored["last_attempt"]["last_good_asof"] == old["asof"]


def test_model_failure_keeps_last_good_while_fresh_data_status_is_distinct(config, harness):
    _, versions, _, failed_jobs, _, _, run = harness
    run()
    path = Path(config["state_root"]) / "assets/US_IXIC.json"
    old = json.loads(path.read_text())["last_good"]
    versions["US_IXIC"] = "new-input"
    failed_jobs.add("US_IXIC")
    audit, code = run()
    assert code == 1
    assert audit["assets"][0]["source_status"] == "ready"
    assert "fit failed" in audit["assets"][0]["error"]
    assert json.loads(path.read_text())["last_good"] == old


def test_changed_selected_result_pointer_does_not_silently_skip(harness):
    calls, _, _, _, _, _, run = harness
    run()
    calls["results"]["US_IXIC"]["record_version"] = "other-research-version"
    audit, _ = run()
    assert audit["counts"]["updated"] == 1


def test_corrupt_state_is_preserved_for_inspection(config, harness):
    calls, _, _, _, _, _, run = harness
    state = Path(config["state_root"]) / "assets/US_IXIC.json"
    state.parent.mkdir(parents=True)
    state.write_text("{incomplete")
    audit, code = run()
    assert code == 1 and state.read_text() == "{incomplete"
    assert len(calls["start"]) == 1 and calls["start"][0]["symbol"] == "KR_KOSDAQ"
    assert audit["counts"]["failed"] == 1


def test_source_identity_mismatch_never_starts_job(config, harness):
    calls, _, _, _, service, fetch, _ = harness

    def wrong(*args, **kwargs):
        frame, metadata = fetch(*args, **kwargs)
        return frame, {**metadata, "id": "WRONG"}

    audit, code = refresh.run_config(config, fetcher=wrong, job_factory=service)
    assert code == 1 and audit["counts"]["failed"] == 2
    assert calls["start"] == []


def test_queue_is_waited_and_only_current_result_is_accepted(config, harness):
    calls, _, _, _, base_service, fetch, _ = harness
    sleeps = []

    class QueuedService(base_service):
        def start(self, body):
            complete = super().start(body)
            return {**complete, "status": "queued"}

    audit, code = refresh.run_config(config, fetcher=fetch, job_factory=QueuedService,
                                     sleeper=lambda seconds: sleeps.append(seconds))
    assert code == 0 and audit["counts"]["updated"] == 2
    assert sleeps == [1, 1] and len(calls["start"]) == 2


def test_result_input_race_is_failure_not_a_successful_refresh(config, harness):
    _, _, _, _, base_service, fetch, _ = harness

    class WrongVersionService(base_service):
        def result(self, job_id):
            return {**super().result(job_id), "data_version": "different-vintage"}

    audit, code = refresh.run_config(config, fetcher=fetch, job_factory=WrongVersionService)
    assert code == 1 and audit["counts"]["failed"] == 2
    assert all("last_good" not in json.loads((Path(config["state_root"]) / "assets" / (s+".json")).read_text())
               for s in config["symbols"])


def test_lock_excludes_another_refresh_and_releases_on_exception(tmp_path):
    with refresh.refresh_lock(tmp_path):
        with pytest.raises(refresh.AlreadyRunning), refresh.refresh_lock(tmp_path):
            pass
    with pytest.raises(RuntimeError), refresh.refresh_lock(tmp_path):
        raise RuntimeError("run failed")
    with refresh.refresh_lock(tmp_path):
        pass


def test_workflow_has_no_automatic_source_fetch_or_publication():
    text = (refresh.ROOT / ".github/workflows/global_research_refresh.yml").read_text(encoding="utf-8")
    assert "contents: read" in text
    assert "persist-credentials: false" in text
    assert "upload-artifact" not in text and "git push" not in text
    assert "--dry-run" in text
    assert "GLOBAL_RESEARCH_REFRESH_ENABLED" in text
