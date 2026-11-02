# ruff: noqa: E402, E702, B905, B007
"""WP1 零假设误报率标定（docs/research_plan_stock_math.md）：六类无泡沫生成过程 × 个股六档尺度 × 过滤集。
生成过程：gbm0（μ=0）、gbm_drift（μ=0.3%/日）、garch（GARCH(1,1)-t5）、powerlaw（无振荡幂律，t_c 超出 5%dt）、
ou_trend（指数趋势 + O-U 残差）、block_boot（真实个股对数收益按 20 日块重排，破坏时序保留分布；需联网取 5 只个股，限速）。
窗口：2–4w XS(10..20 步 2)、1–3m/3–6m SHORT(30..120 步 5)、6–12m/12–24m lite(127..502 步 25)、2–6y XL(525..1500 步 25)。
用法：AUDIT_OUT=/tmp/audit python scripts/audit_stock_math/exp7_null_calibration.py <procs> <reps_lite> <reps_short> <reps_xl>"""
import os
import sys
import time

OUT = os.environ.get("AUDIT_OUT", "/home/ubuntu/audit"); os.makedirs(OUT, exist_ok=True)
os.environ.setdefault("LPPLS_BOX", "v2")
from multiprocessing import Pool

import numpy as np
import pandas as pd

from research.features import lppls_scan
from research.features.lppls_rules import SCALES_FCO6, _derived, grid_rules, rules
from research.lppls import core
from research.pipeline import universe

KINDS = ("gbm0", "gbm_drift", "garch", "powerlaw", "ou_trend", "block_boot")
SIG = 0.02  # A 股个股日对数收益 σ 的典型量级
REAL = {}


def init(real):
    core.ALLOW_INSIDE = True
    REAL.update(real)


def series(kind, n, rng):
    if kind == "gbm0":
        return np.cumsum(rng.normal(0.0, SIG, n))
    if kind == "gbm_drift":
        return np.cumsum(rng.normal(0.003, SIG, n))
    if kind == "garch":
        e = np.empty(n); s2 = SIG**2; a, b = 0.08, 0.90
        for i in range(n):
            e[i] = np.sqrt(s2) * rng.standard_t(5) / np.sqrt(5 / 3); s2 = SIG**2 * (1 - a - b) + a * e[i] ** 2 + b * s2
        return np.cumsum(e)
    if kind == "powerlaw":
        t = np.arange(n, dtype=float); dt = n - 1; tc = dt + 0.05 * dt; m = rng.choice([0.3, 0.5, 0.7])
        return 8 - 0.6 * ((tc - t) / tc) ** m + rng.normal(0, 0.5 * SIG, n)
    if kind == "ou_trend":
        t = np.arange(n, dtype=float); x = np.empty(n); x[0] = 0.0; th = 0.05
        for i in range(1, n):
            x[i] = x[i - 1] - th * x[i - 1] + rng.normal(0, SIG)
        return 0.001 * t + x
    if kind == "block_boot":
        code = rng.choice(sorted(REAL)); r = REAL[code]; L = 20
        starts = rng.integers(0, len(r) - L, size=n // L + 1)
        return np.cumsum(np.concatenate([r[s : s + L] for s in starts])[:n])
    raise ValueError(kind)


def one(args):
    kind, seed, windows = args
    rng = np.random.default_rng(seed)
    n_total = max(windows)
    y_full = series(kind, n_total, rng)
    out = []
    for n in windows:
        y = y_full[-n:]
        row = lppls_scan.fit_one(y)
        d = dict(zip(lppls_scan.COLS[1:], row)); d.update(kind=kind, seed=seed, y_std=float(np.std(y)))
        out.append(d)
    return out


def load_real(codes=("600519", "000858", "300750", "601318", "002594")):
    from research.pipeline.stock import _fit_logp, load_stock
    real = {}
    for c in codes:
        try:
            ohlc, _, _ = load_stock(c)
            real[c] = np.diff(_fit_logp(ohlc).to_numpy(float))
            print(f"[real] {c} n_ret={len(real[c])} sd={real[c].std():.4f}", flush=True)
        except Exception as e:
            print(f"[real] {c} failed: {e}", flush=True)
        time.sleep(1.0)
    return real


def cp_interval(k, n, alpha=0.05):
    from scipy.stats import beta
    lo = beta.ppf(alpha / 2, k, n - k + 1) if k > 0 else 0.0
    hi = beta.ppf(1 - alpha / 2, k + 1, n - k) if k < n else 1.0
    return float(lo), float(hi)


if __name__ == "__main__":
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    reps = [int(x) for x in (sys.argv[2:5] or (200, 100, 40))] + [200, 100, 40][len(sys.argv[2:5]):]
    real = load_real()
    groups = {"lite": (universe.WINDOWS, reps[0]), "short": (lppls_scan.XS_WINDOWS + lppls_scan.SHORT_WINDOWS, reps[1]),
              "xl": (lppls_scan.XL_WINDOWS, reps[2])}
    tasks = [(k, 1000 * gi + s, w) for gi, (g, (w, r)) in enumerate(groups.items()) for k in KINDS for s in range(r)]
    print(f"tasks={len(tasks)} fits={sum(len(w) for _, _, w in tasks)}", flush=True)
    t0 = time.time()
    with Pool(procs, initializer=init, initargs=(real,)) as p:
        rows = [r for rs in p.imap_unordered(one, tasks, chunksize=2) for r in rs]
    df = pd.DataFrame(rows); df["date"] = pd.Timestamp("2020-01-01")
    df.to_parquet(f"{OUT}/exp7_null.parquet")
    d = _derived(df); r = rules(d); g = grid_rules(d)
    sets = {"box": r.box, "lit2": r.lit2, "standard": g.g_fco_standard, "early": g.g_fco_early, "end": g.g_fco_end, "pure": g.g_fco_pure}
    recs = []
    for sc, (lo, hi) in SCALES_FCO6.items():
        for kind in KINDS:
            m = d.n.between(lo, hi) & (d.kind == kind)
            if not m.any():
                continue
            row = {"scale": sc, "kind": kind, "n_windows": int(m.sum()), "n_series": int(d[m].seed.nunique())}
            for nm, col in sets.items():
                k = int(col[m].sum()); lo_, hi_ = cp_interval(k, int(m.sum()))
                row[nm] = round(k / m.sum(), 4); row[f"{nm}_lo"] = round(lo_, 4); row[f"{nm}_hi"] = round(hi_, 4)
            # as-of 级：同一条序列在该尺度的 standard>0 / box 比例≥0.5
            per = d[m].assign(std=g.g_fco_standard[m].to_numpy(), bx=r.box[m].to_numpy()).groupby("seed").agg(std=("std", "max"), bx=("bx", "mean"))
            row["asof_standard_gt0"] = round(float(per["std"].mean()), 4); row["asof_box_ge_half"] = round(float((per["bx"] >= 0.5).mean()), 4)
            recs.append(row)
    summ = pd.DataFrame(recs); summ.to_csv(f"{OUT}/exp7_null_summary.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
    print(summ[["scale", "kind", "n_windows", "n_series", "box", "standard", "early", "end", "pure", "lit2", "asof_standard_gt0", "asof_box_ge_half"]].to_string(index=False))
    print(f"elapsed {time.time() - t0:.0f}s")
