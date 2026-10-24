"""T-INT-P 概率区间（prereg §15.2）：区间 = 从 p_t ≥ τ 起到随后首次 p_t < τ 的天数（上限 60），在事件日（y=1 且有真实顶 t*）上评分；基线 [1,20]。
python -m research.eval.interval_prob"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .dataset import price_series
from .interval import interval_score
from .ladder import OOF_DIR
from .run_interval import block_ci, events_with_tstar

OOF = OOF_DIR / "ladder_dev_R7_sp120_z_C0.1.parquet"
MAXD = 60


def run(tag: str = "tintp_dev"):
    o = pd.read_parquet(OOF)
    p = o.groupby(["symbol", "date"]).p.mean()
    tau0 = float(o.y.mean())
    cal = price_series("sh000001").index
    rows = []
    for sym, ps in p.groupby(level=0):
        ps = ps.droplevel(0)
        ev = events_with_tstar(sym, "dev", ps.index)
        if ev.empty:
            continue
        pv, idx = ps.to_numpy(), ps.index
        for mult in (1.0, 1.5):
            tau = tau0 * mult
            above = pv >= tau
            run_end = np.full(len(pv), np.nan)
            k = len(pv) - 1
            nxt = len(pv)
            while k >= 0:
                if not above[k]:
                    nxt = k
                else:
                    run_end[k] = min(nxt - k, MAXD)
                k -= 1
            pos = idx.get_indexer(ev.date)
            U = run_end[pos]
            rows.append(pd.DataFrame(dict(symbol=sym, date=ev.date.to_numpy(), t_star=ev.t_star.to_numpy(), config=f"tau_x{mult}",
                                          has_alarm=~np.isnan(U), U=np.where(np.isnan(U), 20.0, U))))
    d = pd.concat(rows)
    d["IS"] = interval_score(1, d.U, d.t_star)
    d["IS_base"] = interval_score(1, 20, d.t_star)
    d["cover"] = (d.t_star >= 1) & (d.t_star <= d.U)
    out = []
    for cfg, g in d.groupby("config"):
        dd, lo, hi = block_ci((g.IS - g.IS_base).to_numpy(), g.date, cal)
        out.append(dict(config=cfg, n_events=len(g), share_with_alarm=float(g.has_alarm.mean()), IS=float(g.IS.mean()), IS_base=float(g.IS_base.mean()),
                        coverage=float(g.cover.mean()), width_med=float(g.U[g.has_alarm].median()), dIS=dd, ci_lo=lo, ci_hi=hi, kept=hi < 0))
    tab = pd.DataFrame(out)
    tab.to_csv(f"reports/{tag}.csv", index=False)
    with open(f"reports/{tag}.md", "w") as f:
        f.write(f"# T-INT-P 概率区间（prereg §15.2；开发段主链 R7 OOF，τ = 正标签率 {tau0:.4f}；基线 [1,20]；90% 块 bootstrap）\n\n")
        f.write(tab.round(4).to_markdown(index=False) + "\n\n无报警的事件日区间退化为基线 [1,20]。dIS = IS − IS_base，负为改善。开发段结果，不是样本外。\n")
    print(tab.round(4).to_string(index=False))
    return tab


if __name__ == "__main__":
    run()
