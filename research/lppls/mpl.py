"""§21.2 (b) t_c 的修正剖面似然（MPL）区间（Filimonov–Demos–Sornette 2017，Severini 1998 近似；草案，不接入产品）。

对 t_c 网格上每一点：ψ̂_tc = argmin_{m,ω}（A,B,C₁,C₂ 线性消元）SSE(t_c, ψ)；
    ℓ_MPL(t_c) = ½ ln|XᵀX − H| − ln|Xᵀ(t̂_c, ψ̂) X(t_c, ψ̂_tc)| − (n − p − 2)/2 · ln ŝ_tc                  （论文式 (38)）
其中 X = ∂LPPLS/∂ψ（n×6，ψ = {m, ω, A, B, C₁, C₂}），H = Σ_k ε_k ∂²LPPLS/∂ψ∂ψᵀ，ŝ_tc = SSE/n（式 (19)），p = 7。
名义 1−α 区间 = {t_c : 2[ℓ_max − ℓ_MPL(t_c)] ≤ χ²₁(1−α)}。普通剖面似然 ℓ_P(t_c) = −(n/2) ln ŝ_tc 一并返回作对照。
导数用中心差分（步长 1e-4 相对量）；H 可选（默认计入）。
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.stats import chi2

from .core import design, lin_fit

P_TOTAL = 7


def _model(t: np.ndarray, tc: float, psi: np.ndarray) -> np.ndarray:
    m, w, A, B, C1, C2 = psi
    X = design(t, tc, m, w)
    return X @ np.array([A, B, C1, C2])


def _fit_psi(t: np.ndarray, y: np.ndarray, tc: float, m_bounds, w_bounds, start: tuple[float, float] | None = None) -> np.ndarray:
    """固定 t_c，网格 + Nelder–Mead 求 (m, ω)，线性参数由 lin_fit 消元。"""
    def sse(mw):
        m, w = mw
        if not (m_bounds[0] <= m <= m_bounds[1] and w_bounds[0] <= w <= w_bounds[1]):
            return 1e300
        s, _ = lin_fit(t, y, tc, m, w)
        return s if np.isfinite(s) else 1e300
    cands = []
    for m in np.linspace(m_bounds[0], m_bounds[1], 8):
        for w in np.linspace(w_bounds[0], w_bounds[1], 12):
            cands.append((sse((m, w)), m, w))
    if start is not None:
        cands.append((sse(start), *start))
    cands.sort()
    best = None
    for _s0, m0, w0 in cands[:3]:
        r = minimize(sse, x0=[m0, w0], method="Nelder-Mead", options=dict(xatol=1e-4, fatol=1e-10, maxiter=400))
        if best is None or r.fun < best.fun:
            best = r
    m, w = best.x
    _, beta = lin_fit(t, y, tc, m, w)
    return np.array([m, w, *beta], float)


def _jacobian(t: np.ndarray, tc: float, psi: np.ndarray, h: float = 1e-4) -> np.ndarray:
    base = _model(t, tc, psi)
    J = np.empty((len(t), len(psi)))
    for j in range(len(psi)):
        d = np.zeros_like(psi)
        d[j] = h * max(1.0, abs(psi[j]))
        J[:, j] = (_model(t, tc, psi + d) - _model(t, tc, psi - d)) / (2 * d[j])
    return J, base


def _hessian_term(t: np.ndarray, y: np.ndarray, tc: float, psi: np.ndarray, h: float = 1e-3) -> np.ndarray:
    """H_ij = Σ_k ε_k ∂²f_k/∂ψ_i∂ψ_j；只有非线性参数 (m, ω) 的二阶项非零（线性参数二阶导为 0，交叉项 ∂²f/∂m∂A 等非零）。"""
    k = len(psi)
    eps = y - _model(t, tc, psi)
    H = np.zeros((k, k))
    steps = [h * max(1.0, abs(v)) for v in psi]
    for i in range(k):
        for j in range(i, k):
            di, dj = np.zeros(k), np.zeros(k)
            di[i], dj[j] = steps[i], steps[j]
            fpp = _model(t, tc, psi + di + dj)
            fpm = _model(t, tc, psi + di - dj)
            fmp = _model(t, tc, psi - di + dj)
            fmm = _model(t, tc, psi - di - dj)
            d2 = (fpp - fpm - fmp + fmm) / (4 * steps[i] * steps[j])
            H[i, j] = H[j, i] = float(eps @ d2)
    return H


def _logdet(M: np.ndarray) -> float:
    sign, ld = np.linalg.slogdet(M)
    return ld if sign > 0 else -np.inf


def mpl_profile(t: np.ndarray, y: np.ndarray, tc_grid: np.ndarray, m_bounds=(0.01, 2.0), w_bounds=(1.0, 50.0),
                use_hessian: bool = True) -> dict:
    n = len(t)
    psis, sses = [], []
    start = None
    for tc in tc_grid:
        psi = _fit_psi(t, y, tc, m_bounds, w_bounds, start)
        start = (psi[0], psi[1])
        psis.append(psi)
        sses.append(float(np.sum((y - _model(t, tc, psi)) ** 2)))
    sses = np.array(sses)
    k = int(np.argmin(sses))
    tc_hat, psi_hat = float(tc_grid[k]), psis[k]
    J_hat, _ = _jacobian(t, tc_hat, psi_hat)
    lp = -(n / 2) * np.log(sses / n)
    lm = np.full(len(tc_grid), -np.inf)
    for i, tc in enumerate(tc_grid):
        J, _ = _jacobian(t, tc, psis[i])
        M = J.T @ J
        if use_hessian:
            M = M - _hessian_term(t, y, tc, psis[i])
        ld1 = _logdet(M)
        ld2 = _logdet(J_hat.T @ J)
        if not np.isfinite(ld1) or not np.isfinite(ld2):
            continue
        lm[i] = 0.5 * ld1 - ld2 - (n - P_TOTAL - 2) / 2 * np.log(sses[i] / n)
    return dict(tc_grid=np.asarray(tc_grid, float), lp=lp, lm=lm, tc_hat=tc_hat, tc_hat_mpl=float(tc_grid[int(np.argmax(lm))]),
                psi=np.array(psis), sse=sses)


def interval(prof: dict, level: float = 0.9, which: str = "lm") -> tuple[float, float]:
    """区间端点在网格上线性插值到阈值穿越处（避免粗网格把区间压成单点）。"""
    g, ll = prof["tc_grid"], prof[which]
    ok = np.isfinite(ll)
    g, ll = g[ok], ll[ok]
    cut = ll.max() - chi2.ppf(level, 1) / 2
    k = int(np.argmax(ll))
    lo = g[0] if ll[0] >= cut else g[k]
    for i in range(k, 0, -1):
        if ll[i - 1] < cut <= ll[i]:
            lo = g[i] - (g[i] - g[i - 1]) * (ll[i] - cut) / (ll[i] - ll[i - 1])
            break
    hi = g[-1] if ll[-1] >= cut else g[k]
    for i in range(k, len(g) - 1):
        if ll[i + 1] < cut <= ll[i]:
            hi = g[i] + (g[i + 1] - g[i]) * (ll[i] - cut) / (ll[i] - ll[i + 1])
            break
    return float(lo), float(hi)


def tc_grid(n: int, step: float = 0.5, span: float = 0.2) -> np.ndarray:
    dt = n - 1
    return np.arange(dt - span * dt, dt + span * dt + 1e-9, step)
