"""§17.4-7 反泡沫（JS 1999，ANCHOR=start）开发段评价：ab/ab_strict/ab_loose 规则三尺度置信度 → 底部标签 A1/A2，对照循环平移零分布。
用法：LPPLS_BOX=v2 python -m research.eval.ab_eval"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..features.lppls_rules import SCALES, _derived, rules_ab
from .by_year import event_dates
from .dataset import price_series
from .original_standard import HORIZONS, THRESHOLDS
from .xs_eval import _a1a2

SCAN = Path("data/features/lppls_v2_ab_lite")
OUT = Path("reports/original_standard_dev_v2_ab_lite_bottom")
N_PERM = 500


def main() -> None:
    rng = np.random.default_rng(0)
    rows = []
    for p in sorted(SCAN.glob("*.parquet")):
        sym = p.stem
        sc = pd.read_parquet(p)
        sc = sc[sc.date <= pd.Timestamp("2018-12-31")]
        if sc.empty:
            continue
        logp = price_series(sym)
        cal = logp.index
        lp = logp.to_numpy()
        end = pd.Series(np.arange(len(cal)), index=cal).reindex(sc.date).to_numpy()
        sc["y_std"] = [lp[e + 1 - n : e + 1].std() for e, n in zip(end, sc.n, strict=True)]
        d = _derived(sc)
        r = rules_ab(d)
        tpos = np.sort(cal.get_indexer(event_dates(sym, "bottom")))
        tpos = tpos[tpos >= 0]
        for scale, (lo, hi) in SCALES.items():
            m = d.n.between(lo, hi)
            g = r[m].groupby(d.date[m])
            for rule in r.columns:
                conf = g[rule].mean()
                apos = cal.get_indexer(conf.index)
                ms = min(250, max(1, len(conf) // 4))
                for q in THRESHOLDS:
                    al = conf.to_numpy() >= q
                    for H in HORIZONS:
                        a1, a2 = _a1a2(al, apos, tpos, H)
                        null = np.array([_a1a2(np.roll(al, rng.integers(ms, len(al) - ms)), apos, tpos, H) for _ in range(N_PERM)])
                        rows.append(dict(sym=sym, rule=rule, scale=scale, thr=q, H=H, n_alarm=int(al.sum()), qual_share=float(r[rule][m].mean()),
                                         A1=a1, A2=a2, A1_null=np.nanmedian(null[:, 0]), A2_null=np.nanmedian(null[:, 1]),
                                         p_A1=np.mean(null[:, 0] >= a1), p_A2=np.mean(null[:, 1] >= a2)))
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "alarm_ab.csv", index=False)
    agg = (df.groupby(["rule", "scale", "thr", "H"])
             .agg(n_sym=("sym", "size"), n_alarm=("n_alarm", "sum"), A1_med=("A1", "median"), A1_null=("A1_null", "median"),
                  A2_med=("A2", "median"), A2_null=("A2_null", "median"), p_A1_med=("p_A1", "median"), p_A2_med=("p_A2", "median")).round(3))
    robust = agg[(agg.n_sym >= 4) & (agg.p_A1_med <= 0.05) & (agg.p_A2_med <= 0.05)]
    with open(OUT / "summary.md", "w") as f:
        f.write("# 反泡沫 JS 1999（ANCHOR=start，lite 扫描）底部标签 A1/A2（开发段，6 指数，循环平移零分布 500 次）\n\n")
        f.write(f"稳健区域（≥4 指数且 A1、A2 中位 p≤0.05）：{len(robust)} / {len(agg)} 组合\n\n" + robust.to_markdown() + "\n\n## 全部组合（H=120）\n\n" + agg.xs(120, level="H").to_markdown() + "\n")
    print("robust", len(robust), "/", len(agg))
    print(agg.xs(120, level="H").sort_values("A1_med", ascending=False).head(12).to_string())


if __name__ == "__main__":
    main()
