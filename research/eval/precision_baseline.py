"""Phase 0 精度尺子（描述性、dev_only；docs/plan_stock_engine_precision.md）：把"逃顶/抄底时间与价格精准"变成可测的数。

对象：开发段 6 指数（`lppls_v2`，2000–2018）与 100 只成分股样本（`lppls_v2_lite_stk100`，2010–2018）；底部用 −ln P 扫描
（`lppls_v2_neg_lite*`）与底部标签。报警 = 某尺度置信度（合格窗口比例，E4）≥ q；首报 = 前 GAP 个交易日内无报警的报警日。
每个首报记录：
  T-top  : 到下一个合格顶（标签事件段末 +1 日）的交易日数 lead；H 日内有顶 = hit
  P-top  : miss_up = 顶价/报警价 − 1（卖早损失的涨幅）；avoid = 顶后 126 日最低收盘/报警价 − 1（躲掉的跌幅）；
           fwd120 = 报警后 120 日收益（无论有无顶）
  T-bot / P-bot：对称（有效底标签；buy_early = 报警价/谷价 − 1；fwd120）
零对照：报警序列整体循环平移（≥250 日）N_PERM 次，报 hit 率与 lead 中位的零分布分位（沿用 original_standard 口径）。
用法：LPPLS_BOX=v2 PYTHONPATH=. python -m research.eval.precision_baseline [index|stock|both]"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("LPPLS_BOX", "v2")

from ..features.lppls_rules import SCALES_FCO, _derived, grid_rules, rules  # noqa: E402
from ..labels.top import event_segments  # noqa: E402
from .dataset import price_series  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FEAT = ROOT / "data/features"
LAB = ROOT / "data/labels"
OUT = ROOT / "reports/precision_baseline"
INDEXES = ("sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006")
DEV = (pd.Timestamp("2000-01-01"), pd.Timestamp("2018-12-31"))
RULES = ("box", "standard")
SCALES = {k: SCALES_FCO[k] for k in ("6-12m", "12-24m")}
QS = (0.05, 0.10, 0.20)
H, GAP, POST, N_PERM, MIN_SHIFT = 120, 20, 126, 500, 250


def confidence(scan: pd.DataFrame, logp: pd.Series) -> pd.DataFrame:
    """每个 as-of × 尺度 × 规则的置信度（合格窗口比例）。"""
    pos = pd.Series(np.arange(len(logp)), index=logp.index)
    lp = logp.to_numpy()
    end = pos.reindex(scan.date).to_numpy()
    scan = scan.assign(y_std=[lp[e + 1 - n : e + 1].std() for e, n in zip(end, scan.n, strict=True)])
    d = _derived(scan)
    r = pd.DataFrame({"box": rules(d).box, "standard": grid_rules(d).g_fco_standard})
    out = {}
    for sc, (lo, hi) in SCALES.items():
        m = d.n.between(lo, hi)
        out[sc] = r[m].groupby(d.date[m]).mean()
    return pd.concat(out, axis=1)  # columns (scale, rule)


def event_dates(sym: str, side: str) -> pd.DatetimeIndex:
    lab = pd.read_parquet(LAB / f"{'top' if side == 'top' else 'bottom'}_v1" / f"{sym}.parquet")["main__y"]
    cal = price_series(sym).index
    out = []
    for _, end in event_segments(lab):
        i = cal.get_indexer([end])[0]
        if 0 <= i + 1 < len(cal):
            out.append(cal[i + 1])
    return pd.DatetimeIndex(out)


def first_alarms(alarm: np.ndarray, gpos: np.ndarray, gap: int = GAP) -> np.ndarray:
    """首报：报警且前 gap 个交易日内无报警。返回 grid 索引。"""
    idx = np.where(alarm)[0]
    keep, last = [], -10**9
    for i in idx:
        if gpos[i] - last > gap:
            keep.append(i)
        last = gpos[i]
    return np.array(keep, dtype=int)


def episodes(sym: str, side: str, close: np.ndarray, cal: pd.DatetimeIndex, gpos: np.ndarray, alarm: np.ndarray,
             epos: np.ndarray) -> pd.DataFrame:
    rows = []
    n = len(close)
    for i in first_alarms(alarm, gpos):
        a = gpos[i]
        nxt = epos[epos > a]
        e = int(nxt[0]) if len(nxt) else -1
        hit = e >= 0 and e - a <= H
        row = dict(symbol=sym, side=side, date=cal[a], lead=(e - a) if e >= 0 else np.nan, hit=bool(hit))
        pa = close[a]
        if hit:
            pe = close[e]
            seg = close[a : e + 1]
            if side == "top":
                row.update(miss_up=pe / pa - 1, max_up=seg.max() / pa - 1,
                           avoid=(close[e : min(n, e + POST + 1)].min() / pa - 1))
            else:
                row.update(buy_early=pa / pe - 1, max_dn=seg.min() / pa - 1,
                           gain=(close[e : min(n, e + POST + 1)].max() / pa - 1))
        if a + H < n:
            row["fwd120"] = close[a + H] / pa - 1
            row["path_min120"] = close[a : a + H + 1].min() / pa - 1
            row["path_max120"] = close[a : a + H + 1].max() / pa - 1
        rows.append(row)
    return pd.DataFrame(rows)


def null_hit(alarm: np.ndarray, gpos: np.ndarray, epos: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    out = np.full(N_PERM, np.nan)
    step = max(1, int(np.median(np.diff(gpos))))
    for b in range(N_PERM):
        k = int(rng.integers(MIN_SHIFT // step, len(alarm) - MIN_SHIFT // step))
        fa = first_alarms(np.roll(alarm, k), gpos)
        if len(fa) == 0:
            continue
        a = gpos[fa]
        nxt = np.searchsorted(epos, a, side="right")
        ok = nxt < len(epos)
        out[b] = np.mean(ok & (epos[np.minimum(nxt, len(epos) - 1)] - a <= H))
    return out


def run_symbol(sym: str, side: str, feat_dir: str, lo: pd.Timestamp, hi: pd.Timestamp, seed: int = 0):
    logp = price_series(sym)
    sc = pd.read_parquet(FEAT / feat_dir / f"{sym}.parquet")
    sc = sc[(sc.date >= lo) & (sc.date <= hi)]
    if sc.empty:
        return None, None
    conf = confidence(sc, logp)
    cal = logp.index
    close = np.exp(logp.to_numpy())
    gpos = cal.get_indexer(conf.index)
    epos = np.sort(cal.get_indexer(event_dates(sym, side)))
    epos = epos[epos >= 0]
    rng = np.random.default_rng(seed)
    ep, summ = [], []
    for sc_name in SCALES:
        for rule in RULES:
            x = conf[(sc_name, rule)].fillna(0).to_numpy()
            for q in QS:
                alarm = x >= q
                if alarm.sum() < 3:
                    continue
                e = episodes(sym, side, close, cal, gpos, alarm, epos)
                if e.empty:
                    continue
                e = e.assign(scale=sc_name, rule=rule, q=q)
                ep.append(e)
                nul = null_hit(alarm, gpos, epos, rng)
                summ.append(dict(symbol=sym, side=side, scale=sc_name, rule=rule, q=q, n_first=len(e), hit=e.hit.mean(),
                                 hit_null_mean=np.nanmean(nul), hit_null_p95=np.nanquantile(nul, 0.95),
                                 hit_p=float(np.nanmean(nul >= e.hit.mean())), lead_med=e.lead[e.hit].median(),
                                 lead_q20=e.lead[e.hit].quantile(0.2), lead_q80=e.lead[e.hit].quantile(0.8)))
    return (pd.concat(ep) if ep else None), (pd.DataFrame(summ) if summ else None)


def main(which: str = "both") -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = []
    if which in ("index", "both"):
        jobs += [(s, "top", "lppls_v2", *DEV, "index") for s in INDEXES]
        jobs += [(s, "bottom", "lppls_v2_neg_lite", *DEV, "index") for s in INDEXES]
    if which in ("stock", "both"):
        stks = sorted(p.stem for p in (FEAT / "lppls_v2_lite_stk100").glob("*.parquet"))
        jobs += [(s, "top", "lppls_v2_lite_stk100", pd.Timestamp("2010-01-01"), DEV[1], "stock") for s in stks]
        jobs += [(s, "bottom", "lppls_v2_neg_lite_stk100", pd.Timestamp("2010-01-01"), DEV[1], "stock") for s in stks]
    eps, sums = [], []
    for sym, side, fd, lo, hi, grp in jobs:
        try:
            e, s = run_symbol(sym, side, fd, lo, hi)
        except FileNotFoundError as ex:
            print("skip", sym, side, ex, flush=True)
            continue
        if e is not None:
            eps.append(e.assign(group=grp))
            sums.append(s.assign(group=grp))
            print(sym, side, len(e), flush=True)
    E, S = pd.concat(eps), pd.concat(sums)
    E.to_csv(OUT / f"episodes_{which}.csv", index=False)
    S.to_csv(OUT / f"summary_{which}.csv", index=False)
    print(S.groupby(["group", "side", "scale", "rule", "q"]).agg(
        n_first=("n_first", "sum"), hit=("hit", "mean"), hit_null=("hit_null_mean", "mean"), lead_med=("lead_med", "median")).round(3).to_string())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "both")
