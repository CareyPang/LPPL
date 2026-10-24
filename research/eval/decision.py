"""决策层 D-TOP 的开发段回测（预登记 v1.2 §12.4）。

输入：保留链末级的 CPCV OOF 概率（开发段用未校准的 OOF p，校准段以后用 Platt 后的 p）。
规则：阈值 (p1, p2) × {一步减至 1/3；两步 2/3 → 1/3}；p 连续 20 日 < p1 后恢复满仓。
v1.4 §14.1 连续规则：c1 仓位 = clip(1 − p/0.5, 1/3, 1)；c2 = min(波动率目标仓位, c1)。
执行：T+1（次日收盘成交，保守）；涨跌停日（|日收益| ≥ 9.5%）顺延一日。
成本：佣金 0.025% 双边、印花税 0.1% 卖出、滑点 0.1%。
主评分：每个事件段结束后 60 日内策略最大回撤相对买入持有的减少量（百分点，正为改善），跨事件段平均。
基线：买入持有（恒为 0）、波动率目标（年化 20%，20 日已实现波动）、安慰剂（月末随机减仓，频率同规则，200 个种子取均值）。
淘汰：相对波动率目标与相对安慰剂的改善量，80 日块 bootstrap 90% 区间都不含 0。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .dataset import price_series

RULES = {f"p{int(p1*100)}-{int(p2*100)}_{mode}": (p1, p2, mode)
         for p1, p2 in ((0.15, 0.30), (0.20, 0.40), (0.25, 0.50)) for mode in ("one", "two")}
P_MAX = 0.5  # v1.4 §14.1 连续规则
COMM, STAMP, SLIP = 0.00025, 0.001, 0.001
LIMIT, RESTORE, VOL_TARGET, AFTER = 0.095, 20, 0.20, 60
N_PLACEBO = 200


def target_position(p: np.ndarray, p1: float, p2: float, mode: str) -> np.ndarray:
    s = pd.Series(p)
    calm = s.ge(p1).rolling(RESTORE, min_periods=RESTORE).max().eq(0)
    low = 1 / 3 if mode == "one" else 2 / 3
    tgt = np.where(s >= p2, 1 / 3, np.where(s >= p1, low, np.where(calm, 1.0, np.nan)))
    return pd.Series(tgt).ffill().fillna(1.0).to_numpy()


def execute(tgt: np.ndarray, r: np.ndarray) -> np.ndarray:
    """目标仓位（t 收盘决定）→ 实际持仓（t+1 收盘成交；涨跌停日顺延）。返回每日收益计算用的持仓（期初仓位）。"""
    pos = pd.Series(tgt).shift(1)
    lim = np.abs(r) >= LIMIT
    pos[lim] = np.nan
    return pos.ffill().fillna(1.0).to_numpy()


def strategy_returns(pos: np.ndarray, r: np.ndarray) -> np.ndarray:
    prev = np.concatenate([[1.0], pos[:-1]])
    d = pos - prev
    cost = np.abs(d) * (COMM + SLIP) + np.where(d < 0, -d * STAMP, 0.0)
    return prev * r - cost


def max_drawdown(ret: np.ndarray) -> float:
    eq = np.cumprod(1 + ret)
    return float((eq / np.maximum.accumulate(eq) - 1).min()) if len(eq) else 0.0


def vol_target_position(r: np.ndarray) -> np.ndarray:
    rv = pd.Series(r).rolling(20, min_periods=20).std() * np.sqrt(250)
    return np.minimum(1.0, VOL_TARGET / rv).fillna(1.0).to_numpy()


def placebo_positions(n: int, dates: pd.DatetimeIndex, freq: float, rng: np.random.Generator) -> np.ndarray:
    """月末以概率 freq 减至 1/3，持续 RESTORE 日后恢复；返回 (n, N_PLACEBO)。"""
    me = np.flatnonzero(pd.Series(dates).dt.month.diff().fillna(0).ne(0).to_numpy())
    pos = np.ones((n, N_PLACEBO))
    hit = rng.random((len(me), N_PLACEBO)) < freq
    for i, k in enumerate(me):
        cols = np.flatnonzero(hit[i])
        pos[k : k + RESTORE, cols] = 1 / 3
    return pos


def event_windows(y: np.ndarray) -> list[int]:
    v = y == 1
    ends = np.flatnonzero(v[:-1] & ~v[1:])
    if len(v) and v[-1]:
        ends = np.append(ends, len(v) - 1)
    return [int(e) for e in ends]


def evaluate_series(g: pd.DataFrame, logp: pd.Series, rng: np.random.Generator) -> list[dict]:
    """g：单一 (symbol, path, 连续块) 的 OOF；返回每个事件段 × 策略的事件后 60 日回撤改善量。"""
    lp = logp.reindex(g.date).to_numpy()
    r = np.diff(lp, prepend=lp[0])
    r = np.expm1(r)
    y, p = g.y.to_numpy(), g.p.to_numpy()
    strat = {name: strategy_returns(execute(target_position(p, *cfg), r), r) for name, cfg in RULES.items()}
    vt = vol_target_position(r)
    c1 = np.clip(1 - p / P_MAX, 1 / 3, 1.0)
    strat["c1_linear"] = strategy_returns(execute(c1, r), r)
    strat["c2_linear_x_vol"] = strategy_returns(execute(np.minimum(vt, c1), r), r)
    strat["vol_target"] = strategy_returns(execute(vt, r), r)
    freq = float(np.mean([np.mean(target_position(p, *cfg) < 1) for cfg in RULES.values()]))
    month_freq = min(1.0, freq * 21 / RESTORE)
    pl = placebo_positions(len(r), pd.DatetimeIndex(g.date), month_freq, rng)
    pl_ret = np.column_stack([strategy_returns(execute(pl[:, j], r), r) for j in range(N_PLACEBO)])
    out = []
    for e in event_windows(y):
        a, b = e + 1, min(e + 1 + AFTER, len(r))
        if b - a < 20:
            continue
        bh = max_drawdown(r[a:b])
        row = dict(symbol=g.symbol.iloc[0], path=int(g.path.iloc[0]), date=g.date.iloc[e], bh_dd=bh)
        for name, s in strat.items():
            row[name] = (max_drawdown(s[a:b]) - bh) * 100
        row["placebo"] = float(np.mean([(max_drawdown(pl_ret[a:b, j]) - bh) * 100 for j in range(N_PLACEBO)]))
        out.append(row)
    return out


def block_ci(delta: np.ndarray, dates: pd.Series, cal: pd.DatetimeIndex, block_days: int = 80, B: int = 1000,
             seed: int = 0, level: float = 0.9) -> tuple[float, float, float]:
    blk = cal.get_indexer(dates) // block_days
    g = pd.Series(delta).groupby(blk).agg(["sum", "size"])
    rng = np.random.default_rng(seed)
    vals = [(lambda pick: g["sum"].to_numpy()[pick].sum() / g["size"].to_numpy()[pick].sum())(rng.integers(0, len(g), len(g))) for _ in range(B)]
    a = (1 - level) / 2
    return float(delta.mean()), float(np.quantile(vals, a)), float(np.quantile(vals, 1 - a))


def run(oof_path: str, tag: str = "dtop_dev") -> pd.DataFrame:
    oof = pd.read_parquet(oof_path).sort_values(["symbol", "path", "date"])
    cal = price_series("sh000001").index
    rng = np.random.default_rng(0)
    rows = []
    for sym, gs in oof.groupby("symbol", sort=False):
        logp = price_series(sym)
        for _, g in gs.groupby("path", sort=False):
            idx = cal.get_indexer(g.date)
            blk = np.cumsum(np.diff(idx, prepend=idx[0]) > 10)
            for _, gb in g.groupby(blk):
                if len(gb) > 60:
                    rows.append(pd.DataFrame(evaluate_series(gb.reset_index(drop=True), logp, rng)))
    ev = pd.concat([x for x in rows if len(x)], ignore_index=True)
    res = []
    names = list(RULES) + ["c1_linear", "c2_linear_x_vol", "vol_target", "placebo"]
    for name in names:
        d_vt, lo_vt, hi_vt = block_ci((ev[name] - ev.vol_target).to_numpy(), ev.date, cal)
        d_pl, lo_pl, hi_pl = block_ci((ev[name] - ev.placebo).to_numpy(), ev.date, cal)
        res.append(dict(rule=name, dd_improve_pp=ev[name].mean(), vs_voltarget=d_vt, vt_lo=lo_vt, vt_hi=hi_vt,
                        vs_placebo=d_pl, pl_lo=lo_pl, pl_hi=hi_pl, kept=(lo_vt > 0) & (lo_pl > 0) if name not in ("vol_target", "placebo") else np.nan))
    tab = pd.DataFrame(res)
    ev.to_csv(f"reports/{tag}_events.csv", index=False)
    tab.to_csv(f"reports/{tag}.csv", index=False)
    with open(f"reports/{tag}.md", "w") as f:
        f.write("# D-TOP 决策层开发段回测（§12.4；输入为未校准 OOF 概率；值为事件后 60 日最大回撤相对买入持有的减少量，百分点，正为改善）\n\n")
        f.write(f"事件段 {len(ev)}（含 CPCV 多路径重复），标的 {ev.symbol.nunique()}；买入持有事件后平均最大回撤 {ev.bh_dd.mean()*100:.2f}%。\n\n")
        f.write(tab.round(4).to_markdown(index=False) + "\n\n淘汰规则：相对波动率目标与相对安慰剂的改善量 90% 块 bootstrap 区间下界均 > 0 才保留。\n")
    print(tab.round(4).to_string(), flush=True)
    return tab


if __name__ == "__main__":
    import sys

    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "dtop_dev")
