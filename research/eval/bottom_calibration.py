"""PIT calibration of weekly A-share bottom scores and three-law gates."""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.optimize import brentq

from research.data import cache
from research.eval.bottom_dashboard import _eval_omori
from research.pipeline.overview_export import INDEX_LIST

SEGMENTS = ("dev", "cal", "test")
LIVE_SPLIT = "live"
BUCKETS = ("B0", "B1", "B2", "B3", "B4")
HORIZONS = (24, 50)
P_THRESHOLD_GRID = (0.6, 0.7, 0.85, 1.0)
DM_THRESHOLD_GRID = (0.0, 0.1, 0.2, 0.3)
PRODUCTIVITY_THRESHOLD_GRID = (1.0, 1.35, 2.0)
PROTOTYPE = {
    "p": {"min": 0.85},
    "delta_m": {"min": 0.72, "max": 1.45},
    "productivity": {"max": 1.35},
}
LAW_METRIC_KEYS = {
    "p": "p",
    "delta_m": "delta_m",
    "productivity": "productivity_ratio",
}
RANDOM_REPEATS = 2000
BOOTSTRAP_REPEATS = 2000
BLOCK_WEEKS = 26
EVENT_COOLDOWN_WEEKS = 12
SEED = 20261124
MIN_SEGMENT_WEEKS = 52
DEV_FIT_MIN_EVENTS = 15
DEV_AFTERSHOCK_DAYS = 60
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = ROOT / "web" / "mock" / "data"
DEFAULT_CACHE_ROOT = ROOT / "data" / "cache"
DEFAULT_REPORT_DIR = ROOT / "reports"


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def score_100(frame: dict[str, Any]) -> float | None:
    raw = _number(frame.get("fco_neg_intensity"))
    if raw is None:
        return None
    return raw * 100.0 if 0.0 < raw <= 1.0 else raw


def bucket_membership(score: float | None, omori_green: bool) -> dict[str, bool]:
    return {
        "B0": True,
        "B1": score is not None and score < 30.0,
        "B2": score is not None and 30.0 <= score < 50.0,
        "B3": score is not None and score >= 50.0,
        "B4": score is not None and score >= 50.0 and omori_green,
    }


def independent_positions(positions: list[int], cooldown: int = EVENT_COOLDOWN_WEEKS) -> list[int]:
    selected: list[int] = []
    last: int | None = None
    for position in positions:
        if last is None or position - last >= cooldown:
            selected.append(position)
            last = position
    return selected


def _date_index(daily: pd.DataFrame) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
    dates = pd.DatetimeIndex(pd.to_datetime(daily["date"])).normalize()
    closes = pd.to_numeric(daily["close"], errors="coerce").to_numpy(float)
    returns = np.full(len(closes), np.nan)
    valid = np.isfinite(closes) & (closes > 0)
    for i in range(1, len(closes)):
        if valid[i] and valid[i - 1]:
            returns[i] = closes[i] / closes[i - 1] - 1.0
    return dates, closes, returns


def _q05(returns: np.ndarray, end: int) -> float | None:
    available = returns[: end + 1]
    available = available[np.isfinite(available)]
    if len(available) < 500:
        return None
    return float(np.quantile(available[-500:], 0.05))


def _omori_expected_log_time(p: float, end: int, c: float = 1.0) -> float:
    upper = end + c
    exponent = 1.0 - p
    if abs(exponent) < 1e-7:
        log_ratio = math.log(upper / c)
        integral = log_ratio
        log_integral = 0.5 * (math.log(upper) ** 2 - math.log(c) ** 2)
    else:
        upper_power = upper**exponent
        lower_power = c**exponent
        integral = (upper_power - lower_power) / exponent
        log_integral = (
            upper_power * math.log(upper) - lower_power * math.log(c)
        ) / exponent - integral / exponent
    if integral <= 0 or not np.isfinite(integral) or not np.isfinite(log_integral):
        return float("nan")
    return log_integral / integral


def omori_utsu_mle(event_times: list[int], exposure_days: int, c: float = 1.0) -> float | None:
    if len(event_times) < 5 or exposure_days <= 0:
        return None
    observed = float(np.mean(np.log(np.asarray(event_times, dtype=float) + c)))

    def score(p: float) -> float:
        return _omori_expected_log_time(p, exposure_days, c) - observed

    low, high = -1.0, 1.0
    try:
        f_low, f_high = score(low), score(high)
        for _ in range(32):
            if np.isfinite(f_low) and np.isfinite(f_high) and f_low * f_high <= 0:
                result = float(brentq(score, low, high, maxiter=200))
                return result if np.isfinite(result) else None
            low *= 2.0
            high *= 2.0
            f_low, f_high = score(low), score(high)
    except (OverflowError, ValueError, RuntimeError):
        return None
    return None


def three_law_metrics(daily: pd.DataFrame, asof: str) -> dict[str, Any]:
    dates, closes, returns = _date_index(daily)
    asof_date = pd.Timestamp(asof).normalize()
    end = int(dates.searchsorted(asof_date, side="right")) - 1
    if end < 1:
        return {"p": None, "delta_m": None, "m0": None, "q": None, "t": None, "n_aftershock": None}

    q = _q05(returns, end)
    if q is None or q == 0:
        return {"p": None, "delta_m": None, "m0": None, "q": q, "t": None, "n_aftershock": None}

    return_end = returns[: end + 1]
    start = max(1, end - 119)
    lookback_positions = np.arange(start, end + 1)
    lookback = return_end[start : end + 1]
    if not len(lookback) or not np.isfinite(lookback).any():
        return {"p": None, "delta_m": None, "m0": None, "q": q, "t": None, "n_aftershock": None}
    mainshock_position = int(lookback_positions[np.nanargmin(lookback)])
    mainshock_return = float(returns[mainshock_position])
    exposure = end - mainshock_position
    after_positions = np.arange(mainshock_position + 1, end + 1)
    after_positions = after_positions[returns[after_positions] <= q]
    event_times = [int(position - mainshock_position) for position in after_positions]
    m0 = math.log10(abs(mainshock_return) / abs(q)) if mainshock_return != 0 else None
    delta_m = None
    if len(after_positions) and mainshock_return != 0:
        largest_aftershock = float(np.max(np.abs(returns[after_positions])))
        if largest_aftershock > 0:
            delta_m = math.log10(abs(mainshock_return)) - math.log10(largest_aftershock)

    return {
        "p": omori_utsu_mle(event_times, exposure, c=1.0),
        "delta_m": delta_m,
        "m0": m0,
        "q": q,
        "t": int(exposure),
        "n_aftershock": int(len(after_positions)),
        "mainshock_date": dates[mainshock_position].strftime("%Y-%m-%d"),
        "mainshock_return": mainshock_return,
    }


def dev_mainshock_observations(
    daily: pd.DataFrame, dev_start: str, dev_end: str, symbol: str
) -> list[dict[str, Any]]:
    dates, _, returns = _date_index(daily)
    start_date = pd.Timestamp(dev_start).normalize()
    end_date = pd.Timestamp(dev_end).normalize()
    rows: list[dict[str, Any]] = []
    for position in range(60, len(returns) - DEV_AFTERSHOCK_DAYS):
        if dates[position] < start_date or dates[position + DEV_AFTERSHOCK_DAYS] > end_date:
            continue
        q = _q05(returns, position)
        current = returns[position]
        if q is None or not np.isfinite(current) or current > q:
            continue
        window = returns[position - 60 : position + 61]
        if not np.isfinite(window).all() or current != float(np.min(window)):
            continue
        if current == 0:
            continue
        after = returns[position + 1 : position + 1 + DEV_AFTERSHOCK_DAYS]
        if len(after) != DEV_AFTERSHOCK_DAYS or not np.isfinite(after).all():
            continue
        m0 = math.log10(abs(float(current)) / abs(q))
        rows.append(
            {
                "symbol": symbol,
                "date": dates[position].strftime("%Y-%m-%d"),
                "m0": m0,
                "n_obs": int(np.count_nonzero(after <= q)),
            }
        )
    return rows


def fit_productivity_model(rows: list[dict[str, Any]]) -> dict[str, float]:
    if len(rows) < 2:
        raise ValueError(f"Poisson productivity fit requires at least 2 dev events, got {len(rows)}")
    magnitudes = np.asarray([float(row["m0"]) for row in rows])
    observed = np.asarray([int(row["n_obs"]) for row in rows])
    design = np.column_stack((np.ones(len(rows)), magnitudes * math.log(10.0)))
    result = sm.GLM(observed, design, family=sm.families.Poisson()).fit()
    log_k, alpha = map(float, result.params)
    k = math.exp(log_k)
    if not np.isfinite(k) or not np.isfinite(alpha) or k <= 0:
        raise ValueError("Poisson productivity fit returned non-finite parameters")
    return {"k": k, "alpha": alpha, "log_k": log_k, "n_dev_events": len(rows)}


def add_productivity_ratio(metrics: dict[str, Any], model: dict[str, float] | None) -> dict[str, Any]:
    result = dict(metrics)
    m0 = _number(result.get("m0"))
    exposure = _number(result.get("t"))
    observed = _number(result.get("n_aftershock"))
    if model is None or m0 is None or exposure is None or exposure <= 0 or observed is None:
        result["productivity_ratio"] = None
        result["n_expected"] = None
        return result
    try:
        expected = float(model["k"] * 10.0 ** (model["alpha"] * m0) * (exposure / DEV_AFTERSHOCK_DAYS))
    except OverflowError:
        expected = float("inf")
    result["n_expected"] = expected if np.isfinite(expected) and expected > 0 else None
    result["productivity_ratio"] = (
        observed / expected if np.isfinite(expected) and expected > 0 else None
    )
    return result


def _law_pass(value: float | None, law: str, threshold: float) -> bool:
    if value is None or not np.isfinite(value):
        return False
    if law == "p":
        return value >= threshold
    if law == "delta_m":
        return value >= threshold
    if law == "productivity":
        return value <= threshold
    raise ValueError(f"unknown law: {law}")


def _group_contains(row: dict[str, Any], group: Any) -> bool:
    if isinstance(group, str):
        return bool(row["buckets"].get(group, False))
    kind, law, threshold = group
    if not row["buckets"].get("B3", False):
        return False
    if law not in LAW_METRIC_KEYS:
        raise ValueError(f"unknown law: {law}")
    value = row["laws"].get(LAW_METRIC_KEYS[law])
    if kind == "gate":
        return _law_pass(_number(value), law, float(threshold))
    if kind == "prototype":
        limits = PROTOTYPE[law]
        value = _number(value)
        if value is None:
            return False
        if law == "p":
            return value >= limits["min"]
        if law == "delta_m":
            return limits["min"] <= value <= limits["max"]
        return value <= limits["max"]
    raise ValueError(f"unknown group type: {kind}")


def _event_rows(rows: list[dict[str, Any]], group: Any, horizon: int | None = None) -> list[dict[str, Any]]:
    matching = [i for i, row in enumerate(rows) if row["candidate"] and _group_contains(row, group)]
    selected = independent_positions(matching)
    events = [rows[i] for i in selected]
    if horizon is not None:
        events = [row for row in events if row["outcomes"].get(horizon) is not None]
    return events


def _raw_weeks(rows: list[dict[str, Any]], group: Any, horizon: int) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if row["candidate"] and _group_contains(row, group) and row["outcomes"].get(horizon) is not None
    ]


def _win_rate(rows: list[dict[str, Any]], horizon: int) -> float | None:
    returns = [row["outcomes"][horizon]["ret"] for row in rows]
    return float(np.mean(np.asarray(returns) > 0)) if returns else None


def _summary(
    by_index: dict[str, list[dict[str, Any]]], group: Any, horizon: int
) -> dict[str, Any]:
    week_rows = [row for rows in by_index.values() for row in _raw_weeks(rows, group, horizon)]
    event_rows = [row for rows in by_index.values() for row in _event_rows(rows, group, horizon)]
    returns = [row["outcomes"][horizon]["ret"] for row in event_rows]
    post_mins = [
        row["outcomes"][horizon]["post_min"]
        for row in event_rows
        if row["outcomes"][horizon].get("post_min") is not None
    ]
    return {
        "n_weeks": len(week_rows),
        "n_events": len(event_rows),
        "win_rate": float(np.mean(np.asarray(returns) > 0)) if returns else None,
        "median_ret": float(np.median(returns)) if returns else None,
        "median_post_min": float(np.median(post_mins)) if post_mins else None,
    }


def _random_baseline(
    by_index: dict[str, list[dict[str, Any]]],
    group: Any,
    horizon: int,
    rng: np.random.Generator,
) -> dict[str, float | None]:
    event_counts = {
        symbol: len(_event_rows(rows, group, horizon))
        for symbol, rows in by_index.items()
    }
    rates: list[float] = []
    for _ in range(RANDOM_REPEATS):
        sampled: list[dict[str, Any]] = []
        for symbol, rows in by_index.items():
            pool = _raw_weeks(rows, "B0", horizon)
            count = event_counts[symbol]
            if count and len(pool) >= count:
                positions = rng.choice(len(pool), size=count, replace=False)
                sampled.extend(pool[int(i)] for i in positions)
        rate = _win_rate(sampled, horizon)
        if rate is not None:
            rates.append(rate)
    if not rates:
        return {"p05": None, "p50": None, "p95": None}
    p05, p50, p95 = np.quantile(rates, [0.05, 0.50, 0.95])
    return {"p05": float(p05), "p50": float(p50), "p95": float(p95)}


def _resampled_rows(
    rows: list[dict[str, Any]], rng: np.random.Generator, block_weeks: int = BLOCK_WEEKS
) -> list[dict[str, Any]]:
    n = len(rows)
    if n == 0:
        return []
    sampled: list[dict[str, Any]] = []
    while len(sampled) < n:
        if n <= block_weeks:
            start = 0
            block = n
        else:
            start = int(rng.integers(0, n - block_weeks + 1))
            block = block_weeks
        sampled.extend(rows[start : start + block])
    return sampled[:n]


def _bootstrap_ci(
    by_index: dict[str, list[dict[str, Any]]],
    group_a: Any,
    group_b: Any,
    horizon: int,
    rng: np.random.Generator,
) -> dict[str, float | None]:
    point_a = _summary(by_index, group_a, horizon)["win_rate"]
    point_b = _summary(by_index, group_b, horizon)["win_rate"]
    point = point_a - point_b if point_a is not None and point_b is not None else None
    deltas: list[float] = []
    for _ in range(BOOTSTRAP_REPEATS):
        resampled = {
            symbol: _resampled_rows(rows, rng)
            for symbol, rows in by_index.items()
        }
        rate_a = _win_rate(
            [event for rows in resampled.values() for event in _event_rows(rows, group_a, horizon)],
            horizon,
        )
        rate_b = _win_rate(
            [event for rows in resampled.values() for event in _event_rows(rows, group_b, horizon)],
            horizon,
        )
        if rate_a is not None and rate_b is not None:
            deltas.append(rate_a - rate_b)
    if not deltas:
        return {"estimate": point, "lower": None, "upper": None}
    lower, upper = np.quantile(deltas, [0.025, 0.975])
    return {"estimate": point, "lower": float(lower), "upper": float(upper)}


def _daily_close_asof(daily: pd.DataFrame, asof: str) -> pd.Series:
    indexed = daily.set_index(pd.to_datetime(daily["date"]).dt.normalize())["close"].astype(float)
    return indexed.loc[indexed.index <= pd.Timestamp(asof).normalize()].tail(252)


def _load_daily(symbol: str, cache_root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    original_root = cache.ROOT
    cache.ROOT = cache_root
    try:
        daily = cache.load(symbol, adjust="qfq", auto_refresh=False)
    finally:
        cache.ROOT = original_root
    if daily.empty or not {"date", "close"}.issubset(daily.columns):
        raise ValueError(f"{symbol}: long local cache has no daily date/close data")
    daily = daily.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily = (
        daily.dropna(subset=["date", "close"])
        .loc[lambda frame: frame["close"] > 0]
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    if daily.empty:
        raise ValueError(f"{symbol}: local daily cache has no positive closes")
    return daily, {
        "rows": int(len(daily)),
        "first_date": daily["date"].iloc[0].strftime("%Y-%m-%d"),
        "last_date": daily["date"].iloc[-1].strftime("%Y-%m-%d"),
        "vintage": daily.attrs.get("vintage"),
        "source": daily.attrs.get("source"),
    }


def _load_frames(data_dir: Path, symbol: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = data_dir / f"{symbol}_history.json"
    if not path.exists():
        raise FileNotFoundError(f"missing index history: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    frames = payload.get("frames") or []
    if not frames:
        raise ValueError(f"{path} contains no frames")
    for frame in frames:
        if not frame.get("asof") or not frame.get("split"):
            raise ValueError(f"{symbol}: weekly frame missing asof/split")
    frames = sorted(frames, key=lambda frame: str(frame["asof"]))
    return frames, {"path": str(path), "frames": len(frames)}


def _candidate(frame: dict[str, Any], position: int, closes: list[float | None]) -> bool:
    if position < 20 or frame.get("bottom_first_alert_flag"):
        return False
    close = _number(frame.get("close"))
    window = [value for value in closes[max(0, position - 51) : position + 1] if value is not None]
    return bool(close is not None and close > 0 and window and close / max(window) - 1.0 <= -0.12)


def _outcome(
    frames: list[dict[str, Any]], closes: list[float | None], position: int, horizon: int
) -> dict[str, float] | None:
    entry = closes[position]
    target = position + horizon
    if entry is None or entry <= 0 or target >= len(frames) or closes[target] is None:
        return None
    result = {"ret": float(closes[target] / entry - 1.0)}
    if horizon == 50:
        future = [value for value in closes[position + 1 : position + horizon + 1] if value is not None]
        result["post_min"] = float(min(future) / entry - 1.0) if future else None
    else:
        result["post_min"] = None
    return result


def _dev_ranges(frames: list[dict[str, Any]]) -> tuple[str, str] | None:
    dates = [str(frame["asof"]) for frame in frames if frame.get("split") == "dev"]
    return (min(dates), max(dates)) if dates else None


def _law_grid(law: str) -> tuple[float, ...]:
    return {
        "p": P_THRESHOLD_GRID,
        "delta_m": DM_THRESHOLD_GRID,
        "productivity": PRODUCTIVITY_THRESHOLD_GRID,
    }[law]


def _segment_groups(
    observations: dict[str, dict[str, list[dict[str, Any]]]],
    segment: str,
) -> dict[str, list[dict[str, Any]]]:
    return {symbol: observations[symbol][segment] for symbol, _, _ in INDEX_LIST}


def _law_group(kind: str, law: str, threshold: float | None = None) -> tuple[str, str, float | None]:
    return (kind, law, threshold)


def _grid_results(
    observations: dict[str, dict[str, list[dict[str, Any]]]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    grid: dict[str, Any] = {}
    selected: dict[str, Any] = {}
    dev = _segment_groups(observations, "dev")
    baseline = _summary(dev, "B3", 50)
    for law in ("p", "delta_m", "productivity"):
        trials = []
        for threshold in _law_grid(law):
            group = _law_group("gate", law, threshold)
            stats = _summary(dev, group, 50)
            lift = (
                stats["win_rate"] - baseline["win_rate"]
                if stats["win_rate"] is not None and baseline["win_rate"] is not None
                else None
            )
            trials.append(
                {
                    "threshold": threshold,
                    "n_weeks": stats["n_weeks"],
                    "n_events": stats["n_events"],
                    "win_rate_50w": stats["win_rate"],
                    "baseline_b3_win_rate_50w": baseline["win_rate"],
                    "lift_50w": lift,
                    "eligible": stats["n_events"] >= 30 and lift is not None,
                }
            )
        eligible = [trial for trial in trials if trial["eligible"]]
        best = max(eligible, key=lambda trial: trial["lift_50w"]) if eligible else None
        selected[law] = {
            "threshold": best["threshold"] if best else None,
            "dev_selection": best,
        }
        grid[law] = trials
    return grid, selected


def run_calibration(
    data_dir: Path = DEFAULT_DATA_DIR,
    cache_root: Path = DEFAULT_CACHE_ROOT,
) -> dict[str, Any]:
    started = time.perf_counter()
    frame_sources: dict[str, Any] = {}
    cache_sources: dict[str, Any] = {}
    frames_by_symbol: dict[str, list[dict[str, Any]]] = {}
    daily_by_symbol: dict[str, pd.DataFrame] = {}
    dev_rows: dict[str, list[dict[str, Any]]] = {}
    exclusions: list[dict[str, Any]] = []
    live_counts: dict[str, int] = {}

    for symbol, _, _ in INDEX_LIST:
        frames, frame_meta = _load_frames(data_dir, symbol)
        daily, daily_meta = _load_daily(symbol, cache_root)
        frames_by_symbol[symbol] = frames
        daily_by_symbol[symbol] = daily
        frame_sources[symbol] = frame_meta
        cache_sources[symbol] = daily_meta
        live_counts[symbol] = sum(frame.get("split") == LIVE_SPLIT for frame in frames)
        daily_end = daily["date"].iloc[-1]
        max_research_date = max(
            pd.Timestamp(frame["asof"])
            for frame in frames
            if frame.get("split") in SEGMENTS
        )
        if daily_end < max_research_date:
            raise ValueError(
                f"{symbol}: local cache ends {daily_end.date()}, but non-live weekly frames reach "
                f"{max_research_date.date()}; three-law PIT inputs are incomplete"
            )
        dev_range = _dev_ranges(frames)
        dev_rows[symbol] = (
            dev_mainshock_observations(daily, *dev_range, symbol)
            if dev_range is not None
            else []
        )
        for segment in SEGMENTS:
            n = sum(frame.get("split") == segment for frame in frames)
            if n < MIN_SEGMENT_WEEKS:
                exclusions.append(
                    {
                        "symbol": symbol,
                        "segment": segment,
                        "reason": f"only {n} frames; minimum is {MIN_SEGMENT_WEEKS}",
                    }
                )

    pooled_rows = [row for rows in dev_rows.values() for row in rows]
    if not pooled_rows:
        raise ValueError("no dev mainshock events available for pooled Poisson productivity fit")
    pooled_model = fit_productivity_model(pooled_rows)
    models: dict[str, dict[str, Any]] = {}
    for symbol, _, _ in INDEX_LIST:
        rows = dev_rows[symbol]
        if len(rows) >= DEV_FIT_MIN_EVENTS:
            model = fit_productivity_model(rows)
            models[symbol] = {"fit": "per_index", **model}
        else:
            models[symbol] = {
                "fit": "pooled_7_index",
                "n_index_dev_events": len(rows),
                **pooled_model,
            }

    observations: dict[str, dict[str, list[dict[str, Any]]]] = {
        symbol: {segment: [] for segment in SEGMENTS}
        for symbol, _, _ in INDEX_LIST
    }
    candidate_counts: dict[str, int] = {}
    for symbol, _, _ in INDEX_LIST:
        all_frames = frames_by_symbol[symbol]
        frames = [frame for frame in all_frames if frame.get("split") in SEGMENTS]
        closes = [_number(frame.get("close")) for frame in frames]
        daily = daily_by_symbol[symbol]
        candidate_counts[symbol] = 0
        for position, frame in enumerate(frames):
            segment = str(frame["split"])
            if sum(item.get("split") == segment for item in all_frames) < MIN_SEGMENT_WEEKS:
                continue
            candidate = _candidate(frame, position, closes)
            if not candidate:
                observations[symbol][segment].append(
                    {
                        "candidate": False,
                        "buckets": {},
                        "laws": {},
                        "outcomes": {
                            horizon: _outcome(frames, closes, position, horizon)
                            for horizon in HORIZONS
                        },
                    }
                )
                continue
            candidate_counts[symbol] += 1
            asof = str(frame["asof"])
            close_pit = _daily_close_asof(daily, asof)
            omori_green = _eval_omori(close_pit)["light"] == "green"
            score = score_100(frame)
            laws = three_law_metrics(daily, asof)
            laws = add_productivity_ratio(laws, models[symbol])
            observations[symbol][segment].append(
                {
                    "candidate": True,
                    "asof": asof,
                    "score": score,
                    "buckets": bucket_membership(score, omori_green),
                    "laws": laws,
                    "outcomes": {
                        horizon: _outcome(frames, closes, position, horizon)
                        for horizon in HORIZONS
                    },
                }
            )

    rng = np.random.default_rng(SEED)
    tables: dict[str, Any] = {}
    for segment in SEGMENTS:
        grouped = _segment_groups(observations, segment)
        excluded_index = {
            item["symbol"] for item in exclusions if item["segment"] == segment
        }
        if excluded_index:
            grouped = {symbol: [] if symbol in excluded_index else rows for symbol, rows in grouped.items()}
        tables[segment] = {}
        for bucket in BUCKETS:
            tables[segment][bucket] = {}
            for horizon in HORIZONS:
                stats = _summary(grouped, bucket, horizon)
                random_stats = _random_baseline(grouped, bucket, horizon, rng)
                if bucket == "B0":
                    ci = {"estimate": 0.0, "lower": 0.0, "upper": 0.0}
                else:
                    ci = _bootstrap_ci(grouped, bucket, "B0", horizon, rng)
                stats["random_win_rate"] = random_stats
                stats["ci_delta_vs_b0"] = ci
                stats["superior_to_random"] = (
                    stats["win_rate"] is not None
                    and random_stats["p95"] is not None
                    and stats["win_rate"] > random_stats["p95"]
                )
                tables[segment][bucket][f"{horizon}w"] = stats

    grid, selected = _grid_results(observations)
    law_reports: dict[str, Any] = {}
    for law in ("p", "delta_m", "productivity"):
        threshold = selected[law]["threshold"]
        law_reports[law] = {
            "grid_dev": grid[law],
            "selected_threshold": threshold,
            "selected_by_segment": {},
            "prototype_control": {},
        }
        for segment in SEGMENTS:
            grouped = _segment_groups(observations, segment)
            excluded_index = {
                item["symbol"] for item in exclusions if item["segment"] == segment
            }
            if excluded_index:
                grouped = {symbol: [] if symbol in excluded_index else rows for symbol, rows in grouped.items()}
            for label, group in (
                ("selected", _law_group("gate", law, threshold) if threshold is not None else None),
                ("prototype", _law_group("prototype", law, None)),
            ):
                if group is None:
                    result = {"threshold": None, "n_weeks": 0, "n_events": 0, "win_rate_50w": None, "median_ret_50w": None}
                else:
                    stats = _summary(grouped, group, 50)
                    baseline = _summary(grouped, "B3", 50)
                    result = {
                        "threshold": threshold if label == "selected" else PROTOTYPE[law],
                        "n_weeks": stats["n_weeks"],
                        "n_events": stats["n_events"],
                        "win_rate_50w": stats["win_rate"],
                        "median_ret_50w": stats["median_ret"],
                        "baseline_b3_win_rate_50w": baseline["win_rate"],
                        "lift_50w_vs_b3": (
                            stats["win_rate"] - baseline["win_rate"]
                            if stats["win_rate"] is not None and baseline["win_rate"] is not None
                            else None
                        ),
                    }
                    if segment == "cal":
                        result["cal_ci_vs_b3"] = _bootstrap_ci(grouped, group, "B3", 50, rng)
                        ci = result["cal_ci_vs_b3"]
                        result["verdict"] = (
                            "keep_gate"
                            if result["lift_50w_vs_b3"] is not None
                            and result["lift_50w_vs_b3"] > 0
                            and ci["lower"] is not None
                            and ci["lower"] > 0
                            else "descriptive_only"
                        )
                if label == "selected":
                    law_reports[law]["selected_by_segment"][segment] = result
                else:
                    law_reports[law]["prototype_control"][segment] = result

    return {
        "spec": "bottom_calibration_v1_2026-11-24",
        "seed": SEED,
        "repetitions": {"random": RANDOM_REPEATS, "bootstrap": BOOTSTRAP_REPEATS},
        "definitions": {
            "daily_source": "research.data.cache.load(adjust='qfq', auto_refresh=False)",
            "weekly_source": "web/mock/data/{symbol}_history.json",
            "score": "existing fco_neg_intensity converted to 0-100 as overview_export does",
            "candidate": "summarize_bottom_backtest non-signal baseline drawdown <= -12%; 52-week high window",
            "live_frames": "excluded from tables, decisions, and forward outcome closes",
            "independent_event": "within each index, segment, and bucket; first event, then at least 12 frame-weeks apart",
            "productivity_magnitude": "M=log10(abs(return)/abs(q)); Mc=0; q is the candidate-date trailing 500-return 5th percentile",
            "bootstrap": "index-stratified 26-week moving blocks; pooled independent events are equally weighted",
        },
        "sources": {"histories": frame_sources, "daily_cache": cache_sources},
        "live_frame_counts": live_counts,
        "candidate_week_counts": candidate_counts,
        "dev_productivity_models": models,
        "tables": tables,
        "b3_law_distributions": _b3_law_distributions(observations),
        "three_laws": {
            "threshold_grid": grid,
            "selected": law_reports,
        },
        "exclusions": exclusions,
        "runtime_seconds": round(time.perf_counter() - started, 3),
    }


def _b3_law_distributions(
    observations: dict[str, dict[str, list[dict[str, Any]]]],
) -> dict[str, Any]:
    distributions: dict[str, Any] = {}
    for segment in SEGMENTS:
        rows = [
            row
            for index_rows in _segment_groups(observations, segment).values()
            for row in index_rows
            if row["candidate"] and row["buckets"].get("B3", False)
        ]
        result: dict[str, Any] = {"n_b3_candidate_weeks": len(rows)}
        for metric in LAW_METRIC_KEYS.values():
            values = [
                value
                for row in rows
                if (value := _number(row["laws"].get(metric))) is not None
            ]
            if values:
                p10, p50, p90 = np.quantile(values, [0.1, 0.5, 0.9])
                result[metric] = {
                    "count": len(values),
                    "p10": float(p10),
                    "p50": float(p50),
                    "p90": float(p90),
                }
            else:
                result[metric] = {
                    "count": 0,
                    "p10": None,
                    "p50": None,
                    "p90": None,
                }
        distributions[segment] = result
    return distributions


def _fmt(value: Any, digits: int = 3) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value:.{digits}f}"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 底分 / 三定律校准回测",
        "",
        f"- Seed: `{report['seed']}`; random/bootstrap repetitions: "
        f"`{RANDOM_REPEATS}/{BOOTSTRAP_REPEATS}`; runtime: `{report['runtime_seconds']:.3f}s`.",
        "- Weekly inputs are the seven published index history files; daily PIT inputs are the long local `research.data.cache` qfq caches.",
        "- `live` frames are excluded from samples, decisions, and forward-outcome closes.",
        "",
        "## 每段 × 分档 × 期限",
        "",
        "| 段 | 分档 | 期限 | n_weeks | n_events | win_rate | median_ret | median_post_min | 随机5/50/95 | CI（胜率差） | 优于随机 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for segment in SEGMENTS:
        for bucket in BUCKETS:
            for horizon in HORIZONS:
                stats = report["tables"][segment][bucket][f"{horizon}w"]
                random_stats = stats["random_win_rate"]
                ci = stats["ci_delta_vs_b0"]
                random_text = "/".join(_fmt(random_stats[key]) for key in ("p05", "p50", "p95"))
                ci_text = f"{_fmt(ci['lower'])} to {_fmt(ci['upper'])}"
                lines.append(
                    f"| {segment} | {bucket} | {horizon}w | {stats['n_weeks']} | {stats['n_events']} "
                    f"| {_fmt(stats['win_rate'])} | {_fmt(stats['median_ret'])} "
                    f"| {_fmt(stats['median_post_min'])} | {random_text} | {ci_text} "
                    f"| {'是' if stats['superior_to_random'] else '否'} |"
                )

    lines.extend(["", "## B3 候选周三定律指标分布", ""])
    lines.append("| 段 | B3 候选周 | 指标 | 有效数 | P10 | P50 | P90 |")
    lines.append("|---|---:|---|---:|---:|---:|---:|")
    for segment, distributions in report["b3_law_distributions"].items():
        for metric in LAW_METRIC_KEYS.values():
            result = distributions[metric]
            lines.append(
                f"| {segment} | {distributions['n_b3_candidate_weeks']} | {metric} "
                f"| {result['count']} | {_fmt(result['p10'])} | {_fmt(result['p50'])} "
                f"| {_fmt(result['p90'])} |"
            )

    lines.extend(["", "## 三定律阈值网格（dev 选阈值）", ""])
    for law, law_result in report["three_laws"]["selected"].items():
        lines.extend(
            [
                f"### {law}",
                "",
                "| threshold | n_weeks | n_events | win_rate_50w | B3 win_rate_50w | lift | eligible |",
                "|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for trial in law_result["grid_dev"]:
            lines.append(
                f"| {trial['threshold']} | {trial['n_weeks']} | {trial['n_events']} "
                f"| {_fmt(trial['win_rate_50w'])} | {_fmt(trial['baseline_b3_win_rate_50w'])} "
                f"| {_fmt(trial['lift_50w'])} | {'是' if trial['eligible'] else '否'} |"
            )
        lines.append(f"\nSelected threshold: `{law_result['selected_threshold']}`.")
        lines.extend(["", "Selected threshold and prototype control:", ""])
        lines.append("| 组 | 段 | 阈值 | n_weeks | n_events | win_rate_50w | lift vs B3 | cal CI vs B3 | verdict |")
        lines.append("|---|---|---|---:|---:|---:|---:|---|---|")
        for label in ("selected_by_segment", "prototype_control"):
            for segment, result in law_result[label].items():
                ci = result.get("cal_ci_vs_b3")
                ci_text = f"{_fmt(ci['lower'])} to {_fmt(ci['upper'])}" if ci else "—"
                lines.append(
                    f"| {'selected' if label == 'selected_by_segment' else 'prototype'} | {segment} "
                    f"| {result['threshold']} | {result['n_weeks']} | {result['n_events']} "
                    f"| {_fmt(result.get('win_rate_50w'))} | {_fmt(result.get('lift_50w_vs_b3'))} "
                    f"| {ci_text} | {result.get('verdict', '—')} |"
                )
        lines.append("")

    lines.extend(["## Productivity GLM", ""])
    lines.append("| 指数 | 拟合方式 | dev 主震数 | k | α |")
    lines.append("|---|---|---:|---:|---:|")
    for symbol, model in report["dev_productivity_models"].items():
        lines.append(
            f"| {symbol} | {model['fit']} | {model.get('n_index_dev_events', model['n_dev_events'])} "
            f"| {_fmt(model['k'])} | {_fmt(model['alpha'])} |"
        )
    lines.extend(["", "## Exclusions", ""])
    if report["exclusions"]:
        for item in report["exclusions"]:
            lines.append(f"- {item['symbol']} / {item['segment']}: {item['reason']}.")
    else:
        lines.append("- None.")
    lines.append("")
    lines.append("| 指数 | live 帧数 | 候选周数 | cache rows | cache dates | cache vintage / source |")
    lines.append("|---|---:|---:|---:|---|---|")
    for symbol, cache_meta in report["sources"]["daily_cache"].items():
        lines.append(
            f"| {symbol} | {report['live_frame_counts'][symbol]} | {report['candidate_week_counts'][symbol]} "
            f"| {cache_meta['rows']} | {cache_meta['first_date']}–{cache_meta['last_date']} "
            f"| {cache_meta['vintage']} / {cache_meta['source']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="PIT calibration of bottom-score buckets and three-law gates")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()
    report = run_calibration(args.data_dir, args.cache_root)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.report_dir / "bottom_calibration.json"
    md_path = args.report_dir / "bottom_calibration.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"{json_path}")
    print(f"{md_path}")
    print(f"runtime_seconds={report['runtime_seconds']:.3f}")


if __name__ == "__main__":
    main()
