"""评分（预登记 §6）：Brier（主）、log loss、ECE、BSS、PR-AUC、可靠性表。事件数 < 50 时 ECE 用 5 个等频箱，否则 10 个。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def brier(y, p) -> float:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return float(np.mean((p - y) ** 2))


def log_loss(y, p, eps=1e-6) -> float:
    y, p = np.asarray(y, float), np.clip(np.asarray(p, float), eps, 1 - eps)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def bss(y, p, p_ref) -> float:
    return float(1 - brier(y, p) / brier(y, p_ref))


def reliability(y, p, n_bins: int | None = None) -> pd.DataFrame:
    y, p = np.asarray(y, float), np.asarray(p, float)
    if n_bins is None:
        n_bins = 5 if y.sum() < 50 else 10
    q = np.quantile(p, np.linspace(0, 1, n_bins + 1))
    b = np.clip(np.searchsorted(q[1:-1], p, side="right"), 0, n_bins - 1)
    df = pd.DataFrame(dict(bin=b, y=y, p=p)).groupby("bin").agg(n=("y", "size"), obs=("y", "mean"), pred=("p", "mean"))
    return df


def ece(y, p, n_bins: int | None = None) -> float:
    r = reliability(y, p, n_bins)
    return float(np.sum(r.n / r.n.sum() * np.abs(r.obs - r.pred)))


def pr_auc(y, p) -> float:
    y, p = np.asarray(y, float), np.asarray(p, float)
    order = np.argsort(-p, kind="stable")
    y = y[order]
    tp = np.cumsum(y)
    prec = tp / np.arange(1, len(y) + 1)
    rec = tp / max(y.sum(), 1)
    # 阶梯式面积（average precision）
    return float(np.sum(prec * np.diff(np.concatenate([[0.0], rec]))))


def score_table(y, p, p_ref) -> dict[str, float]:
    return dict(brier=brier(y, p), log_loss=log_loss(y, p), ece=ece(y, p), bss=bss(y, p, p_ref), pr_auc=pr_auc(y, p),
                n=int(len(y)), events_pos=int(np.sum(y)))


def event_metrics(oof: pd.DataFrame, alert_rate: float | None = None) -> dict[str, float]:
    """事件级辅助指标（预登记 §6）。oof 需含 date、symbol、y、p。

    报警阈值取 p 的分位数，使报警率等于 alert_rate（默认 = 正标签率，避免阈值调参）。
    事件段 = 同一标的内连续的 y=1 日；命中 = 段内至少一次报警；提前天数 = 段内首次报警到段末（即顶前一日）的交易日数；
    误报率 = 段外日子中报警的比例。
    """
    y, p = oof.y.to_numpy(), oof.p.to_numpy()
    rate = float(y.mean()) if alert_rate is None else alert_rate
    thr = float(np.quantile(p, 1 - rate))
    alert = p >= thr
    hits, leads, n_seg = 0, [], 0
    for _, g in oof.sort_values("date").groupby("symbol", sort=False):
        v = (g.y.to_numpy() == 1)
        a = g.p.to_numpy() >= thr
        i, n = 0, len(v)
        while i < n:
            if v[i]:
                j = i
                while j + 1 < n and v[j + 1]:
                    j += 1
                n_seg += 1
                idx = np.flatnonzero(a[i : j + 1])
                if len(idx):
                    hits += 1
                    leads.append(j - (i + idx[0]))
                i = j + 1
            else:
                i += 1
    out_seg = y == 0
    return dict(
        thr=thr, n_events=n_seg, hit_rate=hits / max(n_seg, 1), miss_rate=1 - hits / max(n_seg, 1),
        lead_med=float(np.median(leads)) if leads else np.nan,
        false_alarm_rate=float(alert[out_seg].mean()) if out_seg.any() else np.nan,
    )
