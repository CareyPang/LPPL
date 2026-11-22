import numpy as np
import pandas as pd

from research.eval import episode_backtest, export_contract
from research.features import lppls_scan
from research.optim.optimizers import METHODS, de_trf


def _synthetic_lppls(n: int = 160) -> np.ndarray:
    t = np.arange(n, dtype=float)
    dt = n + 12.0 - t
    y = 5.0 - 0.02 * dt**0.5 * (1 + 0.05 * np.cos(8.0 * np.log(dt)))
    return y + np.random.default_rng(7).normal(0, 0.002, n)


def test_de_trf_deterministic_and_registered():
    assert "de_trf" in METHODS
    assert lppls_scan.OPTIMIZER_NAMES["de_trf"] == "de_trf"

    y = _synthetic_lppls()
    row1 = lppls_scan.fit_one(y, opt="de_trf")
    row2 = lppls_scan.fit_one(y, opt="de_trf")

    np.testing.assert_allclose(row1[1:4], row2[1:4], rtol=0, atol=1e-12)
    assert np.isclose(row1[8], row2[8], rtol=0, atol=1e-12)
    assert row1[8] < 0.02

    # 支持 warm_starts 且结果不劣于无热启动
    t = np.arange(len(y), dtype=float)
    lo = np.array([len(y) - 1 + 0.5, 0.1, 6.0])
    hi = np.array([len(y) - 1 + 32.0, 0.9, 13.0])
    base = de_trf(t, y, lo, hi, seed=0)
    warm = de_trf(t, y, lo, hi, seed=0, warm_starts=[base.theta])
    assert warm.sse <= base.sse + 1e-12


def test_fco_intensity_and_cooling_state_pit():
    intensity0, active0 = export_contract._fco_intensity({"6-12m": 0.0, "12-24m": 0.0}, {"6-12m": [], "12-24m": []})
    assert intensity0 == 0.0 and active0 == 0

    intensity1, active1 = export_contract._fco_intensity(
        {"6-12m": 0.30, "12-24m": 0.25},
        {"6-12m": [{"share": 0.8}], "12-24m": [{"share": 0.6}]},
    )
    assert 0.5 <= intensity1 <= 1.0
    assert active1 == 2

    cal = pd.bdate_range("2025-01-02", periods=90)
    # 前 60 天上涨到 150，随后急跌（余震）
    prices = np.concatenate([
        np.linspace(100.0, 150.0, 60),
        np.array([144.0, 138.0, 132.0, 128.0, 125.0, 121.0, 118.0, 117.0, 116.0, 115.0]),
        np.linspace(115.0, 112.0, 20),
    ])
    ohlc = pd.DataFrame({"date": cal, "close": prices})
    asof_aftershock = cal[66]

    # 1) 顶部聚类活跃 -> active_top
    cs_active = export_contract._cooling_state(
        ohlc,
        cal,
        asof_aftershock,
        {"6-12m": {"confidence": {"box": 0.22}}, "12-24m": {"confidence": {"box": 0.0}}},
        {"start": "2025-04-10", "end": "2025-05-01"},
        None,
        {"bucket": "mid"},
    )
    assert cs_active["phase"] == "active_top"
    assert cs_active["reentry_ready"] is False

    # 2) 顶部置信度归零但处于余震冷却期 -> cooling_after_top
    cs_cool = export_contract._cooling_state(
        ohlc,
        cal,
        asof_aftershock,
        {"6-12m": {"confidence": {"box": 0.0}}, "12-24m": {"confidence": {"box": 0.0}}},
        {"start": None, "end": None},
        None,
        {"bucket": "mid"},
    )
    assert cs_cool["phase"] == "cooling_after_top"
    assert cs_cool["top_conf_cleared"] is True
    assert cs_cool["omori_aftershock_active"] is True
    assert cs_cool["reentry_ready"] is False

    # 3) 严格 Point-in-Time：修改 asof 之后的价格不影响 asof 当天的 cooling_state
    ohlc_mut = ohlc.copy()
    ohlc_mut.loc[ohlc_mut["date"] > asof_aftershock, "close"] = 500.0
    cs_cool_mut = export_contract._cooling_state(
        ohlc_mut,
        cal,
        asof_aftershock,
        {"6-12m": {"confidence": {"box": 0.0}}, "12-24m": {"confidence": {"box": 0.0}}},
        {"start": None, "end": None},
        None,
        {"bucket": "mid"},
    )
    assert cs_cool == cs_cool_mut

    # 4) 经过 >20 交易日且低波动阴跌后 -> reentry_watch
    cs_watch = export_contract._cooling_state(
        ohlc,
        cal,
        cal[-1],
        {"6-12m": {"confidence": {"box": 0.0}}, "12-24m": {"confidence": {"box": 0.0}}},
        {"start": None, "end": None},
        None,
        {"bucket": "deep"},
    )
    assert cs_watch["phase"] == "reentry_watch"
    assert cs_watch["reentry_ready"] is True


def test_episode_backtest_extract_and_null_baseline():
    frames = [
        {"asof": "2024-01-05", "split": "test", "w": {"6-12m": None}, "clusters": {"6-12m": []}, "fco_intensity": 0.0},
        {"asof": "2024-01-12", "split": "test", "w": {"6-12m": ["2024-02-01", "2024-03-01"]}, "clusters": {"6-12m": []}, "fco_intensity": 0.62},
        {"asof": "2024-01-19", "split": "test", "w": {"6-12m": ["2024-02-05", "2024-03-05"]}, "clusters": {"6-12m": []}, "fco_intensity": 0.78},
        {"asof": "2024-01-26", "split": "test", "w": {"6-12m": None}, "clusters": {"6-12m": []}, "fco_intensity": 0.0},
        {"asof": "2024-05-03", "split": "test", "w": {"6-12m": ["2024-05-20", "2024-06-15"]}, "clusters": {"6-12m": []}, "fco_intensity": 0.55},
        {"asof": "2024-05-10", "split": "test", "w": {"6-12m": None}, "clusters": {"6-12m": []}, "fco_intensity": 0.0},
    ]
    tops = [
        {"date": "2024-02-20", "max_dd": -0.18},
        {"date": "2024-06-25", "max_dd": -0.22},
    ]

    res = episode_backtest.evaluate_episodes(frames, tops, scale="6-12m", buffer_days=15, n_perm=100, seed=42)
    assert res["n_episodes"] == 2
    assert res["hit_rate_exact"] == 0.5
    assert res["hit_rate_buffered"] == 1.0
    assert res["median_days_to_top"] == 46.0
    assert 0.0 <= res["null_hit_rate_buffered"] <= 1.0
    assert 0.0 < res["p_value_buffered"] <= 1.0
    assert res["episodes"][0]["first_asof"] == "2024-01-12"
    assert res["episodes"][0]["weeks"] == 2
    assert res["episodes"][0]["max_fco_intensity"] == 0.78
