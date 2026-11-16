# ruff: noqa: E402
"""F3（预登记 §25.3）：残差 AR(1) 可行 GLS（Prais–Winsten）对 OLS 的合成门。OLS 与 GLS 用同一套研究实现。
用法：OMP_NUM_THREADS=1 PYTHONPATH=. python scripts/audit_stock_math/exp30_f3_gls.py [procs]"""
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fitacc_common as F

OUT = Path("reports/f3_gls")


def one(c):
    if "null" in c:
        t, y = F.null_series(c)
        truth = None
    else:
        t, y, tr = F.synth(c["n"], c["sigma"], c["kind"], c["phi"], c["seed"])
        truth = tr.theta()
    lo, hi = F.bounds(c["n"])
    th_o, _ = F.fit(t, y, lo, hi, 0.0)
    th_g, rho, it = F.fit_gls(t, y, lo, hi)
    r = dict(c, rho=rho, iters=it)
    for lab, th in (("ols", th_o), ("gls", th_g)):
        r.update({f"{lab}_tc": th[0], f"{lab}_m": th[1], f"{lab}_w": th[2]})
        if truth is None:
            r[f"{lab}_box"] = F.box_pass(t, y, th, lo, hi)
        else:
            for i, k in enumerate(("tc", "m", "w")):
                r[f"{lab}_e{k}"] = abs(th[i] - truth[i])
    return r


def main():
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    cells = list(F.synth_cells(F.SEEDS_B)) + list(F.null_cells())
    with Pool(procs, initializer=F.init) as p:
        D = pd.DataFrame(p.map(one, cells, chunksize=2))
    OUT.mkdir(parents=True, exist_ok=True)
    D.to_csv(OUT / "raw.csv", index=False)
    S, N = D[D.null.isna()], D[D.null.notna()]
    rows = []
    for nz, g in S.groupby("noise"):
        d = dict(noise=nz, rho_med=g.rho.median())
        for k in ("tc", "m", "w"):
            o, q = g[f"ols_e{k}"].median(), g[f"gls_e{k}"].median()
            d.update({f"ols_{k}": o, f"gls_{k}": q, f"ratio_{k}": q / o if o > 0 else np.nan})
        rows.append(d)
    T = pd.DataFrame(rows).set_index("noise")
    ar = T.loc[["ar1_0.5", "ar1_0.9"], ["ratio_tc", "ratio_m", "ratio_w"]]
    g1 = bool((ar <= 0.80).all().all())
    g2 = bool((T.loc["iid", ["ratio_tc", "ratio_m", "ratio_w"]] <= 1.05).all())
    bo, bg = N.ols_box.mean(), N.gls_box.mean()
    g3 = bg <= bo + 0.01
    pd.set_option("display.width", 220)
    print("== S-B 中位绝对误差（ratio = GLS/OLS）\n" + T.round(4).to_string())
    print(f"\nAR(1) 两类三参数 ratio ≤ 0.80：{g1}；iid ratio ≤ 1.05：{g2}")
    print("== N box 合格率\n" + N.groupby("null")[["ols_box", "gls_box"]].mean().round(4).to_string())
    print(f"合并 OLS {bo:.4f} / GLS {bg:.4f}（门 GLS ≤ OLS+0.01：{g3}）")
    print(f"\nF3 合成门：{'通过' if g1 and g2 and g3 else '未通过'}")


if __name__ == "__main__":
    main()
