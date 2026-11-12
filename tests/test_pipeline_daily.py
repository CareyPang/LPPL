import json
from pathlib import Path

import pandas as pd
import pytest

from research.eval import export_contract
from research.eval.export_contract import _price_history
from research.features.lppls_rules import SCALES_FCO
from research.pipeline import daily, stock


def test_price_history_contains_aligned_point_in_time_ohlcv():
    dates = pd.date_range("2024-01-02", periods=3, freq="B")
    ohlc = pd.DataFrame(
        {
            "date": dates,
            "open": [10.0, 11.0, 12.0],
            "high": [11.5, 12.5, 13.5],
            "low": [9.5, 10.5, 11.5],
            "close": [11.0, 12.0, 13.0],
            "volume": [1000, 2000, 3000],
        }
    )

    history = _price_history(ohlc, dates, pd.Timestamp("2024-01-03"))

    assert history["dates"] == ["2024-01-02", "2024-01-03"]
    assert all(len(history[key]) == len(history["dates"]) for key in ("open", "high", "low", "close", "volume"))
    assert all(isinstance(value, int) for value in history["volume"])
    for open_, high, low, close in zip(
        history["open"], history["high"], history["low"], history["close"], strict=True
    ):
        assert high >= max(open_, close) >= min(open_, close) >= low

    without_volume = _price_history(ohlc.drop(columns="volume"), dates, pd.Timestamp("2024-01-03"))
    assert without_volume["volume"] == [None, None]


@pytest.mark.skipif(not Path("data/frozen/v20261024").exists(), reason="需要冻结数据")
def test_daily_frozen_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("LPPLS_BOX", "v2")
    p = daily.run("sh000001", frozen=True, asof="2015-06-12", windows=(130, 200, 300), out=tmp_path, trust_boot=2)
    rec = json.loads(p.read_text())
    conf = rec["top"]["lppls_confidence"]
    assert set(["1-3m", "6-12m", "12-24m"]) <= set(conf)
    assert rec["top"]["p20"]["evidence"] == "fail_i_iii"
    assert rec["top"]["bubble"]["evidence"] == "descriptive"
    assert rec["data_version"].startswith("frozen_")


def test_daily_and_stock_full_share_unique_windows_and_trust_targets(
    tmp_path, monkeypatch
):
    from research.lppls import trust as trust_module

    dates = pd.bdate_range("2010-01-04", periods=1600)
    ohlc = pd.DataFrame({"date": dates, "close": 100.0})
    captured = {}
    monkeypatch.setattr(daily, "load_ohlc", lambda *_args: (ohlc, "fixture-v1"))

    def fit_asof(_logp, asof, windows):
        captured["windows"] = tuple(windows)
        return pd.DataFrame({"date": asof, "n": windows})

    def trust(_logp, _date, rows, b):
        captured["trust_windows"] = rows.n.tolist()
        captured["trust_boot"] = b
        return {"fixture": True}

    monkeypatch.setattr(daily, "fit_asof", fit_asof)
    monkeypatch.setattr(daily, "_derived", lambda rows: rows)
    monkeypatch.setattr(daily, "rules", lambda rows: pd.DataFrame(index=rows.index))
    monkeypatch.setattr(daily, "build_record", lambda *_args, **_kwargs: {"top": {}})
    monkeypatch.setattr(trust_module, "trust", trust)

    daily.run(
        "sh000001",
        asof=str(dates[-1].date()),
        out=tmp_path,
        trust_boot=7,
    )

    assert len(captured["windows"]) == 181
    assert len(set(captured["windows"])) == 181
    assert captured["windows"] == stock._variant_windows("stk_full", len(ohlc))
    assert len(captured["trust_windows"]) == 26
    assert len(set(captured["trust_windows"])) == 26
    assert set(captured["trust_windows"]) == set(range(125, 751, 25))
    stored = pd.read_parquet(
        tmp_path / "fits" / f"sh000001_{dates[-1].date()}.parquet"
    )
    assert not stored.duplicated(["date", "n"]).any()


def test_deduplicating_full_windows_preserves_six_to_twelve_month_top_window():
    date = pd.Timestamp("2024-06-28")
    cal = pd.bdate_range("2022-01-03", periods=800)
    base = pd.DataFrame(
        {
            "date": date,
            "n": [127, 152, 177, 202, 227],
            "ahead": [10.0, 20.0, 30.0, 40.0, 50.0],
        }
    )
    overlap = pd.DataFrame(
        {
            "date": date,
            "n": [525, 550, 575, 600, 625, 650, 675, 700, 725, 750] * 2,
            "ahead": [60.0, 70.0, 80.0, 90.0, 100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
            * 2,
        }
    )
    duplicated = pd.concat([base, overlap], ignore_index=True)
    deduplicated = duplicated.drop_duplicates(["date", "n"], keep="first")

    before = export_contract._top_window(
        export_contract.scale_windows(duplicated, SCALES_FCO), cal, date
    )
    after = export_contract._top_window(
        export_contract.scale_windows(deduplicated, SCALES_FCO), cal, date
    )

    assert before == after
