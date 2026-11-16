# ruff: noqa: E402
"""F2（预登记 §25.2）：t_c 剖面范围合成门。S-A 标定 c，S-B 与 N 判门。"剖面范围"不是置信区间。
用法：OMP_NUM_THREADS=1 PYTHONPATH=. python scripts/audit_stock_math/exp29_f2_profile.py [procs]"""
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fitacc_common as F

OUT = Path("reports/f2_profile")
CS = (0.002, 0.005, 0.01, 0.02, 0.05, 0.1)


def one(c):
    if "null" in c:
        t, y = F.null_series(c)
        tc_true = np.nan
    else:
        t, y, tr = F.synth(c["n"], c["sigma"], c["kind"], c["phi"], c["seed"])
        tc_true = tr.tc
    lo, hi = F.bounds(c["n"])
    tcs, P = F.profile_tc(t, y, lo, hi)
    return dict(c, tc_true=tc_true, tcs=tcs.tolist(), P=P.tolist(), span=float(hi[0] - lo[0]))


def ranges(df, c):
    lo_, hi_, cov = [], [], []
    for r in df.itertuples():
        tcs, P = np.asarray(r.tcs), np.asarray(r.P)
        R = tcs[P <= P.min() * (1 + c)]
        h = tcs[1] - tcs[0]
        lo_.append(R.min())
        hi_.append(R.max())
        cov.append(bool(R.min() - h / 2 <= r.tc_true <= R.max() + h / 2) if np.isfinite(r.tc_true) else np.nan)
    out = df.drop(columns=["tcs", "P"]).copy()
    out["r_lo"], out["r_hi"], out["covered"] = lo_, hi_, cov
    out["width"] = out.r_hi - out.r_lo
    out["width_rel"] = out.width / out.span
    return out


def main():
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    cells = list(F.synth_cells(F.SEEDS_A + F.SEEDS_B)) + list(F.null_cells())
    with Pool(procs, initializer=F.init) as p:
        D = pd.DataFrame(p.map(one, cells, chunksize=2))
    OUT.mkdir(parents=True, exist_ok=True)
    D.to_parquet(OUT / "profiles.parquet")
    S, N = D[D.null.isna()], D[D.null.notna()]
    SA, SB = S[S.seed.isin(F.SEEDS_A)], S[S.seed.isin(F.SEEDS_B)]
    cal = pd.DataFrame([dict(c=c, coverage_A=ranges(SA, c).covered.mean()) for c in CS])
    ok = cal[cal.coverage_A >= 0.80]
    print("== S-A 标定\n" + cal.round(4).to_string(index=False))
    if ok.empty:
        print("\n无 c 使 S-A 覆盖率 ≥ 0.80 → F2 合成门未通过（按 §25.0 不调参）")
        return
    c = float(ok.c.min())
    rb, rn = ranges(SB, c), ranges(N, c)
    rb.to_csv(OUT / "s_b.csv", index=False)
    rn.to_csv(OUT / "null.csv", index=False)
    by_noise = rb.groupby("noise").agg(coverage=("covered", "mean"), width_med=("width", "median"), width_rel_med=("width_rel", "median"))
    by_null = rn.groupby(["null", "n"]).agg(width_rel_med=("width_rel", "median"), width_med=("width", "median"))
    cov, nw = rb.covered.mean(), rn.width_rel.median()
    g1 = 0.80 <= cov <= 0.95
    g2 = bool((by_noise.coverage >= 0.70).all())
    g3 = nw >= 0.5
    print(f"\n冻结 c = {c}\n== S-B 按残差\n{by_noise.round(4).to_string()}\nS-B 合并覆盖率 {cov:.4f}（门 [0.80,0.95]：{g1}）；各类 ≥0.70：{g2}")
    print(f"== N 按零假设\n{by_null.round(4).to_string()}\nN 相对宽度中位 {nw:.4f}（门 ≥0.5：{g3}）")
    print(f"\nF2 合成门：{'通过' if g1 and g2 and g3 else '未通过'}")


if __name__ == "__main__":
    main()
