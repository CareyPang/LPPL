"""开发段探索（dev_only，不改冻结规则）：t_c 分布"收敛/不再后漂"是否在置信度分级之上有增量。

问题：box 6–12 月档置信度 ≥q 报警后，再要求连续 as-of 的 t_c 分位窗稳定（§17.6-2 stab3≥0.5）或
t_c 中位数漂移速度 ≤0.5（t_c 每过一周只后移不到半周），120/60 日内见顶的 A1（精确率）/A2（召回）是否更好、
提前量是否更合理。对照：同报警数下只按置信度高低取前 n 的"匹配报警数"版本，排除"更严=更准"的假增量。
用法：LPPLS_BOX=v2 python -m research.eval.tc_stability_eval
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from ..features.lppls_rules import SCALES_FCO, _derived, rules
from .dataset import price_series
from .original_standard import SCAN, _alarm_metrics, _null, load, stability, top_dates

OUT = Path("reports/tc_stability_dev")
SCALE = os.environ.get("TCS_SCALE", "6-12m")
QS = (0.2, 0.5)
HS = (60, 120)
DRIFT_MAX = 0.5
SPAN_MAX_DAYS = 28  # stab3 的 3 个 as-of 必须落在 4 周内，否则视为缺失


def per_date(sym: str) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    sc, _ = load(sym)
    d = _derived(sc)
    box = rules(d).box.to_numpy()
    lo, hi = SCALES_FCO[SCALE]
    m = d.n.between(lo, hi).to_numpy()
    cal = price_series(sym).index
    conf = pd.Series(box[m], index=d.date[m]).groupby(level=0).mean()
    f = d[m & box]
    g = f.groupby("date").ahead
    q = pd.DataFrame({"n_fit": g.size(), "q20": g.quantile(0.2), "q80": g.quantile(0.8), "med": g.median()})
    q = q[q.n_fit >= 3]
    tab = pd.DataFrame({"conf": conf}).join(q, how="left")
    tab["pos"] = cal.get_indexer(tab.index)
    tab["lo"] = tab.pos + tab.q20
    tab["hi"] = tab.pos + tab.q80
    tab["tc_pos"] = tab.pos + tab.med
    w = tab.dropna(subset=["lo"])
    st = stability(w[["lo", "hi"]], 3)
    span = pd.Series(w.index, index=w.index).diff(2).dt.days
    st[span > SPAN_MAX_DAYS] = np.nan
    tab["stab3"] = st.reindex(tab.index)
    tcp = w.tc_pos
    drift = tcp.diff() / w.pos.diff()
    gap = pd.Series(w.index, index=w.index).diff().dt.days
    drift[gap > 14] = np.nan
    tab["drift"] = drift.reindex(tab.index)
    drift2 = tcp.diff(2) / w.pos.diff(2)
    drift2[pd.Series(w.index, index=w.index).diff(2).dt.days > SPAN_MAX_DAYS] = np.nan
    tab["drift2"] = drift2.reindex(tab.index)
    return tab, cal


def alarms(tab: pd.DataFrame) -> dict[str, np.ndarray]:
    c = tab.conf.fillna(0).to_numpy()
    stab = tab.stab3.to_numpy() >= 0.5
    conv = tab.drift.to_numpy() <= DRIFT_MAX
    conv2 = tab.drift2.to_numpy() <= DRIFT_MAX
    stab_lo = tab.stab3.to_numpy() >= 0.25
    out = {}
    for q in QS:
        base = c >= q
        out[f"conf>={q}"] = base
        out[f"conf>={q}&stab3"] = base & stab
        out[f"conf>={q}&drift<={DRIFT_MAX}"] = base & conv
        out[f"conf>={q}&~stab3"] = base & ~stab
        out[f"conf>={q}&stab3>=0.25"] = base & stab_lo
        out[f"conf>={q}&drift2<={DRIFT_MAX}"] = base & conv2
        out[f"conf>={q}&drift>{DRIFT_MAX}"] = base & ~conv & np.isfinite(tab.drift.to_numpy())
        for name in (f"conf>={q}&stab3", f"conf>={q}&stab3>=0.25", f"conf>={q}&drift<={DRIFT_MAX}", f"conf>={q}&drift2<={DRIFT_MAX}"):
            n = int(out[name].sum())
            if n:
                thr = np.sort(c[base])[::-1][min(n, base.sum()) - 1]
                out[f"{name}|matched"] = base & (c >= thr)
    return out


def lead_times(alarm: np.ndarray, tpos: np.ndarray, gpos: np.ndarray, H: int) -> tuple[float, float]:
    """命中报警的中位提前量（交易日）；每个被覆盖的顶，首次报警到顶的提前量中位数。"""
    ap = gpos[alarm]
    if len(ap) == 0:
        return np.nan, np.nan
    nxt = np.searchsorted(tpos, ap, side="right")
    ok = nxt < len(tpos)
    gaps = tpos[nxt[ok]] - ap[ok]
    gaps = gaps[gaps <= H]
    first = []
    for t in tpos:
        a = ap[(ap < t) & (t - ap <= H)]
        if len(a):
            first.append(t - a.min())
    return (float(np.median(gaps)) if len(gaps) else np.nan, float(np.median(first)) if first else np.nan)


def evaluate(sym: str, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    tab, cal = per_date(sym)
    gpos = tab.pos.to_numpy()
    tpos = np.sort(cal.get_indexer(top_dates(sym)))
    tpos = tpos[(tpos >= gpos.min()) & (tpos <= gpos.max() + max(HS))]
    rng = np.random.default_rng(seed)
    rows = []
    for name, al in alarms(tab).items():
        for H in HS:
            a1, a2 = _alarm_metrics(al, tpos, gpos, H)
            nul = _null(al, tpos, gpos, H, rng) if al.sum() >= 3 else np.full((1, 2), np.nan)
            lt, lf = lead_times(al, tpos, gpos, H)
            rows.append(dict(symbol=sym, alarm=name, H=H, n_alarm=int(al.sum()), n_tops=len(tpos), A1=a1,
                             A1_null=np.nanmean(nul[:, 0]), A1_p=float(np.nanmean(nul[:, 0] >= a1)) if al.sum() >= 3 else np.nan,
                             A2=a2, A2_null=np.nanmean(nul[:, 1]), lead_med=lt, first_lead_med=lf))
    tab["symbol"] = sym
    return pd.DataFrame(rows), tab.reset_index().rename(columns={"index": "date"})


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    syms = os.environ.get("TCS_SYMS", "sh000001,sz399001,sh000300,sz399006,sh000016,sh000905").split(",")
    res, tabs = [], []
    for s in syms:
        if not (SCAN / f"{s}.parquet").exists():
            continue
        r, t = evaluate(s)
        res.append(r)
        tabs.append(t)
        print(s, "done", flush=True)
    tab = pd.concat(res, ignore_index=True)
    per = pd.concat(tabs, ignore_index=True)
    tab.to_csv(OUT / "a1a2.csv", index=False)
    per.to_csv(OUT / "per_date.csv", index=False)
    summ = []
    for (a, H), g in tab.groupby(["alarm", "H"]):
        summ.append(dict(alarm=a, H=H, n_sym=len(g), n_alarm=int(g.n_alarm.sum()), A1_med=g.A1.median(), A1_null_med=g.A1_null.median(),
                         n_pass=int(((g.A1_p <= 0.05) & (g.A2 >= 0.5)).sum()), A2_med=g.A2.median(),
                         lead_med=g.lead_med.median(), first_lead_med=g.first_lead_med.median()))
    s = pd.DataFrame(summ).sort_values(["H", "alarm"])
    s.to_csv(OUT / "summary.csv", index=False)
    print(s.round(3).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
