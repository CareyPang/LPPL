"""§17.4-4 t_c 情景聚类（Gerlach–Demos–Sornette 2019 §4.2）与分位预测窗（Jiang 等 2010 §3.1.1）。

对某个 as-of 日期的合格拟合，在 (dt, t_c−t₂) 平面做 k-means（标准化坐标），Silhouette 选 k；
每个簇单独报告（簇内 t_c−t₂ 的均值、标准差、20/80 与 5/95 分位），**不跨簇平均**；
合格拟合数占比 < MIN_SHARE 或个数 < MIN_FITS 的簇不作为情景。
另按尺度（S/M/L）分别给分位窗，同样不跨尺度合并。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_SHARE, MIN_FITS, K_MAX = 0.05, 3, 4
QS = (0.05, 0.2, 0.5, 0.8, 0.95)


def _kmeans(X: np.ndarray, k: int, seed: int = 0) -> np.ndarray:
    from sklearn.cluster import KMeans

    return KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(X)


def choose_k(X: np.ndarray) -> tuple[int, np.ndarray, float]:
    """k=1..K_MAX；Silhouette 最大者胜出，但只有 Silhouette ≥ 0.5 才接受 k≥2（否则单簇）。"""
    from sklearn.metrics import silhouette_score

    n = len(X)
    if n < 2 * MIN_FITS:
        return 1, np.zeros(n, int), np.nan
    best = (1, np.zeros(n, int), np.nan)
    for k in range(2, min(K_MAX, n // MIN_FITS) + 1):
        lab = _kmeans(X, k)
        if len(set(lab)) < k:
            continue
        s = float(silhouette_score(X, lab))
        if s >= 0.5 and (np.isnan(best[2]) or s > best[2]):
            best = (k, lab, s)
    return best


def _summ(ahead: np.ndarray) -> dict:
    q = np.quantile(ahead, QS)
    return dict(n=len(ahead), ahead_mean=float(ahead.mean()), ahead_std=float(ahead.std(ddof=0)),
                q05=q[0], q20=q[1], q50=q[2], q80=q[3], q95=q[4])


def scenarios(fits: pd.DataFrame) -> pd.DataFrame:
    """fits：某日合格拟合，需含 n（窗口长度）、ahead（t_c−t₂）。返回每簇一行，按簇大小降序。"""
    if len(fits) == 0:
        return pd.DataFrame()
    X = np.column_stack([fits.n.to_numpy(float), fits.ahead.to_numpy(float)])
    Z = (X - X.mean(0)) / np.where(X.std(0) > 0, X.std(0), 1.0)
    k, lab, sil = choose_k(Z)
    rows = []
    for c in range(k):
        f = fits[lab == c]
        share = len(f) / len(fits)
        if len(f) < MIN_FITS or share < MIN_SHARE:
            continue
        rows.append(dict(cluster=c, k=k, silhouette=sil, share=share, dt_min=int(f.n.min()), dt_max=int(f.n.max()),
                         **_summ(f.ahead.to_numpy(float))))
    return pd.DataFrame(rows).sort_values("share", ascending=False).reset_index(drop=True)


def scale_windows(fits: pd.DataFrame, scales: dict[str, tuple[int, int]]) -> pd.DataFrame:
    rows = []
    for sc, (lo, hi) in scales.items():
        f = fits[fits.n.between(lo, hi)]
        if len(f) >= MIN_FITS:
            rows.append(dict(scale=sc, **_summ(f.ahead.to_numpy(float))))
    return pd.DataFrame(rows)
