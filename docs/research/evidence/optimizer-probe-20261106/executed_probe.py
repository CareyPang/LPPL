"""Bounded synthetic optimizer probe; no market data, labels, or production changes.

Runs the repository optimizers with equal work/time ceilings and instrumented
objective/residual/grid calls. This is a numerical diagnostic, not a backtest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import time
from pathlib import Path

for variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[variable] = "1"

import numpy as np  # noqa: E402
import scipy  # noqa: E402
from threadpoolctl import threadpool_info, threadpool_limits  # noqa: E402

from research.lppls import core  # noqa: E402
from research.optim import optimizers as optim  # noqa: E402


class BudgetStop(Exception):
    pass


def cases():
    definitions = [
        ("clean_future", 125, [136.0, .5, 8.5], [5., -.03, .003, .002], 0., 0., False),
        ("iid_future", 250, [267., .6, 9.], [5., -.03, .003, .002], .01, 0., False),
        ("weak_ar1_future", 250, [275., .45, 10.], [5., -.03, .00015, .0001], .015, .6, False),
        ("inside_descriptive", 250, [239.25, .55, 8.5], [5., -.03, .003, .002], .005, 0., True),
    ]
    output = []
    for i, (name, n, theta, beta, sigma, rho, inside) in enumerate(definitions):
        t = np.arange(n, dtype=float)
        noise = np.random.default_rng(20261106 + i).normal(0, sigma, n)
        if rho:
            for j in range(1, n):
                noise[j] += rho * noise[j - 1]
        y = core.design(t, *theta, allow_inside=inside) @ np.asarray(beta) + noise
        output.append(dict(name=name, t=t.tolist(), y=y.tolist(), theta=theta, beta=beta,
                           noise_sigma=sigma, noise_ar1=rho, inside=inside,
                           data_seed=20261106 + i))
    return output


def fit_case(case, method, seed, work_cap=6000, seconds_cap=3.):
    t, y = np.array(case["t"]), np.array(case["y"])
    n = len(t)
    lo = np.array([n - 1 - .2 * (n - 1) if case["inside"] else n - .5, .01, 1.])
    hi = np.array([n - 1 + .2 * (n - 1), 2., 50.])
    original = optim._objective, optim._resid, optim.grid_profile
    old_inside = core.ALLOW_INSIDE
    core.ALLOW_INSIDE = case["inside"]
    count = {"objective": 0, "residual": 0, "grid_points": 0}
    best = [float("inf"), None]
    start, cpu_start = time.perf_counter(), time.process_time()

    def check(cost=1):
        if sum(count.values()) + cost > work_cap:
            raise BudgetStop("work_cap")
        if time.perf_counter() - start >= seconds_cap:
            raise BudgetStop("wall_cap")

    def remember(theta, value):
        if np.isfinite(value) and value < best[0]:
            best[:] = [float(value), np.asarray(theta).copy()]

    def objective(theta, *args, **kwargs):
        check()
        count["objective"] += 1
        value = original[0](theta, *args, **kwargs)
        remember(theta, value)
        return value

    def residual(theta, *args, **kwargs):
        check()
        count["residual"] += 1
        value = original[1](theta, *args, **kwargs)
        remember(theta, value @ value)
        return value

    def grid(t, y, tcs, ms, ws, k=core.K_LPPLS):
        cost = len(tcs) * len(ms) * len(ws)
        check(cost)
        count["grid_points"] += cost
        values = original[2](t, y, tcs, ms, ws, k)
        i, j, l = np.unravel_index(np.argmin(values), values.shape)
        remember([tcs[i], ms[j], ws[l]], values[i, j, l])
        return values

    optim._objective, optim._resid, optim.grid_profile = objective, residual, grid
    reported_nfev, returned_theta, returned_sse, message = None, None, None, None
    status = "returned"
    try:
        if method == "de_lbfgsb":
            result = optim.de_lbfgsb(t, y, lo, hi, seed=seed,
                                     budget={"popsize": 10, "maxiter": 120})
        else:
            result = optim.tcgrid_lm(t, y, lo, hi, seed=seed,
                                     budget={"n_tc": 20, "n_m": 8, "n_w": 10, "topk": 5},
                                     n_random=3)
        reported_nfev, message = result.nfev, result.message
        returned_theta, returned_sse = result.theta.tolist(), result.sse
    except BudgetStop as exc:
        status = str(exc)
    except Exception as exc:
        status, message = "error", type(exc).__name__ + ": " + str(exc)
    finally:
        wall, cpu = time.perf_counter() - start, time.process_time() - cpu_start
        optim._objective, optim._resid, optim.grid_profile = original
        core.ALLOW_INSIDE = old_inside
    theta = returned_theta if returned_theta is not None else best[1].tolist() if best[1] is not None else None
    audited_sse = None
    if theta is not None:
        old = core.ALLOW_INSIDE
        core.ALLOW_INSIDE = case["inside"]
        audited_sse = core.lin_fit(t, y, *theta)[0]
        core.ALLOW_INSIDE = old
    return dict(case=case["name"], method=method, seed=seed, status=status, message=message,
                domain="inside_descriptive" if case["inside"] else "future_only",
                bounds=[lo.tolist(), hi.tolist()], work_cap=work_cap, seconds_cap=seconds_cap,
                calls=count, actual_work=sum(count.values()), reported_nfev=reported_nfev,
                seconds=wall, cpu_seconds=cpu, theta=theta, returned_sse=returned_sse,
                audited_sse=audited_sse,
                tc_absolute_error=None if theta is None else abs(theta[0] - case["theta"][0]),
                near_boundary=None if theta is None else bool(np.any(
                    np.minimum((np.array(theta)-lo)/(hi-lo), (hi-np.array(theta))/(hi-lo)) < 1e-3)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if any(args.out.iterdir()):
        raise SystemExit("Output must be empty; preserve previous evidence.")
    synthetic = cases()
    inputs = json.dumps(synthetic, ensure_ascii=False, indent=2).encode()
    (args.out / "inputs.json").write_bytes(inputs)
    result = {"purpose": "synthetic numerical diagnostic; not market forecast validation",
              "input_sha256": hashlib.sha256(inputs).hexdigest(),
              "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
              "system": platform.platform(), "processor": platform.processor(),
              "optimizer_sha256": hashlib.sha256(Path(optim.__file__).read_bytes()).hexdigest(),
              "core_sha256": hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest(),
              "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "seeds": [0, 1, 2], "rows": []}
    with threadpool_limits(limits=1):
        result["threadpools"] = threadpool_info()
        start = time.perf_counter()
        for case in synthetic:
            for seed in result["seeds"]:
                # Alternate execution order to avoid always giving one method cold caches.
                methods = ["de_lbfgsb", "tcgrid_lm"] if seed % 2 == 0 else ["tcgrid_lm", "de_lbfgsb"]
                for method in methods:
                    row = fit_case(case, method, seed)
                    result["rows"].append(row)
                    print(case["name"], method, seed, row["status"], round(row["seconds"], 3), flush=True)
        result["total_seconds"] = time.perf_counter() - start
    (args.out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
