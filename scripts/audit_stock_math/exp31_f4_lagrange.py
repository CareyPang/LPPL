# ruff: noqa: E402
"""F4（预登记 §25.4）：Demos–Sornette 2017 Lagrange 正则选窗口起点的合成门。
χ²_np = SSE/(N−p)，p=7；λ = χ²_np 对 (t2−t1)=N−1 的 OLS 斜率；n* = argmin χ²_np − λ(N−1)。拟合用现行 tcgrid_lm(n_random=10)。
用法：OMP_NUM_THREADS=1 PYTHONPATH=. python scripts/audit_stock_math/exp31_f4_lagrange.py [procs]"""
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fitacc_common as F

from research.optim.optimizers import tcgrid_lm
from research.synth.nulls import NULLS

OUT = Path("reports/f4_lagrange")
WINDOWS = tuple(range(125, 751, 10))
P_DOF = 7
PREFIX = 250


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
    lam = float(np.polyfit(W.n - 1, W.chi2, 1)[0])
    W["chi2_lam"] = W.chi2 - lam * (W.n - 1)
    k = int(W.chi2_lam.idxmin())
    out = dict(c, lam=lam, n_star=int(W.n[k]), n_chi2np=int(W.n[W.chi2.idxmin()]))
    if is_null:
        out.update(conf=float(W.box.mean()), box_star=bool(W.box[k]))
    else:
        out.update(err_rel=abs(out["n_star"] - c["n"]) / c["n"], err_rel_chi2np=abs(out["n_chi2np"] - c["n"]) / c["n"])
    return out


def main():
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    cells = list(F.synth_cells(F.SEEDS_B)) + [dict(null=k, seed=s) for k in NULLS for s in F.NULL_SEEDS]
    with Pool(procs, initializer=F.init) as p:
        D = pd.DataFrame(p.map(one, cells, chunksize=1))
    OUT.mkdir(parents=True, exist_ok=True)
    D.to_csv(OUT / "raw.csv", index=False)
    S, N = D[D.null.isna()], D[D.null.notna()]
    med = S.err_rel.median()
    g1 = med < 0.20
    conf, star = N.conf.mean(), N.box_star.mean()
    g2 = star <= conf
    pd.set_option("display.width", 220)
    print("== S4 |n*−L_b|/L_b 中位（对照：未正则 χ²_np 最小）\n"
          + S.groupby(["n", "noise"])[["err_rel", "err_rel_chi2np"]].median().round(4).to_string())
    print(f"合并中位 {med:.4f}（门 <0.20：{g1}）；未正则 {S.err_rel_chi2np.median():.4f}")
    print("== N 现行置信度 vs F4 所选窗口 box 合格率\n" + N.groupby("null")[["conf", "box_star"]].mean().round(4).to_string())
    print(f"合并 现行 {conf:.4f} / F4 {star:.4f}（门 F4 ≤ 现行：{g2}）")
    print(f"\nF4 合成门：{'通过' if g1 and g2 else '未通过'}")


if __name__ == "__main__":
    main()
