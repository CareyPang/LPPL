# ruff: noqa: E402, E702
"""§22.2 Q3 合成标定（草案 v1.9；只在合成数据上运行）。
每个任务 = 一条序列 × lite 16 窗（universe.WINDOWS）。窗口过现行过滤集（box 或 STANDARD）时计算 Q3：
  对窗口对数收益 r 做 K=20 个互不相同的循环平移（偏移 lppls_scan.q3_shifts：等距落在 [5, n−6]，§22.1.1），y* = y₀ + cumsum(roll(r,k))，同一 fit_one 重拟，
  e = √(SSE/n)/σ_y；p = (1 + #{e* ≤ e})/(K+1)；f* = 对照中过现行过滤集的比例。
零假设六类沿用 exp7（KINDS）；合成泡沫：强（涨幅 0.6，CF=0.1，exp2 设置）与中等（涨幅 0.3，CF=0.05），t_c 窗外 +5%dt / 窗内 −5%dt 各半。
用法：PYTHONPATH=. LPPLS_BOX=v2 python scripts/audit_stock_math/exp17_q3_calibration.py <procs> <null_reps> <bub_seeds>"""
import os
import sys
import time

OUT = os.environ.get("AUDIT_OUT", "/home/ubuntu/audit"); os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, os.getcwd())
from multiprocessing import Pool

import numpy as np
import pandas as pd

from research.features import lppls_scan
from research.features.lppls_rules import _derived, grid_rules, rules
from research.lppls import core
from research.pipeline import universe
from scripts.audit_stock_math.exp7_null_calibration import KINDS, REAL, load_real, series

K = 20


def init(real):
    core.ALLOW_INSIDE = True
    REAL.update(real)


def bubble(seed, n, tc_rel, rise=0.6, CF=0.1, sigma=0.01, m0=0.5, w0=9.0):
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float); dt = n - 1; tc0 = dt + tc_rel * dt
    X = core.design(t, tc0, m0, w0, allow_inside=True)
    B = -rise / (abs(tc0) ** m0)
    return X @ np.array([8.0, B, CF * abs(B), CF * abs(B)]) + rng.normal(0, sigma, n)


def filt(row, n, y):
    d = dict(zip(lppls_scan.COLS[1:], row, strict=True)); d.update(y_std=float(np.std(y)), date=pd.Timestamp("2020-01-01"), n=n)
    df = _derived(pd.DataFrame([d]))
    return d, bool(rules(df).box.iloc[0]), bool(grid_rules(df).g_fco_standard.iloc[0])


def q3(y):
    n = len(y); r = np.diff(y)
    row = lppls_scan.fit_one(y)
    d, box, std = filt(row, n, y)
    d.update(box=box, standard=std)
    if not (box or std):
        return d
    e = np.sqrt(d["sse"] / n) / np.std(y)
    es, fb, fs = [], 0, 0
    ks = lppls_scan.q3_shifts(n, K)
    for k in ks:
        ys = y[0] + np.concatenate([[0.0], np.cumsum(np.roll(r, k))])
        rs = lppls_scan.fit_one(ys)
        ds, b2, s2 = filt(rs, n, ys)
        es.append(np.sqrt(ds["sse"] / n) / np.std(ys)); fb += b2; fs += s2
    es = np.array(es)
    d.update(e=e, e_star_med=float(np.median(es)), q3_p=(1 + int((es <= e).sum())) / (len(ks) + 1), f_box=fb / len(ks), f_std=fs / len(ks))
    return d


def one(args):
    kind, seed, tc_rel = args
    windows = tuple(universe.WINDOWS)
    rng = np.random.default_rng(seed)
    if kind.startswith("bubble"):
        rise, cf = (0.6, 0.1) if kind == "bubble" else (0.3, 0.05)
        ys = {n: bubble(seed, n, tc_rel, rise, cf) for n in windows}
    else:
        y_full = series(kind, max(windows), rng)
        ys = {n: y_full[-n:] for n in windows}
    out = []
    for _n, y in ys.items():
        d = q3(y); d.update(kind=kind, seed=seed, tc_rel=tc_rel); out.append(d)
    return out


if __name__ == "__main__":
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    null_reps = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    bub_seeds = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    real = load_real()
    tasks = [(k, s, 0.0) for k in KINDS for s in range(null_reps)]
    tasks += [(b, 5000 + s, tr) for b in ("bubble", "bubble_mid") for tr in (0.05, -0.05) for s in range(bub_seeds)]
    print(f"tasks={len(tasks)} K={K}", flush=True)
    t0 = time.time()
    with Pool(procs, initializer=init, initargs=(real,)) as p:
        rows = [r for rs in p.imap_unordered(one, tasks, chunksize=1) for r in rs]
    df = pd.DataFrame(rows); df.to_parquet(f"{OUT}/exp17_q3.parquet")
    print(f"rows={len(df)} elapsed {time.time() - t0:.0f}s", flush=True)
    pas = df[df.box | df.standard]
    print(pas.groupby("kind").agg(n=("q3_p", "size"), p05=("q3_p", lambda x: (x <= 0.05).mean()), p10=("q3_p", lambda x: (x <= 0.10).mean()), f_box=("f_box", "mean")).round(3).to_string())
