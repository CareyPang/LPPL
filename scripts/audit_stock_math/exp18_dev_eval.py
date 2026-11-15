"""§22.3 开发段评价（操作化定义见 docs/preregistration.md §22.3.1）。
臂：lppls_v2 box（登记基线）、lppls_v2_g2 box（现行）、lppls_v2_g3q3 box（_g3）、lppls_v2_g3q3 box_q3（_g3∧Q3）。
口径：全样本 & 剔除 2007/08/2014/15；A1/A2 + 循环平移零分布（≥250 日，1000 次）。
用法：PYTHONPATH=. python scripts/audit_stock_math/exp18_dev_eval.py [out_dir]
"""
from __future__ import annotations

import os
import sys
import zlib
from pathlib import Path

os.environ.setdefault("LPPLS_BOX", "v2")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from research.eval.dataset import price_series  # noqa: E402
from research.eval.original_standard import (  # noqa: E402
    DEV_END,
    HORIZONS,
    MIN_SHIFT,
    N_PERM,
    THRESHOLDS,
    top_dates,
)
from research.features.lppls_rules import SCALES, multiscale_scores  # noqa: E402

INDEXES = ("sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006")
EX = {2007, 2008, 2014, 2015}
ARMS = (("v2_registered", "lppls_v2", "box"), ("current_g2", "lppls_v2_g2", "box"),
        ("g3", "lppls_v2_g3q3", "box"), ("g3_q3", "lppls_v2_g3q3", "box_q3"))
FEAT = Path("data/features")


def load_scan(d: str, sym: str) -> pd.DataFrame:
    p = FEAT / d / f"{sym}.parquet"
    if p.exists():
        sc = pd.read_parquet(p)
    else:  # 本机分片未合并时
        parts = sorted((FEAT / d).glob(f"{sym}__part*of*.parquet"))
        if not parts:
            raise FileNotFoundError(p)
        sc = pd.concat([pd.read_parquet(x) for x in parts]).drop_duplicates(["date", "n"]).sort_values(["date", "n"])
    sc = sc[sc.date <= DEV_END].reset_index(drop=True)
    logp = price_series(sym)
    pos = pd.Series(np.arange(len(logp)), index=logp.index)
    lp = logp.to_numpy()
    end = pos.reindex(sc.date).to_numpy()
    sc["y_std"] = [lp[e + 1 - n : e + 1].std() for e, n in zip(end, sc.n, strict=True)]
    return sc


def metrics(alarm, tpos, gpos, H):
    if alarm.sum() == 0 or len(tpos) == 0:
        return np.nan, np.nan
    ap = gpos[alarm]
    nxt = np.searchsorted(tpos, ap, side="right")
    hit = (nxt < len(tpos)) & (tpos[np.minimum(nxt, len(tpos) - 1)] - ap <= H)
    prev = np.searchsorted(ap, tpos, side="left") - 1
    ok = (prev >= 0) & (tpos - ap[np.maximum(prev, 0)] <= H)
    return float(hit.mean()), float(ok.mean())


def null(alarm, tpos, gpos, H, rng):
    n = len(alarm)
    step = max(1, int(np.median(np.diff(gpos))))
    out = np.empty((N_PERM, 2))
    for b in range(N_PERM):
        k = int(rng.integers(MIN_SHIFT // step, n - MIN_SHIFT // step))
        out[b] = metrics(np.roll(alarm, k), tpos, gpos, H)
    return out


def eval_symbol(sym: str, ms_by_dir: dict[str, pd.DataFrame]) -> list[dict]:
    cal = price_series(sym).index
    tops = top_dates(sym)
    rows = []
    for arm, d, rule in ARMS:
        ms = ms_by_dir[d]
        for sample in ("full", "ex"):
            keep = np.ones(len(ms), bool) if sample == "full" else ~ms.index.year.isin(EX)
            grid = ms.index[keep]
            gpos = cal.get_indexer(grid)
            tt = tops if sample == "full" else tops[~tops.year.isin(EX)]
            tpos = np.sort(cal.get_indexer(tt))
            tpos = tpos[(tpos >= gpos.min()) & (tpos <= gpos.max() + max(HORIZONS))]
            for sc in SCALES:
                col = f"{rule}__{sc}"
                x = ms[col].fillna(0).to_numpy()[keep] if col in ms else np.zeros(len(grid))
                for q in THRESHOLDS:
                    alarm = x >= q
                    for H in HORIZONS:
                        rng = np.random.default_rng(zlib.crc32(f"{sym}|{sc}|{q}|{H}|{sample}".encode()))
                        if alarm.sum() < 3:
                            rows.append(dict(symbol=sym, arm=arm, sample=sample, scale=sc, q=q, H=H, n_alarm=int(alarm.sum())))
                            continue
                        a1, a2 = metrics(alarm, tpos, gpos, H)
                        nu = null(alarm, tpos, gpos, H, rng)
                        rows.append(dict(symbol=sym, arm=arm, sample=sample, scale=sc, q=q, H=H, n_alarm=int(alarm.sum()),
                                         n_top=len(tpos), A1=a1, A1_null=np.nanmean(nu[:, 0]), A1_p=float(np.nanmean(nu[:, 0] >= a1)),
                                         A2=a2, A2_null=np.nanmean(nu[:, 1]), A2_p=float(np.nanmean(nu[:, 1] >= a2))))
    return rows


def gate(tab: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    t = tab.dropna(subset=["A1"]).assign(lift=lambda z: z.A1 - z.A1_null)
    per = (t[t["sample"] == "ex"].groupby(["arm", "symbol"])
           .agg(n_cfg=("A1", "size"), lift_med=("lift", "median"), p_med=("A1_p", "median"), A1_med=("A1", "median"),
                A1_null_med=("A1_null", "median")).reset_index())
    per["pass"] = (per.lift_med > 0) & (per.p_med <= 0.05)
    full = tab[tab["sample"] == "full"].set_index(["symbol", "scale", "q", "H", "arm"])[["A1", "A2"]].unstack("arm")
    out = {}
    for arm in ("g3", "g3_q3", "v2_registered"):
        k = int(per[(per.arm == arm)]["pass"].sum())
        dA1 = (full["A1"][arm] - full["A1"]["current_g2"]).dropna()
        dA2 = (full["A2"][arm] - full["A2"]["current_g2"]).dropna()
        out[arm] = dict(n_index_pass=k, dA1_med=float(dA1.median()) if len(dA1) else np.nan, n_pair=len(dA1),
                        dA2_med=float(dA2.median()) if len(dA2) else np.nan)
    kc = int(per[per.arm == "current_g2"]["pass"].sum())
    out["current_g2"] = dict(n_index_pass=kc)
    g = out["g3_q3"]
    out["verdict_g3_q3"] = bool(g["n_index_pass"] >= 4 and g["dA1_med"] >= 0 and g["dA2_med"] >= 0)
    return per, out


def main(out_dir: str = "reports/q3_dev") -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    syms = os.environ.get("EXP18_SYMBOLS", ",".join(INDEXES)).split(",")
    rows = []
    for sym in syms:
        ms_by_dir = {d: multiscale_scores(load_scan(d, sym)) for d in {a[1] for a in ARMS}}
        rows += eval_symbol(sym, ms_by_dir)
        print("done", sym, flush=True)
    tab = pd.DataFrame(rows)
    tab.to_csv(out / "alarm_grid.csv", index=False)
    per, g = gate(tab)
    per.to_csv(out / "gate_per_index.csv", index=False)
    pd.DataFrame(g).T.to_csv(out / "gate.csv")
    print(per.to_string(index=False))
    print(pd.DataFrame(g).T.to_string())


if __name__ == "__main__":
    main(*sys.argv[1:])
