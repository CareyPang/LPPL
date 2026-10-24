"""阶段 4：LPPLS 多窗口扫描（R3 POWER、R4a–R4f 的共同原始材料）。

预登记 v1.1（计算量修订）：
- 指数：每 5 个交易日一个 as-of 时点，窗口 125–750 日步长 5（126 个，E7）；
- 个股：每 20 个交易日一个时点，窗口 125–750 日步长 25（26 个）；时点只在所属快照段内取。
每个窗口只做一次 LPPLS 拟合（冻结的 tcgrid_lm，搜索域 m∈[0.01,2]、ω∈[1,50]、t_c∈(t₂, t₂+0.2·dt]）
和一次纯幂律拟合（同一 t_c、m 域）。所有过滤规则（原型 ds/strict/TOP、LIT 条件 1/2）在之后由
存下来的参数派生，不再重复拟合。t_c<t₂ 的部分未实现（设计矩阵要求 t_c>t），记录为 v1.1 限制。
停牌处理：窗口内日历交易日缺失超过 10% 的窗口不拟合。
"""
from __future__ import annotations

import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from ..eval.dataset import SPLITS, _snapshot, price_series
from ..labels.run_top import INDEXES
from ..lppls.core import K_POWER, lin_fit
from ..optim.optimizers import tcgrid_lm

OUT = Path("data/features/lppls_v1")
IDX_STEP, STK_STEP = 5, 20
IDX_WINDOWS = tuple(range(125, 751, 5))
STK_WINDOWS = tuple(range(125, 751, 25))
MAX_GAP_SHARE = 0.10
COLS = ["date", "n", "tc", "m", "w", "A", "B", "C1", "C2", "sse", "r2", "pow_tc", "pow_m", "pow_B", "pow_sse"]


def calendar() -> pd.DatetimeIndex:
    return price_series("sh000001").index


def fit_one(y: np.ndarray) -> tuple:
    n = len(y)
    t = np.arange(n, dtype=float)
    dt = n - 1
    lo = np.array([dt + 0.5, 0.01, 1.0])
    hi = np.array([dt + 0.2 * dt, 2.0, 50.0])
    r = tcgrid_lm(t, y, lo, hi, seed=0)
    s, beta = lin_fit(t, y, *r.theta)
    sst = float(((y - y.mean()) ** 2).sum())
    rp = tcgrid_lm(t, y, lo[:2], hi[:2], seed=0, k=K_POWER)
    sp, bp = lin_fit(t, y, rp.theta[0], rp.theta[1], 0.0, K_POWER)
    return (n, *map(float, r.theta), *map(float, beta), float(s), 1 - s / sst,
            float(rp.theta[0]), float(rp.theta[1]), float(bp[1]), float(sp))


def scan_dates(sym: str, dates: list[pd.Timestamp], windows: tuple[int, ...], cal: pd.DatetimeIndex) -> pd.DataFrame:
    logp = price_series(sym)
    pos = {d: i for i, d in enumerate(logp.index)}
    cal_pos = {d: i for i, d in enumerate(cal)}
    rows = []
    for d in dates:
        i = pos.get(d)
        if i is None:
            continue
        for n in windows:
            if i + 1 < n:
                continue
            seg = logp.iloc[i + 1 - n : i + 1]
            ncal = cal_pos[seg.index[-1]] - cal_pos[seg.index[0]] + 1 if seg.index[0] in cal_pos else n
            if n < (1 - MAX_GAP_SHARE) * ncal:
                continue
            rows.append((d, *fit_one(seg.to_numpy())))
    return pd.DataFrame(rows, columns=COLS)


def _task(args):
    sym, dates, windows, cal = args
    return sym, scan_dates(sym, dates, windows, cal)


def asof_dates(sym: str, group: str, cal: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """全局日历上 step 的整数倍位置，限制在该标的所属样本段内。"""
    logp = price_series(sym)
    step = IDX_STEP if group == "index" else STK_STEP
    grid = set(cal[::step])
    if group == "index":
        lo, hi = pd.Timestamp("2000-01-01"), pd.Timestamp("2025-08-31")
        ok = lambda d: lo <= d <= hi  # noqa: E731
    else:
        spans = []
        for a, b, csv, entry in SPLITS.values():
            if sym in _snapshot(csv):
                lo = max(pd.Timestamp(a), pd.Timestamp(entry), logp.index[0] + pd.DateOffset(years=5))
                spans.append((lo, pd.Timestamp(b)))
        ok = lambda d: any(lo <= d <= hi for lo, hi in spans)  # noqa: E731
    return [d for d in logp.index if d in grid and ok(d)]


def run(group: str, procs: int = 8, chunk: int = 10):
    OUT.mkdir(parents=True, exist_ok=True)
    cal = calendar()
    syms = list(INDEXES) if group == "index" else sorted({s for *_, csv, _ in SPLITS.values() for s in _snapshot(csv)})
    windows = IDX_WINDOWS if group == "index" else STK_WINDOWS
    tasks, parts = [], {}
    for sym in syms:
        if (OUT / f"{sym}.parquet").exists():
            continue
        ds = asof_dates(sym, group, cal)
        parts[sym] = [None] * ((len(ds) + chunk - 1) // chunk)
        for j in range(0, len(ds), chunk):
            tasks.append((sym, ds[j : j + chunk], windows, cal))
    print(f"{group}: {len(syms)} symbols, {len(tasks)} tasks", flush=True)
    done_tasks = {s: 0 for s in parts}
    pieces = {s: [] for s in parts}
    with Pool(procs) as pool:
        for k, (sym, df) in enumerate(pool.imap_unordered(_task, tasks)):
            pieces[sym].append(df)
            done_tasks[sym] += 1
            if done_tasks[sym] == len(parts[sym]):
                pd.concat(pieces[sym]).sort_values(["date", "n"]).to_parquet(OUT / f"{sym}.parquet")
                print(f"done {sym}", flush=True)
            if (k + 1) % 100 == 0:
                print(f"tasks {k + 1}/{len(tasks)}", flush=True)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "index")
