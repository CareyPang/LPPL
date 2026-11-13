# ruff: noqa: E402, E702
"""Phase 1b：t_c 分位窗的聚合方式对照（开发段 6 指数，lppls_v2 扫描，不重拟合；描述性）。
报警 = FCO 尺度（6–12m / 12–24m）box 置信度 ≥ 0.10 的 as-of；该尺度合格窗口的 t_c 提前量 ahead=t_c−t₂：
  equal   : 等权 20/80 分位（现行 §17.4 口径）
  r2w     : 以 R² 加权的分位
  errw    : 以 1/rel_err 加权的分位
  cluster : scenarios.scenarios 最大簇的 20/80 分位（Gerlach–Demos–Sornette 2019 §4.2）
  lagr    : Lagrange 选窗（lagrange_pick）所在尺度的等权分位，但中心改为选中窗的 t_c（窗宽同 equal）
指标：下一个合格顶（250 日内）是否落在 [t+q20, t+q80]（cover）vs 同宽朴素窗 [t+1, t+1+width]（cover_naive）；宽度；全部 & 剔 2007/08/2014/15。
用法：LPPLS_BOX=v2 PYTHONPATH=. python scripts/audit_stock_math/exp14_tc_window_variants.py"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("LPPLS_BOX", "v2")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.eval.dataset import price_series
from research.eval.precision_baseline import INDEXES, OUT, SCALES, event_dates
from research.features.lppls_rules import _derived, lagrange_pick, rules
from research.lppls.scenarios import scenarios

EX = {2007, 2008, 2014, 2015}
Q_ALARM = 0.10


def wq(x, w, q):
    o = np.argsort(x); x, w = x[o], w[o]
    c = np.cumsum(w) / w.sum()
    return float(np.interp(q, c, x))


def run_sym(sym: str) -> pd.DataFrame:
    logp = price_series(sym); cal = logp.index; lp = logp.to_numpy()
    sc = pd.read_parquet(f"data/features/lppls_v2/{sym}.parquet"); sc = sc[sc.date <= "2018-12-31"]
    pos = pd.Series(np.arange(len(lp)), index=cal); end = pos.reindex(sc.date).to_numpy()
    sc = sc.assign(y_std=[lp[e + 1 - n : e + 1].std() for e, n in zip(end, sc.n, strict=True)])
    d = _derived(sc); d["box"] = rules(d).box.to_numpy()
    tops = np.sort(cal.get_indexer(event_dates(sym, "top"))); tops = tops[tops >= 0]
    rows = []
    for scn, (lo, hi) in SCALES.items():
        m = d.n.between(lo, hi)
        for date, g in d[m].groupby("date"):
            ok = g[g.box]
            if len(ok) / len(g) < Q_ALARM or len(ok) < 3:
                continue
            tp = int(pos[date]); nxt = tops[tops > tp]
            if not len(nxt) or nxt[0] - tp > 250:
                continue
            gap = int(nxt[0] - tp)
            a = ok.ahead.to_numpy(float)
            variants = {"equal": (np.quantile(a, 0.2), np.quantile(a, 0.8)),
                        "r2w": (wq(a, ok.r2.clip(lower=1e-3).to_numpy(), 0.2), wq(a, ok.r2.clip(lower=1e-3).to_numpy(), 0.8)),
                        "errw": (wq(a, 1 / ok.rel_err.clip(lower=1e-4).to_numpy(), 0.2), wq(a, 1 / ok.rel_err.clip(lower=1e-4).to_numpy(), 0.8))}
            try:
                s = scenarios(ok.assign(dt=ok.n - 1))
                if len(s):
                    best = s.sort_values("n", ascending=False).iloc[0]
                    variants["cluster"] = (float(best["q20"]), float(best["q80"]))
            except Exception:  # noqa: BLE001
                pass
            try:
                pick = lagrange_pick(ok)
                ctr = float(ok.loc[pick.iloc[0], "ahead"]); w = variants["equal"][1] - variants["equal"][0]
                variants["lagr"] = (ctr - w / 2, ctr + w / 2)
            except Exception:  # noqa: BLE001
                pass
            for k, (q20, q80) in variants.items():
                width = max(1.0, q80 - q20)
                rows.append(dict(symbol=sym, scale=scn, date=date, yr=date.year, variant=k, n_ok=len(ok), q20=q20, q80=q80, width=width, gap=gap,
                                 cover=bool(q20 <= gap <= q80), cover_naive=bool(1 <= gap <= 1 + width), err_mid=abs((q20 + q80) / 2 - gap)))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    R = pd.concat([run_sym(s) for s in INDEXES])
    OUT.mkdir(parents=True, exist_ok=True); R.to_csv(OUT / "tc_window_variants.csv", index=False)
    pd.set_option("display.width", 220)
    for name, df in (("全部", R), ("剔 2007/08/2014/15", R[~R.yr.isin(EX)])):
        print(f"== {name}")
        print(df.groupby(["scale", "variant"]).agg(n=("cover", "size"), cover=("cover", "mean"), cover_naive=("cover_naive", "mean"),
                                                   width_med=("width", "median"), err_mid_med=("err_mid", "median")).round(3).to_string())
