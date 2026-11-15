"""描述性：2026 与 2007/2015/2020-21 阶段对比（峰值、250 日最大涨幅、峰后回撤）+ W8（§24.1 原参数）2025-06 后状态机输出。只描述，不评价、不调参。
用法：PYTHONPATH=. python scripts/audit_stock_math/exp24c_w8_regime_2026.py"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from scripts.audit_stock_math.exp21_crash_confirm import monitor  # noqa: E402
from scripts.audit_stock_math.exp24_scan_2026 import A_SH, EXT, logp  # noqa: E402

pd.set_option("display.width", 250)
EPIS = {"2007": ("2006-01-01", "2008-12-31"), "2015": ("2014-07-01", "2016-06-30"), "2020-21": ("2020-01-01", "2022-06-30"), "2026": ("2025-06-01", "2026-10-29")}
rows = []
w8 = []
for sym in A_SH + tuple(EXT):
    lp = logp(sym)
    p = np.exp(lp)
    ru = lp - lp.shift(250)
    for name, (a, b) in EPIS.items():
        q = p[a:b]
        if len(q) < 100 or ru[a:b].dropna().empty:
            continue
        pk = q.idxmax()
        after = p[pk:b]
        rows.append(dict(sym=sym, ep=name, peak=pk.date(), runup250_max=round(float(np.exp(ru[a:pk].max()) - 1), 3),
                         dd_after=round(float(after.min() / q.max() - 1), 3), trough=after.idxmin().date(), days_to_trough=int(len(p[pk:after.idxmin()]) - 1)))
    for side in (+1, -1):
        y = side * lp.to_numpy()
        cal = lp.index
        for t0, c in monitor(y, 0):
            if cal[t0] >= pd.Timestamp("2025-06-01"):
                w8.append(dict(sym=sym, side="top" if side > 0 else "recovery", bubble=cal[t0].date(), confirm=(cal[c].date() if c >= 0 else "open"),
                               p_bubble=round(float(p.iloc[t0]), 1), p_confirm=(round(float(p.iloc[c]), 1) if c >= 0 else np.nan)))
R = pd.DataFrame(rows)
print(R.to_string(index=False))
R.to_csv("reports/regime_2026/episodes.csv", index=False)
W = pd.DataFrame(w8)
print(W.to_string(index=False))
W.to_csv("reports/regime_2026/w8_2025_26.csv", index=False)
