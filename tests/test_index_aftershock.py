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
        "data_version": "fixture-v1",
        "price_history": {"source": "history-source"},
        "top": {},
        "research": {"existing": True},
    }
    path.write_text(json.dumps(record))
    source = pd.DataFrame(
        {"date": dates, "close": [100.0, 101.0, 99.0, 102.0, 103.0]}
    )
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
        "data_version": "fixture-v1",
        "source": "history-source",
        "timezone": None,
    }
    assert captured["archive_root"] is None
    assert published["research"] == {"existing": True, "aftershock": expected}
