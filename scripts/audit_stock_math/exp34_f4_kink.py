# ruff: noqa: E402
"""F4'（预登记 §26.3）：拐点法选窗口起点。ℓ(n)=log χ²_np(n) 两段线性回归（左段斜率自由）取 RSS 最小的 n_k 为 n*；λ 法（§25.4）作对照列。
S4'：种子 25–37；N''：五类零假设 × 种子 20–179（n=800）。门 (a) |n*−L_b|/L_b 中位 < 0.20 且 L_b=227、477 各自 < 0.20；
门 (b) N'' 上 d_i = 1[所选窗口 box 合格] − 现行置信度_i 的均值单侧 95% 上界（正态与 2000 次自助取大）≤ 0.02。
用法：OMP_NUM_THREADS=1 PYTHONPATH=. python scripts/audit_stock_math/exp34_f4_kink.py [procs]"""
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fitacc_common as F

from research.optim.optimizers import tcgrid_lm
from research.synth.nulls import NULLS

OUT = Path("reports/f4_kink")
WINDOWS = tuple(range(125, 751, 10))
P_DOF = 7
PREFIX = 250
S4_SEEDS = tuple(range(25, 38))
NULL_SEEDS = tuple(range(20, 180))
DELTA = 0.02


def s4(c):
    t, yb, _ = F.synth(c["n"], c["sigma"], c["kind"], c["phi"], c["seed"])
    rng = np.random.default_rng(10_000 + c["seed"])
    r = c["sigma"] * rng.standard_normal(PREFIX)
    yp = yb[0] - np.cumsum(r[::-1])[::-1]
    return np.concatenate([yp, yb])


def one(c):
    is_null = "null" in c
    y = F.sample_null(c["null"], n=800, sigma=0.02, seed=c["seed"])[1] if is_null else s4(c)
    rows = []
    for n in WINDOWS:
        if n > len(y):
            continue
        yw = y[-n:]
        t = np.arange(n, dtype=float)
        lo, hi = F.bounds(n)
        r = tcgrid_lm(t, yw, lo, hi, seed=0, n_random=10)
        rows.append(dict(n=n, chi2=r.sse / (n - P_DOF), box=F.box_pass(t, yw, r.theta, lo, hi) if is_null else np.nan))
    W = pd.DataFrame(rows)
    n_kink = F.kink_start(W.n.values, W.chi2.values)
    lam = float(np.polyfit(W.n - 1, W.chi2, 1)[0])
    n_lam = int(W.n[(W.chi2 - lam * (W.n - 1)).idxmin()])
    out = dict(c, n_star=n_kink, n_lam=n_lam, lam=lam)
    if is_null:
        conf = float(W.box.mean())
        bk = bool(W.box[W.n == n_kink].iloc[0])
        bl = bool(W.box[W.n == n_lam].iloc[0])
        out.update(conf=conf, box_star=bk, box_lam=bl, d=bk - conf, d_lam=bl - conf)
    else:
        out.update(err_rel=abs(n_kink - c["n"]) / c["n"], err_rel_lam=abs(n_lam - c["n"]) / c["n"])
    return out


def upper95(d, seed=0):
    d = np.asarray(d, float)
    normal = d.mean() + 1.645 * d.std(ddof=1) / np.sqrt(len(d))
    rng = np.random.default_rng(seed)
    boots = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)])
    return float(normal), float(np.percentile(boots, 95))


def main():
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    cells = list(F.synth_cells(S4_SEEDS)) + [dict(null=k, seed=s) for k in NULLS for s in NULL_SEEDS]
    with Pool(procs, initializer=F.init) as p:
        D = pd.DataFrame(p.map(one, cells, chunksize=1))
    OUT.mkdir(parents=True, exist_ok=True)
    D.to_csv(OUT / "raw.csv", index=False)
    S, N = D[D.null.isna()], D[D.null.notna()]
    by = S.groupby("n")[["err_rel", "err_rel_lam"]].median()
    med = S.err_rel.median()
    ga = med < 0.20 and (by.err_rel < 0.20).all()
    lines = [f"== S4' |n*−L_b|/L_b（拐点法 err_rel；λ 法对照 err_rel_lam）{len(S)} 条\n" + by.round(4).to_string(),
             "按残差：\n" + S.groupby(["n", "noise"])[["err_rel", "err_rel_lam"]].median().round(4).to_string(),
             f"合并中位 {med:.4f}；门 (a)（合并与各 L_b 均 < 0.20）：{ga}"]
    un, ub = upper95(N.d.values)
    gb = max(un, ub) <= DELTA
    lines.append(f"== N'' {len(N)} 条：现行置信度均值 {N.conf.mean():.4f}，所选窗口 box 合格率 {N.box_star.mean():.4f}，"
                 f"mean d = {N.d.mean():+.4f}，单侧 95% 上界 正态 {un:+.4f} / 自助 {ub:+.4f}；门 (b)（≤ {DELTA}）：{gb}")
    lines.append("按零假设类：\n" + N.groupby("null")[["conf", "box_star", "d"]].mean().round(4).to_string())
    ul, ubl = upper95(N.d_lam.values)
    lines.append(f"λ 法对照：box 合格率 {N.box_lam.mean():.4f}，mean d {N.d_lam.mean():+.4f}，上界 {max(ul, ubl):+.4f}")
    lines.append("描述（不进裁决）：N'' 所选窗口 n* 分位 " + ", ".join(f"p{int(q*100)}={N.n_star.quantile(q):.0f}" for q in (0.1, 0.25, 0.5, 0.75, 0.9)))
    lines.append(f"\nF4' 合成门：{'通过' if ga and gb else '未通过'}")
    txt = "\n".join(lines)
    print(txt)
    (OUT / "run.log").write_text(txt + "\n")


if __name__ == "__main__":
    main()
