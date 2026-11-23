"""价格层金融物理与微观结构辅助引擎（严格 Point-in-Time）。

基于 1990–2026 A 股核心宽基（2,060 个回撤周，含 2019 前/后样本外分段检验）的实证结论：
- 保留 4 项经受样本外检验的有效辅助维度：
  1. 自由能筹码势阱（well_F / well_depth / dist_below）：
     高自由能 = 跌穿过去 500 日筹码主势阱、进入低密度出清真空区（反直觉但 IC 最高，2019 前后稳定同向）；
     低自由能 = 停留在半山腰旧筹码密集区（套牢盘阻力阱，胜率最低）。
  2. 250 日筹码均价折价率（vwap_gap = close / VWAP_250 - 1）：衡量全市场持仓平均浮亏深度。
  3. OBV 20 日量价底背离（obv_div）：价弱量稳/暗中吸筹（2019 前后同向，近年更强）。
  4. Amihud 流动性枯竭比（am_ratio = med20 / med120）+ CMF-20 回撤护栏：识别“地量无人再卖”的流动性冰点。
- 明确剔除未通过 2019+ 样本外检验的排列信息熵（pe60）与 DFA 标度指数（dfa60），不计入任何打分权重。
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..features.wells import well_features_at


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def evaluate_price_physics(ohlc: pd.DataFrame, asof: pd.Timestamp | str | None = None) -> dict[str, Any]:
    """对截至 asof 的已收盘 OHLCV 序列计算价格层物理微观结构快照（严格 PIT）。

    Parameters
    ----------
    ohlc : DataFrame
        需包含列 ``date``（或 DatetimeIndex）以及 ``high``, ``low``, ``close``, ``volume``。
    asof : Timestamp | str | None
        截止日期；若提供则严格截断 ``date <= asof``。
    """
    df = ohlc.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        if asof is not None:
            df = df[df["date"] <= pd.Timestamp(asof)]
    elif isinstance(df.index, pd.DatetimeIndex):
        df = df.sort_index()
        if asof is not None:
            df = df[df.index <= pd.Timestamp(asof)]
        df = df.reset_index().rename(columns={df.index.name or "index": "date"})

    for col in ("high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["high", "low", "close", "volume"]).reset_index(drop=True)

    if len(df) < 120:
        return {
            "available": False,
            "evidence": "descriptive",
            "reason": "样本不足（需至少 120 个交易日）",
            "summary_text": "历史交易日不足 120 日，暂无法评估价格层筹码势阱与量价微观结构。",
            "metrics": {},
        }

    c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float)
    lows = df["low"].to_numpy(float)
    v = df["volume"].to_numpy(float)
    n = len(c)

    # 1) 自由能筹码势阱（取最近最多 500 个交易日，与 wells.py 保持一致）
    w_len = min(n, 500)
    x_tp = np.log((h[-w_len:] + lows[-w_len:] + c[-w_len:]) / 3.0)
    r2_tp = ((np.log(np.maximum(h[-w_len:], 1e-12)) - np.log(np.maximum(lows[-w_len:], 1e-12))) ** 2) / 12.0
    well_F, well_depth, dist_below = well_features_at(x_tp, r2_tp, v[-w_len:], float(np.log(c[-1])))
    no_well_below = bool(np.isnan(dist_below))

    # 2) 250 日筹码均价折价率（VWAP 代理）
    v_len = min(n, 250)
    vol_sum = float(np.sum(v[-v_len:]))
    vwap250 = float(np.sum(c[-v_len:] * v[-v_len:]) / vol_sum) if vol_sum > 0 else float(np.mean(c[-v_len:]))
    vwap_gap = float(c[-1] / vwap250 - 1.0) if vwap250 > 0 else 0.0

    # 3) OBV 20 日量价底背离（标准化 OBV 20 日变化 - 标准化价格 20 日变化）
    r = np.zeros(n, dtype=float)
    r[1:] = np.diff(np.log(np.maximum(c, 1e-12)))
    sign = np.sign(np.diff(c, prepend=c[0]))
    obv = np.cumsum(sign * v)
    obv_chg20 = float(obv[-1] - obv[-21])
    obv_std = float(np.std(np.diff(obv[-121:]))) * np.sqrt(20.0) + 1e-12
    px_chg20 = float(c[-1] / c[-21] - 1.0)
    px_std = float(np.std(r[-120:])) * np.sqrt(20.0) + 1e-12
    obv_div = float((obv_chg20 / obv_std) - (px_chg20 / px_std))

    # 4) Amihud 流动性枯竭比（20 日中位 / 120 日中位）
    dv = c * np.where(v > 0, v, np.nan)
    amihud = np.abs(r) / dv
    am20 = float(np.nanmedian(amihud[-20:])) if np.isfinite(amihud[-20:]).any() else np.nan
    am120 = float(np.nanmedian(amihud[-120:])) if np.isfinite(amihud[-120:]).any() else np.nan
    am_ratio = float(am20 / am120) if np.isfinite(am20) and np.isfinite(am120) and am120 > 0 else None

    # 5) CMF-20（仅作短期回撤护栏，不作为抄底加分项）
    rng = np.where((h - lows) > 0, h - lows, np.nan)
    clv = np.where(np.isfinite(rng), ((c - lows) - (h - c)) / rng, 0.0)
    v20 = float(np.sum(v[-20:]))
    cmf20 = float(np.sum(clv[-20:] * v[-20:]) / v20) if v20 > 0 else None

    # 综合“价格是否跌到位”物理状态分级（descriptive，辅助四维底部主状态机）
    in_vacuum = bool(well_F >= 1.25 and no_well_below)
    in_trapped_well = bool(well_F <= 0.55 and well_depth >= 0.25)
    deep_discount = bool(vwap_gap <= -0.10)
    obv_bull_div = bool(obv_div >= 0.65)
    liquidity_dry = bool(am_ratio is not None and am_ratio >= 1.25)

    hits = sum([in_vacuum, deep_discount, obv_bull_div, liquidity_dry])
    if in_vacuum and (deep_discount or obv_bull_div):
        regime = "cleared_vacuum"
        label = "跌穿旧筹码势阱 · 进入高自由能出清区"
        plain = (
            f"价格已跌穿过去 {w_len} 日筹码主势阱（自由能 F={well_F:.2f}，下方无更深旧势阱），"
            f"相对 250 日筹码均价折价 {vwap_gap * 100:+.1f}%，"
            + ("叠加 OBV 底背离暗中吸筹，" if obv_bull_div else "")
            + "价格空间上已具备均值回归弹性（仍需配合 Omori 余震与底部主状态机分批）。"
        )
    elif in_trapped_well:
        regime = "trapped_well"
        label = "位于半山腰旧筹码密集区（套牢阻力阱）"
        plain = (
            f"当前价仍停留在过去 {w_len} 日筹码主势阱内部（自由能 F={well_F:.2f}，井深 {well_depth:.2f}），"
            f"距 250 日筹码均价 {vwap_gap * 100:+.1f}%。实证显示半山腰密集区多为套牢盘而非强支撑，切忌凭支撑位重仓抄底。"
        )
    elif hits >= 2:
        regime = "approaching_value"
        label = "价格空间逐步接近出清区"
        plain = (
            f"自由能 F={well_F:.2f}，距 250 日筹码均价 {vwap_gap * 100:+.1f}%，OBV 背离 {obv_div:+.2f}，"
            f"已满足 {hits}/4 项价格物理出清特征，可纳入分批观察。"
        )
    else:
        regime = "neutral"
        label = "价格物理结构中性"
        plain = (
            f"自由能 F={well_F:.2f}，距 250 日筹码均价 {vwap_gap * 100:+.1f}%，OBV 背离 {obv_div:+.2f}，"
            "暂未出现跌穿筹码势阱或极端流动性枯竭特征。"
        )

    return {
        "available": True,
        "evidence": "descriptive",
        "asof": str(df["date"].iloc[-1].date()) if "date" in df.columns else None,
        "regime": regime,
        "label": label,
        "hits": int(hits),
        "summary_text": plain,
        "metrics": {
            "well_F": round(float(well_F), 3),
            "well_depth": round(float(well_depth), 3),
            "well_dist_below": round(float(dist_below), 4) if not no_well_below else None,
            "no_well_below": no_well_below,
            "vwap250": round(float(vwap250), 2),
            "vwap_gap": round(float(vwap_gap), 4),
            "obv_div": round(float(obv_div), 3),
            "amihud_ratio": round(float(am_ratio), 3) if _safe_float(am_ratio) is not None else None,
            "cmf20": round(float(cmf20), 4) if _safe_float(cmf20) is not None else None,
        },
        "flags": {
            "in_vacuum": in_vacuum,
            "in_trapped_well": in_trapped_well,
            "deep_discount": deep_discount,
            "obv_bull_div": obv_bull_div,
            "liquidity_dry": liquidity_dry,
        },
    }
