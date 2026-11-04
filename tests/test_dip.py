import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from research.dip import events, panel
from research.dip.env import _share_summary
from research.pipeline import stock


def _prices(close: np.ndarray, start: str = "2024-01-02") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.bdate_range(start, periods=len(close)),
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1000.0,
            "amount": 100_000.0,
        }
    )


def _rise_and_fall() -> pd.DataFrame:
    close = np.array([100.0] * 400 + np.linspace(100.0, 400.0, 100).tolist())
    close = np.append(close, [300.0, 240.0, 180.0, 175.0])
    return _prices(close)


def test_events_emit_each_depth_once_on_the_first_matching_date(tmp_path):
    path = tmp_path / "sh600519.parquet"
    _rise_and_fall().to_parquet(path, index=False)

    event_rows, _ = events.one(path, False)
    frame = pd.DataFrame(event_rows)

    assert frame.depth.tolist() == [-0.4, -0.5]
    assert frame.sig_date.tolist() == [
        _rise_and_fall().date.iloc[501].date().isoformat(),
        _rise_and_fall().date.iloc[502].date().isoformat(),
    ]


def test_delisted_outcomes_truncate_and_record_no_touch_as_l():
    close = np.array([100.0, 105.0, 108.0, 109.0, 110.0])
    dates = pd.bdate_range("2020-01-01", periods=len(close))

    outcome = events.outcomes(close, dates, 0, True)

    assert outcome["r60"] == pytest.approx(0.1)
    assert outcome["mdd60"] == pytest.approx(0.05)
    assert outcome["up60"] == pytest.approx(0.1)
    assert outcome["cens60"] is True
    assert outcome["fh60"] == "L"
    assert outcome["fh120"] == "L"


def test_outcomes_use_entry_close_and_future_extrema():
    close = np.full(251, 110.0)
    close[0] = 100.0
    close[1] = 90.0
    close[2] = 130.0
    close[60] = 120.0
    close[120] = 115.0
    close[250] = 105.0
    dates = pd.bdate_range("2020-01-01", periods=len(close))

    outcome = events.outcomes(close, dates, 0, False)

    assert outcome["r60"] == pytest.approx(0.2)
    assert outcome["mdd60"] == pytest.approx(-0.1)
    assert outcome["up60"] == pytest.approx(0.3)
    assert outcome["r120"] == pytest.approx(0.15)
    assert outcome["r250"] == pytest.approx(0.05)
    assert outcome["mdd120"] == pytest.approx(-0.1)
    assert outcome["up120"] == pytest.approx(0.3)


def _write_library(tmp_path, rows):
    event_path = tmp_path / "events.parquet"
    pd.DataFrame(rows).to_parquet(event_path, index=False)
    payload = {
        "version": "test",
        "cutoff": "2026-11-03",
        "n_stocks": len({row["sym"] for row in rows}),
        "n_events": len(rows),
        "events_file": event_path.name,
        "sha256": hashlib.sha256(event_path.read_bytes()).hexdigest(),
        "smoke": False,
    }
    (tmp_path / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    pd.DataFrame({"sym": ["sh600519"], "sw1_name": ["测试行业"]}).to_csv(
        tmp_path / "sw1_current.csv", index=False
    )


def test_panel_structure_and_outside_structure_keep_expected_shape(tmp_path, monkeypatch):
    _write_library(
        tmp_path,
        [
            {
                "sym": "sh600519",
                "depth": -0.4,
                "sig_date": "2018-01-01",
                "entry_date": "2018-01-01",
                "sw1": "测试行业",
                "delisted": False,
                "r60": np.nan,
                "r120": np.nan,
                "r250": np.nan,
                "mdd120": np.nan,
                "up120": np.nan,
                "fh60": "U",
                "fh120": "L",
            }
            for _ in range(30)
        ],
    )
    monkeypatch.setattr(
        panel,
        "_regime",
        lambda prices: {
            "p_hi_filtered": None,
            "hi_vol_ann": None,
            "lo_vol_ann": None,
            "hi_mean_wk": None,
            "lo_mean_wk": None,
            "weeks": 100,
            "note": "波动体制，不是涨跌信号",
        },
    )
    prices = _rise_and_fall()
    prices.attrs["sym"] = "sh600519"

    result = panel.build_panel(prices, tmp_path)

    assert result["in_structure"] is True
    assert result["oos"] == {"items": {}, "label": "样本外检验未完成"}
    verdict = {"items": {"H1": "failed"}, "label": "样本外未通过，仅描述"}
    (tmp_path / "oos_verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False), encoding="utf-8"
    )
    assert panel.build_panel(prices, tmp_path)["oos"] == verdict
    assert result["depth_bucket"] == -0.5
    assert result["similar"]["full"]["n"] == 0
    assert result["similar"]["industry"] is None
    assert result["similar"]["industry_counts"] == {"n": 0, "n_delisted": 0}
    assert result["first_hit"]["fh60"]["hist"]["n"] == 0
    assert result["first_hit"]["fh60"]["rw"].keys() == {"U", "L", "none"}
    assert "well_dist_below" in result["state"]
    assert result["state"]["close"] is not None
    assert all(
        value is None
        for value in result["similar"]["full"]["q"]["r60"]
    )
    assert result["similar"]["full"]["n_outcome"] == {
        "r60": 0,
        "r120": 0,
        "r250": 0,
        "mdd120": 0,
        "up120": 0,
    }
    assert not any(
        isinstance(value, float) and np.isnan(value)
        for value in result["similar"]["full"]["q"]["r60"]
    )

    outside = _prices(np.full(600, 100.0))
    outside.attrs["sym"] = "sh600519"
    other = panel.build_panel(outside, tmp_path)
    assert other["in_structure"] is False
    assert other["similar"] is None
    assert other["first_hit"]["fh60"]["hist"] is None
    assert other["first_hit"]["fh60"]["rw"] is not None


def test_oos_verdict_loads_contents_and_missing_file_falls_back(tmp_path):
    path = tmp_path / "oos_verdict.json"

    assert panel._load_oos_verdict(path) == {
        "items": {},
        "label": "样本外检验未完成",
    }

    verdict = {"items": {"H1": "failed"}, "label": "样本外未通过，仅描述"}
    path.write_text(json.dumps(verdict, ensure_ascii=False), encoding="utf-8")
    assert panel._load_oos_verdict(path) == verdict


def test_state_uses_recent_well_features_and_returns_lower_distance(monkeypatch):
    prices = _prices(np.linspace(80.0, 160.0, 600))
    captured = {}

    def fake_well_features_at(x, r2, volume, x_now):
        captured["x"] = x.copy()
        captured["r2"] = r2.copy()
        captured["volume"] = volume.copy()
        captured["x_now"] = x_now
        return (0.0, 0.0, 0.125)

    monkeypatch.setattr(panel, "well_features_at", fake_well_features_at)

    state, _, _ = panel._state(prices)

    expected = prices.iloc[-500:]
    np.testing.assert_allclose(
        captured["x"],
        np.log((expected.high + expected.low + expected.close).to_numpy() / 3),
    )
    np.testing.assert_allclose(
        captured["r2"],
        (np.log(expected.high) - np.log(expected.low)).to_numpy() ** 2 / 12,
    )
    np.testing.assert_allclose(captured["volume"], expected.volume.to_numpy())
    assert captured["x_now"] == pytest.approx(np.log(prices.close.iloc[-1]))
    assert state["well_dist_below"] == pytest.approx(0.125)


def test_state_returns_null_when_there_is_no_lower_price_well(monkeypatch):
    prices = _prices(np.linspace(80.0, 160.0, 600))
    monkeypatch.setattr(
        panel, "well_features_at", lambda *args: (0.0, 0.0, np.nan)
    )

    state, _, _ = panel._state(prices)

    assert state["well_dist_below"] is None


def test_share_summary_uses_sse_10k_units_and_deduplicates_dates():
    dates = pd.date_range("2026-01-01", periods=22)
    rows = []
    for index, date in enumerate(dates):
        rows.append(
            {"date": date, "code": "510300", "shares": 1_000_000 + index * 1_000}
        )
        rows.append({"date": date, "code": "588000", "shares": 5_000_000})
    rows.append({"date": dates[1], "code": "510300", "shares": 1_001_000})

    summary = _share_summary(pd.DataFrame(rows), "510300")

    assert summary["n_days"] == 22
    assert summary["latest_date"] == "2026-01-22"
    assert summary["latest_shares_yi"] == pytest.approx(102.1)
    assert summary["change_20d_from"] == "2026-01-02"
    assert summary["change_20d_shares_yi"] == pytest.approx(2.0)
    assert summary["change_20d"] == pytest.approx(1_021_000 / 1_001_000 - 1)


def test_summary_reports_valid_sample_count_for_each_outcome():
    frame = pd.DataFrame(
        {
            "r60": [0.1, np.nan],
            "r120": [0.2, np.nan],
            "r250": [0.3, 0.4],
            "mdd120": [-0.2, np.nan],
            "up120": [0.4, 0.5],
            "delisted": [False, True],
            "fh60": ["U", "none"],
            "fh120": ["L", "none"],
        }
    )

    summary = panel._summary(frame)

    assert summary["n"] == 2
    assert summary["n_delisted"] == 1
    assert summary["n_outcome"] == {
        "r60": 1,
        "r120": 1,
        "r250": 2,
        "mdd120": 1,
        "up120": 2,
    }
    assert summary["p_up120_ge30"] == pytest.approx(1.0)
    assert summary["p_up120_ge50"] == pytest.approx(0.5)


def test_predict_adds_dip_without_changing_existing_record_fields(monkeypatch):
    prices = _prices(np.linspace(100.0, 150.0, 600))
    monkeypatch.setattr(
        stock,
        "load_stock",
        lambda code: (
            prices.copy(),
            "test-version",
            {"ipo_in_range": False, "dropped_unclosed_bar": False},
        ),
    )
    monkeypatch.setattr(stock, "_variant_windows", lambda variant, n: ())
    monkeypatch.setattr(stock, "_fit_pairs", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(stock, "_name_and_st", lambda code: ("Name", False))
    monkeypatch.setattr(
        stock,
        "_record",
        lambda *args, **kwargs: {"bottom": {"existing": True}, "top": {}},
    )
    monkeypatch.setattr(stock, "build_panel", lambda frame: {"evidence": "descriptive"})

    result = stock.predict("600519")

    assert result["bottom"] == {"existing": True}
    assert result["dip"] == {"evidence": "descriptive"}
