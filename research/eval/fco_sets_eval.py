"""§17.10：FCO 四套公开过滤集（g_fco_*）在 v2 扫描数据上的原版标准 A1/A2（三尺度、H∈{60,120}、阈值），对照循环平移零分布。
不重扫、不重跑完整 original_standard。用法：LPPLS_BOX=v2 python -m research.eval.fco_sets_eval"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..features.lppls_rules import SCALES, _derived, grid_rules, rules
from .original_standard import HORIZONS, REPORT, SCAN, THRESHOLDS, load, top_dates
from .xs_eval import _a1a2

RULES = ["box", "g_fco_standard", "g_fco_early", "g_fco_end", "g_fco_pure", "g_D0.5_w4_25_m0_1_e014"]
N_PERM = 500


def main() -> None:
    rng = np.random.default_rng(0)
    rows = []
    for p in sorted(SCAN.glob("*.parquet")):
        sym = p.stem
        sc, _ = load(sym)
        if sc.empty:
            continue
        d = _derived(sc)
        r = pd.concat([rules(d), grid_rules(d)], axis=1)
        cal = top_dates.__globals__["price_series"](sym).index
        tpos = np.sort(cal.get_indexer(top_dates(sym)))
        tpos = tpos[tpos >= 0]
        for scale, (lo, hi) in SCALES.items():
            m = d.n.between(lo, hi)
            g = r[m].groupby(d.date[m])
            for rule in RULES:
                if rule not in r:
                    continue
                conf = g[rule].mean()
                apos = cal.get_indexer(conf.index)
                ms = min(250, max(1, len(conf) // 4))
                for q in THRESHOLDS:
                    al = conf.to_numpy() >= q
                    for H in HORIZONS:
                        a1, a2 = _a1a2(al, apos, tpos, H)
                        null = np.array([_a1a2(np.roll(al, rng.integers(ms, len(al) - ms)), apos, tpos, H) for _ in range(N_PERM)])
                        rows.append(dict(sym=sym, rule=rule, scale=scale, thr=q, H=H, n_alarm=int(al.sum()),
                                         A1=a1, A2=a2, A1_null=np.nanmedian(null[:, 0]), A2_null=np.nanmedian(null[:, 1]),
                                         p_A1=np.mean(null[:, 0] >= a1), p_A2=np.mean(null[:, 1] >= a2)))
    df = pd.DataFrame(rows)
    df.to_csv(REPORT / "fco_sets.csv", index=False)
    agg = (df.groupby(["rule", "scale", "thr", "H"])
             .agg(n_sym=("sym", "size"), A1_med=("A1", "median"), A1_null=("A1_null", "median"), A2_med=("A2", "median"),
                  A2_null=("A2_null", "median"), p_A1_med=("p_A1", "median"), p_A2_med=("p_A2", "median"),
                  n_sig=("p_A1", lambda x: int(((x <= 0.05)).sum())))
             .round(3))
    robust = agg[(agg.n_sym >= 4) & (agg.p_A1_med <= 0.05) & (agg.p_A2_med <= 0.05)]
    with open(REPORT / "fco_sets.md", "w") as f:
        f.write("# FCO 四套公开过滤集 vs box / 网格最近点（开发段 v2，三尺度，循环平移零分布 500 次）\n\n")
        f.write(f"稳健区域（≥4 指数且 A1、A2 中位 p≤0.05）：{len(robust)} / {len(agg)} 组合\n\n")
        f.write(robust.to_markdown() + "\n\n## 全部组合（H=120）\n\n" + agg.xs(120, level="H").to_markdown() + "\n")
    print("robust", len(robust), "/", len(agg))
    print(robust.to_string())


if __name__ == "__main__":
    main()
