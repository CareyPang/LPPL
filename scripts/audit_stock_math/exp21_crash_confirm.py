# ruff: noqa: E402, E702
"""§24.1 W8：实时崩盘确认 + 恢复确认（Whitehouse–Harvey–Leybourne 2023 AMAX(k)/SMIN(m,n)，滚动训练期；开发段 6 指数；描述性，dev_only）。
用法：PYTHONPATH=. python scripts/audit_stock_math/exp21_crash_confirm.py [reports/w8_crash_confirm]"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view as swv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.eval.dataset import price_series
from research.labels.run_bottom import build as build_bottom
from research.labels.run_top import build as build_top
from research.labels.top import event_segments

INDEXES = ("sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006")
K, M, N, TRAIN = 10, 10, 2, 500
START, END = pd.Timestamp("2000-01-01"), pd.Timestamp("2018-12-31")
EX = {2007, 2008, 2014, 2015}
WIN, FWD = 60, 60
N_NULL, MIN_SHIFT, SEED = int(os.environ.get("W8_NULL", "200")), 250, 0
FIXED = os.environ.get("W8_TRAIN", "rolling") == "fixed"  # 敏感性：原文固定训练期（样本起点后首个 TRAIN 日），不参与门
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/w8_crash_confirm")


def a_stat(dy: np.ndarray, k: int) -> np.ndarray:
    w = np.arange(1, k + 1, dtype=float)
    sw = swv(dy, k) * w
    out = np.full(len(dy), np.nan)
    out[k - 1 :] = sw.sum(1) / np.sqrt((sw**2).sum(1))
    return out


def s_stat(y: np.ndarray, dy: np.ndarray, m: int, n: int) -> np.ndarray:
    """S_{e,m,n}（原文 (10)）；索引按 dy（dy[i] = y[i+1] − y[i]，对应 y_{t-1} = y[i]）。"""
    T = len(dy)
    out = np.full(T, np.nan)
    D1 = swv(dy[: T - n], m)  # 前段 m 个 Δy，终点 e−n
    X1 = swv(y[: T - n], m)  # 对应 y_{t−1}
    mx, md = X1.mean(1), D1.mean(1)
    sxx = ((X1 - mx[:, None]) ** 2).sum(1); sxd = ((X1 - mx[:, None]) * (D1 - md[:, None])).sum(1); sdd = ((D1 - md[:, None]) ** 2).sum(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        rss = sdd - np.where(sxx > 0, sxd**2 / sxx, 0.0)
    D2 = swv(dy, n)  # 后段 n 个 Δy，终点 e
    e = np.arange(m + n - 1, T)
    s1 = D1.sum(1)[e - (m + n - 1)]; r1 = rss[e - (m + n - 1)]
    s2 = D2.sum(1)[e - (n - 1)]; q2 = (D2**2).sum(1)[e - (n - 1)]
    with np.errstate(divide="ignore", invalid="ignore"):
        out[e] = s1 * s2 / np.sqrt(np.maximum(r1, 1e-300) * np.maximum(q2, 1e-300))
    return out


def monitor(y: np.ndarray, i_start: int = 0) -> list[tuple[int, int]]:
    """返回 [(泡沫触发日, 崩盘确认日)]（价格索引；未确认的泡沫确认日为 −1）。滚动训练期：e 日临界值 = [e−K−M−N−TRAIN, e−K−M−N] 内统计量的 max/min；
    FIXED 时临界值冻结在开发段起点（i_start）后首个可用日。"""
    dy = np.diff(y)
    A, S = a_stat(dy, K), s_stat(y, dy, M, N)
    lag = K + M + N
    Amax = pd.Series(A).rolling(TRAIN, min_periods=TRAIN).max().shift(lag).to_numpy()
    Smin = pd.Series(S).rolling(TRAIN, min_periods=TRAIN).min().shift(lag).to_numpy()
    if FIXED:
        ok = np.isfinite(Amax) & np.isfinite(Smin) & (np.arange(len(A)) >= i_start)
        i0 = int(np.argmax(ok))
        Amax = np.where(np.arange(len(A)) >= i0, Amax[i0], np.nan); Smin = np.where(np.arange(len(S)) >= i0, Smin[i0], np.nan)
    state, t_dia, resume, out = "bubble", -1, -1, []
    for e in range(len(dy)):
        if state == "bubble":
            if np.isfinite(A[e]) and np.isfinite(Amax[e]) and A[e] > Amax[e]:
                state, t_dia = "crash", e
        elif state == "crash":
            if np.isfinite(S[e]) and np.isfinite(Smin[e]) and S[e] < Smin[e]:
                out.append((t_dia + 1, e + 1)); state, resume = "wait", e + K
        elif e >= resume:
            state = "bubble"
    if state == "crash":
        out.append((t_dia + 1, -1))
    return out


def baselines(close: np.ndarray, t0: int, side: int) -> dict[str, int | None]:
    """泡沫触发日 t0 之后的首次触发（PIT）；side=+1 顶部侧（跌破/回撤），−1 恢复侧（上穿/反弹）。"""
    s = pd.Series(close)
    ma20, ma60 = s.rolling(20).mean().to_numpy(), s.rolling(60).mean().to_numpy()
    res = {}
    for name, ma in (("ma20", ma20), ("ma60", ma60)):
        idx = np.flatnonzero((side * (close[t0 + 1 :] - ma[t0 + 1 :]) < 0) & np.isfinite(ma[t0 + 1 :]))
        res[name] = int(t0 + 1 + idx[0]) if len(idx) else None
    seg = close[t0:]
    ext = np.maximum.accumulate(seg) if side > 0 else np.minimum.accumulate(seg)
    idx = np.flatnonzero(side * (seg / ext - 1) <= -0.10)
    res["dd10"] = int(t0 + idx[0]) if len(idx) else None
    return res


def event_days(seg_y: pd.Series, close: np.ndarray, cal: pd.DatetimeIndex, side: int) -> np.ndarray:
    pos = pd.Series(np.arange(len(cal)), index=cal)
    days = []
    for a, b in event_segments(seg_y):
        lo, hi = max(0, int(pos[a]) - 60), min(len(close) - 1, int(pos[b]) + 20)
        w = close[lo : hi + 1]
        days.append(lo + int(np.argmax(w) if side > 0 else np.argmin(w)))
    return np.unique(days)


def score(c: int, events: np.ndarray, close: np.ndarray, side: int) -> dict:
    prev = events[(events <= c) & (events >= c - WIN)]
    hit = len(prev) > 0
    p = int(prev[-1]) if hit else -1
    fwd = close[c + 1 : c + 1 + FWD]; back = close[max(0, c - WIN) : c + 1]
    breach = len(fwd) > 0 and ((fwd.max() > back.max()) if side > 0 else (fwd.min() < back.min()))
    return dict(hit=hit, false=(not hit) or bool(breach), lag=(c - p) if hit else np.nan,
                plag=(side * (close[c] / close[p] - 1)) if hit else np.nan, ev=p)


def run_side(sym: str, logp: pd.Series, events: np.ndarray, side: int) -> tuple[pd.DataFrame, dict]:
    y = side * logp.to_numpy(); close = np.exp(logp.to_numpy()); cal = logp.index
    rows = []
    i_start = int(np.searchsorted(cal, START))
    sd = "top" if side > 0 else "bottom"
    for t0, c in monitor(y, i_start):
        if cal[t0] < START or cal[t0] > END:
            continue
        sig = dict(baselines(close, t0, side), smin=(c if c >= 0 else None))
        for name, cb in sig.items():
            if cb is not None and cb < len(close) and START <= cal[cb] <= END:
                rows.append(dict(symbol=sym, side=sd, t_bubble=cal[t0], rule=name, date=cal[cb], **score(cb, events, close, side)))
    df = pd.DataFrame(rows)
    # 零对照：对数收益循环平移（≥250 日），重跑状态机，事件固定
    rng = np.random.default_rng(SEED); dy = np.diff(y); hits, reps = [], []
    for _ in range(N_NULL):
        k = int(rng.integers(MIN_SHIFT, len(dy) - MIN_SHIFT)); yy = np.concatenate([[y[0]], y[0] + np.cumsum(np.roll(dy, k))])
        cs = [c for _, c in monitor(yy, i_start) if c >= 0 and START <= cal[c] <= END]
        hits.append(np.mean([score(c, events, close, side)["hit"] for c in cs]) if cs else np.nan)
        reps.append((sum(score(c, events, close, side)["hit"] for c in cs), len(cs)))
    if N_NULL == 0:
        hits = [np.nan]
    return df, dict(reps=reps, null_hit_mean=float(np.nanmean(hits)), null_hit_p95=float(np.nanquantile(hits, 0.95)), null_n=int(np.sum(np.isfinite(hits))))


def summarize(df: pd.DataFrame, exclude: bool) -> pd.DataFrame:
    d = df[~df["ev_year"].isin(EX)] if exclude else df
    g = d.groupby(["symbol", "rule"])
    return g.agg(n=("hit", "size"), hit_rate=("hit", "mean"), false_rate=("false", "mean"), lag_med=("lag", "median"), plag_med=("plag", "median")).reset_index()


def gate(df: pd.DataFrame, null: dict) -> dict:
    s = df[df.rule == "smin"]
    g1 = float(s.hit.mean()) > null["null_hit_p95"] if len(s) else False
    def g2(d):
        ok = 0
        for _sym, gs in d.groupby("symbol"):
            tab = gs.groupby("rule").agg(plag=("plag", "median"), fr=("false", "mean"))
            if "smin" not in tab.index or tab.drop("smin").empty:
                continue
            b = tab.drop("smin")
            if b.plag.notna().any():
                best = b.plag.idxmax()
                if tab.loc["smin", "plag"] >= b.loc[best, "plag"] and tab.loc["smin", "fr"] <= b.loc[best, "fr"]:
                    ok += 1
            elif np.isfinite(tab.loc["smin", "plag"]):
                ok += 1
        return ok
    def g3(d):
        tab = d.groupby("rule").agg(plag=("plag", "median"), fr=("false", "mean"))
        if "smin" not in tab.index:
            return False
        b = tab.drop("smin")
        if not b.plag.notna().any():
            return bool(np.isfinite(tab.loc["smin", "plag"]))
        best = b.plag.idxmax()
        return bool(tab.loc["smin", "plag"] >= b.loc[best, "plag"] and tab.loc["smin", "fr"] <= b.loc[best, "fr"])
    ex = df[~df.ev_year.isin(EX)]
    n2 = g2(ex)
    return dict(G1=bool(g1), G1_hit=float(s.hit.mean()) if len(s) else np.nan, **null, G2_pass_idx=n2, G2=n2 >= 4, G3=g3(df), PASS=bool(g1 and n2 >= 4 and g3(df)))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    all_rows, nulls = [], {}
    for sym in INDEXES:
        logp = price_series(sym); logp = logp[logp.index <= END + pd.Timedelta(days=120)]
        close = np.exp(logp.to_numpy()); cal = logp.index
        tops = event_days(build_top(sym, cal, logp.to_numpy())["main__y"], close, cal, +1)
        bots = event_days(build_bottom(sym, cal, logp.to_numpy())["main__y"], close, cal, -1)
        for side, ev in ((+1, tops), (-1, bots)):
            df, null = run_side(sym, logp, ev, side)
            if len(df):
                df["ev_year"] = [cal[int(e)].year if e >= 0 else df.date.iloc[i].year for i, e in enumerate(df.ev)]
                all_rows.append(df)
            nulls[(sym, side)] = null
            print(sym, "top" if side > 0 else "bottom", f"smin_confirms={int((df.rule == 'smin').sum()) if len(df) else 0}", {k: v for k, v in null.items() if k != "reps"}, flush=True)
    E = pd.concat(all_rows, ignore_index=True); E.to_csv(OUT / "events.csv", index=False)
    pd.set_option("display.width", 220)
    for side in ("top", "bottom"):
        d = E[E.side == side]
        if d.empty:
            print(side, "no events"); continue
        # 合并零对照：第 i 次平移在 6 指数上的命中数/确认数相加后取比率，再取 200 次的均值与 95 分位
        sd_ = 1 if side == "top" else -1
        R = np.array([v["reps"] for (_s, sd), v in nulls.items() if sd == sd_], dtype=float)  # (指数, 次, 2)
        pooled_hits = R[:, :, 0].sum(0) / np.maximum(R[:, :, 1].sum(0), 1) if R.size else np.array([np.nan])
        null_pool = dict(null_hit_mean=float(np.nanmean(pooled_hits)), null_hit_p95=float(np.nanquantile(pooled_hits, 0.95)) if R.size else np.nan,
                         null_n=int(R.shape[1]) if R.size else 0, null_confirms_med=float(np.median(R[:, :, 1].sum(0))) if R.size else np.nan)
        full = summarize(d, False); full["sample"] = "all"; ex = summarize(d, True); ex["sample"] = "ex_extreme"
        tab = pd.concat([full, ex]); tab.to_csv(OUT / f"summary_{side}.csv", index=False)
        pooled = d.groupby("rule").agg(n=("hit", "size"), hit_rate=("hit", "mean"), false_rate=("false", "mean"), lag_med=("lag", "median"), plag_med=("plag", "median"))
        pooled_ex = d[~d.ev_year.isin(EX)].groupby("rule").agg(n=("hit", "size"), hit_rate=("hit", "mean"), false_rate=("false", "mean"), lag_med=("lag", "median"), plag_med=("plag", "median"))
        print(f"\n== {side} pooled (all)\n", pooled.round(3)); print(f"== {side} pooled (ex 2007/08/2014/15 by event year)\n", pooled_ex.round(3))
        print(f"== {side} per index\n", tab.round(3).to_string(index=False))
        gt = gate(d, null_pool); print(f"== {side} GATE", gt)
        pd.Series(gt).to_csv(OUT / f"gate_{side}.csv")
