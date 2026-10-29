"""开发段探索（dev_only）：置信度报警之后的**执行规则**对比——不是新预测指标，不改任何冻结判据。

输入：reports/tc_stability_dev/per_date.csv（box 6–12m 置信度，周网格 as-of）+ 冻结价格。
报警事件：置信度首次 ≥0.5 的 as-of 日 d50（事件内上一次 ≥0.2 的首日记 d20）；事件结束 = 置信度连续 8 周 <0.2。
参考量（事后，仅用于评价）：d50 后 250 交易日内最高收盘 peak、peak 后 250 交易日内最低收盘 trough。
规则（d50 起对剩余仓位执行，之前 ≥0.2 时是否先减 1/3 由 tiered 决定）：
  sell_at_50      d50 当日清仓（现行指南的保守读法）
  trail_k         d50 后自最高收盘回撤 ≥k% 清仓（k=8/10/15）
  ma_n            d50 后收盘跌破 n 日均线清仓（n=20/60）
  hold_to_end     持有到事件结束（置信度连续 8 周 <0.2）
  hold_250        持有 250 日（买入持有基线）
每条规则输出：exit 相对 d50 的收益、相对 peak 的捕获比例、exit 距 peak 的交易日数、exit 后 250 日内最大继续下跌（规则漏掉的损失）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ..eval.dataset import price_series

ROOT = Path(__file__).resolve().parents[2]
PER_DATE = ROOT / "reports/tc_stability_dev/per_date.csv"
OUT = ROOT / "reports/exit_rules_dev"
TRAILS = (0.08, 0.10, 0.15)
MAS = (20, 60)
END_WEEKS = 8
H = 250


def episodes(tab: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp | None, pd.Timestamp | None]]:
    """返回 (d20, d50, end)；d20 为本事件内首个 ≥0.2 的 as-of，end 为连续 8 周 <0.2 的首日（None=开发段内未结束）。"""
    c = tab.conf.fillna(0).to_numpy()
    idx = tab.index
    out, i, n = [], 0, len(c)
    while i < n:
        if c[i] < 0.2:
            i += 1
            continue
        d20, d50, end, below, j = idx[i], None, None, 0, i
        while j < n:
            if d50 is None and c[j] >= 0.5:
                d50 = idx[j]
            below = below + 1 if c[j] < 0.2 else 0
            if below >= END_WEEKS:
                end = idx[j - END_WEEKS + 1]
                break
            j += 1
        if d50 is not None:
            out.append((d20, d50, end))
        i = j + 1
    return out


def run_rule(px: pd.Series, d50: pd.Timestamp, end: pd.Timestamp | None, rule: str) -> pd.Timestamp:
    """返回清仓日（收盘成交）。"""
    p = px[px.index >= d50]
    last = p.index[min(H, len(p) - 1)]
    stop = min(end, last) if end is not None else last
    if rule == "sell_at_50":
        return d50
    if rule == "hold_250":
        return last
    if rule == "hold_to_end":
        return stop
    seg = p[p.index <= stop]
    if rule.startswith("trail_"):
        k = float(rule.split("_")[1]) / 100
        dd = seg / seg.cummax() - 1
        hit = dd[dd <= -k]
        return hit.index[0] if len(hit) else stop
    if rule.startswith("ma_"):
        n = int(rule.split("_")[1])
        ma = px.rolling(n).mean()
        below = seg[seg < ma.reindex(seg.index)]
        below = below[below.index > d50]
        return below.index[0] if len(below) else stop
    raise ValueError(rule)


def evaluate(sym: str, per_date: pd.DataFrame) -> list[dict]:
    tab = per_date[per_date.symbol == sym].set_index("date").sort_index()
    px = np.exp(price_series(sym))
    px = px[px.index <= tab.index[-1] + pd.Timedelta(days=400)]
    rows = []
    rules = ["sell_at_50", *[f"trail_{int(k*100)}" for k in TRAILS], *[f"ma_{n}" for n in MAS], "hold_to_end", "hold_250"]
    for d20, d50, end in episodes(tab):
        p = px[px.index >= d50]
        if len(p) < 30:
            continue
        p0 = px.asof(d50)
        win = p.iloc[: H + 1]
        peak_d = win.idxmax()
        peak = win.max()
        after = px[(px.index >= peak_d)].iloc[: H + 1]
        trough = after.min()
        for tiered in (False, True):
            for rule in rules:
                ex = run_rule(px, d50, end, rule)
                pe = px.asof(ex)
                tail = px[px.index >= ex].iloc[: H + 1]
                if tiered:
                    # 三分法：≥20% 时卖 1/3（d20 收盘），≥50% 时再卖 1/3（d50 收盘），剩 1/3 按规则
                    ret = ((px.asof(d20) + p0 + pe) / 3) / p0 - 1
                else:
                    ret = pe / p0 - 1
                rows.append(
                    dict(
                        symbol=sym, d20=d20.date(), d50=d50.date(), end=None if end is None else end.date(),
                        tiered=tiered, rule=rule, exit=ex.date(), ret_vs_d50=ret,
                        peak_ret=peak / p0 - 1, capture=(pe / p0 - 1) / (peak / p0 - 1) if peak > p0 else np.nan,
                        exit_vs_peak=pe / peak - 1, days_exit_to_peak=int(px.index.get_loc(ex) - px.index.get_loc(peak_d)),
                        trough_ret=trough / p0 - 1, missed_fall=tail.min() / pe - 1,
                    )
                )
    return rows


def main() -> None:
    syms = (sys.argv[1] if len(sys.argv) > 1 else "sh000001,sz399001,sh000300,sz399006,sh000016,sh000905").split(",")
    per_date = pd.read_csv(PER_DATE, parse_dates=["date"])
    rows = [r for s in syms if (per_date.symbol == s).any() for r in evaluate(s, per_date)]
    OUT.mkdir(parents=True, exist_ok=True)
    ep = pd.DataFrame(rows)
    ep.to_csv(OUT / "episodes.csv", index=False)
    g = ep.groupby(["tiered", "rule"], sort=False)
    summ = g.agg(
        n=("ret_vs_d50", "size"), ret_med=("ret_vs_d50", "median"), ret_mean=("ret_vs_d50", "mean"),
        ret_min=("ret_vs_d50", "min"), capture_med=("capture", "median"), exit_vs_peak_med=("exit_vs_peak", "median"),
        days_to_peak_med=("days_exit_to_peak", "median"), missed_fall_med=("missed_fall", "median"), missed_fall_min=("missed_fall", "min"),
    ).round(3)
    summ.to_csv(OUT / "summary.csv")
    print(ep[~ep.tiered & (ep.rule == "hold_250")][["symbol", "d20", "d50", "end", "peak_ret", "trough_ret"]].to_string(index=False))
    print(summ.to_string())



def simulate(sym: str, per_date: pd.DataFrame, rule: str, tiered: bool, reentry: str) -> dict:
    """全程模拟（开发段，日频，收盘成交，不计成本）：默认满仓；事件内按 tiered/rule 减仓，事件结束后再入场。
    reentry: 'end' 事件结束日满仓；'end_ma60' 事件结束后首个收盘站上 60 日均线才满仓。"""
    tab = per_date[per_date.symbol == sym].set_index("date").sort_index()
    px = np.exp(price_series(sym))
    px = px[(px.index >= tab.index[0]) & (px.index <= tab.index[-1])]
    ma60 = px.rolling(60).mean()
    w = pd.Series(1.0, index=px.index)
    for d20, d50, end in episodes(tab):
        ex = run_rule(px, d50, end, rule)
        stop = end if end is not None else px.index[-1]
        if tiered:
            w[(w.index >= d20) & (w.index < d50)] = np.minimum(w[(w.index >= d20) & (w.index < d50)], 2 / 3)
            w[(w.index >= d50) & (w.index < ex)] = np.minimum(w[(w.index >= d50) & (w.index < ex)], 1 / 3)
        w[(w.index >= ex) & (w.index < stop)] = 0.0
        if reentry == "end_ma60" and end is not None:
            back = px[(px.index >= end) & (px > ma60)]
            re = back.index[0] if len(back) else px.index[-1]
            w[(w.index >= end) & (w.index < re)] = 0.0
    r = px.pct_change().fillna(0)
    eq = (1 + w.shift(1).fillna(1) * r).cumprod()
    bh = (1 + r).cumprod()
    return dict(
        symbol=sym, rule=rule, tiered=tiered, reentry=reentry, years=round((px.index[-1] - px.index[0]).days / 365.25, 1),
        total=round(eq.iloc[-1], 2), bh_total=round(bh.iloc[-1], 2), mdd=round((eq / eq.cummax() - 1).min(), 3),
        bh_mdd=round((bh / bh.cummax() - 1).min(), 3), time_out=round(1 - w.mean(), 3),
    )


def main_sim() -> None:
    syms = "sh000001,sz399001,sh000300,sz399006,sh000016,sh000905".split(",")
    per_date = pd.read_csv(PER_DATE, parse_dates=["date"])
    rules = ["sell_at_50", "trail_10", "ma_60", "hold_to_end"]
    rows = [
        simulate(s, per_date, ru, t, re)
        for s in syms
        for ru in rules
        for t in (False, True)
        for re in ("end", "end_ma60")
    ]
    sim = pd.DataFrame(rows)
    sim.to_csv(OUT / "simulation.csv", index=False)
    print(sim[sim.symbol.isin(["sh000001", "sh000300", "sz399006"])].to_string(index=False))
    g = sim.groupby(["rule", "tiered", "reentry"], sort=False)
    print(g.agg(total_med=("total", "median"), bh_med=("bh_total", "median"), mdd_med=("mdd", "median"), bh_mdd_med=("bh_mdd", "median"), time_out=("time_out", "median")).round(3).to_string())


if __name__ == "__main__":
    main()
    main_sim()
