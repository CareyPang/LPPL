# ruff: noqa: E402
"""F1（docs/plan_lppls_fit_accuracy.md、预登记 §25.1）：优化器漏找地图。描述性，无门。
窗口 = Phase 1a exp13 的 2182 个开发段真实窗口（6 指数，as-of 每 46 个取 1，窗口 IDX_WINDOWS[::5]），已有 6 种方法的解。
本脚本补一个密网格参照解：t_c 60 × m 30 × ω 40 网格剖面 → SSE 最小的 10 个格点各用 L-BFGS-B 精修，取最小。
参照 SSE = 7 个解（6 方法 + 密网格）的最小值；某方法"漏找" = SSE > 参照 × (1 + 1e-4)。
按参照解分层：t_c 在窗内 / 窗外、m 分箱、窗口长度分箱；并统计生产解（tcgrid_lm_r10）与参照解的 box 合格判定是否翻转。
用法：OMP_NUM_THREADS=1 PYTHONPATH=. python scripts/audit_stock_math/exp28_f1_miss_map.py [procs]"""
import os
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("LPPLS_BOX", "v2")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.eval.dataset import price_series
from research.features.lppls_scan import _box_pass, residual_tests
from research.lppls import core
from research.lppls.core import K_POWER, lin_fit
from research.optim.optimizers import _polish, grid_profile, tcgrid_lm

SRC = "/home/ubuntu/audit/exp13_opt_real.parquet"
OUT = Path("reports/f1_miss_map")
TOL = 1e-4
M_BINS = [0.0, 0.1, 0.3, 0.6, 0.9, 2.01]
N_BINS = [0, 300, 500, 760]


def init():
    core.ALLOW_INSIDE = True


def bounds(n):
    dt = n - 1
    return np.array([0.8 * dt, 0.01, 1.0]), np.array([1.2 * dt, 2.0, 50.0])


def dense(t, y, lo, hi):
    tcs, ms, ws = np.linspace(lo[0], hi[0], 60), np.linspace(lo[1], hi[1], 30), np.linspace(lo[2], hi[2], 40)
    g = grid_profile(t, y, tcs, ms, ws)
    best = None
    for flat in np.argsort(g, axis=None)[:10]:
        i, j, k = np.unravel_index(flat, g.shape)
        th, f, _ = _polish(np.array([tcs[i], ms[j], ws[k]]), t, y, lo, hi)
        if best is None or f < best[1]:
            best = (th, f)
    return best


def row_of(t, y, theta, lo, hi):
    s, beta = lin_fit(t, y, *theta)
    sst = float(((y - y.mean()) ** 2).sum())
    rp = tcgrid_lm(t, y, lo[:2], hi[:2], seed=0, k=K_POWER, n_random=10)
    sp, bp = lin_fit(t, y, rp.theta[0], rp.theta[1], 0.0, K_POWER)
    return (len(y), *map(float, theta), *map(float, beta), float(s), 1 - s / sst, float(rp.theta[0]), float(rp.theta[1]),
            float(bp[1]), float(sp), *residual_tests(t, y, *theta, beta))


def one(args):
    key, y, sols = args
    y = np.asarray(y)
    n = len(y)
    t = np.arange(n, dtype=float)
    lo, hi = bounds(n)
    th_d, f_d = dense(t, y, lo, hi)
    sols = dict(sols)
    sols["dense"] = (th_d, f_d)
    ref = min(sols, key=lambda k: sols[k][1])
    th_r, f_r = sols[ref]
    th_p = sols["tcgrid_lm_r10"][0]
    box_p = _box_pass(y, row_of(t, y, th_p, lo, hi))
    box_r = box_p if np.allclose(th_r, th_p) else _box_pass(y, row_of(t, y, th_r, lo, hi))
    out = []
    for mth, (th, f) in sols.items():
        out.append(dict(symbol=key[0], date=key[1], n=n, method=mth, sse=f, ref_sse=f_r, ref_src=ref, rel=f / f_r - 1,
                        tc=th[0], m=th[1], w=th[2], tc_ref=th_r[0], m_ref=th_r[1], w_ref=th_r[2],
                        ref_inside=bool(th_r[0] <= n - 1), box_prod=box_p, box_ref=box_r))
    return out


def main():
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    df = pd.read_parquet(SRC)
    cache = {s: price_series(s) for s in df.symbol.unique()}
    tasks = []
    for (s, d, n), g in df.groupby(["symbol", "date", "n"]):
        lp = cache[s]
        e = lp.index.get_loc(d)
        y = lp.to_numpy()[e + 1 - n : e + 1]
        sols = [(r.method, (np.array([r.tc, r.m, r.w]), float(r.sse))) for r in g.itertuples()]
        tasks.append(((s, d), y.tolist(), sols))
    with Pool(procs, initializer=init) as p:
        R = pd.DataFrame([r for rs in p.imap_unordered(one, tasks, chunksize=4) for r in rs])
    R["miss"] = R.rel > TOL
    R["m_bin"] = pd.cut(R.m_ref, M_BINS)
    R["n_bin"] = pd.cut(R.n, N_BINS)
    R["dtc"] = (R.tc - R.tc_ref).abs()
    OUT.mkdir(parents=True, exist_ok=True)
    R.astype({"m_bin": str, "n_bin": str}).to_parquet(OUT / "windows.parquet")
    agg = dict(n=("miss", "size"), miss=("miss", "mean"), rel_med_miss=("rel", lambda x: x[x > TOL].median()),
               dtc_med_miss=("dtc", lambda x: x[R.loc[x.index, "miss"]].median()))
    S0 = R.groupby("method").agg(**agg)
    S1 = R.groupby(["method", "ref_inside"]).agg(**agg)
    S2 = R[R.method.isin(["tcgrid_lm_r10", "de_lbfgsb", "dense"])].groupby(["method", "ref_inside", "m_bin"], observed=True).agg(**agg)
    S3 = R[R.method.isin(["tcgrid_lm_r10", "de_lbfgsb"])].groupby(["method", "n_bin"], observed=True).agg(**agg)
    W = R[R.method == "tcgrid_lm_r10"]
    flip = pd.crosstab(W.box_prod, W.box_ref)
    src = W.ref_src.value_counts()
    for name, T in (("by_method", S0), ("by_inside", S1), ("by_inside_m", S2), ("by_n", S3), ("box_flip", flip)):
        T.to_csv(OUT / f"{name}.csv")
    pd.set_option("display.width", 220)
    print(f"窗口 {len(W)}；参照解来源：{src.to_dict()}")
    for name, T in (("按方法", S0), ("按参照 t_c 窗内/窗外", S1), ("按窗内外 × m", S2), ("按窗口长度", S3)):
        print(f"\n== {name}\n{T.round(4).to_string()}")
    print(f"\n== 生产解 vs 参照解 box 合格（行=生产，列=参照）\n{flip.to_string()}")


if __name__ == "__main__":
    main()
