"""DS LPPLS Trust 指标（Zhang–Zhang–Sornette 2016 PLOS ONE，doi:10.1371/journal.pone.0165819，§"DS LPPLS Confidence and Trust"）。

原文定义：对每个窗口，把拟合残差 bootstrap 重采样 B=100 次加回拟合的 LPPLS 价格，得到 100 条"等价的合成序列"，
对每条重新校准并检查是否满足 Table 3 **条件 2**；该窗口的分数 = 通过比例；Trust = 所有窗口分数的中位数。
它衡量"拟合结构对这一次噪声实现有多敏感"（0 差 → 1 完美），与 Confidence（对窗口长度的敏感性）正交。

Table 3 条件 2：m∈[0.1,0.9]、ω∈[6,13]、t_c∈[t₂−0.2dt, t₂+0.12dt]、振荡 (ω/2)ln|(t_c−t₁)/(t_c−t₂)|≥2.5、D=m|B|/(ω|C|)≥1、相对误差≤0.14；
另加 B<0（正泡沫）。相对误差按本仓库 _derived 的口径 sqrt(SSE/n)/std(y)。

证据等级：描述性（原站页面不显示 Trust；本项目未对其做任何预测性检验）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..features.lppls_rules import _derived
from ..features.lppls_scan import COLS, fit_one
from ..lppls.core import design

B_BOOT = 100


def condition2(d: pd.DataFrame) -> pd.Series:
    return ((d.B < 0) & d.m.between(0.1, 0.9) & d.w.between(6, 13)
            & d.ahead.between(-0.2 * d.dt, 0.12 * d.dt) & (d.osc >= 2.5) & (d.D >= 1) & (d.rel_err <= 0.14))


def _fitted(row: pd.Series) -> np.ndarray:
    n = int(row.n)
    X = design(np.arange(n, dtype=float), float(row.tc), float(row.m), float(row.w), allow_inside=True)
    return X @ np.array([row.A, row.B, row.C1, row.C2], float)


def window_trust(y: np.ndarray, row: pd.Series, b: int = B_BOOT, seed: int = 0) -> float:
    """单窗口：残差 iid bootstrap 加回拟合价，重拟合 b 次，返回满足条件 2 的比例。"""
    rng = np.random.default_rng(seed)
    yhat = _fitted(row)
    res = y - yhat
    rows = []
    for _ in range(b):
        ys = yhat + rng.choice(res, size=len(res), replace=True)
        rows.append((pd.NaT, *fit_one(ys)))
    d = pd.DataFrame(rows, columns=COLS)
    d["y_std"] = [float(np.std(y))] * len(d)
    return float(condition2(_derived(d)).mean())


def _task(args):
    y, row, b, seed = args
    return window_trust(y, row, b, seed)


def trust(logp: pd.Series, asof: pd.Timestamp, fits: pd.DataFrame, b: int = B_BOOT, procs: int = 8) -> dict:
    """as-of 日的 Trust：fits 为该日各窗口的拟合表（COLS 列，n 为窗口长度）。返回中位数与各窗口分数。"""
    i = int(logp.index.get_indexer([asof])[0])
    lp = logp.to_numpy(float)
    tasks = [(lp[i + 1 - int(r.n): i + 1], r, b, k) for k, (_, r) in enumerate(fits.iterrows())]
    if procs > 1 and len(tasks) > 1:
        from multiprocessing import Pool
        with Pool(procs) as pool:
            scores = pool.map(_task, tasks)
    else:
        scores = [_task(t) for t in tasks]
    per = {int(r.n): round(s, 2) for (_, r), s in zip(fits.iterrows(), scores, strict=True)}
    return {"trust": round(float(np.median(scores)), 3) if scores else None, "n_windows": len(scores), "n_boot": b,
            "per_window": per, "evidence": "descriptive",
            "definition": "Zhang–Zhang–Sornette 2016 PLOS ONE：残差 bootstrap 100 次重拟合，满足 Table 3 条件 2 的比例，取窗口中位数",
            "note": "衡量拟合对噪声实现的敏感性（1=稳健），原站页面不显示；本项目未做预测性检验，仅描述"}
