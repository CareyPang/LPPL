"""F1–F4（预登记 §25）共用：合成集、Prais–Winsten 变换的网格剖面与精修、t_c 剖面、box 判定行。研究用，不进生产。"""
from __future__ import annotations

import os

import numpy as np
from scipy.optimize import minimize

os.environ.setdefault("LPPLS_BOX", "v2")
from research.features.lppls_scan import _box_pass, residual_tests  # noqa: E402
from research.lppls import core  # noqa: E402
from research.lppls.core import K_POWER, design, lin_fit  # noqa: E402
from research.optim.optimizers import tcgrid_lm  # noqa: E402
from research.synth.lppls_synth import sample  # noqa: E402
from research.synth.nulls import NULLS, sample_null  # noqa: E402

NS = (227, 477)
SIGMAS = (0.01, 0.02)
NOISES = (("iid", 0.5), ("ar1", 0.5), ("ar1", 0.9), ("garch", 0.5))
SEEDS_A = tuple(range(0, 12))
SEEDS_B = tuple(range(12, 25))
NULL_SEEDS = tuple(range(0, 20))


def init():
    core.ALLOW_INSIDE = True


def noise_label(kind, phi):
    return f"ar1_{phi}" if kind == "ar1" else kind


def bounds(n):
    dt = n - 1
    return np.array([0.8 * dt, 0.01, 1.0]), np.array([1.2 * dt, 2.0, 50.0])


def synth(n, sigma, kind, phi, seed):
    dt = n - 1
    t, y, tr = sample(n=n, sigma=sigma, noise=kind, seed=seed, horizon=(5, 0.15 * dt), phi=phi)
    return t, y, tr


def synth_cells(seeds):
    for n in NS:
        for sg in SIGMAS:
            for kind, phi in NOISES:
                for s in seeds:
                    yield dict(n=n, sigma=sg, noise=noise_label(kind, phi), kind=kind, phi=phi, seed=s)


def null_cells(ns=NS, seeds=NULL_SEEDS):
    for kind in NULLS:
        for n in ns:
            for s in seeds:
                yield dict(null=kind, n=n, seed=s)


def null_series(c):
    return sample_null(c["null"], n=c["n"], sigma=0.02, seed=c["seed"])


def pw(a, rho, axis=0):
    """Prais–Winsten：首行 ×√(1−ρ²)，其余行 a_i − ρ·a_{i−1}（沿 axis）。"""
    a = np.moveaxis(np.asarray(a, float), axis, 0)
    out = np.empty_like(a)
    out[0] = np.sqrt(1 - rho**2) * a[0]
    out[1:] = a[1:] - rho * a[:-1]
    return np.moveaxis(out, 0, axis)


def grid_sse(t, y, tcs, ms, ws, rho=0.0):
    yz = pw(y, rho) if rho else y
    yy = float(yz @ yz)
    out = np.full((len(tcs), len(ms), len(ws)), np.inf)
    ones = np.ones_like(t)
    for i, tc in enumerate(tcs):
        dt = tc - t
        if core.ALLOW_INSIDE:
            dt = np.maximum(np.abs(dt), core.MIN_DT)
        elif np.any(dt <= 0):
            continue
        L = np.log(dt)
        f = np.exp(np.outer(ms, L))[:, None, :]
        ph = np.outer(ws, L)[None]
        sh = (len(ms), len(ws), len(t))
        X = np.stack([np.broadcast_to(ones, sh), np.broadcast_to(f, sh), f * np.cos(ph), f * np.sin(ph)], axis=-1)
        if rho:
            X = pw(X, rho, axis=-2)
        U, sv, _ = np.linalg.svd(X, full_matrices=False)
        ok = sv[..., -1] > sv[..., 0] * len(t) * np.finfo(float).eps
        uy = np.einsum("...nk,n->...k", U, yz)
        s = yy - np.einsum("...k,...k->...", uy, uy)
        out[i] = np.where(ok & np.isfinite(s), np.maximum(s, 0.0), np.inf)
    return out


def lin_rho(t, y, theta, rho=0.0):
    X = design(t, *theta)
    if X is None:
        return np.inf, None
    Xz, yz = (pw(X, rho), pw(y, rho)) if rho else (X, y)
    beta, *_ = np.linalg.lstsq(Xz, yz, rcond=None)
    r = yz - Xz @ beta
    s = float(r @ r)
    return (s, beta) if np.isfinite(s) else (np.inf, None)


def fit(t, y, lo, hi, rho=0.0, grid=(40, 20, 30), topk=10):
    tcs, ms, ws = (np.linspace(lo[i], hi[i], grid[i]) for i in range(3))
    g = grid_sse(t, y, tcs, ms, ws, rho)
    best = (None, np.inf)
    for flat in np.argsort(g, axis=None)[:topk]:
        if not np.isfinite(g.flat[flat]):
            break
        i, j, k = np.unravel_index(flat, g.shape)
        r = minimize(lambda x: lin_rho(t, y, x, rho)[0], np.array([tcs[i], ms[j], ws[k]]), method="L-BFGS-B",
                     bounds=list(zip(lo, hi, strict=True)), options=dict(maxiter=200, ftol=1e-12, gtol=1e-8))
        f = min(float(r.fun), float(g.flat[flat]))
        th = r.x if r.fun <= g.flat[flat] else np.array([tcs[i], ms[j], ws[k]])
        if f < best[1]:
            best = (th, f)
    return best


def ac1(u):
    u = u - u.mean()
    return float(np.clip((u[1:] @ u[:-1]) / (u @ u), 0.0, 0.98))


def fit_gls(t, y, lo, hi, iters=3, tol=0.01):
    """§25.3：OLS → ρ₀ → 固定 ρ 拟合 → 用未变换残差更新 ρ，|Δρ|<tol 或 iters 次止。"""
    th, _ = fit(t, y, lo, hi, 0.0)
    _, b = lin_rho(t, y, th, 0.0)
    rho = ac1(y - design(t, *th) @ b)
    n_it = 0
    for _ in range(iters):
        n_it += 1
        th, _ = fit(t, y, lo, hi, rho)
        _, b = lin_rho(t, y, th, rho)
        new = ac1(y - design(t, *th) @ b)
        done = abs(new - rho) < tol
        rho = new
        if done:
            break
    return th, rho, n_it


def profile_tc(t, y, lo, hi, n_tc=81, n_m=30, n_w=40, top=3):
    """§25.2：P(t_c) = min_{m,ω} SSE；每个 t_c 网格取最小 top 个 (m,ω) 格点做有界精修。"""
    tcs = np.linspace(lo[0], hi[0], n_tc)
    ms, ws = np.linspace(lo[1], hi[1], n_m), np.linspace(lo[2], hi[2], n_w)
    g = grid_sse(t, y, tcs, ms, ws)
    P = np.full(n_tc, np.inf)
    for i, tc in enumerate(tcs):
        gi = g[i]
        best = float(gi.min())
        for flat in np.argsort(gi, axis=None)[:top]:
            if not np.isfinite(gi.flat[flat]):
                break
            j, k = np.unravel_index(flat, gi.shape)
            r = minimize(lambda x, tc=tc: lin_rho(t, y, np.array([tc, x[0], x[1]]))[0], np.array([ms[j], ws[k]]),
                         method="L-BFGS-B", bounds=[(lo[1], hi[1]), (lo[2], hi[2])],
                         options=dict(maxiter=200, ftol=1e-12, gtol=1e-8))
            best = min(best, float(r.fun))
        P[i] = best
    return tcs, P


def box_row(t, y, theta, lo, hi):
    s, beta = lin_fit(t, y, *theta)
    sst = float(((y - y.mean()) ** 2).sum())
    rp = tcgrid_lm(t, y, lo[:2], hi[:2], seed=0, k=K_POWER, n_random=10)
    sp, bp = lin_fit(t, y, rp.theta[0], rp.theta[1], 0.0, K_POWER)
    return (len(y), *map(float, theta), *map(float, beta), float(s), 1 - s / sst, float(rp.theta[0]), float(rp.theta[1]),
            float(bp[1]), float(sp), *residual_tests(t, y, *theta, beta))


def box_pass(t, y, theta, lo, hi):
    return _box_pass(y, box_row(t, y, theta, lo, hi))
