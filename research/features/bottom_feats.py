"""底部候选特征（prereg v1.5 §15，`docs/bottom_and_price_layer_design.md` §6.2）：
B2 流动性（Amihud、成交额比值）、B3 Omori 余震（主震后超阈收益率衰减）、B4 熊市高波动状态。全部 as-of（只用 ≤t）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

SHOCK_DD, SHOCK_LOOK, BASE_W, AFTER_W, MAX_DAYS = 0.10, 60, 250, 20, 250


def liquidity(logp: pd.Series, amount: pd.Series) -> pd.DataFrame:
    r = logp.diff().abs()
    amt = amount.replace(0, np.nan)
    amihud20 = (r / amt).rolling(20).mean()
    base = amihud20.rolling(BASE_W).median()
    amt_ratio20 = np.log(amt.rolling(20).mean() / amt.rolling(BASE_W).mean())
    return pd.DataFrame(dict(amihud_rel=np.log(amihud20 / base), amt_ratio20=amt_ratio20, damt5=amt_ratio20 - amt_ratio20.shift(5)))


def omori(logp: pd.Series, k_sigma: float = 2.0) -> pd.DataFrame:
    """主震 = 距 60 日高点回撤首次 ≥ 10%；余震 = |r| > k·σ_ref（σ_ref 为主震前 250 日 std）。
    after_ratio = 最近 20 日余震率 / 主震前基准率；omori_p ≈ log2(前半段余震数 / 后半段余震数)（p>0 衰减中，≈0 未衰减）。"""
    r = logp.diff()
    sig_ref = r.rolling(BASE_W).std().shift(1)
    dd60 = logp - logp.rolling(SHOCK_LOOK).max()
    shock = (dd60 <= -SHOCK_DD) & (dd60.shift(1) > -SHOCK_DD)
    n = len(logp)
    exceed = (r.abs() > k_sigma * sig_ref).to_numpy(float)
    base_rate = pd.Series(exceed, index=logp.index).rolling(BASE_W).mean().to_numpy()
    days = np.full(n, np.nan)
    ratio = np.full(n, np.nan)
    p_hat = np.full(n, np.nan)
    last, base_at = -1, np.nan
    sv = shock.to_numpy()
    for t in range(n):
        if sv[t] and (last < 0 or t - last >= SHOCK_LOOK):  # 同一轮下跌 60 日内只记一次主震
            last, base_at = t, base_rate[t - 1] if t > 0 else np.nan
        if last < 0 or t - last > MAX_DAYS:
            continue
        d = t - last
        days[t] = d
        if d >= AFTER_W:
            recent = exceed[t - AFTER_W + 1 : t + 1].mean()
            ratio[t] = recent / max(base_at, 1 / BASE_W) if np.isfinite(base_at) else np.nan
        if d >= 10:
            h = last + d // 2
            n1 = exceed[last + 1 : h + 1].sum()
            n2 = exceed[h + 1 : t + 1].sum()
            p_hat[t] = np.log2((n1 + 0.5) / (n2 + 0.5))
    sfx = str(k_sigma).replace(".", "")
    out = pd.DataFrame({f"days_since_shock_{sfx}": days, f"after_ratio_{sfx}": ratio, f"omori_p_{sfx}": p_hat}, index=logp.index)
    out[f"days_since_shock_{sfx}"] = out[f"days_since_shock_{sfx}"].fillna(MAX_DAYS)
    return out


def bear_state(logp: pd.Series, rv20: pd.Series) -> pd.DataFrame:
    bear = (logp - logp.shift(500) < 0).astype(float)
    bear[logp.shift(500).isna()] = np.nan
    pct = rv20.rolling(1250, min_periods=250).rank(pct=True)
    return pd.DataFrame(dict(bear500=bear, rv20_pct=pct, bear_x_rv=bear * pct))


def build(logp: pd.Series, amount: pd.Series, rv20: pd.Series) -> pd.DataFrame:
    return pd.concat([liquidity(logp, amount), omori(logp, 2.0), omori(logp, 2.5), bear_state(logp, rv20)], axis=1)
