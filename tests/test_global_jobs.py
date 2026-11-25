"""Local job orchestration boundaries: no HTTP, processes or model fitting."""
import copy
from concurrent.futures import Future

import pandas as pd
import pytest

from research.data import global_events
from research.pipeline import global_jobs as jobs
from research.pipeline.global_terminal import SCALES


class QueuedExecutor:
    def __init__(self, **_):
        self.submitted = []

    def submit(self, function, *args):
        self.submitted.append((function, args))
        return Future()


class InlinePool:
    def __init__(self, **_):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def submit(self, function, *args):
        future = Future()
        try:
            future.set_result(function(*args))
        except Exception as error:
            future.set_exception(error)
        return future


def frame():
    return pd.DataFrame({"date": pd.bdate_range(end="2026-11-20", periods=35),
                         "close": [100.+i for i in range(35)]})


def record(symbol="US_IXIC", asof="2026-11-20", version="original"):
    return {"symbol": symbol, "asof": asof, "name": symbol, "data_version": "prices",
            "record_version": version, "model_version": "frozen-model", "fit_code_version": "math",
            "price_history": {"dates": [asof], "close": [100.]}, "top": {
                "scale_windows": [], "scale_clusters": {}, "lppls_confidence": {s: 0 for s in SCALES}},
            "research": {"cycles_1_5": {"sentinel": "keep-existing-model"}}, "params": {},
            "stock_meta": {"evidence": "research_candidate"}, "future_calendar": {},
            "source": "fixture", "source_meta": {}}


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "ThreadPoolExecutor", QueuedExecutor)
    monkeypatch.setattr(jobs, "ProcessPoolExecutor", InlinePool)
    return jobs.GlobalJobs(tmp_path/"jobs", tmp_path/"sources")


@pytest.fixture
def execution(service, monkeypatch):
    calls = {"fit": [], "make": [], "fetch": [], "events": []}
    data = frame()
    monkeypatch.setattr(jobs, "WINDOWS", (10, 14, 18))
    monkeypatch.setattr(jobs, "method_identity", lambda: {"hash": "frozen-math"})

    def fetch(symbol, root, refresh, full_history=False):
        calls["fetch"].append((symbol, refresh))
        return data.copy(), {"source": "fixture"}

    def fit(task):
        calls["fit"].append(copy.deepcopy(task))
        return {"status": "complete", "asset_id": task["asset_id"], "asof": task["asof"],
                "n": task["n"], "fit_input_hash": task["key"], "row": {"fixture": True}}

    def make(symbol, all_data, metadata, asof, cells, method):
        calls["make"].append((symbol, str(asof.date()), copy.deepcopy(cells)))
        value = record(symbol, str(asof.date()))
        value.pop("record_version")  # make_record returns an unsealed result, like production.
        prefix = all_data[all_data.date <= asof]
        value["price_history"] = {"dates": prefix.date.dt.strftime("%Y-%m-%d").tolist(),
                                  "close": prefix.close.tolist()}
        return value

    def events(symbol, root, asof, **options):
        calls["events"].append((symbol, asof, options))
        return {"symbol": symbol, "asof": asof, "mode": options["mode"], "status": "ready",
                "items": [], "model_input": False}

    def aftershock(value):
        return {**value, "research": {**value["research"], "aftershock": {
            "symbol": value["symbol"], "asof": value["asof"], "status": "complete"}}}

    monkeypatch.setattr(jobs, "fetch_snapshot", fetch)
    monkeypatch.setattr(jobs, "load_cached_snapshot", lambda symbol, root: fetch(symbol, root, False))
    monkeypatch.setattr(jobs, "fit_job", fit)
    monkeypatch.setattr(jobs, "make_record", make)
    monkeypatch.setattr(global_events, "collect_market_events", events)
    monkeypatch.setattr(service, "_aftershock", aftershock)
    return calls


@pytest.mark.parametrize("body", [None, [], {"symbol": "MRVL"}, {"symbol": "UNKNOWN"},
    {"symbol": "US_NDX", "refresh": "true"}, {"symbol": "US_NDX", "asof": "2026-02-30"},
    {"symbol": "US_NDX", "asof": "2026-1-01"}, {"symbol": "US_NDX", "asof": True}])
def test_start_rejects_invalid_parameters_without_enqueuing(service, body):
    with pytest.raises((ValueError, TypeError)):
        service.start(body)
    assert service.executor.submitted == []
    assert service.active == {}


def test_start_deduplicates_same_asset_and_cutoff(service):
    first = service.start({"symbol": "us_ndx", "asof": "2026-11-20", "refresh": False})
    again = service.start({"symbol": "US_NDX", "asof": "2026-11-20", "refresh": True})
    assert first["job_id"] == again["job_id"]
    assert len(service.executor.submitted) == 1
    assert service.executor.submitted[0][1][-1] is False
    assert first["status"] == "queued"
    assert service.capabilities()["history_auto_run"] is False


def test_distinct_cutoffs_are_separate_jobs_and_queue_is_bounded(service):
    for day in range(1, 9):
        service.start({"symbol": "US_NDX", "asof": f"2026-11-{day:02}"})
    with pytest.raises(RuntimeError, match="队列"):
        service.start({"symbol": "US_NDX", "asof": "2026-11-09"})
    assert len(service.active) == 8
    assert len(service.executor.submitted) == 8


def test_historical_job_fits_one_exact_endpoint_and_never_later_prices(service, execution):
    job = service.start({"symbol": "US_IXIC", "asof": "2026-11-13", "refresh": False})
    service._run(job["job_id"], False)
    final = service.get(job["job_id"])
    assert final["status"] == "complete"
    assert len(execution["make"]) == 1
    assert len(execution["fit"]) == 3
    assert {task["asof"] for task in execution["fit"]} == {"2026-11-13"}
    assert all(max(task["dates"]) == "2026-11-13" for task in execution["fit"])
    assert all(len(task["dates"]) == task["n"] for task in execution["fit"])
    assert all(call[2]["mode"] == "historical" for call in execution["events"])
    assert service.result(job["job_id"])["price_history"]["dates"][-1] == "2026-11-13"
    assert service.active == {}
    assert not (service.root/"pointers/US_IXIC_latest.json").exists()


def test_unavailable_exact_day_fails_instead_of_nearest_session(service, execution):
    job = service.start({"symbol": "US_IXIC", "asof": "2026-11-14"})
    service._run(job["job_id"], True)
    final = service.get(job["job_id"])
    assert final["status"] == "failed"
    assert "不会用邻近日期" in final["error"]
    assert execution["fit"] == []
    assert service.active == {}


def test_current_job_fetches_current_news_only_after_model_is_ready(service, execution, monkeypatch):
    transitions = []
    update = service._update

    def observe(job_id, **changes):
        transitions.append(changes.get("status"))
        update(job_id, **changes)

    monkeypatch.setattr(service, "_update", observe)
    job = service.start({"symbol": "US_IXIC"})
    service._run(job["job_id"], True)
    assert transitions.index("current_ready") < transitions.index("complete")
    assert execution["events"][-1][2] == {"refresh": True, "mode": "current"}
    assert service.result(job["job_id"])["research"]["market_events"]["mode"] == "current"
    assert service.selected_result("US_IXIC")["job_id"] == job["job_id"]


def test_historical_enrichment_discards_current_news_without_mutating_original(service, execution):
    original = record()
    original["research"]["market_events"] = {"mode": "current", "items": [{"title": "future headline"}]}
    before = copy.deepcopy(original)
    replay = service.enrich(original, historical=True)
    assert replay["research"]["market_events"]["mode"] == "historical"
    assert replay["research"]["market_events"]["items"] == []
    assert original == before
    assert replay["top"] == before["top"]
    assert replay["research"]["cycles_1_5"] == before["research"]["cycles_1_5"]


def test_aftershock_and_news_failure_preserve_lppl_and_clear_current_headlines(service, execution, monkeypatch):
    def failed(*_args, **_kwargs):
        raise RuntimeError("supplement unavailable")

    monkeypatch.setattr(service, "_aftershock", failed)
    monkeypatch.setattr(global_events, "collect_market_events", failed)
    original = record()
    original["research"]["market_events"] = {"mode": "current", "items": [{"title": "future"}]}
    enriched = service.enrich(original, historical=True)
    assert enriched["top"] == original["top"]
    assert enriched["price_history"] == original["price_history"]
    assert enriched["research"]["aftershock"]["status"] == "failed"
    assert enriched["research"]["market_events"]["status"] == "failed"
    assert enriched["research"]["market_events"]["items"] == []
    job = service.start({"symbol": "US_IXIC"})
    service._run(job["job_id"], True)
    assert service.get(job["job_id"])["status"] == "complete"
    result = service.result(job["job_id"])
    assert result["top"] == original["top"]
    assert result["research"]["aftershock"]["status"] == "failed"


def store_result(service, value, job_id):
    value = copy.deepcopy(value)
    value["fixture_version_label"] = value.pop("record_version")
    value["record_version"] = jobs.identity(value)
    service.jobs[job_id] = {"job_id": job_id, "symbol": value["symbol"], "asof": value["asof"], "status": "complete"}
    jobs.atomic_json(service.root/"results"/f"{job_id}.json", value)
    jobs.atomic_json(service.root/"pointers"/f"{value['symbol']}_{value['asof']}.json",
                     {"job_id": job_id, "asof": value["asof"], "record_version": value["record_version"]})
    return value


def test_history_adds_new_date_but_keeps_existing_selected_frame_exactly(service, execution):
    old = {"asof": "2026-11-13", "record_version": "original", "immutable_sentinel": "preserve"}
    existing = {"frames": [old], "revisions": []}
    before = copy.deepcopy(existing)
    store_result(service, record(asof="2026-11-13", version="new-same-day"), "a"*32)
    store_result(service, record(asof="2026-11-20", version="new-date"), "b"*32)
    history = service.history("US_IXIC", existing)
    assert [row["asof"] for row in history["frames"]] == ["2026-11-13", "2026-11-20"]
    assert history["frames"][0] == old
    assert existing == before
    assert history["frames"][1]["research"]["market_events"]["mode"] == "historical"


@pytest.mark.parametrize("corruption", [None, {"asset_id": "US_NDX"}, {"asof": "2026-11-19"},
                                       {"n": 14}, {"fit_input_hash": "wrong"}, {"status": "failed"}])
def test_cached_fit_requires_all_identity_fields(service, execution, monkeypatch, corruption):
    monkeypatch.setattr(jobs, "WINDOWS", (10,))
    data = frame()
    asof = pd.Timestamp("2026-11-20")
    key = jobs.fit_key(data, asof, 10, "g3", {"hash": "frozen-math"})
    cached = {"asset_id": "US_IXIC", "asof": "2026-11-20", "n": 10,
              "fit_input_hash": key, "status": "complete", "row": {"cached": True}}
    cached.update(corruption or {})
    jobs.atomic_json(service.root/"fits"/f"{key}.json", cached)
    job = service.start({"symbol": "US_IXIC", "asof": "2026-11-20"})
    service._run(job["job_id"], False)
    final = service.get(job["job_id"])
    assert final["status"] == "complete"
    assert final["cache_reused"] == (1 if corruption is None else 0)
    assert len(execution["fit"]) == (0 if corruption is None else 1)


@pytest.mark.parametrize("field,bad", [("symbol", "US_NDX"), ("asof", "2026-11-19"), ("record_version", "wrong")])
def test_selected_pointer_cannot_return_wrong_identity(service, field, bad):
    value = record()
    value[field] = bad
    stored = store_result(service, value, "c"*32)
    jobs.atomic_json(service.root/"pointers/US_IXIC_2026-11-20.json",
                     {"job_id": "c"*32, "asof": "2026-11-20",
                      "record_version": "wrong" if field == "record_version" else stored["record_version"]})
    with pytest.raises((ValueError, KeyError)):
        service.selected_result("US_IXIC", "2026-11-20")


def test_refresh_failure_reuses_cache_with_stale_reason(service, execution, monkeypatch):
    def fetch(symbol, root, refresh, full_history=False):
        if refresh:
            raise ConnectionError("upstream unavailable")
        return frame(), {"source": "dated cache"}

    monkeypatch.setattr(jobs, "fetch_snapshot", fetch)
    job = service.start({"symbol": "US_IXIC"})
    service._run(job["job_id"], True)
    assert service.get(job["job_id"])["status"] == "complete"
    result = service.result(job["job_id"])
    assert result["source_status"] == "stale"
    assert "upstream unavailable" in result["stale_reason"]


def test_current_news_reads_new_daily_cache_without_mutating_archive_or_backfilling_history(service, execution, monkeypatch):
    original = record()
    original['research']['market_events'] = {'mode': 'current', 'items': [{'title': 'old cached title'}]}
    sealed = store_result(service, original, 'd' * 32)
    archive = service.root / 'results' / ('d' * 32 + '.json')
    before = archive.read_bytes()
    cached_title = ['new daily cache title']
    calls = []

    def cached_events(symbol, root, asof, **options):
        calls.append((symbol, root, asof, options))
        assert options.get('refresh', False) is False  # Rendering must never download news.
        return {'symbol': symbol, 'asof': asof, 'mode': options['mode'], 'status': 'ok',
                'items': [{'title': cached_title[0]}] if options['mode'] == 'current' else [],
                'model_input': False}

    monkeypatch.setattr(global_events, 'collect_market_events', cached_events)
    first = service.enrich(service.result('d' * 32), historical=False)
    assert first['research']['market_events']['items'][0]['title'] == 'new daily cache title'
    cached_title[0] = 'later daily cache title'
    second = service.enrich(service.result('d' * 32), historical=False)
    assert second['research']['market_events']['items'][0]['title'] == 'later daily cache title'
    historical = service.enrich(service.result('d' * 32), historical=True)
    assert historical['research']['market_events']['items'] == []
    assert historical['research']['market_events']['mode'] == 'historical'
    assert all(c[1] == service.source_root for c in calls)
    assert second['top'] == sealed['top'] and historical['price_history'] == sealed['price_history']
    assert archive.read_bytes() == before
    assert service.result('d' * 32) == sealed
