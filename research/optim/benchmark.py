"""合成数据上比较四种优化器。输出 reports/optimizer_benchmark.json + .md。

评价维度：|Δtc|（bar）、|Δm|、|Δω|、SSE 相对真值 SSE 的比值（<1 表示拟合到了噪声，
也是正常的；>1 表示没找到全局极小）、失败率（SSE 比真值大 5% 以上视为失败）、
多 seed 分散度、nfev、墙钟。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ..lppls.core import default_bounds, sse
from ..synth.lppls_synth import sample
from .optimizers import METHODS

REPORTS = Path(__file__).resolve().parents[2] / "reports"


def run(n_cases=20, sigmas=(0.01, 0.03), noises=("iid", "ar1"), methods=tuple(METHODS), seeds=(0, 1, 2), n=250):
    rows = []
    for noise in noises:
        for sigma in sigmas:
            for case in range(n_cases):
                t, y, tr = sample(n=n, sigma=sigma, noise=noise, seed=1000 * case + 7)
                lo, hi = default_bounds(n, horizon=(1, 90))
                s_true = sse(tr.theta(), t, y)
                for mth in methods:
                    thetas = []
                    for seed in seeds:
                        r = METHODS[mth](t, y, lo, hi, seed=seed)
                        thetas.append(r.theta)
                        rows.append(dict(noise=noise, sigma=sigma, case=case, method=mth, seed=seed,
                                         dtc=float(r.theta[0] - tr.tc), dm=float(r.theta[1] - tr.m),
                                         dw=float(r.theta[2] - tr.w), sse_ratio=r.sse / s_true,
                                         fail=bool(r.sse > 1.05 * s_true), nfev=r.nfev, sec=r.seconds))
                    th = np.array(thetas)
                    for row in rows[-len(seeds):]:
                        row["seed_spread_tc"] = float(th[:, 0].max() - th[:, 0].min())
                print(f"{noise} σ={sigma} case={case} done", flush=True)
    return rows


def summarize(rows):
    import pandas as pd

    df = pd.DataFrame(rows)
    g = df.groupby(["noise", "sigma", "method"])
    s = g.agg(med_abs_dtc=("dtc", lambda x: float(np.median(np.abs(x)))),
              p90_abs_dtc=("dtc", lambda x: float(np.quantile(np.abs(x), 0.9))),
              med_abs_dm=("dm", lambda x: float(np.median(np.abs(x)))),
              med_abs_dw=("dw", lambda x: float(np.median(np.abs(x)))),
              fail_rate=("fail", "mean"), med_sse_ratio=("sse_ratio", "median"),
              med_seed_spread_tc=("seed_spread_tc", "median"),
              med_nfev=("nfev", "median"), med_sec=("sec", "median")).reset_index()
    return df, s


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cases", type=int, default=20)
    p.add_argument("--quick", action="store_true")
    a = p.parse_args()
    if a.quick:
        rows = run(n_cases=3, sigmas=(0.02,), noises=("iid",), seeds=(0, 1))
    else:
        rows = run(n_cases=a.cases)
    df, s = summarize(rows)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "optimizer_benchmark.json").write_text(json.dumps(rows, indent=1))
    md = "# 优化器合成数据对比\n\n" + s.to_markdown(index=False, floatfmt=".3g") + "\n"
    (REPORTS / "optimizer_benchmark.md").write_text(md)
    print(s.to_string())
