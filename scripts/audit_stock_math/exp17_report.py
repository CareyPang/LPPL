# ruff: noqa: E702
"""汇总 exp17_q3.parquet → §22.2 合成门判定表（窗口级 FPR 的 CP95% 上界、泡沫通过率）。"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import beta

OUT = os.environ.get("AUDIT_OUT", "/home/ubuntu/audit")
NULLS = ("gbm0", "gbm_drift", "garch", "powerlaw", "ou_trend", "block_boot")


def cp_hi(k, n, conf=0.95):
    return 1.0 if k == n else float(beta.ppf(conf, k + 1, n - k))


def table(df, filt_col):
    base = df[filt_col].fillna(False).astype(bool)
    rows = []
    for alpha in (None, 0.05, 0.10):
        for var in ("none", "fstar"):
            if alpha is None and var == "fstar":
                continue
            ok = base.copy()
            if alpha is not None:
                ok &= df.q3_p.fillna(1.0) <= alpha
                if var == "fstar":
                    fcol = "f_box" if filt_col == "box" else "f_std"
                    ok &= df[fcol].fillna(1.0) < 0.5
            r = dict(filter=filt_col, alpha="现行" if alpha is None else alpha, variant=var)
            worst = 0.0
            for k in NULLS:
                m = df.kind == k
                n, c = int(m.sum()), int((ok & m).sum())
                r[k] = f"{c / n:.3f}[{cp_hi(c, n):.3f}]"
                worst = max(worst, cp_hi(c, n))
            r["worst_cp95"] = round(worst, 3)
            for b in ("bubble", "bubble_mid"):
                m = df.kind == b
                r[b] = round(float((ok & m).sum() / m.sum()), 3)
                r[b + "_cond"] = round(float((ok & m).sum() / max(1, (base & m).sum())), 3)
            r["admissible"] = bool(worst <= 0.10 and alpha is not None)
            r["pass_gate"] = bool(r["admissible"] and r["bubble"] >= 0.30)
            rows.append(r)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = pd.read_parquet(sys.argv[1] if len(sys.argv) > 1 else f"{OUT}/exp17_q3.parquet")
    print(f"rows={len(df)} kinds={df.kind.value_counts().to_dict()}")
    pas = df[df.box | df.standard]
    print("\n过现行过滤集的窗口数（Q3 计算样本）：", pas.groupby("kind").size().to_dict())
    print("\nq3_p 分布（过滤通过窗口）：")
    print(pas.groupby("kind").q3_p.describe()[["count", "mean", "25%", "50%", "75%"]].round(3).to_string())
    print("\nf_box / f_std 均值：")
    print(pas.groupby("kind")[["f_box", "f_std"]].mean().round(3).to_string())
    print("\n原窗口 e 与对照中位 e* 之比（<1 = 原窗口更好）：")
    print((pas.e / pas.e_star_med).groupby(pas.kind).median().round(3).to_string())
    for fc in ("box", "standard"):
        t = table(df, fc)
        t.to_csv(f"{OUT}/exp17_gate_{fc}.csv", index=False)
        print(f"\n=== 过滤集 {fc}：窗口级 FPR[CP95 上界] / 泡沫通过率 ===")
        print(t.to_string(index=False))
    # 按 tc 窗内/窗外分泡沫
    bb = df[df.kind.str.startswith("bubble")]
    for alpha in (0.05, 0.10):
        g = bb.assign(ok=(bb.box | bb.standard) & (bb.q3_p.fillna(1) <= alpha)).groupby(["kind", "tc_rel"]).ok.mean().round(3)
        print(f"\n泡沫通过率（box∨STANDARD ∧ Q3 α={alpha}）按 t_c 位置：\n{g.to_string()}")
    np.set_printoptions(precision=3)
