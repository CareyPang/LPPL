# ruff: noqa: E402, E702
"""§24.5 W9：MAR(r,1) 崩盘概率（Lanne–Saikkonen 2011 近似 ML；Lanne–Luoto–Saikkonen 2012 样本加权预测；Hecq–Voisin 用法）。
滚动 500 日窗口、线性去趋势、Student-t 误差；p_H = P(min_{i≤H} P_{t+i}/P_t ≤ 0.90)，H∈{20,60}；
基线：气候概率、逻辑回归(HAR + 250 日涨幅/回撤)；CPCV(6,2,gap80)+250 日块 bootstrap；ECE。开发段 6 指数一次，描述性。
用法：PYTHONPATH=. python scripts/audit_stock_math/exp23_mar_crash.py [outdir] [procs]"""
import os
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import t as student_t

os.environ.setdefault("LPPLS_BOX", "v2")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.eval.dataset import price_series
from research.eval.splits import cpcv_paths
from scripts.audit_stock_math.exp22_lppls_conf_vol import (
    END,
    EPS,
    EX,
    HAR,
    INDEXES,
    R1B1,
    START,
    block_ci,
    lrv,
)

W, M, NTR, STEP, SEED = 500, 2000, 300, 5, 0
HS, CRASH = (20, 60), 0.90
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/w9_mar_crash")
PROCS = int(sys.argv[2]) if len(sys.argv) > 2 else 6


def t_logpdf(e: np.ndarray, sig: float, nu: float) -> np.ndarray:
    return student_t.logpdf(e / sig, nu) - np.log(sig)


def mar_fit(x: np.ndarray, r: int) -> dict:
    """MAR(r,1)：φ(L)(1−ψL⁻¹)x_t = ε_t，ε~t(ν,σ)。近似 ML（丢首 r、末 1 个观测）。"""
    def resid(th):
        phi, psi = th[0], th[1]
        v = x[1:] - phi * x[:-1] if r == 1 else x[1:]  # r=0 也丢首个观测，使两种 r 的似然覆盖同一组 498 个残差
        return v[:-1] - psi * v[1:]
    def nll(th):
        return -float(np.sum(t_logpdf(resid(th), np.exp(th[2]), np.exp(th[3]))))
    best = None
    for phi0 in ((0.0, 0.5) if r == 1 else (0.0,)):
        for psi0 in (0.2, 0.6, 0.9):
            th0 = np.array([phi0, psi0, np.log(np.std(np.diff(x)) + 1e-6), np.log(5.0)])
            res = minimize(nll, th0, method="L-BFGS-B", bounds=[(-0.999, 0.999), (-0.999, 0.999), (-12, 3), (np.log(1.5), np.log(30))])
            if best is None or res.fun < best.fun:
                best = res
    phi, psi, sig, nu = best.x[0], best.x[1], float(np.exp(best.x[2])), float(np.exp(best.x[3]))
    return dict(r=r, phi=phi if r == 1 else 0.0, psi=psi, sig=sig, nu=nu, ll=-best.fun)


def mar_prob(y: np.ndarray, rng: np.random.Generator) -> dict:
    """y：窗内对数收盘（长 W）。返回 p_H 与拟合参数。"""
    tt = np.arange(W, dtype=float); A = np.column_stack([np.ones(W), tt]); b, *_ = np.linalg.lstsq(A, y, rcond=None)
    x = y - A @ b
    fits = [mar_fit(x, 0), mar_fit(x, 1)]; f = max(fits, key=lambda d: d["ll"])
    phi, psi, sig, nu = f["phi"], f["psi"], f["sig"], f["nu"]
    Hm = max(HS)
    eps = student_t.rvs(nu, scale=sig, size=(M, Hm + NTR), random_state=rng)
    # u_{T+i} = Σ_k ψ^k ε_{T+i+k}，k=0..NTR-1
    wts = psi ** np.arange(NTR)
    u = np.stack([eps[:, i : i + NTR] @ wts for i in range(1, Hm + 1)], axis=1)  # (M, Hm) → u_{T+1..T+Hm}
    uT = x[-1] - phi * x[-2]
    lw = t_logpdf(uT - psi * u[:, 0], sig, nu); w = np.exp(lw - lw.max()); w /= w.sum()
    xs = np.empty((M, Hm)); prev = np.full(M, x[-1])
    for i in range(Hm):
        prev = phi * prev + u[:, i]; xs[:, i] = prev
    trend = b[0] + b[1] * (W - 1 + np.arange(1, Hm + 1))  # 窗内最后一日为 W−1，预测期 T+i 对应 W−1+i
    ratio = np.exp(trend[None, :] + xs - y[-1])
    out = dict(**{k: f[k] for k in ("r", "phi", "psi", "sig", "nu")}, ess=float(1 / np.sum(w**2)))
    for H in HS:
        out[f"p{H}"] = float(np.sum(w * (np.min(ratio[:, :H], axis=1) <= CRASH)))
    return out


def panel(sym: str) -> pd.DataFrame:
    rng = np.random.default_rng(SEED + INDEXES.index(sym))
    logp = price_series(sym); cal = logp.index; lp = logp.to_numpy(); close = np.exp(lp); r = np.diff(lp, prepend=np.nan)
    rows, last = [], -10**9
    for t in range(W, len(lp)):
        if cal[t] < START or t + max(HS) >= len(lp) or cal[t + max(HS)] > END or t - last < STEP:
            continue
        last = t
        mp = mar_prob(lp[t - W + 1 : t + 1], rng)
        hi250 = lp[t - 250 : t + 1].max()
        rows.append(dict(symbol=sym, date=cal[t], lrv1=np.log(abs(r[t]) + EPS), lrv5=lrv(r, t - 4, t + 1), lrv22=lrv(r, t - 21, t + 1),
                         runup250=lp[t] - lp[t - 250], dd250=1 - np.exp(lp[t] - hi250), **mp,
                         **{f"y{H}": int(np.min(close[t + 1 : t + H + 1]) / close[t] <= CRASH) for H in HS}))
    df = pd.DataFrame(rows); df.to_csv(OUT / f"panel_{sym}.csv", index=False); print(sym, len(df), flush=True)
    return df


def logit_fit_predict(Xtr, ytr, Xte, ridge=1e-4, iters=50):
    A = np.column_stack([np.ones(len(Xtr)), Xtr]); B = np.column_stack([np.ones(len(Xte)), Xte])
    mu, sd = A[:, 1:].mean(0), A[:, 1:].std(0) + 1e-12; A[:, 1:] = (A[:, 1:] - mu) / sd; B[:, 1:] = (B[:, 1:] - mu) / sd
    beta = np.zeros(A.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-A @ beta)); Wd = p * (1 - p) + 1e-9
        g = A.T @ (p - ytr) + ridge * beta; Hs = (A * Wd[:, None]).T @ A + ridge * np.eye(len(beta))
        step = np.linalg.solve(Hs, g); beta -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return np.clip(1 / (1 + np.exp(-B @ beta)), 1e-6, 1 - 1e-6)


def logit(p):
    p = np.clip(p, 1e-3, 1 - 1e-3); return np.log(p / (1 - p))


def cpcv_brier(P: pd.DataFrame, H: int, paths) -> pd.DataFrame:
    y = P[f"y{H}"].to_numpy().astype(float); pm = P[f"p{H}"].to_numpy(); Xb = P[HAR + R1B1].to_numpy(); Xc = np.column_stack([Xb, logit(pm)])
    out = []
    for tr, te, _ in paths:
        rec = dict(date=P.date.to_numpy()[te], symbol=P.symbol.to_numpy()[te], y=y[te])
        rec["b_clim"] = (y[te] - y[tr].mean()) ** 2
        rec["b_base"] = (y[te] - logit_fit_predict(Xb[tr], y[tr], Xb[te])) ** 2
        rec["b_mar"] = (y[te] - pm[te]) ** 2
        rec["b_cand"] = (y[te] - logit_fit_predict(Xc[tr], y[tr], Xc[te])) ** 2
        out.append(pd.DataFrame(rec))
    return pd.concat(out).set_index("date")


def ece(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    idx = np.minimum((p * bins).astype(int), bins - 1); tot = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            tot += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(tot)


def bss(df, m, b):
    return 1 - df[f"b_{m}"].sum() / df[f"b_{b}"].sum()


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    with Pool(PROCS) as pool:
        P = pd.concat(pool.map(panel, INDEXES), ignore_index=True).dropna()
    P.to_csv(OUT / "panel.csv", index=False)
    print("panel", len(P), P.groupby("symbol").size().to_dict(), "base rate", {H: round(P[f"y{H}"].mean(), 3) for H in HS},
          "r=1 share", round((P.r == 1).mean(), 3), "psi med", round(P.psi.median(), 3), "nu med", round(P.nu.median(), 2), "ess med", round(P.ess.median(), 1), flush=True)
    tdays = price_series("sh000001").index; tdays = tdays[(tdays >= START) & (tdays <= END)]
    paths = cpcv_paths(P.date, tdays, n_blocks=6, k=2, gap=80)
    res = []
    for H in HS:
        L = cpcv_brier(P, H, paths); ex = L[~L.index.year.isin(EX)]
        row = dict(H=H, n=len(P), n_paths=len(paths), base_rate=float(P[f"y{H}"].mean()))
        d1, lo1, hi1 = block_ci(L, lambda df: bss(df, "mar", "clim"), tdays)
        d2, lo2, hi2 = block_ci(L, lambda df: bss(df, "cand", "base"), tdays)
        pm, yy = P[f"p{H}"].to_numpy(), P[f"y{H}"].to_numpy().astype(float)
        row.update(bss_mar_clim=d1, lo1=lo1, hi1=hi1, bss_mar_clim_ex=bss(ex, "mar", "clim"), bss_cand_base=d2, lo2=lo2, hi2=hi2, bss_cand_base_ex=bss(ex, "cand", "base"),
                   bss_base_clim=bss(L, "base", "clim"), ece_mar=ece(pm, yy), p_mean=float(pm.mean()), auc_proxy=float(pm[yy == 1].mean() - pm[yy == 0].mean()))
        row["G1"] = bool(lo1 > 0); row["G2"] = bool(lo2 > 0 and row["bss_cand_base_ex"] > 0); row["G3"] = bool(row["ece_mar"] <= 0.05)
        row["pass"] = bool(row["G1"] and row["G2"] and row["G3"])
        rel = pd.DataFrame(dict(p=pm, y=yy)); rel["bin"] = np.minimum((rel.p * 10).astype(int), 9)
        rel.groupby("bin").agg(n=("y", "size"), p_mean=("p", "mean"), y_mean=("y", "mean")).to_csv(OUT / f"reliability_h{H}.csv")
        res.append(row); print(H, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()}, flush=True)
    R = pd.DataFrame(res); R.to_csv(OUT / "gate.csv", index=False); print("GATE W9:", bool(R["pass"].any()))
