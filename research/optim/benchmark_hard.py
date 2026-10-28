"""阶段 3b：加难度合成数据上比较四种优化器，并按预登记规则冻结。

python -m research.optim.benchmark_hard  →  reports/optimizer_benchmark_hard.{json,md}
冻结规则（docs/preregistration.md §8）：失败率 ≤1% 的方法中，"落入全局极小"比例最高者；并列取 nfev 最少。
全局极小判据：该方法 SSE ≤ 各方法该案例最优 SSE × (1 + 1e-6)。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..lppls.core import default_bounds, sse
from ..synth.hard import SCENARIOS, sample_hard
from .optimizers import METHODS

OUT = Path(__file__).resolve().parents[2] / "reports"


def run(n_cases=15, sigmas=(0.01, 0.03), noises=("iid", "garch"), seeds=(0, 1), methods=tuple(METHODS)):
    rows = []
    for sc in SCENARIOS:
        for noise in noises:
            for sigma in sigmas:
                for case in range(n_cases):
                    t, y, tr = sample_hard(sc, sigma=sigma, noise=noise, seed=1000 * case + 11)
                    hz = (1, 200) if sc == "far_tc" else (1, 90)
                    lo, hi = default_bounds(tr.n, horizon=hz)
                    s_true = sse(tr.theta(), t, y)
                    for mth in methods:
                        for seed in seeds:
                            r = METHODS[mth](t, y, lo, hi, seed=seed)
                            rows.append(dict(scenario=sc, noise=noise, sigma=sigma, case=case, method=mth, seed=seed,
                                             sse=float(r.sse), sse_ratio=float(r.sse / s_true),
                                             dtc=float(r.theta[0] - tr.tc), dm=float(r.theta[1] - tr.m),
                                             dw=float(r.theta[2] - tr.w), nfev=int(r.nfev), sec=float(r.seconds)))
                print(f"{sc} {noise} σ={sigma} done", flush=True)
    df = pd.DataFrame(rows)
    key = ["scenario", "noise", "sigma", "case"]
    df["best"] = df.groupby(key)["sse"].transform("min")
    df["global"] = df["sse"] <= df["best"] * (1 + 1e-6)
    df["fail"] = ~np.isfinite(df["sse"]) | (df["sse_ratio"] > 1.05)
    return df


def summarize(df: pd.DataFrame):
    g = df.groupby("method")
    tab = pd.DataFrame(dict(fail_rate=g["fail"].mean(), global_rate=g["global"].mean(),
                            med_abs_dtc=g["dtc"].apply(lambda s: s.abs().median()),
                            p90_abs_dtc=g["dtc"].apply(lambda s: s.abs().quantile(0.9)),
                            med_nfev=g["nfev"].median(), med_sec=g["sec"].median()))
    per_sc = df.groupby(["scenario", "method"])["global"].mean().unstack()
    ok = tab[tab.fail_rate <= 0.01]
    pool = ok if len(ok) else tab
    pool = pool.sort_values(["global_rate", "med_nfev"], ascending=[False, True])
    return tab, per_sc, pool.index[0]


def main():
    df = run()
    tab, per_sc, winner = summarize(df)
    OUT.mkdir(exist_ok=True)
    df.to_json(OUT / "optimizer_benchmark_hard.json", orient="records")
    md = ["# 优化器加难度基准（阶段 3b）\n",
          f"合成案例：{df.groupby(['scenario','noise','sigma','case']).ngroups} 个 × 4 种方法 × 2 个种子 = {len(df)} 次拟合。\n",
          "场景：base、weak_osc（弱振荡）、short（n=60/90）、boundary（m、ω 贴近过滤边界）、far_tc（t_c 距末端 60–150 日）；噪声 iid 和 GARCH；σ=1%、3%。\n",
          "全局极小判据：SSE ≤ 该案例四种方法最优 SSE × (1+1e-6)。失败判据：SSE > 1.05 × 真值 SSE。\n",
          "## 总表\n", tab.round(4).to_markdown(), "\n\n## 各场景落入全局极小的比例\n", per_sc.round(3).to_markdown(),
          f"\n\n## 按预登记规则冻结\n失败率 ≤1% 的方法中，全局极小比例最高者（并列取 nfev 最少）：**{winner}**。\n"]
    (OUT / "optimizer_benchmark_hard.md").write_text("\n".join(md))
    print(tab.round(4))
    print("WINNER", winner)


if __name__ == "__main__":
    main()
