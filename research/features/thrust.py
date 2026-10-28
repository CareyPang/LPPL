"""起涨确认特征（prereg §15.1 阶段二，确认型）：放量、余震结束后的首个正向冲击、融资由降转升；宽度由 run_breadth 单独生成。全部 as-of。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def thrust_features(logp: pd.Series, amount: pd.Series, after_ratio: pd.Series) -> pd.DataFrame:
    r = logp.diff()
    sig_ref = r.rolling(250).std().shift(1)
    amt = amount.replace(0, np.nan)
    f = pd.DataFrame(index=logp.index)
    f["amt_jump"] = np.log(amt / amt.rolling(20).mean().shift(1))
    f["amt_jump5"] = np.log(amt.rolling(5).mean() / amt.rolling(20).mean().shift(5))
    up_shock = (r > 2 * sig_ref).astype(float)
    calm = (after_ratio.fillna(1.0) <= 1.2).astype(float)
    f["first_up_shock"] = (up_shock * calm).rolling(5).max()  # 余震已回基准后 5 日内出现过 >2σ 上涨日
    f["ret5"] = logp - logp.shift(5)
    return f


def margin_turn(lev_d20: pd.Series) -> pd.Series:
    """融资余额 20 日变化由负转正（最近 10 日内发生过）。"""
    turn = ((lev_d20 > 0) & (lev_d20.shift(1) <= 0)).astype(float)
    return turn.rolling(10).max()


def breadth(prices: pd.DataFrame) -> pd.DataFrame:
    """prices: 列 = 成分股对数价，索引 = 日期。返回市场级宽度：20 日新高比例、单日上涨比例、20 日新高比例的 5 日变化。"""
    hi20 = (prices >= prices.rolling(20).max()).astype(float).where(prices.notna())
    up = (prices.diff() > 0).astype(float).where(prices.notna())
    f = pd.DataFrame(dict(br_hi20=hi20.mean(axis=1), br_up=up.mean(axis=1)))
    f["br_hi20_d5"] = f.br_hi20 - f.br_hi20.shift(5)
    return f
