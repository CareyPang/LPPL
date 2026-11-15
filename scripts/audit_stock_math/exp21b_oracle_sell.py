# ruff: noqa: E402, E702
"""§24.4 补充：W8 的"顶后固定 N 日卖出"参考列。该规则须事先知道顶日，实时不可行，只作卖出价的理论参考上限，不参与门。
用法：PYTHONPATH=. python scripts/audit_stock_math/exp21b_oracle_sell.py [reports/w8_crash_confirm]"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.eval.dataset import price_series
from research.labels.run_top import build as build_top
from scripts.audit_stock_math.exp21_crash_confirm import END, EX, INDEXES, START, event_days

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/w8_crash_confirm")
NS = (5, 10, 20)

if __name__ == "__main__":
    rows = []
    for sym in INDEXES:
        logp = price_series(sym); logp = logp[logp.index <= END + pd.Timedelta(days=120)]
        close = np.exp(logp.to_numpy()); cal = logp.index
        for p in event_days(build_top(sym, cal, logp.to_numpy())["main__y"], close, cal, +1):
            if not (START <= cal[p] <= END) or p + max(NS) >= len(close):
                continue
            rows.append(dict(symbol=sym, top=cal[p], ev_year=cal[p].year, **{f"sell_p{n}": close[p + n] / close[p] - 1 for n in NS}))
    df = pd.DataFrame(rows); df.to_csv(OUT / "oracle_sell.csv", index=False)
    ev = pd.read_csv(OUT / "events.csv", parse_dates=["date"]); ev = ev[(ev.side == "top") & ev.hit]
    for name, d, e in (("all", df, ev), ("ex_extreme", df[~df.ev_year.isin(EX)], ev[~ev.ev_year.isin(EX)])):
        print(f"== {name}: tops={len(d)}")
        print(d[[f"sell_p{n}" for n in NS]].median().round(4).to_string())
        print(e.groupby("rule").plag.agg(["size", "median"]).round(4).to_string())
