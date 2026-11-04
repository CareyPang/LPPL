import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from research.dip import events, panel
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
    event_path = tmp_path / "events_smoke.parquet"
    pd.DataFrame(rows).to_parquet(event_path, index=False)
    payload = {
        "version": "test",
        "cutoff": "2026-11-03",
        "n_stocks": 223,
        "n_events": len(rows),
        "events_file": event_path.name,
        "sha256": hashlib.sha256(event_path.read_bytes()).hexdigest(),
        "smoke": True,
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
    assert result["depth_bucket"] == -0.5
    assert result["similar"]["full"]["n"] == 0
    assert result["similar"]["industry"] is None
    assert result["first_hit"]["fh60"]["hist"]["n"] == 0
    assert result["first_hit"]["fh60"]["rw"].keys() == {"U", "L", "none"}
    assert result["state"]["well_dist_below"] is not None
    assert result["state"]["close"] is not None
    assert all(
        value is None
        for value in result["similar"]["full"]["q"]["r60"]
    )
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
