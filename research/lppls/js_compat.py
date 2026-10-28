"""JavaScript engine bounds, derived fields, and filter semantics."""
from __future__ import annotations

import math
import time

import numpy as np

from ..optim.optimizers import METHODS
from .core import lin_fit


def _value(f, key):
    if isinstance(f, dict):
        return f[key]
    if hasattr(f, key):
        return getattr(f, key)
    if key == "ahead":
        return f.tc - (f.n - 1)
    if key == "O":
        return f.n_osc()
    if key == "D":
        return f.damping
    if key == "R2":
        return f.r2
    return getattr(f, key)


def JS_DS(f) -> bool:
    return (
        _value(f, "B") < 0
        and _value(f, "m") >= 0.01
        and _value(f, "m") <= 0.99
        and _value(f, "w") >= 2
        and _value(f, "w") <= 15
        and _value(f, "ahead") <= max(5, 0.1 * _value(f, "n"))
        and _value(f, "O") >= 2.5
        and _value(f, "D") >= 0.5
    )


def JS_STRICT(f) -> bool:
    return (
        _value(f, "B") < 0
        and _value(f, "m") > 0.1
        and _value(f, "m") < 0.9
        and _value(f, "w") > 6
        and _value(f, "w") < 13
        and _value(f, "ahead") <= 90
        and _value(f, "O") >= 2.5
        and _value(f, "D") >= 1
        and _value(f, "R2") >= 0.9
    )


JS_FILTERS = {"ds": JS_DS, "strict": JS_STRICT}


def derived(theta, beta, sse: float, sst: float, n: int) -> dict[str, float]:
    tc, m, w = map(float, theta)
    _, B, C1, C2 = map(float, beta)
    t2 = n - 1
    amplitude = math.hypot(C1, C2)
    damping = m * abs(B) / (w * amplitude) if amplitude > 0 else math.inf
    oscillations = (w / (2 * math.pi)) * math.log(tc / (tc - t2))
    r2 = 1 - sse / sst if sst > 0 else 0.0
    return {"D": damping, "O": oscillations, "R2": r2, "ahead": tc - t2}


def _js_truthy(value) -> bool:
    return value is not None and value is not False and value != 0 and value != ""


def js_bounds(n: int, opt: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    opt = opt or {}
    t2 = n - 1
    raw_ahead = opt.get("aheadHi")
    if _js_truthy(raw_ahead):
        max_ahead = raw_ahead
    else:
        max_ahead = min(252, max(20, math.floor(0.3 * n + 0.5)))
    ahead_lo = opt["aheadLo"] if "aheadLo" in opt else 0.5
    if ahead_lo is None:
        ahead_lo = 0.0
    m_lo = opt.get("mLo") if _js_truthy(opt.get("mLo")) else 0.01
    m_hi = opt.get("mHi") if _js_truthy(opt.get("mHi")) else 0.99
    w_lo = opt.get("wLo") if _js_truthy(opt.get("wLo")) else 2.0
    w_hi = opt.get("wHi") if _js_truthy(opt.get("wHi")) else 25.0
    lo = np.array([t2 + ahead_lo, m_lo, w_lo], dtype=float)
    hi = np.array([t2 + max_ahead, m_hi, w_hi], dtype=float)
    return lo, hi


def fit_window(
    y,
    opt: dict | None,
    method: str = "de_lbfgsb",
    seed: int = 0,
    budget: dict | None = None,
    power_budget: dict | None = None,
) -> dict:
    y = np.asarray(y, dtype=float)
    n = len(y)
    t = np.arange(n, dtype=float)
    opt = opt or {}
    lo, hi = js_bounds(n, opt)
    if method not in METHODS:
        raise ValueError(f"Unknown optimizer: {method}")

    started = time.perf_counter()
    result = METHODS[method](t, y, lo, hi, seed=seed, budget=budget)
    tc, m, w = map(float, result.theta)
    sse, beta = lin_fit(t, y, tc, m, w)
    sst = float(np.sum((y - np.mean(y)) ** 2))
    stats = derived(result.theta, beta, sse, sst, n)
    fit = {
        "n": n,
        "tc": tc,
        "ahead": stats["ahead"],
        "m": m,
        "w": w,
        "A": float(beta[0]),
        "B": float(beta[1]),
        "C1": float(beta[2]),
        "C2": float(beta[3]),
        "D": stats["D"],
        "O": stats["O"],
        "R2": stats["R2"],
        "sse": float(sse),
        "ds": False,
        "strict": False,
        "method": method,
        "nfev": int(result.nfev),
        "seconds": float(result.seconds),
        "theta": [tc, m, w],
        "beta": list(map(float, beta)),
    }
    fit["ds"] = JS_DS(fit)
    fit["strict"] = JS_STRICT(fit)

    if opt.get("power") is not False:
        power_started = time.perf_counter()
        power_lo = np.array([lo[0], 0.01], dtype=float)
        power_hi = np.array([hi[0], 0.99], dtype=float)
        power = METHODS[method](
            t,
            y,
            power_lo,
            power_hi,
            seed=seed,
            budget=power_budget if power_budget is not None else budget,
            k=2,
        )
        sse_pow = max(float(power.sse), float(sse))
        nu = max(1, n - 7)
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            f_stat = float(((sse_pow - sse) / 2) / (sse / nu))
            p_f = float(np.power(1 + (2 * f_stat) / nu, -nu / 2))
        fit.update(
            ssePow=sse_pow,
            Fstat=f_stat,
            pF=p_f,
            power_method=method,
            power_nfev=int(power.nfev),
            power_seconds=float(time.perf_counter() - power_started),
        )

    fit["total_seconds"] = float(time.perf_counter() - started)
    return fit
