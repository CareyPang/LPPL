"""F4 synthetic test: Lagrange-regularised window start t1 (Demos & Sornette 2019, Physica A, arXiv 1707.07162).

Paper (section 2, eqs. 1, 10-11): chi2_np = SSE / ((t2 - t1) - p); chi2_lambda = chi2_np - lambda * (t2 - t1),
lambda = empirical large-scale linear trend of chi2_np over the scanned window sizes; p = 8 for LPPLS
(7 model parameters + t1, section 4.2.1).  The production fitter (tcgrid_lm, v2 search box) is used unchanged.

Pre-registered before running (no re-tuning afterwards):
- testbed: 800-point series. Bubble of true length L in (130, 250, 500) occupies the last L points; before it a
  low-slope random walk (daily sd 0.012, total drift U(-0.15, 0.15)). Bubble noise AR(1) rho in (0.5, 0.8, 0.95)
  or AR(1)-GARCH(1,1) with rho drawn from the same set. Nulls: the six F2/F3 null generators at n=800.
- windows 30..750 step 10, fit on the last n points (t2 fixed at the series end).
- variants: current (lagrange_pick as in production research code: all windows, p=7, OLS slope);
  main (drop unconverged = non-finite SSE / failed linear solve, and B>=0; p=8, OLS slope, lambda<=0 -> lambda=0);
  longest (as main, lambda<=0 -> longest valid window); theilsen (as main, Theil-Sen slope);
  nobound (as main, also drop fits with t_c, m or omega on the search boundary).
  tcgrid_lm has no convergence flag, so boundary hits are reported as a separate comparison, not the main filter.
- gate (main variant): per L, median |n* - L| < 0.2 L; pooled over nulls, single-window trigger rate of the
  picked window passing `box` <= current multi-window alarm rate (any of S/M/L box fraction >= 0.10).
"""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import pandas as pd
from scipy.stats import theilslopes

from ..features.lppls_rules import SCALES, _derived, lagrange_pick, rules
from ..lppls.core import lin_fit
from ..lppls.spec import SCAN_BOXES
from ..optim.optimizers import tcgrid_lm
from .profile_synth import NULL_SET, _ar1_noise, _block_pools, _garch_ar1_noise, _null

SEED = 20261126
N_TOTAL = 800
L_SET = (130, 250, 500)
RHO_SET = (0.5, 0.8, 0.95)
NOISE_SET = ("AR1_0.5", "AR1_0.8", "AR1_0.95", "GARCH_AR1")
REPS = 40
WINDOWS = tuple(range(30, 751, 10))
P_PAPER = 8
ALARM = 0.10
BOX = SCAN_BOXES["v2"]


def _bubble(L: int, noise_name: str, rng) -> tuple[np.ndarray, dict]:
    dt = L - 1
    ahead = float(rng.uniform(0.02 * dt + 1.0, 0.18 * dt))
    tc = dt + ahead
    m = float(rng.uniform(0.1, 0.9))
    omega = float(rng.uniform(6.0, 13.0))
    phi = float(rng.uniform(0.0, 2.0 * np.pi))
    total_rise = float(rng.uniform(0.3, 1.2))
    b = -total_rise / (tc**m - ahead**m)
    c = float(rng.uniform(0.0, min(0.1, m / omega))) * abs(b)
    if noise_name == "GARCH_AR1":
        rho = float(rng.choice(RHO_SET))
    else:
        rho = float(noise_name.split("_")[1])
    sd = float(rng.uniform(0.02, 0.06))
    pre_len = N_TOTAL - L
    pre_drift = float(rng.uniform(-0.15, 0.15)) / pre_len
    pre_steps = pre_drift + rng.normal(0.0, 0.012, size=pre_len)
    noise = _garch_ar1_noise(L, rho, sd, rng) if noise_name == "GARCH_AR1" else _ar1_noise(L, rho, sd, rng)
    t = np.arange(L, dtype=float)
    dist = tc - t
    det = 4.0 + b * dist**m + c * dist**m * np.cos(omega * np.log(dist) - phi)
    bubble = det + noise
    # pre-segment walks into the bubble's first point: pre[k] = bubble[0] - sum(steps[k+1:])
    tail = np.cumsum(pre_steps[::-1])[::-1]
    pre = bubble[0] - tail
    y = np.r_[pre, bubble]
    return y, {"L": L, "t1_true": pre_len, "tc_true": pre_len + tc, "m_true": m, "w_true": omega, "rho": rho, "sd": sd}


def tasks(source_root: Path) -> list[dict]:
    raw, centered = _block_pools(source_root)
    rng = np.random.default_rng(SEED)
    out = []
    for L in L_SET:
        for noise in NOISE_SET:
            for rep in range(REPS):
                y, p = _bubble(L, noise, rng)
                out.append({"task_id": f"bubble:{L}:{noise}:{rep:03d}", "kind": "bubble", "noise": noise, "y": y, **p})
    for cls in NULL_SET:
        for rep in range(REPS):
            y, p = _null(N_TOTAL, cls, rng, raw, centered)
            out.append({"task_id": f"null:{cls}:{rep:03d}", "kind": "null", "null_class": cls, "y": y, "L": np.nan})
    return out


def fit_window(y: np.ndarray) -> dict:
    """Same call as lppls_scan.fit_one main branch (v2 box, tcgrid_lm, seed 0, n_random 10)."""
    n = len(y)
    t = np.arange(n, dtype=float)
    dt = n - 1
    tc_lo, tc_hi = BOX["tc"]
    lo = np.array([dt + (tc_lo if tc_lo >= 0.5 else tc_lo * dt), BOX["m"][0], BOX["w"][0]])
    hi = np.array([dt + 0.2 * dt, BOX["m"][1], BOX["w"][1]])
    r = tcgrid_lm(t, y, lo, hi, seed=0, n_random=BOX["n_random"])
    s, beta = lin_fit(t, y, *r.theta)
    sst = float(((y - y.mean()) ** 2).sum())
    tol = 1e-6 * (hi - lo)
    at_bound = bool(np.any(np.abs(r.theta - lo) <= tol) or np.any(np.abs(r.theta - hi) <= tol))
    if beta is None:
        beta = np.full(4, np.nan)
    return dict(n=n, tc=float(r.theta[0]), m=float(r.theta[1]), w=float(r.theta[2]), A=float(beta[0]), B=float(beta[1]),
                C1=float(beta[2]), C2=float(beta[3]), sse=float(s), r2=1 - s / sst, y_std=float(np.std(y)), at_bound=at_bound)


def _worker(task: dict) -> list[dict]:
    y = np.asarray(task["y"], float)
    meta = {k: v for k, v in task.items() if k != "y"}
    rows = []
    for n in WINDOWS:
        a = time.perf_counter()
        row = fit_window(y[-n:])
        row["seconds"] = time.perf_counter() - a
        rows.append({**meta, **row})
    return rows


def run(source_root: Path, out: Path, workers: int) -> None:
    ts = tasks(source_root)
    rows, start = [], time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_worker, t) for t in ts]
        for i, f in enumerate(as_completed(futs), 1):
            rows.extend(f.result())
            if i % 20 == 0:
                print(f"{i}/{len(futs)} series elapsed={time.perf_counter() - start:.0f}s", flush=True)
    frame = pd.DataFrame(rows).sort_values(["task_id", "n"]).reset_index(drop=True)
    out.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out / "rows.parquet")


VARIANTS = ("main", "longest", "theilsen", "nobound")


def _pick(g: pd.DataFrame, variant: str, p: int = P_PAPER) -> tuple[float, float, int]:
    """Returns (picked n, lambda, number of windows used). NaN pick if nothing valid."""
    ok = np.isfinite(g.sse) & np.isfinite(g.B) & (g.B < 0)
    if variant == "nobound":
        ok &= ~g.at_bound
    v = g[ok]
    if len(v) < 3:
        return np.nan, np.nan, len(v)
    x = v.n.to_numpy(float)
    chi = v.sse.to_numpy(float) / (x - 1 - p)  # t2 - t1 = n - 1
    lam = theilslopes(chi, x)[0] if variant == "theilsen" else np.polyfit(x, chi, 1)[0]
    if lam <= 0:
        if variant == "longest":
            return float(x.max()), float(lam), len(v)
        lam_used = 0.0
    else:
        lam_used = lam
    return float(x[int(np.argmin(chi - lam_used * x))]), float(lam), len(v)


def analyse(frame: pd.DataFrame) -> dict:
    frame = frame.copy()
    frame["date"] = frame.task_id
    for col in ("pow_tc", "pow_m", "pow_B", "pow_sse"):
        frame[col] = np.nan  # power-law fit not run; `power` rule unused here
    d = _derived(frame)
    r = rules(d)
    d["box"], d["lit1"] = r.box.to_numpy(), r.lit1.to_numpy()
    cur = lagrange_pick(d)
    recs = []
    for tid, g in d.groupby("task_id"):
        rec = {"task_id": tid, "kind": g.kind.iloc[0], "L": g.L.iloc[0], "noise": g.noise.iloc[0],
               "null_class": g.null_class.iloc[0], "rho": g.rho.iloc[0] if "rho" in g else np.nan,
               "valid_share": float((np.isfinite(g.sse) & (g.B < 0)).mean()),
               "bound_share": float(g.at_bound.mean()), "bneg_share": float((g.B < 0).mean())}
        row = d.loc[cur[tid]]
        rec.update(current_n=float(row.n), current_box=bool(row.box), current_lit1=bool(row.lit1))
        for var in VARIANTS:
            n_star, lam, used = _pick(g, var)
            rec[f"{var}_n"], rec[f"{var}_lambda"], rec[f"{var}_used"] = n_star, lam, used
            hit = g[g.n == n_star]
            rec[f"{var}_box"] = bool(hit.box.iloc[0]) if len(hit) else False
            rec[f"{var}_lit1"] = bool(hit.lit1.iloc[0]) if len(hit) else False
        for sc, (lo, hi) in SCALES.items():
            gs = g[g.n.between(lo, hi)]
            n_star, lam, _ = _pick(gs, "main")
            rec[f"main_{sc}_n"], rec[f"main_{sc}_lambda"] = n_star, lam
            rec[f"alarm_box_{sc}"] = float(gs.box.mean()) >= ALARM
            rec[f"alarm_lit1_{sc}"] = float(gs.lit1.mean()) >= ALARM
        rec["alarm_box_any"] = any(rec[f"alarm_box_{sc}"] for sc in SCALES)
        rec["alarm_lit1_any"] = any(rec[f"alarm_lit1_{sc}"] for sc in SCALES)
        recs.append(rec)
    return pd.DataFrame(recs)


def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(f"{v:.3f}" if isinstance(v, float) else str(v) for v in row) + " |")
    return "\n".join(lines)


def report(out: Path) -> None:
    frame = pd.read_parquet(out / "rows.parquet")
    per = analyse(frame)
    per.to_parquet(out / "per_series.parquet")
    b, nl = per[per.kind == "bubble"], per[per.kind == "null"]
    lines = ["# F4 合成检验：Lagrange 正则选窗起点", "",
             f"序列 {len(per)}（泡沫 {len(b)}，零假设 {len(nl)}），拟合 {len(frame)} 次，单窗耗时中位 {frame.seconds.median():.3f}s。", ""]
    err = []
    for (L, noise), g in list(b.groupby(["L", "noise"])) + [((L, "ALL"), g) for L, g in b.groupby("L")]:
        row = {"L": int(L), "noise": noise, "N": len(g)}
        for var in ("current", *VARIANTS):
            e = (g[f"{var}_n"] - L).abs()
            row[f"{var}_med_err/L"] = float(e.median() / L)
            if var != "current":
                row[f"{var}_nan"] = int(g[f"{var}_n"].isna().sum())
        row["lambda<=0"] = float((g.main_lambda <= 0).mean())
        row["valid_share"] = float(g.valid_share.median())
        err.append(row)
    err = pd.DataFrame(err)
    lines += ["## 起点定位误差（中位 |n*−L| / L；门槛 < 0.2）", "", _md(err), ""]
    sc_rows = []
    for L, g in b.groupby("L"):
        sc_rows.append({"L": int(L), **{f"{sc}_med_n": float(g[f"main_{sc}_n"].median()) for sc in SCALES},
                        **{f"{sc}_med_err/L": float((g[f"main_{sc}_n"] - L).abs().median() / L) for sc in SCALES}})
    lines += ["## 分尺度单点 t1*（main 口径，尺度内估 λ）", "", _md(pd.DataFrame(sc_rows)), ""]
    trig = []
    for name, g in [("null_ALL", nl)] + [(c, g) for c, g in nl.groupby("null_class")] + [("bubble_ALL", b)]:
        trig.append({"group": name, "N": len(g),
                     "alarm_box_any": float(g.alarm_box_any.mean()), "current_box": float(g.current_box.mean()),
                     "main_box": float(g.main_box.mean()), "longest_box": float(g.longest_box.mean()),
                     "theilsen_box": float(g.theilsen_box.mean()), "nobound_box": float(g.nobound_box.mean()),
                     "alarm_lit1_any": float(g.alarm_lit1_any.mean()), "main_lit1": float(g.main_lit1.mean())})
    lines += ["## 触发率（单窗 = 选中窗口过 box；现行 = 任一尺度 box 合格占比 ≥10%）", "", _md(pd.DataFrame(trig)), ""]
    allrow = err[err.noise == "ALL"]
    pass1 = bool((allrow["main_med_err/L"] < 0.2).all())
    pass2 = bool(nl.main_box.mean() <= nl.alarm_box_any.mean())
    lines += ["## 合成门（main 口径）", "",
              f"- 起点误差：{'通过' if pass1 else '不通过'}（" + "，".join(f"L={int(r.L)}: {r['main_med_err/L']:.3f}" for _, r in allrow.iterrows()) + "）",
              f"- 零假设单窗触发率 ≤ 现行：{'通过' if pass2 else '不通过'}（单窗 {nl.main_box.mean():.3f}，现行 {nl.alarm_box_any.mean():.3f}）",
              f"- 结论：{'过门' if pass1 and pass2 else '未过门'}", ""]
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("run", "report"))
    ap.add_argument("--source-root", type=Path, default=Path("/home/ubuntu/work/global-full"))
    ap.add_argument("--out", type=Path, default=Path("reports/lagrange_synth"))
    ap.add_argument("--workers", type=int, default=7)
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.source_root, a.out, a.workers)
    report(a.out)


if __name__ == "__main__":
    main()
