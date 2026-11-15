"""描述性：FCO 三尺度 LPPLS box 置信度，2007/2015/2020-21/2024-10 与 2026 前瞻期对比（开发/校准/测试段沿用既有扫描，2026 用 exp24 扫描）。只描述，无门。
用法：LPPLS_BOX=v2 PYTHONPATH=. python scripts/audit_stock_math/exp24b_conf_regime_2026.py [exp24 输出目录]"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, ".")
os.environ.setdefault("LPPLS_BOX", "v2")

from research.features.lppls_rules import SCALES_FCO, _derived, rules  # noqa: E402
from scripts.audit_stock_math.exp24_scan_2026 import A_SH, logp  # noqa: E402

OUT = "reports/regime_2026"
SCAN = sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/audit/regime2026/scan"

def conf(sc, lp):
    if "y_std" not in sc:
        pos = pd.Series(np.arange(len(lp)), index=lp.index)
        end = pos.reindex(sc.date).to_numpy()
        v = lp.to_numpy()
        sc = sc.assign(
            y_std=[
                v[e + 1 - n : e + 1].std()
                for e, n in zip(end, sc.n, strict=True)
            ]
        )
    d = _derived(sc)
    d["box"] = rules(d).box.to_numpy()
    return pd.DataFrame({f"conf_{k}": d[d.n.between(lo, hi)].groupby("date").box.mean() for k, (lo, hi) in SCALES_FCO.items()})

allc = []
for sym in A_SH + ("NDX", "IXIC"):
    lp = logp(sym)
    parts = []
    for src in ("lppls_v2_g2", "lppls_v2_cal", "lppls_v2_test"):
        f = f"data/features/{src}/{sym}.parquet"
        if os.path.exists(f):
            parts.append(conf(pd.read_parquet(f), lp).assign(src=src))
    f = f"{SCAN}/{sym}.parquet"
    if os.path.exists(f):
        parts.append(conf(pd.read_parquet(f), lp).assign(src="fwd2026"))
    c = pd.concat(parts).sort_index()
    c["sym"] = sym
    allc.append(c)
C = pd.concat(allc)
C.to_csv(f"{OUT}/conf_hist.csv")
EP = {"2007": ("2006-06-01", "2008-06-30"), "2015": ("2014-10-01", "2015-12-31"), "2020-21": ("2020-06-01", "2021-12-31"), "2024-10": ("2024-09-15", "2025-03-31"), "2026": ("2025-09-01", "2026-10-29")}
rows = []
for sym, g in C.groupby("sym"):
    for ep, (a, b) in EP.items():
        q = g.loc[a:b]
        if len(q):
            rows.append(dict(sym=sym, ep=ep, n=len(q), **{f"{k}_max": round(q[k].max(), 3) for k in q.columns if k.startswith("conf_")},
                             **{f"{k}_mean": round(q[k].mean(), 3) for k in q.columns if k.startswith("conf_")}, peakdate_12_24=q["conf_12-24m"].idxmax().date()))
print(pd.DataFrame(rows).to_string(index=False))
# 全历史（开发段）12–24m 置信度分布，供比较
dev = C[C.src == "lppls_v2_g2"]
print("dev conf_12-24m 分位(0.5/0.9/0.99):", dev["conf_12-24m"].quantile([.5, .9, .99]).round(3).tolist(), " 6-12m:", dev["conf_6-12m"].quantile([.5, .9, .99]).round(3).tolist())
# 2026 前瞻期：as-of 置信度与其后 60 日最大回撤（W7 同向性的描述性复核；样本重叠、无门）
fw = []
for sym in A_SH + ("NDX", "IXIC"):
    lp = logp(sym)
    p = np.exp(lp).to_numpy()
    f = C[(C.sym == sym) & (C.src == "fwd2026")]
    for d, r in f.iterrows():
        i = lp.index.get_indexer([d])[0]
        if 0 <= i and i + 60 < len(p):
            w = p[i : i + 61]
            fw.append(dict(sym=sym, date=d.date(), **{k: r[k] for k in f.columns if k.startswith("conf_")},
                           mdd60=(w / np.maximum.accumulate(w)).min() - 1,
                           ret250=p[i] / p[i - 250] - 1))  # 同 W7 panel 的 runup250（秩相同）
F = pd.DataFrame(fw)
F.to_csv(f"{OUT}/fwd2026_mdd60.csv", index=False)
A = F[F.sym.isin(A_SH)]
res = lambda a, b: a - np.polyval(np.polyfit(b, a, 1), b)  # noqa: E731
for k in ("conf_1-3m", "conf_6-12m", "conf_12-24m", "ret250"):
    pr = spearmanr(res(A[k].rank().to_numpy(), A.ret250.rank().to_numpy()), res(A.mdd60.rank().to_numpy(), A.ret250.rank().to_numpy()))[0] if k != "ret250" else np.nan
    print(f"A 股 {k}: Spearman(·, mdd60)={spearmanr(A[k], A.mdd60)[0]:.3f}  控制 ret250 后偏相关={pr:.3f}  n={len(A)}")
print(A.assign(c612_pos=A["conf_6-12m"] > 0).groupby("c612_pos").mdd60.describe().round(3).to_string())
