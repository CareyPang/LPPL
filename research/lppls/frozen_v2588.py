"""Frozen numerical LPPLS kernel extracted from the audited user research.

Original math AST (Xmat/lin/fit_one):
ac00580978ed58cc57a5a1a5c07b69846d5516ec7499722ea46f6d49fc715c01.
No archive paths, data fetching or execution side effects. The legacy strict_pass
field retains 2.5 full cycles; research aggregation separately evaluates 1.5.
"""
# Preserve the audited numerical AST, including its legacy exception and zip semantics.
# ruff: noqa: E722, B905
import math

import numpy as np
from scipy.optimize import differential_evolution, minimize

from ..pipeline.long_horizon import DE as DE_CONFIG
from ..pipeline.long_horizon import LB as LBFGS_CONFIG


def Xmat(t, tc, m, w):
    tau = tc - t
    if np.any(tau <= 0):
        raise ValueError('nonpositive tau')
    p = np.power(tau, m)
    ph = w * np.log(tau)
    return np.column_stack((np.ones_like(t), p, p * np.cos(ph), p * np.sin(ph)))

def lin(t, y, tc, m, w):
    X = Xmat(t, tc, m, w)
    beta, _, rank, sv = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    sse = float(res @ res)
    cond = float(sv[0] / sv[-1]) if len(sv) and sv[-1] > 0 else float('inf')
    return {'beta': beta, 'rank': int(rank), 'sv': sv, 'sse': sse, 'condition': cond}

def fit_one(y, seed):
    n = len(y)
    t = np.arange(n, dtype=float)
    bounds = [(float(n), float(n + 89)), (0.1, 0.9), (6.0, 13.0)]

    def obj(z):
        try:
            return lin(t, y, float(z[0]), float(z[1]), float(z[2]))['sse']
        except:
            return 1e+100
    de = differential_evolution(obj, bounds=bounds, strategy=DE_CONFIG['strategy'], popsize=25, maxiter=1500, tol=1e-08, atol=0.0, mutation=DE_CONFIG['mutation'], recombination=0.7, seed=int(seed), workers=1, updating='deferred', polish=False)
    try:
        lb = minimize(obj, de.x, method='L-BFGS-B', bounds=bounds, options=LBFGS_CONFIG)
        lbe = None
    except Exception as e:
        lb = None
        lbe = repr(e)
    z = np.asarray(de.x, dtype=float)
    s = float(de.fun)
    if lb is not None and np.all(np.isfinite(lb.x)) and np.isfinite(lb.fun) and (lb.fun <= s):
        z = np.asarray(lb.x)
        s = float(lb.fun)
    q = lin(t, y, *z)
    b = q['beta']
    sst = float((y - y.mean()) @ (y - y.mean()))
    r2 = 1 - q['sse'] / sst if sst > 0 else float('nan')
    amp = float(math.hypot(b[2], b[3]))
    damp = float(z[1] * abs(b[1]) / (z[2] * amp)) if amp > 0 else float('nan')
    nosc = float(z[2] / (2 * math.pi) * math.log(z[0] / (z[0] - (n - 1))))
    bd = []
    for nm, v, (lo, hi) in zip(('tc', 'm', 'omega'), z, bounds):
        if abs(v - lo) < 1e-06:
            bd.append(nm + '_LOW')
        if abs(v - hi) < 1e-06:
            bd.append(nm + '_HIGH')
    lgood = bool(lb is not None and lb.success)
    ok = bool(de.success and lgood)
    strict = bool(ok and 0.1 < z[1] < 0.9 and (6 < z[2] < 13) and (b[1] < 0) and (damp >= 1) and (nosc >= 2.5) and (r2 >= 0.9) and (q['rank'] >= 4) and (q['condition'] <= 1 / math.sqrt(np.finfo(float).eps)))
    return {'x': z, 'beta': b, 'sse': q['sse'], 'r2': r2, 'damping': damp, 'nosc': nosc, 'rank': q['rank'], 'condition': q['condition'], 'strict_pass': strict, 'optimizer_success': ok, 'boundary_status': '|'.join(bd) if bd else 'INTERIOR', 'de': {'success': bool(de.success), 'message': str(de.message), 'fun': float(de.fun), 'nit': int(getattr(de, 'nit', -1)), 'nfev': int(getattr(de, 'nfev', -1)), 'x': np.asarray(de.x).tolist(), 'population': np.asarray(getattr(de, 'population', [])).tolist(), 'population_energies': np.asarray(getattr(de, 'population_energies', [])).tolist()}, 'lbfgs': {'success': lgood, 'message': str(lb.message) if lb is not None else lbe, 'fun': float(lb.fun) if lb is not None and np.isfinite(lb.fun) else None, 'nit': int(getattr(lb, 'nit', -1)) if lb is not None else -1, 'nfev': int(getattr(lb, 'nfev', -1)) if lb is not None else -1, 'x': np.asarray(lb.x).tolist() if lb is not None else None}, 'de_config': DE_CONFIG, 'lbfgs_config': LBFGS_CONFIG, 'linear_solver': 'numpy.linalg.lstsq SVD-backed'}

def profile_fit(y, tc, seed):
    n = len(y)
    t = np.arange(n, dtype=float)
    bounds = [(0.1, 0.9), (6.0, 13.0)]

    def obj(z):
        try:
            return lin(t, y, tc, float(z[0]), float(z[1]))['sse']
        except:
            return 1e+100
    de = differential_evolution(obj, bounds=bounds, strategy='best1bin', popsize=25, maxiter=1500, tol=1e-08, atol=0.0, mutation=(0.5, 1.0), recombination=0.7, seed=int(seed), workers=1, updating='deferred', polish=False)
    lb = minimize(obj, de.x, method='L-BFGS-B', bounds=bounds, options=LBFGS_CONFIG)
    z = np.asarray(lb.x if np.isfinite(lb.fun) and lb.fun <= de.fun else de.x, dtype=float)
    return {'m': float(z[0]), 'omega': float(z[1]), 'sse': float(min(de.fun, lb.fun)), 'de_success': bool(de.success), 'lbfgs_success': bool(lb.success), 'de_nfev': int(getattr(de, 'nfev', -1)), 'de_nit': int(getattr(de, 'nit', -1)), 'population': np.asarray(getattr(de, 'population', [])).tolist(), 'population_energies': np.asarray(getattr(de, 'population_energies', [])).tolist(), 'config': {'de': DE_CONFIG, 'lbfgs': LBFGS_CONFIG}}
