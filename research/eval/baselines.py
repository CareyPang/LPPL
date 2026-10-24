"""R0 基率、R1 波动率逻辑回归；开发段 CPCV 评分与配对 ΔBrier 的时间块 bootstrap 区间（预登记 §5、§6）。"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .metrics import brier, score_table
from .splits import cpcv_paths

R1_FEATURES = ["rv20", "rv60", "rv120", "rv_ratio"]


def r0_predict(y_train: np.ndarray, n_test: int) -> np.ndarray:
    return np.full(n_test, float(np.mean(y_train)))


def logit_model(C: float = 1.0):
    return make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=1000))


def cpcv_oof(df: pd.DataFrame, trading_days: pd.DatetimeIndex, fit_predict, gap: int = 80) -> pd.DataFrame:
    """每条路径的测试样本预测；返回 DataFrame(date, symbol, y, p, path)。"""
    out = []
    for i, (tr, te, _) in enumerate(cpcv_paths(df.date, trading_days, gap=gap)):
        p = fit_predict(df[tr], df[te])
        out.append(pd.DataFrame(dict(date=df.date[te].to_numpy(), symbol=df.symbol[te].to_numpy(),
                                     y=df.y[te].to_numpy(), p=p, path=i)))
    return pd.concat(out, ignore_index=True)


def paired_delta_brier(oof_a: pd.DataFrame, oof_b: pd.DataFrame, block_days: int = 80, B: int = 1000, seed: int = 0, level: float = 0.9):
    """ΔBrier = Brier(a) − Brier(b)，按日期块（block_days 个交易日）bootstrap；返回 (delta, lo, hi)，默认 90% 区间、块长 80 日（预登记 §6）。"""
    m = oof_a.merge(oof_b, on=["date", "symbol", "path"], suffixes=("_a", "_b"))
    d = (m.p_a - m.y_a) ** 2 - (m.p_b - m.y_b) ** 2
    days = np.sort(m.date.unique())
    blk = pd.Series(np.arange(len(days)) // block_days, index=days)
    g = d.groupby(blk.reindex(m.date).to_numpy()).agg(["sum", "size"])
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(B):
        pick = rng.integers(0, len(g), len(g))
        vals.append(g["sum"].to_numpy()[pick].sum() / g["size"].to_numpy()[pick].sum())
    a = (1 - level) / 2
    return float(d.mean()), float(np.quantile(vals, a)), float(np.quantile(vals, 1 - a))


def evaluate(oof: pd.DataFrame, oof_ref: pd.DataFrame) -> dict:
    m = oof.merge(oof_ref[["date", "symbol", "path", "p"]], on=["date", "symbol", "path"], suffixes=("", "_ref"))
    s = score_table(m.y, m.p, m.p_ref)
    s["brier_ref"] = brier(m.y, m.p_ref)
    return s
