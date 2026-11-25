"""Synthetic and development-segment comparison for the LPPLS tc profile fitter."""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import pandas as pd

from ..data.global_terminal import load_cached_snapshot
from ..lppls.profile_fit import C_GRID, fit_window, profile_fit, profile_range
from ..pipeline.global_terminal import WINDOWS as FIT_WINDOWS

N_SET = (63, 126, 252, 504, 1008)
NOISE_SET = ("AR1", "GARCH")
NULL_SET = ("N1_RW", "N2_RW_GARCH", "N3_TREND_AR1", "N4_TREND_GARCH_AR1", "N5_BLOCK", "N6_BLOCK_DRIFT")
ASSETS = ("US_SPX", "US_IXIC", "US_NDX", "US_DJI", "JP_N225", "KR_KOSPI", "KR_KOSDAQ")
CUTOFF = "2018-12-31"
BLOCK = 20
BURN_IN = 500
SYNTH_SEED = 20261125
REAL_SEED = 7
SYNTHETIC_FITS_PER_GROUP = 200
NULL_FITS_PER_GROUP = 100
G3_PER_BUBBLE_GROUP = 50
REAL_PER_ASSET = 43


def _ar1_noise(length: int, rho: float, marginal_sd: float, rng) -> np.ndarray:
    innovation_sd = marginal_sd * np.sqrt(1.0 - rho**2)
    innovations = rng.normal(0.0, innovation_sd, size=length + BURN_IN)
    noise = np.zeros(length + BURN_IN, dtype=float)
    for index in range(1, len(noise)):
        noise[index] = rho * noise[index - 1] + innovations[index]
    return noise[BURN_IN:]


def _garch_series(count: int, unconditional_sd: float, rng) -> np.ndarray:
    w0 = unconditional_sd**2 * 0.02
    sigma2 = np.empty(count, dtype=float)
    eta = np.empty(count, dtype=float)
    z = rng.standard_t(5, size=count) / np.sqrt(5.0 / 3.0)
    sigma2[0] = unconditional_sd**2
    eta[0] = np.sqrt(sigma2[0]) * z[0]
    for index in range(1, count):
        sigma2[index] = w0 + 0.08 * eta[index - 1] ** 2 + 0.90 * sigma2[index - 1]
        eta[index] = np.sqrt(sigma2[index]) * z[index]
    return eta


def _garch_innovations(length: int, unconditional_sd: float, rng) -> np.ndarray:
    return _garch_series(length + BURN_IN, unconditional_sd, rng)[BURN_IN:]


def _garch_ar1_noise(length: int, rho: float, marginal_sd: float, rng) -> np.ndarray:
    innovations = _garch_series(
        length + BURN_IN, marginal_sd * np.sqrt(1.0 - rho**2), rng
    )
    noise = np.zeros(length + BURN_IN, dtype=float)
    for index in range(1, len(noise)):
        noise[index] = rho * noise[index - 1] + innovations[index]
    return noise[BURN_IN:]


def _block_pools(source_root: Path) -> tuple[np.ndarray, np.ndarray]:
    raw_blocks, centered_blocks = [], []
    cutoff = pd.Timestamp(CUTOFF)
    for asset in ASSETS:
        frame, _ = load_cached_snapshot(asset, source_root)
        dates = pd.to_datetime(frame.date)
        prefix = frame.loc[dates <= cutoff]
        returns = np.diff(np.log(prefix.close.to_numpy(dtype=float)))
        centered = returns - returns.mean()
        if len(returns) < BLOCK:
            raise ValueError(f"Not enough development returns to form blocks for {asset}")
        raw_blocks.extend(
            returns[start : start + BLOCK]
            for start in range(len(returns) - BLOCK + 1)
        )
        centered_blocks.extend(
            centered[start : start + BLOCK]
            for start in range(len(centered) - BLOCK + 1)
        )
    return np.asarray(raw_blocks, dtype=float), np.asarray(centered_blocks, dtype=float)


def _sample_blocks(blocks: np.ndarray, length: int, rng) -> np.ndarray:
    count = int(np.ceil(length / BLOCK))
    selected = rng.integers(0, len(blocks), size=count)
    return blocks[selected].reshape(-1)[:length]


def _bubble(n: int, noise_name: str, rng) -> tuple[np.ndarray, dict]:
    t2 = n - 1
    dt = t2
    ahead = float(rng.uniform(0.02 * dt + 1.0, 0.18 * dt))
    tc = t2 + ahead
    m = float(rng.uniform(0.1, 0.9))
    omega = float(rng.uniform(6.0, 13.0))
    phi = float(rng.uniform(0.0, 2.0 * np.pi))
    total_rise = float(rng.uniform(0.3, 1.2))
    b = -total_rise / (tc**m - ahead**m)
    ratio = float(rng.uniform(0.0, min(0.1, m / omega)))
    c = ratio * abs(b)
    rho = float(rng.uniform(0.85, 0.98))
    marginal_sd = float(rng.uniform(0.02, 0.06))
    if noise_name == "AR1":
        noise = _ar1_noise(n, rho, marginal_sd, rng)
    else:
        noise = _garch_ar1_noise(n, rho, marginal_sd, rng)
    t = np.arange(n, dtype=float)
    distance = np.abs(tc - t)
    y = 4.0 + b * distance**m + c * distance**m * np.cos(
        omega * np.log(distance) - phi
    ) + noise
    return y, {
        "tc_true": tc,
        "m_true": m,
        "w_true": omega,
        "b_true": b,
        "rho": rho,
        "sd": marginal_sd,
        "total_rise": total_rise,
    }


def _null(
    n: int,
    null_name: str,
    rng,
    raw_blocks: np.ndarray,
    centered_blocks: np.ndarray,
) -> tuple[np.ndarray, dict]:
    t = np.arange(n, dtype=float)
    dt = n - 1
    if null_name == "N1_RW":
        total_rise = float(rng.uniform(0.3, 1.2))
        drift = total_rise / dt
        returns = drift + rng.normal(0.0, 0.015, size=n - 1)
        y = 4.0 + np.r_[0.0, np.cumsum(returns)]
        params = {"total_rise": total_rise}
    elif null_name == "N2_RW_GARCH":
        total_rise = float(rng.uniform(0.3, 1.2))
        drift = total_rise / dt
        returns = drift + _garch_innovations(n - 1, 0.015, rng)
        y = 4.0 + np.r_[0.0, np.cumsum(returns)]
        params = {"total_rise": total_rise, "unconditional_sd": 0.015}
    elif null_name == "N3_TREND_AR1":
        total_rise = float(rng.uniform(0.3, 1.2))
        drift = total_rise / dt
        rho = float(rng.uniform(0.85, 0.98))
        marginal_sd = float(rng.uniform(0.02, 0.06))
        y = 4.0 + drift * t + _ar1_noise(n, rho, marginal_sd, rng)
        params = {"total_rise": total_rise, "rho": rho, "sd": marginal_sd}
    elif null_name == "N4_TREND_GARCH_AR1":
        total_rise = float(rng.uniform(0.3, 1.2))
        drift = total_rise / dt
        rho = float(rng.uniform(0.85, 0.98))
        marginal_sd = float(rng.uniform(0.02, 0.06))
        y = 4.0 + drift * t + _garch_ar1_noise(n, rho, marginal_sd, rng)
        params = {"total_rise": total_rise, "rho": rho, "sd": marginal_sd}
    elif null_name == "N5_BLOCK":
        returns = _sample_blocks(raw_blocks, n - 1, rng)
        y = 4.0 + np.r_[0.0, np.cumsum(returns)]
        params = {}
    elif null_name == "N6_BLOCK_DRIFT":
        total_rise = float(rng.uniform(0.3, 1.2))
        drift = total_rise / dt
        returns = _sample_blocks(centered_blocks, n - 1, rng) + drift
        y = 4.0 + np.r_[0.0, np.cumsum(returns)]
        params = {"total_rise": total_rise}
    else:
        raise ValueError(f"Unknown null class: {null_name}")
    return y, params


def _box_pass(fit) -> bool:
    ahead = fit.tc - (fit.n - 1)
    return bool(
        np.isfinite(fit.sse)
        and np.isfinite(fit.beta[1])
        and fit.beta[1] < 0
        and 0.1 <= fit.m <= 0.9
        and 6.0 <= fit.w <= 13.0
        and 0.0 <= ahead <= 90.0
    )


def _profile_worker(task: dict) -> dict:
    y = np.asarray(task["y"], dtype=float)
    fit = profile_fit(y)
    result = {
        "task_id": task["task_id"],
        "kind": task["kind"],
        "n": int(task["n"]),
        "noise": task.get("noise"),
        "null_class": task.get("null_class"),
        "rep": int(task["rep"]),
        "tc_true": task.get("tc_true"),
        "m_true": task.get("m_true"),
        "w_true": task.get("w_true"),
        "tc_hat": fit.tc,
        "tc_grid_hat": fit.grid_tc,
        "tc_polished": fit.polished_tc,
        "m_hat": fit.m,
        "w_hat": fit.w,
        "b_hat": float(fit.beta[1]),
        "sse_profile": fit.sse,
        "profile_seconds": fit.seconds,
        "box_pass": _box_pass(fit),
        "tc_grid": fit.tcs.tolist(),
        "inside_grid": fit.inside.tolist(),
        "profile": fit.profile.tolist(),
        "refined": fit.refined.tolist(),
        "pm": fit.pm.tolist(),
        "pw": fit.pw.tolist(),
    }
    for c in C_GRID:
        interval = profile_range(fit.tcs, fit.profile, c)
        key = f"c_{c:g}"
        result[f"{key}_lo"] = interval["lo"]
        result[f"{key}_hi"] = interval["hi"]
        result[f"{key}_width"] = interval["width"]
        result[f"{key}_components"] = interval["n_components"]
        result[f"{key}_ahead_lo"] = interval["ahead_lo"]
        result[f"{key}_ahead_hi"] = interval["ahead_hi"]
        if task["kind"] == "bubble":
            true_tc = float(task["tc_true"])
            result[f"{key}_covered"] = bool(
                np.isfinite(interval["lo"])
                and interval["lo"] <= true_tc <= interval["hi"]
            )
    if task.get("compare_g3"):
        os.environ["LPPLS_BOX"] = "v2"
        from ..pipeline.global_terminal import fit_job

        close = np.exp(y)
        dates = pd.bdate_range("2000-01-03", periods=len(close))
        g3 = fit_job(
            {
                "close": close.tolist(),
                "dates": [str(date.date()) for date in dates],
                "asof": str(dates[-1].date()),
                "n": len(close),
                "optimizer": "g3",
                "asset_id": "US_SPX",
                "key": "replay",
            }
        )
        if g3["status"] != "complete":
            raise RuntimeError(f"synthetic G3 fit failed for {task['task_id']}: {g3.get('error')}")
        g3_row = g3["row"]
        g3_sse = float(g3_row["sse"])
        g3_tc = float(g3_row["tc"])
        result["sse_g3"] = g3_sse
        result["g3_tc"] = g3_tc
        result["g3_inside"] = bool(g3_tc <= len(close) - 1)
        result["f1_ratio"] = (
            (fit.sse - g3_sse) / g3_sse if g3_sse > 0 else np.nan
        )
    return result


def _synthetic_tasks(source_root: Path) -> list[dict]:
    raw_blocks, centered_blocks = _block_pools(source_root)
    rng = np.random.default_rng(SYNTH_SEED)
    tasks = []
    for n in N_SET:
        for noise_name in NOISE_SET:
            for rep in range(SYNTHETIC_FITS_PER_GROUP):
                y, params = _bubble(n, noise_name, rng)
                tasks.append(
                    {
                        "task_id": f"bubble:{n}:{noise_name}:{rep:03d}",
                        "kind": "bubble",
                        "n": n,
                        "noise": noise_name,
                        "rep": rep,
                        "y": y,
                        "compare_g3": rep < G3_PER_BUBBLE_GROUP,
                        **params,
                    }
                )
        for null_name in NULL_SET:
            for rep in range(NULL_FITS_PER_GROUP):
                y, params = _null(n, null_name, rng, raw_blocks, centered_blocks)
                tasks.append(
                    {
                        "task_id": f"null:{n}:{null_name}:{rep:03d}",
                        "kind": "null",
                        "n": n,
                        "null_class": null_name,
                        "rep": rep,
                        "y": y,
                        **params,
                    }
                )
    return tasks


def _format(value, digits=4):
    if value is None or pd.isna(value):
        return "—"
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, np.bool_)):
        return "是" if value else "否"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return f"{float(value):.{digits}f}"


def _markdown_table(columns: list[str], rows: list[list]) -> str:
    rendered = [[_format(value) for value in row] for row in rows]
    widths = [
        max(len(str(columns[index])), *(len(row[index]) for row in rendered))
        for index in range(len(columns))
    ]
    header = "| " + " | ".join(str(value).ljust(widths[i]) for i, value in enumerate(columns)) + " |"
    divider = "| " + " | ".join("-" * width for width in widths) + " |"
    body = [
        "| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(columns))) + " |"
        for row in rendered
    ]
    return "\n".join([header, divider, *body])


def _distribution_rows(frame: pd.DataFrame, group_columns: list[str], value: str):
    rows = []
    for keys, group in frame.groupby(group_columns, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        values = pd.to_numeric(group[value], errors="coerce")
        values = values[np.isfinite(values)]
        if not len(values):
            continue
        rows.append(
            [
                *keys,
                len(values),
                values.quantile(0.05),
                values.median(),
                values.quantile(0.95),
                (values > 1e-6).mean() * 100.0,
                (values < -1e-6).mean() * 100.0,
            ]
        )
    return rows


def _summary(rows: pd.DataFrame, out: Path) -> None:
    c_columns = [f"c_{c:g}" for c in C_GRID]
    lines = []
    bubble = rows[rows.kind == "bubble"].copy()
    nulls = rows[rows.kind == "null"].copy()

    coverage = []
    for (n, noise), group in bubble.groupby(["n", "noise"], sort=True):
        coverage.append(
            [n, noise]
            + [group[f"{column}_covered"].mean() * 100.0 for column in c_columns]
        )
    coverage.append(
        ["pooled", "全部"]
        + [bubble[f"{column}_covered"].mean() * 100.0 for column in c_columns]
    )
    lines.extend(
        [
            "## T1 覆盖率 (%)",
            "",
            _markdown_table(["n", "噪声", *[f"c={c:g}" for c in C_GRID]], coverage),
            "",
        ]
    )

    null_width = []
    for (n, null_class), group in nulls.groupby(["n", "null_class"], sort=True):
        widths = pd.to_numeric(group["c_0.05_width"], errors="coerce").dropna()
        if len(widths):
            null_width.append([n, null_class, widths.median() / n])
    lines.extend(
        [
            "## T2 零假设区间宽度中位数 / n",
            "",
            _markdown_table(["n", "类别", "中位宽度/n"], null_width),
            "",
        ]
    )
    null_domain = []
    for (n, null_class), group in nulls.groupby(["n", "null_class"], sort=True):
        widths = pd.to_numeric(group["c_0.05_width"], errors="coerce").dropna()
        if len(widths):
            null_domain.append([n, null_class, widths.median() / (0.4 * (n - 1))])
    lines.extend(
        [
            "## T2 零假设区间宽度中位数 / (0.4dt)",
            "",
            _markdown_table(["n", "类别", "中位宽度/(0.4dt)"], null_domain),
            "",
        ]
    )

    for denominator, label in (
        ("n", "n"),
        ("domain", "0.4dt"),
    ):
        bubble_width = []
        for (n, noise), group in bubble.groupby(["n", "noise"], sort=True):
            widths = pd.to_numeric(group["c_0.05_width"], errors="coerce").dropna()
            divisor = n if denominator == "n" else 0.4 * (n - 1)
            if len(widths):
                bubble_width.append([n, noise, widths.median() / divisor])
        lines.extend(
            [
                f"## T3 泡沫区间宽度中位数 / {label}",
                "",
                _markdown_table(["n", "噪声", f"中位宽度/{label}"], bubble_width),
                "",
            ]
        )

    pass_rows = []
    for (n, noise), group in bubble.groupby(["n", "noise"], sort=True):
        pass_rows.append([n, f"bubble_{noise}", group.box_pass.mean() * 100.0])
    for (n, null_class), group in nulls.groupby(["n", "null_class"], sort=True):
        pass_rows.append([n, null_class, group.box_pass.mean() * 100.0])
    lines.extend(
        [
            "## T4 合格框通过率 (%)",
            "",
            _markdown_table(["n", "类别", "通过率"], pass_rows),
            "",
        ]
    )

    errors = []
    for (n, noise), group in bubble.groupby(["n", "noise"], sort=True):
        errors.append(
            [
                n,
                noise,
                (group.tc_hat - group.tc_true).abs().median(),
                (group.m_hat - group.m_true).abs().median(),
                (group.w_hat - group.w_true).abs().median(),
            ]
        )
    lines.extend(
        [
            "## T5 泡沫参数绝对误差中位数",
            "",
            _markdown_table(["n", "噪声", "|tc 误差|", "|m 误差|", "|ω 误差|"], errors),
            "",
        ]
    )

    g3 = bubble[bubble.sse_g3.notna()].copy()
    g3_rows = _distribution_rows(g3, ["n", "g3_inside"], "f1_ratio")
    lines.extend(
        [
            "## T6 合成 F1：(SSE_profile − SSE_g3)/SSE_g3",
            "",
            _markdown_table(
                ["n", "g3 窗内", "样本数", "p5", "p50", "p95", ">1e-6 (%)", "<-1e-6 (%)"],
                g3_rows,
            ),
            "",
        ]
    )

    real = rows[rows.kind == "real"].copy()
    real_rows = _distribution_rows(real, ["n", "asset"], "real_ratio")
    lines.extend(
        [
            "## T6r 开发段真实窗口：(SSE_profile − SSE_cache)/SSE_cache",
            "",
            _markdown_table(
                ["n", "资产", "样本数", "p5", "p50", "p95", ">1e-6 (%)", "<-1e-6 (%)"],
                real_rows,
            ),
            "",
        ]
    )

    timing = []
    for n, group in rows[rows.kind.isin(["bubble", "null"])].groupby("n", sort=True):
        times = pd.to_numeric(group.profile_seconds, errors="coerce").dropna()
        timing.append([n, times.median(), times.quantile(0.95)])
    lines.extend(
        [
            "## T7 profile_fit 耗时 (秒)",
            "",
            _markdown_table(["n", "中位数", "p95"], timing),
            "",
        ]
    )
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def _profile_synthetic(source_root: Path, workers: int) -> pd.DataFrame:
    tasks = _synthetic_tasks(source_root)
    results = []
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_profile_worker, task) for task in tasks]
        for done, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if done % 100 == 0:
                print(
                    f"synthetic {done}/{len(futures)} elapsed={time.perf_counter()-started:.1f}s",
                    flush=True,
                )
    return pd.DataFrame(results).sort_values("task_id").reset_index(drop=True)


def _real_candidates(source_root: Path, fits_dir: Path):
    cutoff = pd.Timestamp(CUTOFF)
    dev_frames, candidates = {}, {asset: [] for asset in ASSETS}
    for asset in ASSETS:
        frame, _ = load_cached_snapshot(asset, source_root)
        dates = pd.to_datetime(frame.date)
        dev = frame.loc[dates <= cutoff].reset_index(drop=True)
        if dev.empty:
            raise ValueError(f"No development data through {CUTOFF} for {asset}")
        dev_frames[asset] = dev
        max_i = len(dev) - 1
        pattern = re.compile(rf"{re.escape(asset)}_(\d+)\.json$")
        for path in sorted(fits_dir.glob(f"{asset}_*.json")):
            match = pattern.fullmatch(path.name)
            if not match:
                continue
            index = int(match.group(1))
            if index + 1 < max(FIT_WINDOWS) or index > max_i:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            expected_asof = str(pd.Timestamp(dev.date.iloc[index]).date())
            if payload.get("asof") != expected_asof:
                raise ValueError(
                    f"Development fit identity mismatch: {path.name} expected {expected_asof}, "
                    f"found {payload.get('asof')}"
                )
            by_window = {int(cell["n"]): cell for cell in payload.get("fits", [])}
            for n in FIT_WINDOWS:
                cell = by_window.get(n)
                row = cell.get("row") if isinstance(cell, dict) else None
                cached_sse = row.get("sse") if isinstance(row, dict) else None
                candidates[asset].append(
                    {
                        "asset": asset,
                        "i": index,
                        "n": n,
                        "asof": expected_asof,
                        "cached_sse": cached_sse,
                        "cache_status": cell.get("status") if isinstance(cell, dict) else None,
                        "path": path,
                    }
                )
    counts = {asset: len(values) for asset, values in candidates.items()}
    print(f"eligible dev pairs by asset: {counts}", flush=True)
    insufficient = {asset: count for asset, count in counts.items() if count < REAL_PER_ASSET}
    if insufficient:
        raise RuntimeError(f"Not enough completed development pairs per asset: {insufficient}")
    rng = np.random.default_rng(REAL_SEED)
    selected = []
    for asset in ASSETS:
        available = candidates[asset]
        indices = rng.choice(len(available), size=REAL_PER_ASSET, replace=False)
        selected.extend(available[int(index)] for index in indices)
    incomplete = [
        (pair["asset"], pair["asof"], pair["n"], pair["cache_status"])
        for pair in selected
        if pair["cache_status"] != "complete"
        or pair["cached_sse"] is None
        or not np.isfinite(pair["cached_sse"])
    ]
    if incomplete:
        raise RuntimeError(f"Selected development pairs lack a cached SSE: {incomplete}")
    return dev_frames, selected


def _fit_job_recompute(pair: dict, frame: pd.DataFrame) -> dict:
    from ..pipeline.global_terminal import fit_job

    prefix = frame.iloc[: pair["i"] + 1]
    return fit_job(
        {
            "close": prefix.close.tolist(),
            "dates": [str(pd.Timestamp(value).date()) for value in prefix.date],
            "asof": pair["asof"],
            "n": pair["n"],
            "optimizer": "g3",
            "asset_id": pair["asset"],
            "key": "replay",
        }
    )


def _real_worker(task: dict) -> dict:
    fit = fit_window(np.asarray(task["close_slice"], dtype=float))
    cached_sse = float(task["cached_sse"])
    ratio = (fit.sse - cached_sse) / cached_sse if cached_sse > 0 else np.nan
    return {
        "task_id": task["task_id"],
        "kind": "real",
        "asset": task["asset"],
        "i": int(task["i"]),
        "asof": task["asof"],
        "n": int(task["n"]),
        "sse_cached": cached_sse,
        "sse_profile": fit.sse,
        "real_ratio": ratio,
        "profile_seconds": fit.seconds,
        "tc_hat": fit.tc,
        "tc_grid_hat": fit.grid_tc,
        "tc_polished": fit.polished_tc,
        "m_hat": fit.m,
        "w_hat": fit.w,
        "b_hat": float(fit.beta[1]),
        "tc_grid": fit.tcs.tolist(),
        "inside_grid": fit.inside.tolist(),
        "profile": fit.profile.tolist(),
        "refined": fit.refined.tolist(),
        "pm": fit.pm.tolist(),
        "pw": fit.pw.tolist(),
    }


def _profile_real(source_root: Path, fits_dir: Path, workers: int) -> pd.DataFrame:
    dev_frames, selected = _real_candidates(source_root, fits_dir)
    checks = [selected[index] for index in (0, 43, 86)]
    check_results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_fit_job_recompute, pair, dev_frames[pair["asset"]])
            for pair in checks
        ]
        check_results = [future.result() for future in futures]
    for pair, result in zip(checks, check_results, strict=True):
        if result["status"] != "complete":
            raise RuntimeError(
                f"fit_job validation failed for {pair['asset']} {pair['asof']} n={pair['n']}: "
                f"{result.get('error')}"
            )
        recomputed = float(result["row"]["sse"])
        if not np.isclose(recomputed, pair["cached_sse"], rtol=1e-10, atol=1e-12):
            raise RuntimeError(
                f"Cached SSE y-convention mismatch for {pair['asset']} {pair['asof']} "
                f"n={pair['n']}: cached={pair['cached_sse']:.17g}, fit_job={recomputed:.17g}"
            )
    print(
        "fit_job SSE checks passed: "
        + ", ".join(
            f"{pair['asset']}/{pair['asof']}/n={pair['n']}" for pair in checks
        ),
        flush=True,
    )

    tasks = []
    for pair in selected:
        frame = dev_frames[pair["asset"]]
        end = pair["i"] + 1
        start = end - pair["n"]
        tasks.append(
            {
                "task_id": f"real:{pair['asset']}:{pair['i']}:{pair['n']}",
                **pair,
                "close_slice": frame.close.iloc[start:end].to_numpy(dtype=float),
            }
        )
    results = []
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_real_worker, task) for task in tasks]
        for done, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if done % 50 == 0:
                print(
                    f"real {done}/{len(futures)} elapsed={time.perf_counter()-started:.1f}s",
                    flush=True,
                )
    return pd.DataFrame(results).sort_values("task_id").reset_index(drop=True)


def _benchmark_y(n: int) -> np.ndarray:
    t2 = n - 1
    ahead = max(1.0, 0.1 * (n - 1))
    tc = t2 + ahead
    m, omega, total_rise = 0.5, 8.0, 0.6
    b = -total_rise / (tc**m - ahead**m)
    t = np.arange(n, dtype=float)
    distance = np.abs(tc - t)
    c = 0.05 * abs(b)
    return 4.0 + b * distance**m + c * distance**m * np.cos(
        omega * np.log(distance) - 0.7
    )


def benchmark(out: Path, repeats: int = 3) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    result = {}
    for n in (63, 252, 1008):
        y = _benchmark_y(n)
        timings = [profile_fit(y).seconds for _ in range(repeats)]
        result[str(n)] = {
            "seconds": timings,
            "median": float(np.median(timings)),
            "max": float(np.max(timings)),
        }
        print(f"benchmark n={n}: {result[str(n)]}", flush=True)
    result["repeats"] = repeats
    result["n1008_median_over_20s"] = result["1008"]["median"] > 20.0
    (out / "benchmark.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def run_all(source_root: Path, fits_dir: Path, out: Path, workers: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    print(f"synthetic seed={SYNTH_SEED}; workers={workers}", flush=True)
    synthetic = _profile_synthetic(source_root, workers)
    synthetic.to_parquet(out / "rows.parquet", index=False)
    print(f"synthetic complete: {len(synthetic)} rows", flush=True)
    real = _profile_real(source_root, fits_dir, workers)
    combined = pd.concat((synthetic, real), ignore_index=True, sort=False)
    combined.to_parquet(out / "rows.parquet", index=False)
    _summary(combined, out)
    print(
        f"real complete: {len(real)} rows; wrote {out / 'rows.parquet'} and {out / 'summary.md'}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    benchmark_parser = subparsers.add_parser("benchmark")
    benchmark_parser.add_argument("--out", type=Path, default=Path("reports/profile_synth"))
    benchmark_parser.add_argument("--repeats", type=int, default=3)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--source-root", type=Path, default=Path("/home/ubuntu/work/global-full"))
    run_parser.add_argument("--fits-dir", type=Path, default=Path("/home/ubuntu/work/intl27/fits"))
    run_parser.add_argument("--out", type=Path, default=Path("reports/profile_synth"))
    run_parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.command == "benchmark":
        result = benchmark(args.out, args.repeats)
        if result["n1008_median_over_20s"]:
            raise SystemExit(2)
        return
    run_all(args.source_root, args.fits_dir, args.out, args.workers)


if __name__ == "__main__":
    main()
