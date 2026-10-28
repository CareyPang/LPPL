"""Numerical parity checks between the browser engine and the Python core.

Run with ``python -m research.lppls.parity``. Node is used only as a local
subprocess; the harness itself has no npm dependencies.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.cache import load
from ..optim.optimizers import METHODS
from ..synth.lppls_synth import sample
from .core import lin_fit
from .js_compat import JS_DS, JS_STRICT, derived, fit_window, js_bounds

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "tools" / "js_parity" / "harness.js"
REPORTS = ROOT / "reports"
ANALYZE_OPT = {"pop": 24, "gens": 45, "nm": 120, "keepWS": False}
CRITICAL_TOP_OPT = {
    "pop": 18,
    "gens": 28,
    "nm": 50,
    "power": False,
    "aheadLo": 1,
    "aheadHi": 120,
    "mLo": 0.05,
    "mHi": 0.99,
    "wLo": 3,
    "wHi": 16,
}
SYNTHETIC_NS = (60, 125, 250, 500, 700)
NOISES = ("iid", "ar1")
SIGMAS = (0.01, 0.03)
SYNTHETIC_SEEDS = (0, 1, 2)
REAL_DATES = (
    "2007-12-28",
    "2009-10-30",
    "2011-10-28",
    "2013-12-31",
    "2015-06-12",
    "2017-12-29",
    "2019-12-31",
    "2021-12-31",
    "2023-12-29",
    "2025-10-24",
)
REAL_WINDOW_SIZES = (125, 250, 500, 700)
METHOD_BUDGETS = {
    "de_lbfgsb": {"popsize": 8, "maxiter": 30},
    "ms_lm": {"starts": 4},
    "tcgrid_lm": {"n_tc": 20, "n_m": 10, "n_w": 12, "topk": 3},
    "cmaes": {"maxfevals": 600, "restarts": 0},
}


@dataclass
class Case:
    case_id: str
    kind: str
    y: np.ndarray
    details: dict

    @property
    def n(self) -> int:
        return len(self.y)


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js is required for parity; put node on PATH and retry.")
    return node


def run_harness(job: dict) -> dict:
    completed = subprocess.run(
        [_node(), str(HARNESS)],
        input=json.dumps(job, separators=(",", ":"), allow_nan=False),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"Node parity harness failed ({completed.returncode}):\n{completed.stderr}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from Node harness: {completed.stdout[:500]}") from exc


def _engine_windows() -> tuple[int, ...]:
    source = (ROOT / "web" / "app" / "engine.js").read_text()
    match = re.search(r"OD\.WINDOWS\s*=\s*\[([^\]]+)\]", source)
    if match is None:
        raise RuntimeError("Could not read OD.WINDOWS from web/app/engine.js")
    return tuple(int(value.strip()) for value in match.group(1).split(","))


def make_cases(include_real: bool = True) -> list[Case]:
    cases = []
    for n in SYNTHETIC_NS:
        for noise in NOISES:
            for sigma in SIGMAS:
                for seed in SYNTHETIC_SEEDS:
                    _, y, truth = sample(n=n, sigma=sigma, noise=noise, seed=seed)
                    cases.append(
                        Case(
                            f"synth_n{n}_{noise}_s{sigma:g}_seed{seed}",
                            "synthetic",
                            y,
                            {
                                "n": n,
                                "noise": noise,
                                "sigma": sigma,
                                "sample_seed": seed,
                                "truth_tc": float(truth.tc),
                                "truth_m": float(truth.m),
                                "truth_w": float(truth.w),
                            },
                        )
                    )

    if not include_real:
        return cases

    frame = load("sh000001", frozen="v20261024").reset_index(drop=True)
    dates = frame["date"].to_numpy(dtype="datetime64[ns]")
    closes = frame["close"].to_numpy(dtype=float)
    windows = set(_engine_windows())
    for requested_date in REAL_DATES:
        end = int(np.searchsorted(dates, np.datetime64(requested_date), side="right") - 1)
        if end < 0:
            continue
        actual_date = pd.Timestamp(frame.loc[end, "date"]).strftime("%Y-%m-%d")
        for n in REAL_WINDOW_SIZES:
            if n not in windows or end + 1 < n:
                continue
            y = np.log(closes[end + 1 - n : end + 1])
            cases.append(
                Case(
                    f"real_{actual_date}_n{n}",
                    "real",
                    y,
                    {"requested_date": requested_date, "actual_date": actual_date, "n": n},
                )
            )
    return cases


def fixed_theta_check(y, case_seed: int = 0, n_random: int = 200) -> dict:
    y = np.asarray(y, dtype=float)
    n = len(y)
    lo, hi = js_bounds(n, ANALYZE_OPT)
    rng = np.random.default_rng(case_seed)
    thetas = rng.uniform(lo, hi, size=(n_random, 3))
    tests = [
        {"tc": float(tc), "m": float(m), "w": float(w), "k": 4}
        for tc, m, w in thetas
    ]
    for offset in (0.0, 0.25, 2.0, 10.0):
        tc = n - 1 - offset
        tests.append({"tc": tc, "m": 0.5, "w": 8.0, "k": 4})
    job = {
        "type": "linfit",
        "cases": [{"y": y.tolist(), **test} for test in tests],
    }
    js_results = run_harness(job)["results"]
    t = np.arange(n, dtype=float)
    rel_sse = []
    rel_beta = []
    infeasible_agree = []
    for test, js in zip(tests, js_results, strict=True):
        py_sse, py_beta = lin_fit(t, y, test["tc"], test["m"], test["w"], test["k"])
        js_sse = js["sse"]
        js_infeasible = js_sse is None
        py_infeasible = not np.isfinite(py_sse) or py_beta is None
        infeasible_agree.append(js_infeasible == py_infeasible)
        if js_infeasible or py_infeasible:
            continue
        denom = max(abs(js_sse), 1e-300)
        if max(abs(js_sse), abs(py_sse)) > 1e-14:
            rel_sse.append(abs(js_sse - py_sse) / denom)
        js_beta = np.asarray(js["beta"], dtype=float)
        py_beta = np.asarray(py_beta, dtype=float)
        beta_denom = max(np.linalg.norm(js_beta), 1e-300)
        rel_beta.append(float(np.linalg.norm(js_beta - py_beta) / beta_denom))
    return {
        "points": len(tests),
        "finite_points": len(rel_sse),
        "max_relative_sse": max(rel_sse, default=0.0),
        "max_relative_beta": max(rel_beta, default=0.0),
        "infeasible_agreement": (
            sum(infeasible_agree) / len(infeasible_agree) if infeasible_agree else 1.0
        ),
        "infeasible_points": sum(
            js["sse"] is None for js in js_results
        ),
    }


def derived_check(y, js_fit: dict) -> dict:
    y = np.asarray(y, dtype=float)
    n = len(y)
    t = np.arange(n, dtype=float)
    theta = (js_fit["tc"], js_fit["m"], js_fit["w"])
    py_sse, beta = lin_fit(t, y, *theta)
    sst = float(np.sum((y - np.mean(y)) ** 2))
    py_derived = derived(theta, beta, py_sse, sst, n)
    py_fit = {
        **py_derived,
        "n": n,
        "B": float(beta[1]),
        "m": float(theta[1]),
        "w": float(theta[2]),
    }
    rel = {}
    for key in ("D", "O", "R2"):
        js_value = js_fit.get(key)
        py_value = py_derived[key]
        if js_value is None or not math.isfinite(float(js_value)) or not math.isfinite(py_value):
            rel[key] = 0.0 if js_value is None and not math.isfinite(py_value) else math.inf
        else:
            rel[key] = abs(float(js_value) - py_value) / max(abs(float(js_value)), 1e-300)
    ds = JS_DS(py_fit)
    strict = JS_STRICT(py_fit)
    return {
        "relative_errors": rel,
        "max_relative_error": max(rel.values(), default=0.0),
        "ds_agreement": ds == bool(js_fit["ds"]),
        "strict_agreement": strict == bool(js_fit["strict"]),
        "python_ds": ds,
        "python_strict": strict,
    }


def _safe_float(value):
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _quantile(values, q):
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return float(np.quantile(finite, q)) if finite else None


def _markdown_table(rows: list[dict], columns: list[tuple[str, str]], digits: int = 4) -> str:
    if not rows:
        return "_No rows._"
    header = "| " + " | ".join(label for _, label in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, divider]
    for row in rows:
        values = []
        for key, _ in columns:
            value = row.get(key)
            if isinstance(value, (float, np.floating)):
                values.append(f"{value:.{digits}g}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def run_full_parity(cases: list[Case] | None = None) -> dict:
    cases = cases or make_cases()
    fixed_rows = []
    fit_rows = []
    derived_rows = []
    nm_worse = []

    for case_index, case in enumerate(cases):
        fixed = fixed_theta_check(case.y, case_seed=1009 + case_index, n_random=200)
        fixed_rows.append({"case_id": case.case_id, "kind": case.kind, "n": case.n, **fixed})

        job = {
            "type": "fitwindow",
            "cases": [
                {"y": case.y.tolist(), "opt": ANALYZE_OPT, "seed": seed}
                for seed in range(3)
            ],
        }
        js_fits = run_harness(job)["results"]
        for seed, js_fit in enumerate(js_fits):
            if seed == 0:
                derived_result = derived_check(case.y, js_fit)
                derived_rows.append(
                    {"case_id": case.case_id, "kind": case.kind, **derived_result}
                )
            js_sse = js_fit.get("sse")
            if js_fit.get("_nmSse") is not None and js_fit.get("_deSse") is not None:
                de_sse = float(js_fit["_deSse"])
                nm_sse = float(js_fit["_nmSse"])
                if nm_sse > de_sse * (1 + 1e-6):
                    nm_worse.append(
                        {
                            "case_id": case.case_id,
                            "seed": seed,
                            "de_sse": de_sse,
                            "nm_sse": nm_sse,
                            "nm_relative_increase": nm_sse / max(de_sse, 1e-300) - 1,
                        }
                    )
            if js_sse is None or not math.isfinite(float(js_sse)):
                continue
            for method in METHODS:
                started = time.perf_counter()
                py_fit = fit_window(
                    case.y,
                    ANALYZE_OPT,
                    method=method,
                    seed=seed,
                    budget=METHOD_BUDGETS[method],
                )
                py_seconds = time.perf_counter() - started
                ratio = float(py_fit["sse"]) / float(js_sse)
                fit_rows.append(
                    {
                        "case_id": case.case_id,
                        "kind": case.kind,
                        "seed": seed,
                        "method": method,
                        "ratio": ratio,
                        "ratio_delta": ratio - 1,
                        "abs_tc": abs(float(py_fit["tc"]) - float(js_fit["tc"])),
                        "abs_m": abs(float(py_fit["m"]) - float(js_fit["m"])),
                        "abs_w": abs(float(py_fit["w"]) - float(js_fit["w"])),
                        "ds_agreement": py_fit["ds"] == bool(js_fit["ds"]),
                        "strict_agreement": py_fit["strict"] == bool(js_fit["strict"]),
                        "js_seconds": _safe_float(js_fit.get("seconds")),
                        "python_seconds": float(py_seconds),
                        "python_sse": float(py_fit["sse"]),
                        "js_sse": float(js_sse),
                    }
                )
        print(f"parity {case_index + 1}/{len(cases)} {case.case_id}", flush=True)

    best_by_js = {}
    for row in fit_rows:
        key = (row["case_id"], row["seed"])
        if key not in best_by_js or row["ratio"] < best_by_js[key]["ratio"]:
            best_by_js[key] = row

    fixed_groups = []
    for kind in ("synthetic", "real"):
        subset = [row for row in fixed_rows if row["kind"] == kind]
        if subset:
            fixed_groups.append(
                {
                    "kind": kind,
                    "cases": len(subset),
                    "points": sum(row["points"] for row in subset),
                    "max_relative_sse": max(row["max_relative_sse"] for row in subset),
                    "max_relative_beta": max(row["max_relative_beta"] for row in subset),
                    "infeasible_agreement": min(row["infeasible_agreement"] for row in subset),
                }
            )

    fit_summaries = []
    for method in METHODS:
        subset = [row for row in fit_rows if row["method"] == method]
        fit_summaries.append(
            {
                "method": method,
                "count": len(subset),
                "median_ratio": _quantile([row["ratio"] for row in subset], 0.5),
                "p10_ratio": _quantile([row["ratio"] for row in subset], 0.1),
                "p90_ratio": _quantile([row["ratio"] for row in subset], 0.9),
                "median_ratio_delta": _quantile([row["ratio_delta"] for row in subset], 0.5),
                "p10_ratio_delta": _quantile([row["ratio_delta"] for row in subset], 0.1),
                "p90_ratio_delta": _quantile([row["ratio_delta"] for row in subset], 0.9),
                "median_abs_tc": _quantile([row["abs_tc"] for row in subset], 0.5),
                "median_abs_m": _quantile([row["abs_m"] for row in subset], 0.5),
                "median_abs_w": _quantile([row["abs_w"] for row in subset], 0.5),
                "ds_agreement": (
                    sum(row["ds_agreement"] for row in subset) / len(subset) if subset else 1.0
                ),
                "strict_agreement": (
                    sum(row["strict_agreement"] for row in subset) / len(subset) if subset else 1.0
                ),
                "median_js_seconds": _quantile([row["js_seconds"] for row in subset], 0.5),
                "median_python_seconds": _quantile([row["python_seconds"] for row in subset], 0.5),
            }
        )

    best_summary = {
        "count": len(best_by_js),
        "median_ratio": _quantile([row["ratio"] for row in best_by_js.values()], 0.5),
        "median_ratio_delta": _quantile(
            [row["ratio_delta"] for row in best_by_js.values()], 0.5
        ),
        "p90_ratio": _quantile([row["ratio"] for row in best_by_js.values()], 0.9),
        "threshold_pass": bool(best_by_js) and _quantile(
            [row["ratio"] for row in best_by_js.values()], 0.5
        ) <= 1 + 1e-6,
    }
    derived_summary = {
        "count": len(derived_rows),
        "max_relative_error": max(
            (row["max_relative_error"] for row in derived_rows), default=0.0
        ),
        "ds_agreement": (
            sum(row["ds_agreement"] for row in derived_rows) / len(derived_rows)
            if derived_rows
            else 1.0
        ),
        "strict_agreement": (
            sum(row["strict_agreement"] for row in derived_rows) / len(derived_rows)
            if derived_rows
            else 1.0
        ),
        "threshold_pass": all(
            row["max_relative_error"] < 1e-8
            and row["ds_agreement"]
            and row["strict_agreement"]
            for row in derived_rows
        ),
    }

    report = {
        "metadata": {
            "analyze_opt": ANALYZE_OPT,
            "critical_top_opt": CRITICAL_TOP_OPT,
            "synthetic_cases": sum(case.kind == "synthetic" for case in cases),
            "real_cases": sum(case.kind == "real" for case in cases),
            "case_count": len(cases),
            "methods": list(METHODS),
            "method_budgets": METHOD_BUDGETS,
        },
        "fixed_theta": {
            "groups": fixed_groups,
            "cases": fixed_rows,
            "pass": all(
                row["max_relative_sse"] < 1e-8 and row["infeasible_agreement"] == 1
                for row in fixed_rows
            ),
        },
        "derived_filters": {
            "summary": derived_summary,
            "cases": derived_rows,
        },
        "full_fit": {
            "methods": fit_summaries,
            "best_method": best_summary,
            "comparisons": fit_rows,
            "js_nm_worse_than_de": nm_worse,
        },
    }

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "js_parity.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )
    (REPORTS / "js_parity.md").write_text(render_report(report))
    return report


def render_report(report: dict) -> str:
    metadata = report["metadata"]
    fixed = report["fixed_theta"]
    derived_summary = report["derived_filters"]["summary"]
    full = report["full_fit"]
    lines = [
        "# JavaScript / Python LPPLS numerical parity",
        "",
        f"- Cases: {metadata['case_count']} total "
        f"({metadata['synthetic_cases']} synthetic, {metadata['real_cases']} frozen-index windows).",
        f"- Analyze fit options: `{json.dumps(metadata['analyze_opt'], sort_keys=True)}`; "
        "because `power` is not false, the browser also fits the nested power model.",
        f"- Critical top-scan options: `{json.dumps(metadata['critical_top_opt'], sort_keys=True)}` "
        "(the top rule is declared at `web/app/critical.js:90`, with executable comparisons "
        "at lines 91–92; Python `TOP_RULE` is `research/lppls/core.py:91`, and the same "
        "criteria are documented at `web/review.html:237`).",
        "- `TOP_RULE` mirrors the critical top scan; it is intentionally distinct from the "
        "browser engine's `OD.FILTERS.ds` / `OD.FILTERS.strict` gates.",
        "- Real data: `sh000001`, frozen vintage `v20261024`, log-close windows.",
        "- JavaScript bounds follow `fitWindow`; random fixed-parameter checks use 200 feasible "
        "points and four infeasible `tc <= n-1` points per case.",
        "",
        "## A. Fixed-parameter linear fit",
        "",
        _markdown_table(
            fixed["groups"],
            [
                ("kind", "Case type"),
                ("cases", "Cases"),
                ("points", "θ points"),
                ("max_relative_sse", "Max relative SSE Δ"),
                ("max_relative_beta", "Max relative β Δ"),
                ("infeasible_agreement", "Infeasible agreement"),
            ],
        ),
        "",
        "Per-case fixed-θ maxima:",
        "",
        _markdown_table(
            fixed["cases"],
            [
                ("case_id", "Case"),
                ("n", "n"),
                ("points", "θ points"),
                ("max_relative_sse", "Max relative SSE Δ"),
                ("max_relative_beta", "Max relative β Δ"),
                ("infeasible_agreement", "Infeasible agreement"),
            ],
            digits=3,
        ),
        "",
        f"Overall pass: **{fixed['pass']}** (SSE relative error < 1e-8 when non-tiny; "
        "infeasible / `None` agreement 100%).",
        "",
        "## B. Derived values and browser filters at the JavaScript optimum",
        "",
        _markdown_table(
            [derived_summary],
            [
                ("count", "Cases"),
                ("max_relative_error", "Max relative Δ across D/O/R²"),
                ("ds_agreement", "DS agreement"),
                ("strict_agreement", "Strict agreement"),
                ("threshold_pass", "Pass"),
            ],
        ),
        "",
        "Relative differences compare Python `lin_fit` plus the JavaScript formulas for D, O, "
        "and R² against the browser fit result.",
        "",
        "## C. Full optimization comparison",
        "",
        _markdown_table(
            full["methods"],
            [
                ("method", "Python optimizer"),
                ("count", "Comparisons"),
                ("median_ratio_delta", "Median SSE ratio−1"),
                ("p10_ratio_delta", "P10 ratio−1"),
                ("p90_ratio_delta", "P90 ratio−1"),
                ("median_abs_tc", "Median |Δtc|"),
                ("median_abs_m", "Median |Δm|"),
                ("median_abs_w", "Median |Δw|"),
                ("ds_agreement", "DS agreement"),
                ("strict_agreement", "Strict agreement"),
                ("median_js_seconds", "Median JS sec"),
                ("median_python_seconds", "Median Python sec"),
            ],
        ),
        "",
        f"Best Python method per JS fit: median SSE ratio "
        f"`{full['best_method']['median_ratio']}` over {full['best_method']['count']} fits; "
        f"required ≤ 1 + 1e-6: **{full['best_method']['threshold_pass']}**.",
        "",
        f"JavaScript Nelder–Mead candidate worse than the DE candidate in "
        f"{len(full['js_nm_worse_than_de'])} fits.",
        "",
    ]
    if full["js_nm_worse_than_de"]:
        lines.extend(
            [
                _markdown_table(
                    full["js_nm_worse_than_de"][:20],
                    [
                        ("case_id", "Case"),
                        ("seed", "Seed"),
                        ("de_sse", "DE SSE"),
                        ("nm_sse", "NM SSE"),
                        ("nm_relative_increase", "NM relative increase"),
                    ],
                ),
                "",
            ]
        )
    lines.extend(
        [
            "A negative `sse_py/sse_js − 1` means the Python optimizer found a lower SSE. "
            "Python optimizer budgets are listed in the JSON report; the browser uses the "
            "unmodified analyze options above.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    report = run_full_parity()
    print(f"report: {REPORTS / 'js_parity.md'}")
    print(f"json: {REPORTS / 'js_parity.json'}")
    print(f"fixed-θ pass: {report['fixed_theta']['pass']}")
    print(f"derived/filter pass: {report['derived_filters']['summary']['threshold_pass']}")
    print(f"best Python median SSE ratio: {report['full_fit']['best_method']['median_ratio']}")
    print(f"best-method threshold pass: {report['full_fit']['best_method']['threshold_pass']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
