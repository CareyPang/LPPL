"""单元测试：价格层金融物理与微观结构辅助引擎（严格 PIT）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.price_layer.physics_price import evaluate_price_physics


def _make_ohlc(closes: list[float], vols: list[float] | None = None) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=len(closes))
    c = np.asarray(closes, dtype=float)
    v = np.asarray(vols if vols is not None else [1e6] * len(closes), dtype=float)
    return pd.DataFrame({
        "date": dates,
        "open": c * 0.998,
        "high": c * 1.015,
        "low": c * 0.985,
        "close": c,
        "volume": v,
    })


def test_short_series_returns_unavailable():
    df = _make_ohlc([100.0] * 60)
    res = evaluate_price_physics(df)
    assert res["available"] is False
    assert res["evidence"] == "descriptive"


def test_vacuum_break_below_dense_well_detected_and_pit_isolated():
    # 先在 100 附近横盘 260 日堆积深筹码势阱，随后跌穿到 68（高自由能出清真空区）
    rng = np.random.default_rng(42)
    base = 100.0 + rng.normal(0.0, 1.5, size=260)
    drop = np.linspace(98.0, 68.0, 60)
    closes = list(base) + list(drop)
    vols = [2e6] * 260 + [8e5] * 60
    df = _make_ohlc(closes, vols)

    res = evaluate_price_physics(df)
    assert res["available"] is True
    assert res["metrics"]["well_F"] > 1.25
    assert res["metrics"]["no_well_below"] is True
    assert res["metrics"]["vwap_gap"] < -0.10
    assert res["flags"]["in_vacuum"] is True
    assert res["regime"] == "cleared_vacuum"

    # 严格 PIT 截断：只看前 200 天（横盘区）时结果不得受后续暴跌影响
    asof_mid = df["date"].iloc[199]
    res_mid = evaluate_price_physics(df, asof=asof_mid)
    res_trunc = evaluate_price_physics(df.iloc[:200])
    assert res_mid["metrics"] == res_trunc["metrics"]
    assert res_mid["flags"]["in_vacuum"] is False
