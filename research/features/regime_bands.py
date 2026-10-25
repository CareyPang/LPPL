"""§17.10 补项：FCO 平台公开的"月度体制带"（描述性、非预测；文献 §16.16 前端原文定义）。

每个已完成的日历月，以该资产自身前 WINDOW_MONTHS 个已完成月为参照：
- 月收益 r = close/open − 1（月初开盘到月末收盘）；excursion = 月内最大回撤（从月内最高到之后最低，按 high/low）。
- 阈值：r 的 5/25/40/60/80 分位，excursion 的 40/95 分位（只用之前的月份，不含本月）。
- HIGH_RISK 三通道：① r < p5；② r < p25 且 exc > p40；③ exc > p95 且 r < p60。
- 否则 r < p40 BEARISH、[p40, p60) NEUTRAL、[p60, p80) BULLISH、≥ p80 RALLY。
用法：python -m research.features.regime_bands → reports/regime_bands_index.csv
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

WINDOW_MONTHS = 60
STATES = ("HIGH_RISK", "BEARISH", "NEUTRAL", "BULLISH", "RALLY")


def monthly_table(ohlc: pd.DataFrame) -> pd.DataFrame:
    """ohlc：含 date/open/high/low/close 的日频表。返回每个日历月一行：ret、exc（月内最大回撤，正数）。"""
    d = ohlc.set_index(pd.to_datetime(ohlc["date"])).sort_index()
    rows = []
    for ym, g in d.groupby(d.index.to_period("M")):
        hi_run = g["high"].cummax()
        exc = float(((hi_run - g["low"]) / hi_run).max())
        rows.append(dict(month=str(ym), ret=float(g["close"].iloc[-1] / g["open"].iloc[0] - 1), exc=exc, n_days=len(g)))
    return pd.DataFrame(rows).set_index("month")


def classify(m: pd.DataFrame, window: int = WINDOW_MONTHS) -> pd.DataFrame:
    """对每个月用之前 window 个月做分位阈值；不足 window 个月 → state 为 NaN。"""
    out = m.copy()
    out["state"] = pd.Series([None] * len(m), index=m.index, dtype=object)
    out["channel"] = pd.Series([None] * len(m), index=m.index, dtype=object)
    r, e = m["ret"].to_numpy(), m["exc"].to_numpy()
    for i in range(len(m)):
        if i < window:
            continue
        rr, ee = r[i - window : i], e[i - window : i]
        p5, p25, p40, p60, p80 = np.percentile(rr, [5, 25, 40, 60, 80])
        e40, e95 = np.percentile(ee, [40, 95])
        ch = []
        if r[i] < p5:
            ch.append(1)
        if r[i] < p25 and e[i] > e40:
            ch.append(2)
        if e[i] > e95 and r[i] < p60:
            ch.append(3)
        if ch:
            out.iloc[i, out.columns.get_loc("state")] = "HIGH_RISK"
            out.iloc[i, out.columns.get_loc("channel")] = "+".join(map(str, ch))
        elif r[i] < p40:
            out.iloc[i, out.columns.get_loc("state")] = "BEARISH"
        elif r[i] < p60:
            out.iloc[i, out.columns.get_loc("state")] = "NEUTRAL"
        elif r[i] < p80:
            out.iloc[i, out.columns.get_loc("state")] = "BULLISH"
        else:
            out.iloc[i, out.columns.get_loc("state")] = "RALLY"
    return out


def regime_bands(ohlc: pd.DataFrame, window: int = WINDOW_MONTHS) -> pd.DataFrame:
    return classify(monthly_table(ohlc), window)


if __name__ == "__main__":
    frames = []
    for p in sorted(Path("data/frozen/v20261024").glob("*_qfq.parquet")):
        sym = p.stem.replace("_qfq", "")
        rb = regime_bands(pd.read_parquet(p))
        rb["symbol"] = sym
        frames.append(rb.reset_index())
    allb = pd.concat(frames)
    Path("reports").mkdir(exist_ok=True)
    allb.to_csv("reports/regime_bands_index.csv", index=False)
    done = allb.dropna(subset=["state"])
    print(done.groupby("symbol").state.value_counts(normalize=True).unstack().round(2).to_string())
    for sym, mo in [("sh000001", "2007-10"), ("sh000001", "2008-10"), ("sh000001", "2015-06"), ("sh000001", "2015-07"), ("sh000001", "2024-09")]:
        row = allb[(allb.symbol == sym) & (allb.month == mo)]
        print(sym, mo, row[["ret", "exc", "state", "channel"]].round(3).to_dict("records"))
