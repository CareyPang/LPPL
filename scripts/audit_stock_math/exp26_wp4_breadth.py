"""WP4 广度与指数联动（描述性，不报警，无门；docs/drafts_forward_expansion_wp456.md §J.1）。
样本：开发段 2010–2018，lppls_v2_lite_stk100 的 100 只沪深300 成分股（约每 20 个交易日一个 as-of）。
广度 = 各 as-of 置信度 > 0 的股票比例（6–12m / 12–24m × box / STANDARD）。零模型：每只股票的置信度序列独立循环平移（≥250 交易日），300 次。
内生/外生标签：沪深300 自 250 日高点回撤首次 ≥15%（回撤回到 <5% 后才可再触发）为事件；事件前 60 交易日内指数 6–12m 或 12–24m box 置信度 ≥0.10 → 内生，否则外生。
偏离草案：冻结数据里没有 PIT 市值，市值三分位没法算，本次只给全体口径。
用法：PYTHONPATH=. python scripts/audit_stock_math/exp26_wp4_breadth.py"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("LPPLS_BOX", "v2")
from research.eval.dataset import price_series  # noqa: E402
from research.eval.precision_baseline import confidence  # noqa: E402

LO, HI, N_PERM, MIN_SHIFT, PRE = pd.Timestamp("2010-01-01"), pd.Timestamp("2018-12-31"), 300, 250, 60
OUT = Path("reports/wp4_breadth")
COLS = [(s, r) for s in ("6-12m", "12-24m") for r in ("box", "standard")]


def dd_events(lp: pd.Series, thr: float = 0.15, reset: float = 0.05) -> list[pd.Timestamp]:
    p = np.exp(lp)
    dd = 1 - p / p.rolling(250, min_periods=1).max()
    ev, armed = [], True
    for d, v in dd.items():
        if armed and v >= thr:
            ev.append(d)
            armed = False
        elif not armed and v < reset:
            armed = True
    return ev


def main() -> None:
    feat = Path("data/features/lppls_v2_lite_stk100")
    confs = {}
    for f in sorted(feat.glob("*.parquet")):
        sc = pd.read_parquet(f)
        sc = sc[(sc.date >= LO) & (sc.date <= HI)]
        if not sc.empty:
            confs[f.stem] = confidence(sc, price_series(f.stem))
    dates = sorted(set().union(*[c.index for c in confs.values()]))
    cal = price_series("sh000300").index
    step = max(1, int(np.median(np.diff(cal.get_indexer(dates)))))
    min_k = int(np.ceil(MIN_SHIFT / step))
    rng = np.random.default_rng(0)
    rows, nullq = [], {}
    for col in COLS:
        M = pd.DataFrame({s: c[col] for s, c in confs.items()}).reindex(dates)
        X = (M.fillna(0).to_numpy() > 0).astype(float)
        valid = M.notna().to_numpy()
        obs = np.where(valid, X, np.nan)
        br = np.nanmean(obs, axis=1)
        T = len(dates)
        null = np.empty((N_PERM, T))
        for k in range(N_PERM):
            Z = np.full_like(obs, np.nan)
            for j in range(obs.shape[1]):
                sh = int(rng.integers(min_k, T - min_k))
                Z[:, j] = np.roll(obs[:, j], sh)
            null[k] = np.nanmean(Z, axis=1)
        pct = (null < br).mean(axis=0)
        nullq[col] = pct
        rows.append(pd.DataFrame({"date": dates, "scale": col[0], "rule": col[1], "breadth": br, "null_med": np.median(null, 0),
                                  "null_q95": np.quantile(null, 0.95, 0), "null_pct": pct}))
    Bt = pd.concat(rows)
    lp = price_series("sh000300")
    ic = confidence(pd.read_parquet("data/features/lppls_v2/sh000300.parquet"), lp)
    ic = ic[(ic.index >= LO - pd.Timedelta(days=120)) & (ic.index <= HI)]
    evs = [e for e in dd_events(lp[(lp.index >= LO - pd.Timedelta(days=400)) & (lp.index <= HI)]) if e >= LO]
    er = []
    for e in evs:
        i = cal.get_loc(e)
        w0 = cal[max(0, i - PRE)]
        win = ic[(ic.index >= w0) & (ic.index < e)]
        mx = float(win[[("6-12m", "box"), ("12-24m", "box")]].max().max()) if not win.empty else np.nan
        bw = Bt[(Bt.date >= w0) & (Bt.date < e)]
        r = dict(event=e.date(), idx_conf_box_max=mx, label="内生" if mx >= 0.10 else "外生")
        for (s, ru), q in bw.groupby(["scale", "rule"]):
            r[f"br_{s}_{ru}_max"] = q.breadth.max()
            r[f"pct_{s}_{ru}_max"] = q.null_pct.max()
        er.append(r)
    E = pd.DataFrame(er)
    S = Bt.groupby(["scale", "rule"]).agg(breadth_med=("breadth", "median"), breadth_max=("breadth", "max"), null_med=("null_med", "median"),
                                          share_above_q95=("null_pct", lambda x: (x >= 0.95).mean())).reset_index()
    OUT.mkdir(parents=True, exist_ok=True)
    Bt.to_csv(OUT / "breadth.csv", index=False)
    E.to_csv(OUT / "events.csv", index=False)
    S.to_csv(OUT / "summary.csv", index=False)
    pd.set_option("display.width", 240)
    print(f"股票 {len(confs)} 只，as-of {len(dates)} 个，步长 {step} 日，最小平移 {min_k} 步")
    print("== 广度摘要（share_above_q95 = 观测广度高于零分布 95 分位的 as-of 占比；零模型下期望 ≈0.05）")
    print(S.round(3).to_string(index=False))
    print("\n== 沪深300 回撤 ≥15% 事件与事前 60 日广度")
    print(E.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
