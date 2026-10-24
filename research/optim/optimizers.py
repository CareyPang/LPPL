"""四种非线性优化器，统一接口 ``fit(t, y, lo, hi, seed, budget) -> Result``。

代价均为变量投影残差 r(θ)=y-Xβ̂(θ)（lin_fit），即在 θ 处对 β 已做最小二乘消元。

  de_lbfgsb   : scipy differential_evolution（rand1bin，含 polish=False）→ L-BFGS-B 精修
  ms_lm       : 多起点 Levenberg–Marquardt（scipy least_squares，method='trf' 含边界，
                 'lm' 本身不支持边界，trf 是其带信赖域反射的有界版本）
  tcgrid_lm   : tc 网格剖面：对每个 tc 固定，先对 (m,ω) 粗网格取 SSE 最小，
                 再在 top-K 个 tc 上做三参数 LM 精修
  cmaes       : pycma CMA-ES（有界，BoundTransform）→ L-BFGS-B 精修

每个 Result 记录 nfev、墙钟、终止原因，便于冻结预算。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import differential_evolution, least_squares, minimize

from ..lppls.core import K_LPPLS, K_POWER, design, lin_fit


@dataclass
class Result:
    theta: np.ndarray
    sse: float
    nfev: int
    seconds: float
    method: str
    message: str = ""
    extra: dict = field(default_factory=dict)


def _objective(theta, t, y, k=K_LPPLS):
    w = theta[2] if len(theta) > 2 else 0.0
    return lin_fit(t, y, theta[0], theta[1], w, k)[0]


def _resid(theta, t, y, k=K_LPPLS):
    w = theta[2] if len(theta) > 2 else 0.0
    X = design(t, theta[0], theta[1], w, k)
    if X is None:
        return np.full_like(y, 1e3)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return y - X @ beta


def _polish(theta, t, y, lo, hi, k=K_LPPLS) -> tuple[np.ndarray, float, int]:
    r = minimize(_objective, theta, args=(t, y, k), method="L-BFGS-B", bounds=list(zip(lo, hi, strict=True)),
                 options=dict(maxiter=200, ftol=1e-12, gtol=1e-8))
    return r.x, float(r.fun), int(r.nfev)


def _clip(x, lo, hi):
    return np.minimum(np.maximum(x, lo), hi)


def de_lbfgsb(t, y, lo, hi, seed=0, budget=None, *, k=K_LPPLS) -> Result:
    budget = budget or dict(popsize=15, maxiter=100)
    t0 = time.perf_counter()
    r = differential_evolution(_objective, list(zip(lo, hi, strict=True)), args=(t, y, k), seed=seed, polish=False,
                               strategy="rand1bin", popsize=budget["popsize"], maxiter=budget["maxiter"],
                               tol=1e-8, mutation=(0.5, 1.0), recombination=0.7, init="latinhypercube")
    x, f, n2 = _polish(r.x, t, y, lo, hi, k)
    return Result(x, f, int(r.nfev) + n2, time.perf_counter() - t0, "de_lbfgsb", str(r.message),
                  dict(de_sse=float(r.fun)))


def ms_lm(t, y, lo, hi, seed=0, budget=None, *, k=K_LPPLS) -> Result:
    budget = budget or dict(starts=30)
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    best, nfev, conv = None, 0, 0
    for _ in range(budget["starts"]):
        x0 = lo + rng.random(len(lo)) * (hi - lo)
        try:
            r = least_squares(_resid, x0, args=(t, y, k), bounds=(lo, hi), method="trf",
                              x_scale="jac", ftol=1e-12, xtol=1e-12, gtol=1e-10, max_nfev=400)
        except Exception:  # noqa: BLE001
            continue
        nfev += int(r.nfev)
        conv += int(r.status > 0)
        f = float(r.fun @ r.fun)
        if best is None or f < best[1]:
            best = (r.x, f)
    return Result(best[0], best[1], nfev, time.perf_counter() - t0, "ms_lm", f"converged {conv}/{budget['starts']}")


def grid_profile(t, y, tcs, ms, ws, k=K_LPPLS):
    """批量计算 (tc, m, w) 网格上的 SSE（批量 SVD，与 lin_fit 的 lstsq 同解）。

    返回 sse 数组，形状 (n_tc, n_m, n_w)；k=K_POWER 时 n_w 维为 1。不可行点为 inf。
    """
    yy = float(y @ y)
    ms = np.asarray(ms, float)
    ws = np.asarray(ws, float) if k == K_LPPLS else np.zeros(1)
    out = np.full((len(tcs), len(ms), len(ws)), np.inf)
    ones = np.ones_like(t)
    for i, tc in enumerate(tcs):
        dt = tc - t
        if np.any(dt <= 0):
            continue
        L = np.log(dt)
        f = np.exp(np.outer(ms, L))  # (n_m, n)
        if k == K_POWER:
            X = np.stack([np.broadcast_to(ones, f.shape), f], axis=-1)[:, None]  # (n_m,1,n,2)
        else:
            ph = np.outer(ws, L)  # (n_w, n)
            c, s_ = np.cos(ph), np.sin(ph)
            fm = f[:, None, :]
            X = np.stack(
                [np.broadcast_to(ones, (len(ms), len(ws), len(t))), np.broadcast_to(fm, (len(ms), len(ws), len(t))),
                 fm * c[None], fm * s_[None]], axis=-1)  # (n_m,n_w,n,4)
        U, sv, _ = np.linalg.svd(X, full_matrices=False)
        rank_ok = sv[..., -1] > sv[..., 0] * len(t) * np.finfo(float).eps
        uy = np.einsum("...nk,n->...k", U, y)
        sse = yy - np.einsum("...k,...k->...", uy, uy)
        sse = np.where(rank_ok & np.isfinite(sse), np.maximum(sse, 0.0), np.inf)
        out[i] = sse
    return out


def tcgrid_lm(t, y, lo, hi, seed=0, budget=None, *, k=K_LPPLS) -> Result:
    budget = budget or dict(n_tc=40, n_m=12, n_w=16, topk=5)
    t0 = time.perf_counter()
    tcs = np.linspace(lo[0], hi[0], budget["n_tc"])
    ms = np.linspace(lo[1], hi[1], budget["n_m"])
    if k != K_LPPLS:
        grid = grid_profile(t, y, tcs, ms, None, k)[:, :, 0]
        nfev = grid.size
        prof = grid.min(axis=1)
        arg = [ms[int(np.argmin(grid[i]))] for i in range(len(tcs))]
        order = np.argsort(prof)[: budget["topk"]]
        best = None
        for i in order:
            x0 = np.array([tcs[i], arg[i]])
            r = least_squares(_resid, x0, args=(t, y, k), bounds=(lo, hi), method="trf",
                              x_scale="jac", ftol=1e-12, xtol=1e-12, gtol=1e-10, max_nfev=400)
            nfev += int(r.nfev)
            f = float(r.fun @ r.fun)
            if best is None or f < best[1]:
                best = (r.x, f)
        return Result(best[0], best[1], nfev, time.perf_counter() - t0, "tcgrid_lm", "",
                      dict(profile=prof, tcs=tcs))
    ws = np.linspace(lo[2], hi[2], budget["n_w"])
    grid = grid_profile(t, y, tcs, ms, ws, k)
    nfev = grid.size
    prof = grid.reshape(len(tcs), -1).min(axis=1)
    arg = []
    for i in range(len(tcs)):
        j, l_ = np.unravel_index(np.argmin(grid[i]), grid[i].shape)
        arg.append((ms[j], ws[l_]))
    order = np.argsort(prof)[: budget["topk"]]
    best = None
    for i in order:
        x0 = np.array([tcs[i], *arg[i]])
        r = least_squares(_resid, x0, args=(t, y, k), bounds=(lo, hi), method="trf", x_scale="jac",
                          ftol=1e-12, xtol=1e-12, gtol=1e-10, max_nfev=400)
        nfev += int(r.nfev)
        f = float(r.fun @ r.fun)
        if best is None or f < best[1]:
            best = (r.x, f)
    return Result(best[0], best[1], nfev, time.perf_counter() - t0, "tcgrid_lm", "", dict(profile=prof, tcs=tcs))


def cmaes(t, y, lo, hi, seed=0, budget=None, *, k=K_LPPLS) -> Result:
    import cma

    budget = budget or dict(maxfevals=3000, restarts=2)
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    best, nfev = None, 0
    for restart in range(budget["restarts"] + 1):
        x0 = lo + rng.random(len(lo)) * (hi - lo)
        es = cma.CMAEvolutionStrategy(x0, 0.3 * float(np.mean(hi - lo)) / 3, dict(
            bounds=[list(lo), list(hi)], seed=int(seed) + restart + 1, verbose=-9,
            maxfevals=budget["maxfevals"] // (budget["restarts"] + 1), tolfun=1e-11,
            CMA_stds=list((hi - lo) / 3), popsize=12))
        while not es.stop():
            xs = es.ask()
            es.tell(xs, [_objective(x, t, y, k) for x in xs])
        nfev += es.countevals
        xb, fb = es.result.xbest, es.result.fbest
        if best is None or fb < best[1]:
            best = (np.asarray(xb), float(fb))
    x, f, n2 = _polish(_clip(best[0], lo, hi), t, y, lo, hi, k)
    return Result(x, f, nfev + n2, time.perf_counter() - t0, "cmaes", str(es.stop()))


METHODS = dict(de_lbfgsb=de_lbfgsb, ms_lm=ms_lm, tcgrid_lm=tcgrid_lm, cmaes=cmaes)
