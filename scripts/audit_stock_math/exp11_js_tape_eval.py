# ruff: noqa: E402, E702
"""Phase 0：评价 web/app/critical.js 顶部引擎（38 窗 + 锚定窗、DE+NM、高斯核 t_c 聚类）在开发段 6 指数上的时间/价格精度。
输入：/home/ubuntu/audit/js_tape_<sym>.csv（node js_tape.mjs 每 5 日一次 topScan 的精简记录：主聚类 lo/hi/mid/n/conf）。
指标（每个有主聚类的截止日 T）：
  err_mid  = |T+mid − 下一个合格顶| （交易日），has_top250 = 其后 250 日内有顶；cover = 顶 ∈ [T+lo, T+hi]；
  hit_pm5  = |err_mid| ≤ 5；对照 = 同一批截止日、mid 从全部截止日随机重排 500 次（tc_cluster_dev 口径）
价格（首次出现主聚类 = 首报，GAP 20 日）：miss_up = 顶价/报警价−1；avoid = 顶后 126 日最低/报警价−1；fwd120。
用法：PYTHONPATH=. python scripts/audit_stock_math/exp11_js_tape_eval.py"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("LPPLS_BOX", "v2")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.eval.dataset import price_series
from research.eval.precision_baseline import GAP, INDEXES, OUT, POST, H, event_dates

AUD = Path(os.environ.get("AUDIT_OUT", "/home/ubuntu/audit"))
rng = np.random.default_rng(0)


def eval_sym(sym: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    tape = pd.read_csv(AUD / f"js_tape_{sym}.csv")
    logp = price_series(sym); cal = logp.index; close = np.exp(logp.to_numpy()); n = len(close)
    tops = np.sort(cal.get_indexer(event_dates(sym, "top"))); tops = tops[tops >= 0]
    t = tape[tape.c1_mid.notna()].copy()
    T = t["T"].to_numpy(int)
    nxt = np.searchsorted(tops, T, side="right"); has = nxt < len(tops)
    top = np.where(has, tops[np.minimum(nxt, len(tops) - 1)], -1)
    pred = T + t.c1_mid.to_numpy(int)
    t["has_top250"] = has & (top - T <= 250)
    t["err_mid"] = np.where(t.has_top250, np.abs(pred - top), np.nan)
    t["cover"] = t.has_top250 & (top >= T + t.c1_lo.to_numpy()) & (top <= T + t.c1_hi.to_numpy())
    t["hit_pm5"] = t.err_mid <= 5
    t["top_date"] = [cal[x].date() if x >= 0 else None for x in top]
    t["top_rel"] = np.where(t.has_top250, top - T, np.nan)
    # 价格：首报
    rows = []; last = -10**9
    for i, Ti in enumerate(T):
        if Ti - last <= GAP:
            last = Ti; continue
        last = Ti
        e = top[i]; hit = e >= 0 and e - Ti <= H
        r = dict(symbol=sym, date=cal[Ti].date(), hit=bool(hit), lead=(e - Ti) if e >= 0 else np.nan, conf=t.c1_conf.iloc[i])
        if hit:
            r.update(miss_up=close[e] / close[Ti] - 1, avoid=close[e : min(n, e + POST + 1)].min() / close[Ti] - 1)
        if Ti + H < n:
            r["fwd120"] = close[Ti + H] / close[Ti] - 1
        rows.append(r)
    return t.assign(symbol=sym), pd.DataFrame(rows)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    tapes, eps = [], []
    for s in INDEXES:
        if not (AUD / f"js_tape_{s}.csv").exists():
            print("missing", s); continue
        a, b = eval_sym(s); tapes.append(a); eps.append(b); print(s, "asof", len(a), "has_top250", int(a.has_top250.sum()), "hit±5", round(a[a.has_top250].hit_pm5.mean(), 3), "cover", round(a[a.has_top250].cover.mean(), 3), flush=True)
    T = pd.concat(tapes); E = pd.concat(eps)
    T.to_csv(OUT / "js_tape_asof.csv", index=False); E.to_csv(OUT / "js_tape_episodes.csv", index=False)
    d = T[T.has_top250]
    # 零对照：对每个有顶的截止日，把 mid 换成随机抽取的其他截止日的 mid（500 次），看 ±5 日命中率
    mids = T.c1_mid.to_numpy(); rel = d.top_rel.to_numpy()
    nul = np.array([(np.abs(rng.choice(mids, len(rel)) - rel) <= 5).mean() for _ in range(500)])
    print("null hit±5: mean", round(nul.mean(), 3), "p95", round(np.quantile(nul, 0.95), 3))
    print("\n== 全部 6 指数（有顶 250 日内的截止日）")
    print(dict(n_asof=len(T), n_has_top=len(d), share=round(len(d) / len(T), 3), err_med=d.err_mid.median(), err_p80=d.err_mid.quantile(0.8),
               hit_pm5=round(d.hit_pm5.mean(), 3), cover=round(d.cover.mean(), 3), width_med=(d.c1_hi - d.c1_lo).median()))
    for thr in (0.1, 0.2, 0.3):
        dd = d[d.c1_conf >= thr]
        print(f"conf>={thr}", dict(n=len(dd), err_med=dd.err_mid.median(), hit_pm5=round(dd.hit_pm5.mean(), 3), cover=round(dd.cover.mean(), 3)))
    print("\n== 首报价格指标")
    print(E.describe().loc[["count", "25%", "50%", "75%"], ["lead", "miss_up", "avoid", "fwd120"]].round(3).to_string())
    print("hit rate (top within 120d)", round(E.hit.mean(), 3), "n", len(E))
