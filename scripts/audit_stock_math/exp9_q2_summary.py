# ruff: noqa: E402, E702, B905, B007
"""exp9 结果汇总：六类零假设 × 24 网格点的窗口级 FPR（Clopper–Pearson 95% 上界）、合成泡沫通过率；§21.1 第 3 条门槛判定。
用法：AUDIT_OUT=... PYTHONPATH=. python exp9_q2_summary.py [filter]  filter∈{standard, box, any}"""
import itertools
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import beta

OUT = os.environ.get("AUDIT_OUT", "/home/ubuntu/audit")
BLOCKS = (5, 10, 20); ALPHAS = (0.05, 0.01); NULLS = ("ar1", "ar1_t5")
KINDS = ("gbm0", "garch", "block_boot", "ou_trend", "gbm_drift", "powerlaw")


def cp_upper(k: int, n: int, conf: float = 0.95) -> float:
    return 1.0 if n == 0 else (1.0 if k >= n else float(beta.ppf(conf, k + 1, n - k)))


def q2_pass(df: pd.DataFrame, blk: int, a_lr: float, a_l: float, nm: str) -> pd.Series:
    return (df[f"lr_p_b{blk}"] <= a_lr) & (df["lomb_rel"] <= 0.25) & (df[f"lomb_p_{nm}"] <= a_l)


def summarize(df: pd.DataFrame, filt: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    sel = df["standard"] if filt == "standard" else df["box"] if filt == "box" else (df["box"] | df["standard"])
    d = df[sel & df["lam"].notna()].copy()
    rows = []
    for blk, a_lr, a_l, nm in itertools.product(BLOCKS, ALPHAS, ALPHAS, NULLS):
        p = q2_pass(d, blk, a_lr, a_l, nm)
        r = dict(block=blk, alpha_lr=a_lr, alpha_lomb=a_l, lomb_null=nm)
        worst = 0.0
        for k in KINDS:
            m = d["kind"] == k
            n_k, x_k = int(m.sum()), int(p[m].sum())
            r[f"{k}_n"] = n_k; r[f"{k}_fpr"] = x_k / n_k if n_k else np.nan; r[f"{k}_ub"] = cp_upper(x_k, n_k)
            worst = max(worst, r[f"{k}_ub"])
        r["worst_ub"] = worst
        mb = d["kind"] == "bubble"
        r["bubble_n"] = int(mb.sum()); r["bubble_pass"] = float(p[mb].mean()) if mb.any() else np.nan
        r["admissible"] = worst <= 0.10
        rows.append(r)
    grid = pd.DataFrame(rows)
    # 过滤前的基数：每类生成窗口数、通过现行过滤的窗口数（= Q2 的分母）
    base = df.groupby("kind").agg(windows=("n", "size"), box=("box", "sum"), standard=("standard", "sum"))
    base["q2_eval"] = df[sel].groupby("kind").size()
    return grid, base


if __name__ == "__main__":
    filt = sys.argv[1] if len(sys.argv) > 1 else "any"
    df = pd.read_parquet(f"{OUT}/exp9_q2.parquet")
    grid, base = summarize(df, filt)
    grid.to_csv(f"{OUT}/exp9_grid_{filt}.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
    print("## base counts"); print(base.to_string())
    cols = ["block", "alpha_lr", "alpha_lomb", "lomb_null"] + [f"{k}_fpr" for k in KINDS] + ["worst_ub", "bubble_pass", "admissible"]
    print(f"## grid ({filt})"); print(grid[cols].round(3).to_string())
    adm = grid[grid.admissible]
    if len(adm):
        best = adm.sort_values("bubble_pass", ascending=False).iloc[0]
        print(f"## best admissible: block={best.block} a_lr={best.alpha_lr} a_l={best.alpha_lomb} null={best.lomb_null} bubble_pass={best.bubble_pass:.3f} worst_ub={best.worst_ub:.3f} -> {'PASS' if best.bubble_pass >= 0.30 else 'FAIL (<0.30)'}")
    else:
        print("## no admissible grid point (all worst_ub > 0.10) -> (a) 淘汰")
    # 单独看 LR 与 Lomb 各自的边际误报（诊断）
    d = df[(df.box | df.standard) & df.lam.notna()]
    diag = d.groupby("kind").agg(n=("lam", "size"), lr_b10_05=("lr_p_b10", lambda x: (x <= 0.05).mean()), lr_b20_05=("lr_p_b20", lambda x: (x <= 0.05).mean()),
                                lomb_ar1_05=("lomb_p_ar1", lambda x: (x <= 0.05).mean()), lomb_t5_05=("lomb_p_ar1_t5", lambda x: (x <= 0.05).mean()), freq_ok=("lomb_rel", lambda x: (x <= 0.25).mean()))
    print("## marginal diagnostics (box|standard windows)"); print(diag.round(3).to_string())
