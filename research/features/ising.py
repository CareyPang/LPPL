"""§21.4 (d) Ising 序参量代理（横截面相干性；research-only，不进产品）。

φ_t(s)：as-of t 成分股中尺度 s（6–12m: n∈[127,252]；12–24m: n∈[253,504]）上存在 STANDARD 合格窗口的比例。
  登记写 Q2 合格；Q2 合成标定未通过（reports/q2_calibration.md），按 §21.4 括注改用 STANDARD（grid_rules.g_fco_standard）。
  成分股 LPPLS 来自已登记的 lppls_v2_lite_stk100（csi300_20100104 分层抽样 100 只，as-of 步长 20 日，lite 23 窗）；
  按 as-of 前向填充到日频（只用过去值，PIT 安全，最多 20 个交易日陈旧）。Δφ = φ_t − φ_{t−20}。
χ_t：csi300_20100104 全部 300 只成分股 60 日日收益的平均两两相关系数（磁化率代理），只用 t 及以前。
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from ..eval.dataset import price_series
from .lppls_rules import _derived, grid_rules

ROOT = Path(__file__).resolve().parents[2]
STK = ROOT / "data/features" / os.environ.get("ISING_STK_DIR", "lppls_v2_lite_stk100")
SCALES = {"6_12": (127, 252), "12_24": (253, 504)}
CHI_WIN = 60


def phi(tdays: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for f in sorted(STK.glob("*.parquet")):
        d = pd.read_parquet(f)
        d["y_std"] = np.nan  # rel_err 不参与 STANDARD
        d = _derived(d)
        d["std_ok"] = grid_rules(d).g_fco_standard.to_numpy()
        for name, (lo, hi) in SCALES.items():
            s = d[d.n.between(lo, hi)].groupby("date").std_ok.any().astype(float).rename(f"phi_{name}")
            rows.append(s.to_frame().assign(symbol=f.stem))
    x = pd.concat(rows)
    out = x.groupby("date").agg({c: "mean" for c in x.columns if c.startswith("phi_")}).dropna(how="all")
    out["n_stk"] = x.groupby("date").symbol.nunique()
    out = out.reindex(tdays, method="ffill")
    for name in SCALES:
        out[f"dphi_{name}"] = out[f"phi_{name}"] - out[f"phi_{name}"].shift(20)
    return out


def chi(symbols: list[str], tdays: pd.DatetimeIndex, win: int = CHI_WIN, min_names: int = 50) -> pd.Series:
    px = pd.concat({s: price_series(s) for s in symbols}, axis=1).reindex(tdays)
    r = px.diff()
    vals = np.full(len(tdays), np.nan)
    R = r.to_numpy()
    for i in range(win, len(tdays)):
        blk = R[i - win + 1 : i + 1]
        ok = ~np.isnan(blk).any(axis=0)
        if ok.sum() < min_names:
            continue
        c = np.corrcoef(blk[:, ok].T)
        k = c.shape[0]
        vals[i] = (c.sum() - k) / (k * (k - 1))
    return pd.Series(vals, index=tdays, name="chi")


def market_features(symbols: list[str], tdays: pd.DatetimeIndex) -> pd.DataFrame:
    return phi(tdays).join(chi(symbols, tdays)).rename_axis("date").reset_index()
