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

import os
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from ..eval.dataset import SPLITS, _snapshot, price_series
from ..labels.run_top import INDEXES
from ..lppls import core as _core
from ..lppls.core import K_POWER, design, lin_fit
from ..optim.optimizers import de_lbfgsb, tcgrid_lm

# 搜索域版本（预登记 v1.7 §17.1）：v1 = 宽域（v1.1 登记：m∈[0.01,2]、ω∈[1,50]、t_c≤t₂+0.2dt）；
# v2 = 原型 engine.js / Filimonov–Sornette 2013 域（m∈[0.01,0.99]、ω∈[2,25]、t_c≤t₂+min(0.2dt,115)）。
# 由环境变量 LPPLS_BOX 选择，输出目录随版本分开，v1 结果保留为失败记录不覆盖。
BOX = os.environ.get("LPPLS_BOX", "v1")
BOXES = {
    # v1：E7 表 3 搜索域，但 t_c 只能在 t₂ 之后、无短尺度、单起点（v1.1 登记）
    "v1": dict(m=(0.01, 2.0), w=(1.0, 50.0), tc=(0.5, 0.2), inside=False, n_random=0, short=False),
    # proto：原型 engine.js 搜索域（预登记 §17.1 的变体，非主版本）
    "proto": dict(m=(0.01, 0.99), w=(2.0, 25.0), tc=(0.5, 0.2), inside=False, n_random=0, short=False, tc_cap=115.0),
    # v2：§17.4 原版复现——E7 搜索域 + t_c∈[t₂−0.2dt, t₂+0.2dt] + 10 随机起点 + 短尺度 30–120 日窗口
    "v2": dict(m=(0.01, 2.0), w=(1.0, 50.0), tc=(-0.2, 0.2), inside=True, n_random=10, short=True),
}
# §17.4-7 反泡沫两种形式：SIGN=neg → 对 −ln P 拟合（Yan–Woodard–Sornette 2010 负泡沫，t_c 在未来）；
# ANCHOR=start → t_c 搜索域改为窗口起点之前 [t₁−0.2dt, t₁]（Johansen–Sornette 1999 反泡沫，描述峰后衰减振荡）。
# §17.6 补齐：LPPLS_WINDOWS=full（默认）| xs（探索尺度 15–30 日，样本点少，只作参考）| lite（步长 10、随机起点 3，用于负泡沫/反泡沫减配扫描）
WINDOWS_MODE = os.environ.get("LPPLS_WINDOWS", "full")
SIGN = os.environ.get("LPPLS_SIGN", "pos")
ANCHOR = os.environ.get("LPPLS_ANCHOR", "end")
STOCK_SAMPLE = int(os.environ.get("LPPLS_STOCK_SAMPLE", "0"))
SUFFIX = ("_neg" if SIGN == "neg" else "") + ("_ab" if ANCHOR == "start" else "") + ("" if WINDOWS_MODE == "full" else f"_{WINDOWS_MODE}")
XS_WINDOWS = (15, 20, 25, 30)
OUT_TAG = os.environ.get("LPPLS_OUT_TAG", "")  # 样本段分目录（如 _cal），避免 run() 因开发段 parquet 已存在而跳过
OUT = Path(f"data/features/lppls_{BOX}{SUFFIX}" + (f"_stk{STOCK_SAMPLE}" if STOCK_SAMPLE else "") + OUT_TAG)
LOMB_W = np.arange(1.0, 50.01, 0.25)
IDX_STEP, STK_STEP = 5, 20
IDX_WINDOWS = tuple(range(125, 751, 5))
STK_WINDOWS = tuple(range(125, 751, 25))
MAX_GAP_SHARE = 0.10
COLS = ["date", "n", "tc", "m", "w", "A", "B", "C1", "C2", "sse", "r2", "pow_tc", "pow_m", "pow_B", "pow_sse",
        "lomb_w", "lomb_pn", "df_t"]
# §20 偏离 _g3：LPPLS_G3=1 → tcgrid_lm 与 de_lbfgsb 取最小 SSE（g3_src=哪一个赢）；§22 Q3：LPPLS_Q3=K>0 → 对过 box 的窗口做 K 个
# 循环平移对照重拟，记 q3_p=(1+#{e*≤e})/(K+1)（e=√(SSE/n)/σ_y），未过 box 的窗口 q3_p=NaN。两者默认关闭，关闭时输出与现行逐位相同。
G3 = os.environ.get("LPPLS_G3", "") == "1"
Q3_K = int(os.environ.get("LPPLS_Q3", "0"))
EXTRA_COLS = (["g3_src"] if G3 else []) + (["q3_p"] if Q3_K else [])
COLS = COLS + EXTRA_COLS
SHORT_WINDOWS = tuple(range(30, 121, 5))
# 仅日更/产品显示用的补充窗口（FCO 六档中的 2–4 周与 2–6 年）；不进入开发/校准/测试段扫描与评价
XS_WINDOWS = tuple(range(10, 21, 2))
XL_WINDOWS = tuple(range(525, 1501, 25))


def residual_tests(t: np.ndarray, y: np.ndarray, tc: float, m: float, w: float, beta: np.ndarray) -> tuple[float, float, float]:
    """Jiang 2010 §2.3–2.4 的两项：去趋势残差 r=(y−A−B f)/f 对 ln|t_c−t| 的 Lomb 峰频与归一化峰功率；
    拟合残差的 DF 回归 t 统计量（Δe_t = c + ρ e_{t−1}，t_ρ；越负越平稳，渐近 5% 临界值约 −2.86）。"""
    from scipy.signal import lombscargle

    dtt = np.maximum(np.abs(tc - t), _core.MIN_DT)
    f = dtt ** m
    r = (y - beta[0] - beta[1] * f) / f
    x = np.log(dtt)
    try:
        pn = lombscargle(x, r - r.mean(), LOMB_W, normalize=True)
        j = int(np.argmax(pn))
        lomb_w, lomb_pn = float(LOMB_W[j]), float(pn[j])
    except Exception:
        lomb_w, lomb_pn = np.nan, np.nan
    X = design(t, tc, m, w)
    e = y - X @ beta if X is not None else np.full_like(y, np.nan)
    de, e1 = np.diff(e), e[:-1]
    Z = np.column_stack([np.ones_like(e1), e1])
    try:
        coef, *_ = np.linalg.lstsq(Z, de, rcond=None)
        res = de - Z @ coef
        s2 = float(res @ res) / max(1, len(de) - 2)
        cov = s2 * np.linalg.inv(Z.T @ Z)
        df_t = float(coef[1] / np.sqrt(cov[1, 1]))
    except Exception:
        df_t = np.nan
    return lomb_w, lomb_pn, df_t


def calendar() -> pd.DatetimeIndex:
    return price_series("sh000001").index


def fit_one(y: np.ndarray) -> tuple:
    n = len(y)
    t = np.arange(n, dtype=float)
    dt = n - 1
    bx = BOXES[BOX]
    tc_lo, tc_hi = bx["tc"]
    ahead_hi = 0.2 * dt if bx.get("tc_cap") is None else min(0.2 * dt, bx["tc_cap"])
    if ANCHOR == "start":
        lo = np.array([-0.2 * dt, bx["m"][0], bx["w"][0]])
        hi = np.array([-0.5, bx["m"][1], bx["w"][1]])
    else:
        lo = np.array([dt + (tc_lo if tc_lo >= 0.5 else tc_lo * dt), bx["m"][0], bx["w"][0]])
        hi = np.array([dt + ahead_hi, bx["m"][1], bx["w"][1]])
    if SIGN == "neg":
        y = -y
    n_random = 3 if WINDOWS_MODE == "lite" else bx["n_random"]
    r = tcgrid_lm(t, y, lo, hi, seed=0, n_random=n_random)
    src = "tcgrid_lm"
    if G3:
        r2 = de_lbfgsb(t, y, lo, hi, seed=0)
        if r2.sse < r.sse:
            r, src = r2, "de_lbfgsb"
    s, beta = lin_fit(t, y, *r.theta)
    sst = float(((y - y.mean()) ** 2).sum())
    rp = tcgrid_lm(t, y, lo[:2], hi[:2], seed=0, k=K_POWER, n_random=n_random)
    sp, bp = lin_fit(t, y, rp.theta[0], rp.theta[1], 0.0, K_POWER)
    row = (n, *map(float, r.theta), *map(float, beta), float(s), 1 - s / sst,
           float(rp.theta[0]), float(rp.theta[1]), float(bp[1]), float(sp),
           *residual_tests(t, y, *r.theta, beta))
    if G3:
        row = (*row, src)
    if Q3_K:
        row = (*row, _q3_p(y, row, lo, hi, n_random))
    return row


def _box_pass(y: np.ndarray, row: tuple) -> bool:
    from .lppls_rules import _derived, rules
    d = dict(zip(COLS[1 : 1 + len(row)], row, strict=True))
    d.update(y_std=float(np.std(y)), date=pd.Timestamp("2000-01-01"))
    return bool(rules(_derived(pd.DataFrame([d]))).box.iloc[0])


def q3_shifts(n: int, k: int) -> list[int]:
    """§22.1.1：K 个互不相同的循环平移偏移，等距落在 [5, n−6]（离恒等平移两侧都 ≥5 日）。
    原写法 round(n/K·j) mod (n−1) 在 j=K 时给出偏移 1（近恒等），n=30 时偏移 5 重复三次。可用偏移不足 K 个时全部取用。"""
    lo, hi = 5, n - 6
    if hi - lo + 1 <= k:
        return list(range(lo, hi + 1))
    if k == 1:
        return [(lo + hi) // 2]
    return [lo + int(round((hi - lo) * j / (k - 1))) for j in range(k)]


def _q3_p(y: np.ndarray, row: tuple, lo, hi, n_random: int) -> float:
    """§22.1（偏移集按 §22.1.1 更正）：对过 box 的窗口，K 个互不相同的循环平移对照（q3_shifts）各重拟一次（同一优化器组合），
    p=(1+#{e*≤e})/(K+1)。未过 box 返回 NaN（不算，省算力）。"""
    if not _box_pass(y, row):
        return float("nan")
    n = len(y)
    t = np.arange(n, dtype=float)
    e = np.sqrt(row[COLS.index("sse") - 1] / n) / np.std(y)
    r = np.diff(y)
    cnt = 0
    ks = q3_shifts(n, Q3_K)
    for k in ks:
        ys = y[0] + np.concatenate([[0.0], np.cumsum(np.roll(r, k))])
        f = tcgrid_lm(t, ys, lo, hi, seed=0, n_random=n_random)
        if G3:
            f2 = de_lbfgsb(t, ys, lo, hi, seed=0)
            if f2.sse < f.sse:
                f = f2
        if np.sqrt(f.sse / n) / np.std(ys) <= e:
            cnt += 1
    return (1 + cnt) / (len(ks) + 1)


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


def asof_dates(sym: str, group: str, cal: pd.DatetimeIndex, splits: tuple[str, ...] = ("dev", "cal", "test")) -> list[pd.Timestamp]:
    """全局日历上 step 的整数倍位置，限制在该标的所属样本段内。"""
    logp = price_series(sym)
    step = IDX_STEP if group == "index" else STK_STEP
    grid = set(cal[::step])
    if group == "index":
        sel = [(pd.Timestamp(a), pd.Timestamp(b)) for name, (a, b, *_) in SPLITS.items() if name in splits]
        lo = max(pd.Timestamp("2000-01-01"), min(a for a, _ in sel))
        hi = min(pd.Timestamp("2025-08-31"), max(b for _, b in sel))
        ok = lambda d: lo <= d <= hi  # noqa: E731
    else:
        spans = []
        for name, (a, b, csv, entry) in SPLITS.items():
            if name in splits and sym in _snapshot(csv):
                lo = max(pd.Timestamp(a), pd.Timestamp(entry), logp.index[0] + pd.DateOffset(years=5))
                spans.append((lo, pd.Timestamp(b)))
        ok = lambda d: any(lo <= d <= hi for lo, hi in spans)  # noqa: E731
    return [d for d in logp.index if d in grid and ok(d)]


SHARD = os.environ.get("LPPLS_SHARD", "")  # "i/N"：只扫该标的 as-of 日期的第 i::N 子集，输出 <sym>__part{i}of{N}.parquet（§20 _g2 重扫走 Actions 矩阵）
SYMBOLS = tuple(x for x in os.environ.get("LPPLS_SYMBOLS", "").split(",") if x)  # 只扫这些标的（空=全部）


def _shard_dates(ds: list[pd.Timestamp], shard: str = SHARD) -> tuple[list[pd.Timestamp], str]:
    """按 "i/N" 取日期子集（交错切分，使每片覆盖整个样本段）；返回 (日期, 文件名后缀)。"""
    if not shard:
        return ds, ""
    i, n = (int(x) for x in shard.split("/"))
    if not 0 <= i < n:
        raise ValueError(f"bad LPPLS_SHARD {shard!r}")
    return ds[i::n], f"__part{i}of{n}"


def run(group: str, procs: int = 8, chunk: int = 10, splits: tuple[str, ...] = ("dev", "cal", "test")):
    """splits：个股只扫这些样本段（§12.2 算力门触发后只扫 dev）。"""
    OUT.mkdir(parents=True, exist_ok=True)
    _core.ALLOW_INSIDE = bool(BOXES[BOX]["inside"])
    cal = calendar()
    syms = list(INDEXES) if group == "index" else sorted({s for n, (*_, csv, _) in SPLITS.items() if n in splits for s in _snapshot(csv)})
    if SYMBOLS:
        syms = [s for s in syms if s in SYMBOLS]
    if group != "index" and STOCK_SAMPLE:
        # §17.11 个股样本：按市场（sh/sz）分层、固定种子抽 STOCK_SAMPLE 只，先判断横截面排名值不值得全跑
        rng = np.random.default_rng(20261025)
        by_mkt = {m: sorted(x for x in syms if x.startswith(m)) for m in ("sh", "sz")}
        picked = []
        for xs in by_mkt.values():
            k = round(STOCK_SAMPLE * len(xs) / len(syms))
            picked += list(rng.choice(xs, size=min(k, len(xs)), replace=False))
        syms = sorted(picked)
    windows = IDX_WINDOWS if group == "index" else STK_WINDOWS
    if BOXES[BOX]["short"]:
        windows = SHORT_WINDOWS + windows
    if WINDOWS_MODE == "xs":
        windows = XS_WINDOWS
    elif WINDOWS_MODE == "lite":
        windows = tuple(w for w in windows if w % 10 == 0)
    tasks, parts = [], {}
    for sym in syms:
        ds, suffix = _shard_dates(asof_dates(sym, group, cal, splits))
        if (OUT / f"{sym}{suffix}.parquet").exists() or not ds:
            continue
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
                pd.concat(pieces[sym]).sort_values(["date", "n"]).to_parquet(OUT / f"{sym}{_shard_dates([])[1]}.parquet")
                print(f"done {sym}", flush=True)
            if (k + 1) % 100 == 0:
                print(f"tasks {k + 1}/{len(tasks)}", flush=True)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "index", procs=int(os.environ.get("LPPLS_PROCS", "8")),
        splits=tuple(sys.argv[2].split(",")) if len(sys.argv) > 2 else ("dev", "cal", "test"))
