import json

import pandas as pd

from research.pipeline import index_daily


def test_index_daily_attaches_aftershock_from_pit_close_frame(tmp_path, monkeypatch):
    dates = pd.bdate_range("2026-01-05", periods=5)
    asof = str(dates[3].date())
    path = tmp_path / f"sh000300_{asof}.json"
    record = {
        "symbol": "sh000300",
        "asof": asof,
        "data_version": "vintage_2026-01-08_fixture",
        "price_history": {"source": "history-source"},
        "top": {},
        "research": {"existing": True},
    }
    path.write_text(json.dumps(record))
    source = pd.DataFrame(
        {"date": dates, "close": [100.0, 101.0, 99.0, 102.0, 103.0]}
    )
    source.attrs.update(vintage="2026-01-08", source="fixture")
    expected = {
        "schema_version": "aftershock_v1",
        "symbol": "sh000300",
        "asof": asof,
        "modules": {},
    }
    captured = {}

    def daily_run(*args, **kwargs):
        captured["daily_run"] = (args, kwargs)
        return path

    def cache_load(sym, **kwargs):
        captured["cache_load"] = (sym, kwargs)
        return source.copy()

    def analyze_aftershock(asset_id, frame, cutoff, metadata, archive_root=None):
        captured.update(
            asset_id=asset_id,
            frame=frame,
            cutoff=cutoff,
            metadata=metadata,
            archive_root=archive_root,
        )
        return expected

    monkeypatch.setattr(index_daily.daily, "run", daily_run)
    monkeypatch.setattr(index_daily.cache, "load", cache_load)
    monkeypatch.setattr(index_daily, "analyze_aftershock", analyze_aftershock)

    result_path = index_daily.run(
        "sh000300",
        asof=asof,
        windows=(125,),
        out=tmp_path,
        trust_boot=0,
        opt="g3",
    )
    published = json.loads(result_path.read_text())

    assert captured["daily_run"] == (
        ("sh000300",),
        {
            "frozen": False,
            "asof": asof,
            "windows": (125,),
            "out": tmp_path,
            "trust_boot": 0,
            "opt": "g3",
        },
    )
    assert captured["cache_load"] == (
        "sh000300",
        {"frozen": None, "auto_refresh": False},
    )
    assert captured["asset_id"] == "sh000300"
    assert captured["cutoff"] == asof
    assert captured["frame"].columns.tolist() == ["date", "close"]
    pd.testing.assert_frame_equal(
        captured["frame"].reset_index(drop=True),
        source.loc[source.date <= pd.Timestamp(asof), ["date", "close"]].reset_index(
            drop=True
        ),
    )
    assert captured["metadata"] == {
        "symbol": "sh000300",
        "asset_id": "sh000300",
        "data_version": "vintage_2026-01-08_fixture",
        "source": "history-source",
        "timezone": None,
    }
    assert captured["archive_root"] is None
    assert published["research"] == {"existing": True, "aftershock": expected}


def test_index_daily_keeps_fit_record_when_aftershock_enrichment_fails(
    tmp_path, monkeypatch, capsys
):
    asof = "2026-01-08"
    path = tmp_path / f"sh000300_{asof}.json"
    record = {
        "symbol": "sh000300",
        "asof": asof,
        "data_version": "vintage_2026-01-08_fixture",
        "top": {},
        "research": {"existing": True},
    }
    path.write_text(json.dumps(record))
    source = pd.DataFrame(
        {"date": pd.bdate_range("2026-01-05", periods=5), "close": [1, 2, 3, 4, 5]}
    )
    source.attrs.update(vintage="2026-01-08", source="fixture")

    monkeypatch.setattr(index_daily.daily, "run", lambda *_args, **_kwargs: path)
    monkeypatch.setattr(index_daily.cache, "load", lambda *_args, **_kwargs: source)

    def fail_analysis(*_args, **_kwargs):
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(index_daily, "analyze_aftershock", fail_analysis)

    result_path = index_daily.run("sh000300", asof=asof, out=tmp_path, trust_boot=0)
    published = json.loads(result_path.read_text())

    assert result_path == path
    assert "aftershock" not in published["research"]
    assert published["research"]["aftershock_status"] == {
        "status": "unavailable",
        "reason": "RuntimeError: fixture failure",
    }
    assert "aftershock enrichment unavailable for sh000300" in capsys.readouterr().err


def test_index_daily_skips_aftershock_for_mismatched_price_vintage(
    tmp_path, monkeypatch
):
    asof = "2026-01-08"
    path = tmp_path / f"sh000300_{asof}.json"
    record = {
        "symbol": "sh000300",
        "asof": asof,
        "data_version": "vintage_2026-01-07_fixture",
        "top": {},
        "research": {},
    }
    path.write_text(json.dumps(record))
    source = pd.DataFrame(
        {"date": pd.bdate_range("2026-01-05", periods=5), "close": [1, 2, 3, 4, 5]}
    )
    source.attrs.update(vintage="2026-01-08", source="fixture")
    cache_calls = []

    monkeypatch.setattr(index_daily.daily, "run", lambda *_args, **_kwargs: path)
    monkeypatch.setattr(
        index_daily.cache,
        "load",
        lambda *args, **kwargs: cache_calls.append((args, kwargs)) or source,
    )

    def unexpected_analysis(*_args, **_kwargs):
        raise AssertionError("analysis must not run across price vintages")

    monkeypatch.setattr(index_daily, "analyze_aftershock", unexpected_analysis)

    result_path = index_daily.run("sh000300", asof=asof, out=tmp_path, trust_boot=0)
    published = json.loads(result_path.read_text())

    assert result_path == path
    assert len(cache_calls) == 1
    assert "aftershock" not in published["research"]
    assert published["research"]["aftershock_status"] == {
        "status": "unavailable",
        "reason": "price_vintage_mismatch",
    }
