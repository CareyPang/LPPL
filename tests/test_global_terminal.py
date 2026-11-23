"""Global sample boundaries: no network/model fit required by contract tests."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from research.data.global_terminal import normalise, save_snapshot
from research.pipeline import global_terminal as pipeline


def payload(symbol="MRVL", timezone="America/New_York", dates=None, adjusted=None):
    dates = dates or ["2026-11-19T14:30:00+00:00", "2026-11-20T14:30:00+00:00"]
    return {"chart": {"error": None, "result": [{
        "meta": {"symbol": symbol, "exchangeTimezoneName": timezone, "exchangeName": "NMS", "currency": "USD"},
        "timestamp": [int(datetime.fromisoformat(v).timestamp()) for v in dates],
        "indicators": {"quote": [{"open": [100, 104], "high": [110, 112], "low": [90, 96],
                                   "close": [100, 110], "volume": [5000, 6000]}],
                       "adjclose": [{"adjclose": adjusted or [50, 110]}]},
    }]}}


def frame(count=1550):
    dates = pd.bdate_range("2019-01-01", periods=count)
    return pd.DataFrame({"date": dates, "open": 100., "high": 102., "low": 98.,
                         "close": np.arange(count) / 10 + 100, "volume": 1000.})


def row(n, asof, *, ahead=20., omega=8.):
    return {"date": str(asof.date()), "n": n, "tc": n - 1 + ahead, "m": .5, "w": omega,
            "A": 5., "B": -.01, "C1": .0001, "C2": .0001, "sse": .01,
            "r2": .95, "pow_B": -.01, "pow_m": .5, "y_std": .1}


def test_stock_adjusts_ohlc_not_volume_and_does_not_claim_volume_units():
    data, meta = normalise(payload(), "US_MRVL", datetime(2026, 11, 21, tzinfo=UTC))
    assert data.close.tolist() == [50, 110]
    assert data.open.tolist() == [50, 104]
    assert data.volume.tolist() == [5000, 6000]
    assert meta["volume_unit"] == "vendor_native"
    assert meta["public_redistribution"] == "NOT_ESTABLISHED"


def test_exchange_date_and_incomplete_session_cutoff():
    data, meta = normalise(payload(), "US_MRVL", datetime(2026, 11, 20, 18, tzinfo=UTC))
    assert data.date.dt.strftime("%Y-%m-%d").tolist() == ["2026-11-19"]
    assert meta["dropped_unclosed_bars"] == 1
    # Midnight UTC is still previous exchange date; do not label it UTC day.
    p = payload(dates=["2026-11-20T00:30:00+00:00", "2026-11-21T00:30:00+00:00"])
    data, _ = normalise(p, "US_MRVL", datetime(2026, 11, 22, tzinfo=UTC))
    assert data.date.dt.strftime("%Y-%m-%d").tolist() == ["2026-11-19", "2026-11-20"]


def test_wrong_identity_or_missing_stock_adjustment_rejected():
    with pytest.raises(ValueError, match="identity"):
        normalise(payload(symbol="AAPL"), "US_MRVL", datetime(2026, 11, 21, tzinfo=UTC))
    p = payload()
    del p["chart"]["result"][0]["indicators"]["adjclose"]
    with pytest.raises(ValueError, match="adjusted closes"):
        normalise(p, "US_MRVL", datetime(2026, 11, 21, tzinfo=UTC))


def test_index_close_unchanged_and_missing_ohlc_not_invented():
    p = payload(symbol="^GSPC")
    del p["chart"]["result"][0]["indicators"]["quote"][0]["open"]
    data, meta = normalise(p, "US_SPX", datetime(2026, 11, 21, tzinfo=UTC))
    assert data.close.tolist() == [100, 110]
    assert data.open.isna().all()
    assert meta["adjustment"] == "none"


def test_asof_plan_is_exact_trading_rows_and_input_hash_ignores_future():
    data = frame(40)
    dates = pipeline.selected_asofs(data)
    assert dates == [data.date.iloc[-1], data.date.iloc[-6], data.date.iloc[-11]]
    cutoff = data.date.iloc[-11]
    original = pipeline.fit_key(data, cutoff, 14, "g3", {"hash": "frozen"})
    changed = data.copy()
    changed.loc[changed.date > cutoff, "close"] = 9999.
    assert pipeline.fit_key(changed, cutoff, 14, "g3", {"hash": "frozen"}) == original
    changed.loc[changed.date == cutoff, "close"] = 9999.
    assert pipeline.fit_key(changed, cutoff, 14, "g3", {"hash": "frozen"}) != original
    with pytest.raises(ValueError, match="Exact as-of"):
        pipeline.fit_key(data, pd.Timestamp("2026-11-22"), 14, "g3", {"hash": "frozen"})


def test_complete_cycles_rule_is_separate_from_production_box():
    rows = [row(252, pd.Timestamp("2026-11-20"), ahead=10),
            row(21, pd.Timestamp("2026-11-20"), ahead=90),
            row(252, pd.Timestamp("2026-11-20"), ahead=-10)]
    derived, rules = pipeline.derived_and_rules(rows)
    assert rules.box.tolist() == [True, True, False]
    assert rules.box_cycles_1_5.tolist() == [True, False, False]
    assert derived.n_osc.iloc[0] == pytest.approx(8 / (2 * np.pi) * np.log(261 / 10))
    counts = pipeline.filter_diagnostics(derived, rules)
    assert counts["completed"] == 3
    assert counts["box_qualified"] == 2
    assert counts["cycles_1_5_qualified"] == 1
    assert counts["tc_inside_sample"] == 1


def test_incomplete_plan_never_aggregates_as_complete():
    data = frame()
    with pytest.raises(ValueError, match="incomplete window plan"):
        pipeline.make_record("US_SPX", data, {}, data.date.iloc[-1], [], {})


def test_qualified_fit_without_minimum_cluster_is_distinct():
    asof = pd.Timestamp("2026-11-20")
    derived, rules = pipeline.derived_and_rules([row(252, asof, ahead=10)])
    result = pipeline.aggregate(derived, rules, asof, pd.bdate_range(end=asof, periods=252), "us")
    assert result["lppls_confidence"]["6-12m"] == 1
    assert result["scale_clusters"]["6-12m"] == []
    assert result["signal_status"] == "no_cluster"
    assert result["indicators"]["6-12m"]["signal_status"] == "no_cluster"


def test_history_snapshot_has_only_asof_prices_and_independent_research():
    data = frame()
    asof = data.date.iloc[-6]
    metadata = {"source": "test fixture only", "asof": str(data.date.iloc[-1].date()),
                "adjustment": "none", "volume_unit": "vendor_native", "timezone": "America/New_York",
                "exchange": "NMS", "normalized_sha256": "fixture"}
    cells = [{"n": n, "status": "complete", "row": row(n, asof), "fit_input_hash": f"frozen-{n}"}
             for n in pipeline.WINDOWS]
    record = pipeline.make_record("US_SPX", data, metadata, asof, cells, {"hash": "fixture", "source_sha": "fixture"})
    assert record["price_history"]["dates"][-1] == str(asof.date())
    assert record["source_meta"]["model_asof"] == str(asof.date())
    assert record["source_meta"]["source_asof"] > record["source_meta"]["model_asof"]
    assert record["top"]["drawdown_price"]["value"] is None
    assert record["validation"] == []
    assert record["first_visible_at"] is None
    assert record["future_calendar"]["status"] == "weekday_estimate"
    assert record["future_calendar"]["verified"] is False
    historical = pipeline.history_frame(record)
    assert historical["research"]["cycles_1_5"] == record["research"]["cycles_1_5"]
    assert historical["params"] == record["params"]
    assert historical["snapshot_path"] == f"global/US_SPX_{asof.date()}.json"


def test_nonfinite_values_serialize_as_null():
    # Only test serialization: numerical production optimizer already has its own tests.
    value = pipeline.clean({"sse": np.float64(.5), "bad": np.nan, "n": np.int64(10)})
    assert value == {"sse": .5, "bad": None, "n": 10}


def test_transient_windows_reader_lock_retries_atomically(monkeypatch, tmp_path):
    attempts = []
    def locked_once(path, value):
        attempts.append((path, value))
        if len(attempts) == 1:
            raise PermissionError("reader briefly holds file")
    monkeypatch.setattr(pipeline, "_atomic_json", locked_once)
    monkeypatch.setattr(pipeline.time, "sleep", lambda _: None)
    pipeline.atomic_json(tmp_path / "progress.json", {"complete": 1})
    assert len(attempts) == 2


def test_same_raw_payload_different_close_cutoff_preserves_both_vintages(tmp_path):
    p = payload()
    raw = json.dumps(p).encode()
    before, info_before = normalise(p, "US_MRVL", datetime(2026, 11, 20, 18, tzinfo=UTC))
    after, info_after = normalise(p, "US_MRVL", datetime(2026, 11, 21, tzinfo=UTC))
    old = save_snapshot(tmp_path, raw, before, info_before)
    original = (tmp_path / old["normalized_file"]).read_bytes()
    new = save_snapshot(tmp_path, raw, after, info_after)
    assert old["raw_sha256"] == new["raw_sha256"]
    assert old["normalized_file"] != new["normalized_file"]
    assert old["metadata_file"] != new["metadata_file"]
    assert (tmp_path / old["normalized_file"]).read_bytes() == original
    assert (tmp_path / old["metadata_file"]).exists()


def mini_record(asof="2026-11-20", version="one"):
    return {"symbol": "US_SPX", "name": "fixture", "asof": asof, "model_version": "fixture",
            "fit_code_version": version, "data_version": version, "generated_at": "2026-11-23T00:00:00Z",
            "price_history": {"close": [100]}, "top": {"scale_windows": [], "scale_clusters": {},
                "lppls_confidence": {s: 0 for s in pipeline.SCALES}}, "stock_meta": {},
            "research": {}, "params": {}, "future_calendar": {}, "source": "fixture", "source_meta": {}}


def test_archive_and_history_keep_earlier_dates_and_same_date_versions(tmp_path):
    older = mini_record("2026-11-06")
    first = mini_record()
    revised = mini_record(version="two")
    pipeline.export_record(tmp_path, older, False)
    pipeline.export_record(tmp_path, first, True)
    first_path = tmp_path / "US_SPX_2026-11-20.json"
    previous = json.loads(first_path.read_text(encoding="utf-8"))
    historical = pipeline.export_record(tmp_path, revised, True)
    assert [f["asof"] for f in historical["frames"]] == ["2026-11-06", "2026-11-20"]
    assert len(historical["revisions"]) == 1
    assert historical["revisions"][0]["record_version"] == previous["record_version"]
    assert len(list((tmp_path / "archive/US_SPX/2026-11-20").glob("*.json"))) == 2
    later_export = copy.deepcopy(revised)
    later_export["generated_at"] = "2026-11-24T00:00:00Z"
    pipeline.export_record(tmp_path, later_export, True)
    assert len(list((tmp_path / "archive/US_SPX/2026-11-20").glob("*.json"))) == 2


def test_archive_tampering_is_detected_before_alias_update(tmp_path):
    record = mini_record()
    stored = pipeline.archive_record(tmp_path, record)
    path = tmp_path / stored["archive_path"].removeprefix("global/")
    stored["price_history"]["close"] = [999]
    path.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(ValueError, match="identity mismatch"):
        pipeline.archive_record(tmp_path, record)


def test_git_head_is_provenance_not_fit_cache_identity(monkeypatch):
    monkeypatch.setattr(pipeline.subprocess, "check_output", lambda *a, **k: "a" * 40)
    before = pipeline.method_identity()
    monkeypatch.setattr(pipeline.subprocess, "check_output", lambda *a, **k: "b" * 40)
    after = pipeline.method_identity()
    assert before["source_sha"] != after["source_sha"]
    assert before["hash"] == after["hash"]
    monkeypatch.setattr(pipeline.inspect, "getsource", lambda _: "def fit_job(task):\n    return task\n")
    changed = pipeline.method_identity()
    assert changed["hash"] != after["hash"]


def test_raw_output_under_git_repository_rejected():
    with pytest.raises(ValueError, match="outside the Git repository"):
        pipeline.checked_root(pipeline.ROOT / "data/global-test")


def mock_runner(monkeypatch, data=None):
    data = frame(40) if data is None else data
    meta = {"asof": str(data.date.iloc[-1].date()), "source": "fixture"}
    monkeypatch.setattr(pipeline, "WINDOWS", (10,))
    monkeypatch.setattr(pipeline, "fetch_snapshot", lambda *a, **k: (data, meta))
    monkeypatch.setattr(pipeline, "method_identity", lambda: {"hash": "mock"})
    monkeypatch.setattr(pipeline, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(pipeline.time, "sleep", lambda _: None)
    def fit(task):
        return {"status": "complete", "asset_id": task["asset_id"], "asof": task["asof"], "n": task["n"],
                "fit_input_hash": task["key"], "row": row(task["n"], pd.Timestamp(task["asof"]))}
    monkeypatch.setattr(pipeline, "fit_job", fit)
    def export_failure(*args):
        raise RuntimeError("fixture exporter failure")
    monkeypatch.setattr(pipeline, "make_record", export_failure)
    return data


def test_completed_fits_with_export_failure_never_reports_complete(monkeypatch, tmp_path):
    mock_runner(monkeypatch)
    result = pipeline.run(tmp_path, ["US_SPX"], 1, 30)
    assert result["counts"]["completed"] == 3
    assert result["counts"]["exports_completed"] == 0
    assert result["counts"]["exports_failed"] == 3
    assert result["status"] == "partial"
    assert all(item["stage"] == "export" for item in result["errors"])


def test_corrupt_fit_cache_does_not_abort_other_dates(monkeypatch, tmp_path):
    data = mock_runner(monkeypatch)
    asof = data.date.iloc[-1]
    key = pipeline.fit_key(data, asof, 10, "g3", {"hash": "mock"})
    path = tmp_path / "fits/US_SPX" / str(asof.date()) / f"10-{key}.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")
    result = pipeline.run(tmp_path, ["US_SPX"], 1, 30)
    assert result["counts"]["completed"] == 2
    assert result["counts"]["failed"] == 1
    assert result["status"] == "partial"
    assert result["errors"][0]["stage"] == "cache"
    assert path.read_text(encoding="utf-8") == "not json"


def test_short_source_is_recorded_as_source_failure(monkeypatch, tmp_path):
    mock_runner(monkeypatch, frame(3))
    result = pipeline.run(tmp_path, ["US_SPX"], 1, 30)
    assert result["counts"]["source_failed"] == 1
    assert result["assets"][0]["status"] == "source_failed"
    assert result["status"] == "partial"


def frozen_small_run(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "WINDOWS", (10,))
    data = frame(40)
    metadata = {"id": "US_SPX", **pipeline.ASSETS["US_SPX"], "source": "test fixture only",
                "asof": str(data.date.iloc[-1].date()), "adjustment": "none", "volume_unit": "vendor_native", "exchange": "test"}
    metadata = save_snapshot(tmp_path / "source/US_SPX", b"fixture", data, metadata)
    method = pipeline.method_identity()
    dates = pipeline.selected_asofs(data)
    for asof in dates:
        key = pipeline.fit_key(data, asof, 10, "g3", method)
        path = tmp_path / "fits/US_SPX" / str(asof.date()) / f"10-{key}.json"
        pipeline.atomic_json(path, {"status": "complete", "asset_id": "US_SPX", "asof": str(asof.date()),
            "n": 10, "fit_input_hash": key, "row": row(10, asof)})
    manifest = {"status": "complete", "counts": {"completed": 3, "failed": 0}, "method": method,
                "assets": [{"id": "US_SPX", "source_meta": metadata, "completed_asofs": [str(d.date()) for d in dates]}]}
    path = tmp_path / "frozen-run.json"
    pipeline.atomic_json(path, manifest)
    return path, metadata


def test_export_only_uses_exact_frozen_source_and_never_downloads_or_starts_pool(monkeypatch, tmp_path):
    path, _ = frozen_small_run(monkeypatch, tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("No download or optimizer pool in export-only mode")
    monkeypatch.setattr(pipeline, "fetch_snapshot", forbidden)
    monkeypatch.setattr(pipeline, "ProcessPoolExecutor", forbidden)
    result = pipeline.reexport_cached(tmp_path, path)
    assert result["status"] == "complete"
    assert result["counts"]["exports_completed"] == 3
    assert len(list((tmp_path / "global/archive/US_SPX").glob("*/*.json"))) == 3
    historical = json.loads((tmp_path / "global/US_SPX_history.json").read_text(encoding="utf-8"))
    assert len(historical["frames"]) == 3


def test_export_only_rejects_corrupt_source(monkeypatch, tmp_path):
    path, metadata = frozen_small_run(monkeypatch, tmp_path)
    (tmp_path / "source/US_SPX" / metadata["raw_file"]).write_bytes(b"corrupt")
    result = pipeline.reexport_cached(tmp_path, path)
    assert result["status"] == "partial"
    assert result["counts"]["exports_completed"] == 0
    assert "checksum" in result["errors"][0]["error"]


@pytest.mark.parametrize("invalid", [np.nan, 0.])
def test_missing_ohlc_is_labeled_not_synthesized(invalid):
    data = frame()
    asof = data.date.iloc[-1]
    data.loc[data.date == asof, "open"] = invalid
    metadata = {"source": "fixture", "asof": str(asof.date()), "adjustment": "none", "volume_unit": "vendor_native",
                "timezone": "Asia/Seoul", "exchange": "KSE", "normalized_sha256": "fixture"}
    cells = [{"n": n, "status": "complete", "row": row(n, asof), "fit_input_hash": str(n)} for n in pipeline.WINDOWS]
    record = pipeline.make_record("KR_KOSPI", data, metadata, asof, cells, {"hash": "fixture", "source_sha": "fixture"})
    price = record["price_history"]
    assert price["ohlc_missing_dates"] == [str(asof.date())]
    assert price["ohlc_missing_count"] == 1
    assert price["last_bar_kind"] == "close_only"
    assert price["open"][-1] is None
    assert price["ohlc_invalid_fields"][str(asof.date())] == ["open"]
    assert price["high"][-1] == 102.
