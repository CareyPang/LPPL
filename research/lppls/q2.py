"""§21.1 (a) Q2 合格判据的两项统计检验（草案，不接入产品判据；只在合成标定与开发段报告中使用）。

1. 嵌套似然比（R5 硬门化）：同一窗口、同一 t_c/m 搜索域，LPPLS（7 参数）与纯幂律 PL（C₁=C₂=0，4 参数）
   Λ = n·ln(SSE_PL / SSE_LPPLS)。零分布：PL 拟合值 + PL 残差的平稳块 bootstrap（Politis–Romano 1994，几何块长，
   均值块长 block ∈ {5,10,20}）生成 y*，重拟两模型得 Λ*，B 次；p = (1 + #{Λ* ≥ Λ}) / (B + 1)。
2. Lomb 振荡显著（R5b 硬门化，Zhou–Sornette 2002）：PL 去趋势残差 r=(y−A−B f)/f 对 x=ln|t_c−t| 的 Lomb 周期图，
   峰值角频率与拟合 ω 的相对差 ≤ tol，峰高 p 由模拟零分布确定：AR(1) 与 AR(1)+t₅ 噪声各 n_sim 条
   （与残差同长度、同方差、同一阶自相关），p = (1 + #{peak* ≥ peak}) / (n_sim + 1)。
"""
from __future__ import annotations

import numpy as np
from scipy.signal import lombscargle

from ..optim.optimizers import tcgrid_lm
from .core import K_POWER, MIN_DT, lin_fit

FAST_BUDGET = dict(n_tc=20, n_m=8, n_w=10, topk=3)
LOMB_W = np.arange(1.0, 50.01, 0.25)


def stationary_block_resample(e: np.ndarray, rng: np.random.Generator, mean_block: int) -> np.ndarray:
    """Politis–Romano 平稳 bootstrap：块起点均匀、块长 ~ Geometric(1/mean_block)，循环取样。"""
    n = len(e)
    out = np.empty(n)
    k = 0
    p = 1.0 / max(1, mean_block)
    while k < n:
        s = int(rng.integers(0, n))
        L = int(rng.geometric(p))
        m = min(L, n - k)
        out[k : k + m] = np.take(e, np.arange(s, s + m) % n)
        k += m
    return out


def fit_both(t: np.ndarray, y: np.ndarray, lo: np.ndarray, hi: np.ndarray, seed: int = 0, n_random: int = 0,
             budget: dict | None = None) -> dict:
    """同一搜索域下分别拟合 LPPLS 与 PL，返回 SSE、参数与 PL 拟合值/残差。lo/hi = (tc, m, w) 边界。"""
    r = tcgrid_lm(t, y, lo, hi, seed=seed, n_random=n_random, budget=budget)
    s_l, beta_l = lin_fit(t, y, *r.theta)
    rp = tcgrid_lm(t, y, lo[:2], hi[:2], seed=seed, k=K_POWER, n_random=n_random, budget=budget)
    s_p, beta_p = lin_fit(t, y, rp.theta[0], rp.theta[1], 0.0, K_POWER)
    dtt = np.maximum(np.abs(rp.theta[0] - t), MIN_DT)
    fit_p = beta_p[0] + beta_p[1] * dtt ** rp.theta[1]
    return dict(theta=np.asarray(r.theta, float), beta=np.asarray(beta_l, float), sse=float(s_l),
                theta_pl=np.asarray([rp.theta[0], rp.theta[1]], float), beta_pl=np.asarray(beta_p, float), sse_pl=float(s_p),
                fit_pl=fit_p, resid_pl=y - fit_p)


def lr_stat(n: int, sse_pl: float, sse_lppls: float) -> float:
    return float(n * np.log(max(sse_pl, 1e-300) / max(sse_lppls, 1e-300)))


def nested_lr_test(t: np.ndarray, y: np.ndarray, lo: np.ndarray, hi: np.ndarray, block: int = 10, B: int = 200,
                   seed: int = 0, budget: dict | None = FAST_BUDGET, fit: dict | None = None) -> dict:
    """返回 Λ、Λ* 零分布分位与 p 值。fit 可传入 fit_both 的结果以免重复拟合。"""
    n = len(y)
    fit = fit or fit_both(t, y, lo, hi, seed=seed, budget=budget)
    lam = lr_stat(n, fit["sse_pl"], fit["sse"])
    rng = np.random.default_rng(seed + 7919)
    lam_star = np.empty(B)
    for b in range(B):
        yb = fit["fit_pl"] + stationary_block_resample(fit["resid_pl"], rng, block)
        fb = fit_both(t, yb, lo, hi, seed=int(rng.integers(1 << 30)), budget=budget)
        lam_star[b] = lr_stat(n, fb["sse_pl"], fb["sse"])
    p = float((1 + np.sum(lam_star >= lam)) / (B + 1))
    return dict(lam=lam, p=p, lam_q95=float(np.quantile(lam_star, 0.95)), lam_q99=float(np.quantile(lam_star, 0.99)), B=B, block=block)


def _lomb_peak(x: np.ndarray, r: np.ndarray) -> tuple[float, float]:
    pn = lombscargle(x, r - r.mean(), LOMB_W, normalize=True)
    j = int(np.argmax(pn))
    return float(LOMB_W[j]), float(pn[j])


def _ar1_params(r: np.ndarray) -> tuple[float, float]:
    r0 = r - r.mean()
    phi = float(np.dot(r0[1:], r0[:-1]) / max(np.dot(r0[:-1], r0[:-1]), 1e-300))
    phi = float(np.clip(phi, -0.99, 0.99))
    sig = float(np.std(r0) * np.sqrt(max(1 - phi**2, 1e-6)))
    return phi, sig


def _simulate_ar1(n: int, phi: float, sig: float, rng: np.random.Generator, student_t: bool, n_sim: int = 1) -> np.ndarray:
    """n_sim 条 AR(1) 路径（行），平稳初值；lfilter 向量化。"""
    from scipy.signal import lfilter

    eps = rng.standard_t(5, (n_sim, n)) / np.sqrt(5 / 3) if student_t else rng.standard_normal((n_sim, n))
    eps *= sig
    eps[:, 0] /= np.sqrt(max(1 - phi**2, 1e-6))
    return lfilter([1.0], [1.0, -phi], eps, axis=1)


def lomb_test(t: np.ndarray, y: np.ndarray, theta: np.ndarray, beta: np.ndarray, null_model: str = "ar1",
              n_sim: int = 1000, tol: float = 0.25, seed: int = 0) -> dict:
    """去趋势残差 r=(y−A−B f)/f（f=|t̂_c−t|^m̂，A,B 取 LPPLS 拟合值，与 `lppls_scan.residual_tests`/Jiang 2010 §2.3 同口径）
    对 x=ln|t̂_c−t| 的 Lomb 峰：峰频/ω̂ 相对差与模拟零分布 p 值。null_model ∈ {"ar1", "ar1_t5"}。"""
    tc, m, w_hat = float(theta[0]), float(theta[1]), float(theta[2])
    dtt = np.maximum(np.abs(tc - t), MIN_DT)
    f = dtt**m
    r = (y - beta[0] - beta[1] * f) / f
    x = np.log(dtt)
    w_peak, pk = _lomb_peak(x, r)
    phi, sig = _ar1_params(r)
    rng = np.random.default_rng(seed + 104729)
    sims = _simulate_ar1(len(r), phi, sig, rng, null_model == "ar1_t5", n_sim)
    peaks = np.array([_lomb_peak(x, sims[i])[1] for i in range(n_sim)])
    p = float((1 + np.sum(peaks >= pk)) / (n_sim + 1))
    rel = float(abs(w_peak - w_hat) / max(abs(w_hat), 1e-9))
    return dict(w_peak=w_peak, peak=pk, p=p, rel_dw=rel, freq_ok=bool(rel <= tol), phi=phi, null_model=null_model, n_sim=n_sim)


def q2_pass(lr: dict, lomb: dict, alpha_lr: float, alpha_l: float) -> bool:
    return bool(lr["p"] <= alpha_lr and lomb["freq_ok"] and lomb["p"] <= alpha_l)
