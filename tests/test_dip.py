import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import requests

from research.dip import env, events, oos_h3, panel
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
    assert result["lib"]["reference_asof"] == result["state"]["asof"]
    assert result["lib"]["note"] == "参考库截止晚于行情日期，已按结果成熟日期筛选"
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


def test_share_http_403_degrades_without_crashing(monkeypatch):
    monkeypatch.setattr(
        env, "fetch_tencent_sina",
        lambda *args: pd.DataFrame({"date": ["2026-01-01"]}),
    )
    monkeypatch.setattr(env.time, "sleep", lambda *_: None)
    def forbidden(*args, **kwargs):
        raise requests.HTTPError("403 Client Error")
    monkeypatch.setattr(env.requests, "get", forbidden)

    frame = env._share_history()
    summary = _share_summary(frame, "510300")

    assert summary == {
        "available": False,
        "reason": "HTTPError: 403 Client Error",
    }


def test_share_http_403_carries_forward_previous_data(monkeypatch):
    monkeypatch.setattr(
        env, "fetch_tencent_sina",
        lambda *args: pd.DataFrame({"date": ["2026-01-01"]}),
    )
    monkeypatch.setattr(env.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        env.requests, "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.HTTPError("403")),
    )
    previous = {
        "asof": "2025-12-31",
        "shares": {"510300": {"latest_shares_yi": 10.0}},
    }

    summary = _share_summary(env._share_history(), "510300", previous)

    assert summary["latest_shares_yi"] == 10.0
    assert summary["stale"] is True
    assert summary["as_of"] == "2025-12-31"


def test_summary_reports_valid_sample_count_for_each_outcome():
    frame = pd.DataFrame(
        {
            "sig_date": ["2020-01-01", "2020-01-01"],
            "r60": [0.1, np.nan],
            "r120": [0.2, np.nan],
            "r250": [0.3, 0.4],
            "mdd60": [-0.1, -0.2],
            "up60": [0.2, 0.3],
            "mdd120": [-0.2, np.nan],
            "up120": [0.4, 0.5],
            "known60": ["2020-03-01", "2020-03-01"],
            "known120": ["2020-05-01", "2020-05-01"],
            "known250": ["2020-12-01", "2020-12-01"],
            "fh60_known": ["2020-03-01", "2020-03-01"],
            "fh120_known": ["2020-05-01", "2020-05-01"],
            "delisted": [False, True],
            "fh60": ["U", "none"],
            "fh120": ["L", "none"],
        }
    )

    summary = panel._summary(frame, "2026-01-01")

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
    assert not any(summary["n_excluded_immature"].values())


def test_panel_maturity_gate_and_future_signals(tmp_path, monkeypatch):
    prices = _rise_and_fall()
    prices.attrs["sym"] = "sh600519"
    asof = panel._state(prices)[0]["asof"]
    rows = [
        {
            "sym": "sh600519",
            "depth": -0.5,
            "sig_date": "2024-12-01",
            "entry_date": "2024-12-02",
            "sw1": "测试行业",
            "delisted": False,
            "r60": 0.1,
            "mdd60": -0.1,
            "up60": 0.2,
            "known60": "2025-02-01",
            "r120": 0.9,
            "mdd120": -0.3,
            "up120": 0.9,
            "known120": "2026-01-01",
            "r250": 0.9,
            "known250": "2026-06-01",
            "fh60": "U",
            "fh60_known": "2025-02-01",
            "fh120": "L",
            "fh120_known": "2026-01-01",
        },
        {
            "sym": "sh600519",
            "depth": -0.5,
            "sig_date": "2024-11-01",
            "entry_date": "2024-11-04",
            "sw1": "测试行业",
            "delisted": False,
            "r60": 0.3,
            "mdd60": -0.2,
            "up60": 0.4,
            "known60": "2025-01-01",
            "r120": 0.2,
            "mdd120": -0.1,
            "up120": 0.3,
            "known120": "2025-06-01",
            "r250": 0.5,
            "known250": "2025-11-01",
            "fh60": "L",
            "fh60_known": "2025-01-01",
            "fh120": "U",
            "fh120_known": "2025-06-01",
        },
    ]
    monkeypatch.setattr(
        panel,
        "_regime",
        lambda frame: {
            "p_hi_filtered": None,
            "hi_vol_ann": None,
            "lo_vol_ann": None,
            "hi_mean_wk": None,
            "lo_mean_wk": None,
            "weeks": 0,
            "status": "short_history",
            "note": "周收益不足 104 周；波动体制，不是涨跌信号",
        },
    )

    _write_library(tmp_path, rows)
    first = panel.build_panel(prices, tmp_path)
    summary = first["similar"]["full"]
    assert first["lib"]["reference_asof"] == asof
    assert summary["n_outcome"]["r60"] == 2
    assert summary["n_outcome"]["r120"] == 1
    assert summary["q"]["r120"] == pytest.approx([0.2] * 5)
    assert summary["n_excluded_immature"]["r60"] == 0
    assert summary["n_excluded_immature"]["r120"] == 1
    assert first["first_hit"]["fh60"]["hist"]["n"] == 2
    assert first["first_hit"]["fh120"]["hist"]["n"] == 1

    future_event = dict(rows[0], sig_date="2026-01-01", entry_date="2026-01-02")
    _write_library(tmp_path, rows + [future_event])
    second = panel.build_panel(prices, tmp_path)
    assert second["similar"] == first["similar"]
    assert second["first_hit"] == first["first_hit"]


def test_h3_uses_only_known_same_regime_refs_and_keeps_h2_baseline():
    references = pd.DataFrame(
        {
            "p_hi": [0.2] * 30 + [0.8] * 30 + [np.nan] * 5,
            "fh60": [("U", "L", "none")[index % 3] for index in range(65)],
            "fh60_known": ["2020-01-01"] * 65,
        }
    )
    references["regime"] = references.p_hi.map(oos_h3._regime_label)
    test_event = {
        "regime": "low",
        "fh60": "U",
        "fh60_known": "2020-02-01",
        "entry_date": "2020-02-01",
        "depth": -0.5,
    }

    result = oos_h3._h3_event(test_event, references, "fh60")

    all_reference = references[references.fh60_known < test_event["entry_date"]]
    low_reference = all_reference[all_reference.regime == "low"]
    p2 = np.array(
        [(all_reference.fh60 == category).mean() for category in ("U", "L", "none")]
    )
    p3 = np.array(
        [(low_reference.fh60 == category).mean() for category in ("U", "L", "none")]
    )
    observed = np.array([1.0, 0.0, 0.0])
    expected_delta = ((p2 - observed) ** 2).sum() - ((p3 - observed) ** 2).sum()
    assert result["n_ref"] == 65
    assert result["n_sub"] == 30
    assert result["n_ref_unknown"] == 5
    assert result["fallback"] is False
    assert result["d"] == pytest.approx(expected_delta)
    assert oos_h3._regime_label(np.nan) == "unknown"
    assert (
        oos_h3._h3_event(
            {**test_event, "regime": "unknown"}, references, "fh60"
        )
        is None
    )


def test_h3_fallback_is_counted_when_known_same_regime_refs_are_fewer_than_30():
    references = pd.DataFrame(
        [
            {
                "regime": "low" if index < 10 else "high" if index < 35 else "unknown",
                "fh60": ("U", "L", "none")[index % 3],
                "fh60_known": "2020-01-01",
            }
            for index in range(40)
        ]
    )
    test_event = {
        "regime": "low",
        "fh60": "L",
        "entry_date": "2020-02-01",
        "depth": -0.5,
    }

    row = oos_h3._h3_event(test_event, references, "fh60")
    result = oos_h3._aggregate_group(
        "全市场",
        pd.DataFrame(
            [
                {
                    **row,
                    "month": "2020-02",
                    "year": "2020",
                }
            ]
        ),
        np.random.default_rng(1),
    )

    assert row["n_sub"] == 10
    assert row["n_ref_unknown"] == 5
    assert row["fallback"] is True
    assert row["d"] == pytest.approx(0.0)
    assert result["n_fallback"] == 1
    assert result["n_ref_unknown"] == 5
    assert result["n_ref_unknown_share"] == pytest.approx(5 / 40)


def test_regime_nonconvergence_has_explicit_status(monkeypatch):
    class NonconvergedModel:
        def fit(self, **kwargs):
            return SimpleNamespace(mle_retvals={"converged": False})

    monkeypatch.setattr(
        "statsmodels.tsa.regime_switching.markov_regression.MarkovRegression",
        lambda *args, **kwargs: NonconvergedModel(),
    )
    dates = pd.bdate_range("2018-01-01", periods=800)
    close = 100 * np.exp(np.cumsum(np.sin(np.arange(len(dates)) / 7) * 0.01))
    result = panel._regime(pd.DataFrame({"date": dates, "close": close}))

    assert result["p_hi_filtered"] is None
    assert result["status"] == "nonconverged"
    assert result["note"] == "波动体制估计未收敛，不是涨跌信号"


def test_regime_short_history_has_explicit_status():
    prices = _prices(np.linspace(100.0, 120.0, 300))

    result = panel._regime(prices)

    assert result["status"] == "short_history"
    assert result["p_hi_filtered"] is None


def test_regime_fit_is_reproducible_for_same_series():
    dates = pd.bdate_range("2018-01-01", periods=1000)
    rng = np.random.default_rng(19)
    returns = np.concatenate(
        [rng.normal(0.0002, 0.008, 500), rng.normal(0.0001, 0.02, 500)]
    )
    close = 100 * np.exp(np.cumsum(returns))
    prices = pd.DataFrame({"date": dates, "close": close})

    first = panel._regime(prices)
    second = panel._regime(prices)

    assert first["status"] == second["status"] == "ok"
    assert first["p_hi_filtered"] is not None
    assert first["p_hi_filtered"] == second["p_hi_filtered"]


def test_phi_cache_invalidates_when_events_hash_changes(tmp_path):
    lib_dir = tmp_path / "lib"
    cache_dir = tmp_path / "cache"
    out_dir = tmp_path / "out"
    lib_dir.mkdir()
    cache_dir.mkdir()
    out_dir.mkdir()
    events_path = lib_dir / "events.parquet"
    events_path.write_bytes(b"old-events")
    (lib_dir / "manifest.json").write_text(
        json.dumps({"events_file": "events.parquet"}), encoding="utf-8"
    )
    phi_path = out_dir / "phi.parquet"
    meta_path = out_dir / "phi.meta.json"
    phi_path.write_bytes(b"cached-phi")
    original_meta = oos_h3._phi_cache_meta(lib_dir, cache_dir)
    meta_path.write_text(json.dumps(original_meta), encoding="utf-8")
    assert oos_h3._phi_cache_reusable(phi_path, meta_path, original_meta)

    events_path.write_bytes(b"new-events")
    changed_meta = oos_h3._phi_cache_meta(lib_dir, cache_dir)
    assert changed_meta["events_sha256"] != original_meta["events_sha256"]
    assert not oos_h3._phi_cache_reusable(phi_path, meta_path, changed_meta)


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
