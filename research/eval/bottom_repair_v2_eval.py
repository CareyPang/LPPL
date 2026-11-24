"""Strict point-in-time evaluation of the bottom-repair V2 price scores."""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import io
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.data import cache
from research.eval.bottom_calibration import (
    DEFAULT_CACHE_ROOT,
    DEFAULT_DATA_DIR,
    DEFAULT_REPORT_DIR,
    SEED,
    SEGMENTS,
    _load_frames,
    _number,
    score_100,
)
from research.pipeline.overview_export import INDEX_LIST

SEGMENT_ENDS = {
    "dev": pd.Timestamp("2018-12-31"),
    "cal": pd.Timestamp("2021-12-31"),
    "test": pd.Timestamp("2025-08-29"),
}
SCORE_NAMES = ("low_shock", "short", "medium")
THRESHOLDS = (50, 60, 70)
V2_STATES = tuple(
    f"V2_{score_name}_{threshold}" for score_name in SCORE_NAMES for threshold in THRESHOLDS
)
BASELINE_STATES = ("OLD50", "STOPFALL", "B0")
STATES = (*V2_STATES, *BASELINE_STATES)
HORIZONS = (5, 10, 20, 60)
LOCATION_WINDOWS = (20, 60)
MIN_VALID_SESSIONS = 120
DD_LOOKBACK = 252
DD_THRESHOLD = -0.12
LABEL_LOOKBACK = 60
LABEL_FORWARD = 61
EVENT_COOLDOWN = 20
OLD50_MAX_AGE_DAYS = 10
RANDOM_REPEATS = 2000
BOOTSTRAP_REPEATS = 2000
OHLC_COLUMNS = ("open", "high", "low", "close")
BOOLEAN_METRICS = {
    "within5_20",
    "within5_60",
    "in_zone_20",
    "in_zone_60",
    "win_R20",
}
METRIC_NAMES = (
    "within5_20",
    "within5_60",
    "entry_dist_20",
    "entry_dist_60",
    "range_pos_20",
    "range_pos_60",
    "in_zone_20",
    "in_zone_60",
    "low_offset_20",
    "low_offset_60",
    "R5",
    "R10",
    "R20",
    "R60",
    "win_R20",
    "MAE20",
)
LEDGER_COLUMNS = (
    "state",
    "segment",
    "symbol",
    "date",
    "score",
    "entry_open",
    *(f"R{horizon}" for horizon in HORIZONS),
    "win_R20",
    "MAE20",
    *(
        f"{metric}_{window}"
        for window in LOCATION_WINDOWS
        for metric in (
            "entry_dist",
            "within5",
            "range_pos",
            "in_zone",
            "low_offset",
        )
    ),
)
ROOT = Path(__file__).resolve().parents[2]


def clip(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def ema(values: list[float] | np.ndarray, period: int) -> np.ndarray:
    closes = np.asarray(values, dtype=float)
    result = np.full(len(closes), np.nan, dtype=float)
    valid_positions = np.flatnonzero(np.isfinite(closes))
    if len(valid_positions) < period:
        return result

    seed_positions = valid_positions[:period]
    seed_position = int(seed_positions[-1])
    current = float(np.mean(closes[seed_positions]))
    result[seed_position] = current
    alpha = 2.0 / (period + 1.0)
    for position in range(seed_position + 1, len(closes)):
        if not np.isfinite(closes[position]):
            continue
        current = alpha * float(closes[position]) + (1.0 - alpha) * current
        result[position] = current
    return result


def downside_volatility(returns: np.ndarray, position: int, period: int) -> float | None:
    start = position - period + 1
    if start < 0:
        return None
    sample = returns[start : position + 1]
    if len(sample) != period or not np.isfinite(sample).all():
        return None
    downside = np.minimum(sample, 0.0)
    return float(np.sqrt(np.mean(np.square(downside))))


def f4_from_volatility(dv5: float | None, dv20: float | None) -> float | None:
    if dv20 is None or dv20 == 0.0 or dv5 is None:
        return None
    if dv5 == 0.0:
        return 1.0
    if dv5 < 0.0 or dv20 < 0.0:
        return None
    return clip(0.5 + math.log(dv20 / dv5) / (2.0 * math.log(2.0)))


def scores_from_features(
    f1: float | None,
    f2: float | None,
    f3: float | None,
    f4: float | None,
) -> dict[str, float | None]:
    if f1 is None or f4 is None:
        return {"low_shock": None, "short": None, "medium": None}
    shock = (f1 + f4) / 2.0
    low_shock = 100.0 * shock
    short = 100.0 * math.sqrt(shock * f2) if f2 is not None else None
    medium = (
        100.0 * math.sqrt(shock * (f2 + f3) / 2.0) if f2 is not None and f3 is not None else None
    )
    return {"low_shock": low_shock, "short": short, "medium": medium}


def compute_features(
    highs: list[float] | np.ndarray,
    lows: list[float] | np.ndarray,
    closes: list[float] | np.ndarray,
) -> dict[str, Any]:
    high = np.asarray(highs, dtype=float)
    low = np.asarray(lows, dtype=float)
    close = np.asarray(closes, dtype=float)
    if len(high) != len(low) or len(low) != len(close):
        raise ValueError("OHLC arrays must have equal lengths")

    size = len(close)
    returns = np.full(size, np.nan, dtype=float)
    true_range = np.full(size, np.nan, dtype=float)
    if size > 1:
        returns[1:] = np.log(close[1:] / close[:-1])
        true_range[1:] = np.maximum.reduce(
            (
                high[1:] - low[1:],
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1]),
            )
        )
    ema20 = ema(close, 20)
    ema60 = ema(close, 60)
    a_values = np.full(size, np.nan, dtype=float)
    dv5_values = np.full(size, np.nan, dtype=float)
    dv20_values = np.full(size, np.nan, dtype=float)
    feature_values = {name: np.full(size, np.nan, dtype=float) for name in ("f1", "f2", "f3", "f4")}
    score_values = {name: np.full(size, np.nan, dtype=float) for name in SCORE_NAMES}

    for position in range(size):
        if position + 1 < MIN_VALID_SESSIONS or position < 24:
            continue
        if not np.isfinite(ema60[position - 20]) or not np.isfinite(ema60[position]):
            continue
        prior_true_ranges = true_range[position - 20 : position]
        if len(prior_true_ranges) != 20 or not np.isfinite(prior_true_ranges).all():
            continue
        scale = float(np.mean(prior_true_ranges))
        if not np.isfinite(scale) or scale <= 0.0:
            continue
        a_values[position] = scale

        recent_low = float(np.min(low[position - 4 : position + 1]))
        prior_low = float(np.min(low[position - 24 : position - 4]))
        f1 = clip(0.5 + ((recent_low - prior_low) / scale) / 2.0)
        f2 = clip(0.5 + ((close[position] - ema20[position]) / scale) / 4.0)
        f3 = clip(0.5 + ((ema60[position] - ema60[position - 20]) / scale) / 4.0)
        dv5 = downside_volatility(returns, position, 5)
        dv20 = downside_volatility(returns, position, 20)
        dv5_values[position] = np.nan if dv5 is None else dv5
        dv20_values[position] = np.nan if dv20 is None else dv20
        f4 = f4_from_volatility(dv5, dv20)
        feature_values["f1"][position] = f1
        feature_values["f2"][position] = f2
        feature_values["f3"][position] = f3
        if f4 is not None:
            feature_values["f4"][position] = f4
        scores = scores_from_features(f1, f2, f3, f4)
        for score_name, score in scores.items():
            if score is not None:
                score_values[score_name][position] = score

    return {
        "returns": returns,
        "true_range": true_range,
        "a": a_values,
        "ema20": ema20,
        "ema60": ema60,
        "dv5": dv5_values,
        "dv20": dv20_values,
        **feature_values,
        "scores": score_values,
    }


def segment_for_date(value: Any) -> str:
    date = pd.Timestamp(value).normalize()
    if date <= SEGMENT_ENDS["dev"]:
        return "dev"
    if date <= SEGMENT_ENDS["cal"]:
        return "cal"
    if date <= SEGMENT_ENDS["test"]:
        return "test"
    return "live"


def label_window_valid(
    segment_labels: list[str],
    position: int,
    lookback: int = LABEL_LOOKBACK,
    forward: int = LABEL_FORWARD,
) -> bool:
    start = position - lookback
    end = position + forward
    if start < 0 or end >= len(segment_labels):
        return False
    segment = segment_labels[position]
    if segment not in SEGMENTS:
        return False
    return all(segment_labels[index] == segment for index in range(start, end + 1))


def select_state_positions(
    candidate_positions: list[int],
    state_flags: np.ndarray | list[bool],
    cooldown: int = EVENT_COOLDOWN,
) -> list[int]:
    selected: list[int] = []
    last_event: int | None = None
    for position in candidate_positions:
        if not state_flags[position]:
            continue
        if last_event is None or position - last_event >= cooldown:
            selected.append(position)
            last_event = position
    return selected


def old50_signal(
    event_date: Any, frame_dates: list[pd.Timestamp], frame_scores: list[float | None]
) -> tuple[bool, float | None]:
    date = pd.Timestamp(event_date).normalize()
    frame_position = bisect.bisect_right(frame_dates, date) - 1
    if frame_position < 0:
        return False, None
    score = frame_scores[frame_position]
    age_days = (date - frame_dates[frame_position]).days
    return bool(score is not None and score >= 50.0 and age_days <= OLD50_MAX_AGE_DAYS), score


def stopfall_signal(
    position: int,
    close: np.ndarray,
    low: np.ndarray,
    ema20: np.ndarray,
) -> bool:
    if position < 24 or not np.isfinite(ema20[position]):
        return False
    recent_low = float(np.min(low[position - 4 : position + 1]))
    prior_low = float(np.min(low[position - 24 : position - 4]))
    return bool(close[position] > ema20[position] and recent_low > prior_low)


def event_metrics(
    position: int,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
) -> dict[str, float | bool | None] | None:
    if position - LABEL_LOOKBACK < 0 or position + LABEL_FORWARD >= len(opens):
        return None
    entry_position = position + 1
    entry = float(opens[entry_position])
    if entry <= 0.0:
        return None

    metrics: dict[str, float | bool | None] = {"entry_open": entry}
    for horizon in HORIZONS:
        exit_open = float(opens[entry_position + horizon])
        metrics[f"R{horizon}"] = float(exit_open / entry - 1.0)
    metrics["win_R20"] = bool(metrics["R20"] > 0.0)
    metrics["MAE20"] = float(np.min(lows[position + 1 : position + 21]) / entry - 1.0)

    for window in LOCATION_WINDOWS:
        start = position - window
        end = position + window + 1
        window_lows = lows[start:end]
        window_highs = highs[start:end]
        lowest_low = float(np.min(window_lows))
        highest_high = float(np.max(window_highs))
        entry_distance = float(entry / lowest_low - 1.0)
        range_position = (
            None
            if highest_high == lowest_low
            else float((closes[position] - lowest_low) / (highest_high - lowest_low))
        )
        earliest_low = int(np.flatnonzero(window_lows == lowest_low)[0])
        metrics[f"entry_dist_{window}"] = entry_distance
        metrics[f"within5_{window}"] = bool(entry_distance <= 0.05)
        metrics[f"range_pos_{window}"] = range_position
        metrics[f"in_zone_{window}"] = (
            bool(range_position <= 0.20) if range_position is not None else None
        )
        metrics[f"low_offset_{window}"] = int(start + earliest_low - position)
    return metrics


def _load_daily_ohlc(symbol: str, cache_root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    original_root = cache.ROOT
    cache.ROOT = Path(cache_root)
    try:
        daily = cache.load(symbol, adjust="qfq", auto_refresh=False)
    finally:
        cache.ROOT = original_root
    if daily.empty or not {"date", *OHLC_COLUMNS}.issubset(daily.columns):
        raise ValueError(f"{symbol}: local qfq cache lacks daily OHLC fields")

    source_metadata = dict(daily.attrs)
    raw_rows = len(daily)
    daily = daily.copy()
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce").dt.normalize()
    if daily["date"].isna().any():
        raise ValueError(f"{symbol}: cache contains invalid dates")
    for column in OHLC_COLUMNS:
        daily[column] = pd.Series(
            [_number(value) for value in daily[column]],
            index=daily.index,
            dtype=float,
        )
    daily = daily.sort_values("date", kind="mergesort")
    duplicate_rows = len(daily) - daily["date"].nunique()
    daily = daily.drop_duplicates("date", keep="last")
    prices = daily.loc[:, list(OHLC_COLUMNS)].to_numpy(dtype=float)
    valid_prices = np.isfinite(prices).all(axis=1) & (prices > 0.0).all(axis=1)
    invalid_ohlc_rows = int((~valid_prices).sum())
    daily = daily.loc[valid_prices].reset_index(drop=True)
    if daily.empty:
        raise ValueError(f"{symbol}: no qfq rows remain after OHLC validation")
    return daily, {
        "raw_rows": int(raw_rows),
        "duplicate_rows_dropped": int(duplicate_rows),
        "invalid_ohlc_rows_dropped": invalid_ohlc_rows,
        "valid_rows": int(len(daily)),
        "first_date": daily["date"].iloc[0].strftime("%Y-%m-%d"),
        "last_date": daily["date"].iloc[-1].strftime("%Y-%m-%d"),
        "vintage": source_metadata.get("vintage"),
        "source": source_metadata.get("source"),
    }


def _metric_statistic(events: list[dict[str, Any]], metric_name: str) -> float | None:
    values = [
        event["metrics"][metric_name]
        for event in events
        if event["metrics"].get(metric_name) is not None
    ]
    if not values:
        return None
    if metric_name in BOOLEAN_METRICS:
        return float(np.mean(values))
    return float(np.median(values))


def _summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for metric_name in METRIC_NAMES:
        values = [
            event["metrics"][metric_name]
            for event in events
            if event["metrics"].get(metric_name) is not None
        ]
        metrics[metric_name] = {
            "statistic": "share" if metric_name in BOOLEAN_METRICS else "median",
            "value": (
                float(np.mean(values))
                if metric_name in BOOLEAN_METRICS and values
                else (float(np.median(values)) if values else None)
            ),
            "n_valid": len(values),
        }
    return {"n_events": len(events), "metrics": metrics}


def _random_baseline(
    state_events_by_index: dict[str, list[dict[str, Any]]],
    b0_events_by_index: dict[str, list[dict[str, Any]]],
    rng: np.random.Generator,
    repeats: int = RANDOM_REPEATS,
) -> dict[str, Any]:
    requested = {symbol: len(rows) for symbol, rows in state_events_by_index.items()}
    drawn = {
        symbol: min(count, len(b0_events_by_index.get(symbol, [])))
        for symbol, count in requested.items()
    }
    shortfall = {symbol: requested[symbol] - drawn[symbol] for symbol in requested}
    draw_statistics = {metric: [] for metric in METRIC_NAMES}
    for _ in range(repeats):
        sample: list[dict[str, Any]] = []
        for symbol, count in drawn.items():
            pool = b0_events_by_index.get(symbol, [])
            if count == 0:
                continue
            selected = rng.choice(len(pool), size=count, replace=False)
            sample.extend(pool[int(index)] for index in selected)
        for metric_name in METRIC_NAMES:
            value = _metric_statistic(sample, metric_name)
            if value is not None:
                draw_statistics[metric_name].append(value)

    random_metrics: dict[str, Any] = {}
    for metric_name, values in draw_statistics.items():
        metric_type = "share" if metric_name in BOOLEAN_METRICS else "median"
        if values:
            p5, median, p95 = np.quantile(values, [0.05, 0.50, 0.95])
            random_metrics[metric_name] = {
                "statistic": metric_type,
                "median": float(median),
                "p5": float(p5),
                "p95": float(p95),
                "valid_draws": len(values),
            }
        else:
            random_metrics[metric_name] = {
                "statistic": metric_type,
                "median": None,
                "p5": None,
                "p95": None,
                "valid_draws": 0,
            }
    return {
        "draws": repeats,
        "requested_by_index": requested,
        "drawn_by_index": drawn,
        "shortfall_by_index": shortfall,
        "total_shortfall": int(sum(shortfall.values())),
        "total_events_per_draw": int(sum(drawn.values())),
        "metrics": random_metrics,
    }


def _select_v2_variant(results: dict[str, Any]) -> dict[str, Any]:
    score_order = {score_name: index for index, score_name in enumerate(SCORE_NAMES)}
    eligible: list[dict[str, Any]] = []
    for state in V2_STATES:
        dev = results[state]["dev"]
        observed = dev["metrics"]["within5_60"]["value"]
        random_median = dev["random_baseline"]["metrics"]["within5_60"]["median"]
        if dev["n_events"] < 30 or observed is None or random_median is None:
            continue
        score_name, threshold = state.removeprefix("V2_").rsplit("_", 1)
        eligible.append(
            {
                "state": state,
                "score": score_name,
                "threshold": int(threshold),
                "dev_events": dev["n_events"],
                "dev_within5_60_share": observed,
                "dev_random_median_within5_60": random_median,
                "dev_lift": observed - random_median,
                "score_order": score_order[score_name],
            }
        )
    if not eligible:
        raise ValueError("no V2 variant has at least 30 dev events with valid random stats")
    selected = max(
        eligible,
        key=lambda row: (
            row["dev_lift"],
            row["threshold"],
            -row["score_order"],
        ),
    )
    selected = dict(selected)
    selected["eligible_variants"] = eligible
    selected["selection_rule"] = (
        "maximize dev within5_60 share minus random median; ties prefer higher "
        "threshold, then low_shock, short, medium"
    )
    return selected


def _verdict_for_state(state: str, results: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for segment in ("dev", "test"):
        row = results[state][segment]
        summary = row["metrics"]
        random = row["random_baseline"]["metrics"]
        observed_location = summary["within5_60"]["value"]
        random_location_p95 = random["within5_60"]["p95"]
        observed_mae = summary["MAE20"]["value"]
        random_mae_median = random["MAE20"]["median"]
        location_ok = (
            observed_location is not None
            and random_location_p95 is not None
            and observed_location > random_location_p95
        )
        mae_ok = (
            observed_mae is not None
            and random_mae_median is not None
            and observed_mae >= random_mae_median
        )
        checks[segment] = {
            "n_events": row["n_events"],
            "minimum_events_met": row["n_events"] >= 15,
            "within5_60_share": observed_location,
            "random_within5_60_p95": random_location_p95,
            "location_condition": bool(location_ok),
            "median_MAE20": observed_mae,
            "random_median_MAE20": random_mae_median,
            "mae_condition": bool(mae_ok),
            "win_R20_share": summary["win_R20"]["value"],
            "random_win_R20_p95": random["win_R20"]["p95"],
        }

    if checks["test"]["n_events"] < 15:
        verdict = "NOT_ESTABLISHED"
    elif all(
        checks[segment]["minimum_events_met"]
        and checks[segment]["location_condition"]
        and checks[segment]["mae_condition"]
        for segment in ("dev", "test")
    ):
        verdict = "VALID"
    else:
        verdict = "NOT_VALID"
    return_context = {
        segment: {
            "win_R20_share": checks[segment]["win_R20_share"],
            "random_win_R20_p95": checks[segment]["random_win_R20_p95"],
        }
        for segment in ("dev", "test")
    }
    return {
        "state": state,
        "verdict": verdict,
        "checks": checks,
        "return_context": return_context,
        "return_outcome_note": (
            "R20 win share versus random P95 is reported for dev and test but "
            "does not affect the verdict."
        ),
    }


def _bootstrap_difference(
    left_by_index: dict[str, list[dict[str, Any]]],
    right_by_index: dict[str, list[dict[str, Any]]],
    metric_name: str,
    rng: np.random.Generator,
    repeats: int = BOOTSTRAP_REPEATS,
) -> dict[str, Any]:
    left_events = [event for rows in left_by_index.values() for event in rows]
    right_events = [event for rows in right_by_index.values() for event in rows]
    left_point = _metric_statistic(left_events, metric_name)
    right_point = _metric_statistic(right_events, metric_name)
    if left_point is None or right_point is None:
        return {
            "difference": None,
            "ci95": [None, None],
            "left_events": len(left_events),
            "right_events": len(right_events),
            "statistic": "share" if metric_name in BOOLEAN_METRICS else "median",
            "bootstrap_draws": repeats,
        }

    differences: list[float] = []
    for _ in range(repeats):
        resampled_left: list[dict[str, Any]] = []
        resampled_right: list[dict[str, Any]] = []
        for symbol in left_by_index:
            left_rows = left_by_index[symbol]
            right_rows = right_by_index.get(symbol, [])
            if left_rows:
                indices = rng.integers(len(left_rows), size=len(left_rows))
                resampled_left.extend(left_rows[int(index)] for index in indices)
            if right_rows:
                indices = rng.integers(len(right_rows), size=len(right_rows))
                resampled_right.extend(right_rows[int(index)] for index in indices)
        left_value = _metric_statistic(resampled_left, metric_name)
        right_value = _metric_statistic(resampled_right, metric_name)
        if left_value is not None and right_value is not None:
            differences.append(left_value - right_value)
    lower, upper = np.quantile(differences, [0.025, 0.975])
    return {
        "difference": float(left_point - right_point),
        "ci95": [float(lower), float(upper)],
        "left_events": len(left_events),
        "right_events": len(right_events),
        "statistic": "share" if metric_name in BOOLEAN_METRICS else "median",
        "bootstrap_draws": repeats,
        "resampling": "with replacement within each index, preserving each state's index counts",
    }


def _candidate_positions(
    closes: np.ndarray, segment_labels: list[str]
) -> tuple[dict[str, list[int]], dict[str, dict[str, int]]]:
    dd252 = np.full(len(closes), np.nan, dtype=float)
    for position in range(DD_LOOKBACK - 1, len(closes)):
        trailing = closes[position - DD_LOOKBACK + 1 : position + 1]
        dd252[position] = float(closes[position] / np.max(trailing) - 1.0)

    candidates = {segment: [] for segment in SEGMENTS}
    diagnostics: dict[str, dict[str, int]] = {}
    for segment in SEGMENTS:
        segment_positions = [
            position for position, label in enumerate(segment_labels) if label == segment
        ]
        dd_pass_positions = [
            position
            for position in segment_positions
            if np.isfinite(dd252[position]) and dd252[position] <= DD_THRESHOLD
        ]
        valid_positions = [
            position
            for position in dd_pass_positions
            if label_window_valid(segment_labels, position)
        ]
        candidates[segment] = valid_positions
        diagnostics[segment] = {
            "sessions": len(segment_positions),
            "dd252_unavailable_sessions": sum(
                not np.isfinite(dd252[position]) for position in segment_positions
            ),
            "dd252_threshold_pass_days": len(dd_pass_positions),
            "label_window_excluded_days": len(dd_pass_positions) - len(valid_positions),
            "candidate_days": len(valid_positions),
        }
    return candidates, diagnostics


def _prepare_old50(
    dates: pd.Series, frames: list[dict[str, Any]]
) -> tuple[np.ndarray, list[float | None]]:
    frame_dates = [pd.Timestamp(frame["asof"]).normalize() for frame in frames]
    frame_scores = [score_100(frame) for frame in frames]
    if frame_dates != sorted(frame_dates):
        raise ValueError("weekly frame dates are not sorted")
    flags = np.zeros(len(dates), dtype=bool)
    scores: list[float | None] = [None] * len(dates)
    for position, date in enumerate(dates):
        is_signal, score = old50_signal(date, frame_dates, frame_scores)
        flags[position] = is_signal
        if is_signal:
            scores[position] = score
    return flags, scores


def _make_markdown_report(report: dict[str, Any]) -> str:
    def pct(value: float | None) -> str:
        return "—" if value is None else f"{100.0 * value:.1f}%"

    def number(value: float | None, digits: int = 3) -> str:
        return "—" if value is None else f"{value:.{digits}f}"

    def triple(values: dict[str, Any] | None, percent: bool) -> str:
        if values is None:
            return "—"
        format_value = pct if percent else number
        return " / ".join(format_value(values[key]) for key in ("median", "p5", "p95"))

    lines = [
        "# Bottom repair V2 price-score evaluation",
        "",
        "- Daily inputs: qfq OHLC from the local cache; weekly `fco_neg_intensity` frames are used only for OLD50.",
        "- Session segments: dev through 2018-12-31; cal 2019-01-01–2021-12-31; test 2022-01-01–2025-08-29; later sessions are live.",
        "- Candidate label windows require t−60 through t+61 to exist wholly inside the event segment. State events use a 20-session cooldown per index/state.",
        "- Outcomes use next-session open O(t+1); all prices are gross index prices with no costs. Indices are not tradable; ETF execution is a later round.",
        f"- Random baselines: {report['parameters']['random_repeats']} draws, seed {report['parameters']['seed']}; sample B0 events without replacement per index.",
        f"- Event ledger: `{report['event_ledger']['path']}`; rows={report['event_ledger']['row_count']}; SHA-256 of uncompressed CSV=`{report['event_ledger']['sha256_uncompressed_csv']}`.",
        f"- Runtime: {report['runtime_seconds']:.3f} seconds.",
        "",
        "## Per-state, per-segment results",
        "",
        "| State | Segment | Events | Within5_60 share | Random median / P5 / P95 | Median entry_dist_60 | Win R20 | Random win R20 P95 | Median R20 | Median MAE20 | Random median MAE20 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for state in STATES:
        for segment in SEGMENTS:
            row = report["results"][state][segment]
            metrics = row["metrics"]
            random_metrics = row["random_baseline"]["metrics"]
            lines.append(
                f"| {state} | {segment} | {row['n_events']} | "
                f"{pct(metrics['within5_60']['value'])} | "
                f"{triple(random_metrics['within5_60'], True)} | "
                f"{pct(metrics['entry_dist_60']['value'])} | "
                f"{pct(metrics['win_R20']['value'])} | "
                f"{pct(random_metrics['win_R20']['p95'])} | "
                f"{pct(metrics['R20']['value'])} | "
                f"{pct(metrics['MAE20']['value'])} | "
                f"{pct(random_metrics['MAE20']['median'])} |"
            )

    lines.extend(
        [
            "",
            "## Per-index candidate and event counts",
            "",
            "Each event column is the independent event count for that index and segment.",
        ]
    )
    for segment in SEGMENTS:
        lines.extend(
            [
                "",
                f"### {segment}",
                "",
                "| Index | Candidate days | " + " | ".join(STATES) + " |",
                "|---|---:|" + "---:|" * len(STATES),
            ]
        )
        for symbol, _, _ in INDEX_LIST:
            counts = report["per_index_counts"][symbol]["segments"][segment]
            event_counts = counts["events"]
            lines.append(
                f"| {symbol} | {counts['candidate_days']} | "
                + " | ".join(str(event_counts[state]) for state in STATES)
                + " |"
            )

    selection = report["selection"]
    lines.extend(
        [
            "",
            "## Dev-only V2 selection",
            "",
            f"**Selected: {selection['state']}**; dev events={selection['dev_events']}; "
            f"within5_60={pct(selection['dev_within5_60_share'])}; "
            f"random median={pct(selection['dev_random_median_within5_60'])}; "
            f"lift={pct(selection['dev_lift'])}.",
            "",
            "Selection maximizes dev within5_60 share minus its random median among variants with at least 30 dev events; ties prefer higher T, then low_shock, short, medium.",
            "",
            "## Verdicts",
            "",
            "| State | Verdict | Dev within5_60 / random P95 | Dev median MAE20 / random median | Test within5_60 / random P95 | Test median MAE20 / random median | Win R20 / random P95 (dev; test, report only) |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for state, verdict in report["verdicts"].items():
        dev = verdict["checks"]["dev"]
        test = verdict["checks"]["test"]
        return_context = verdict["return_context"]
        lines.append(
            f"| {state} | {verdict['verdict']} | "
            f"{pct(dev['within5_60_share'])} / {pct(dev['random_within5_60_p95'])} | "
            f"{pct(dev['median_MAE20'])} / {pct(dev['random_median_MAE20'])} | "
            f"{pct(test['within5_60_share'])} / {pct(test['random_within5_60_p95'])} | "
            f"{pct(test['median_MAE20'])} / {pct(test['random_median_MAE20'])} | "
            f"{pct(return_context['dev']['win_R20_share'])} / "
            f"{pct(return_context['dev']['random_win_R20_p95'])}; "
            f"{pct(return_context['test']['win_R20_share'])} / "
            f"{pct(return_context['test']['random_win_R20_p95'])} |"
        )
    lines.extend(
        [
            "",
            "Verdict rule: VALID requires both dev and test to have at least 15 events, within5_60 strictly above random P95, and median MAE20 at least the random median. Test events below 15 yields NOT_ESTABLISHED. R20 win-rate comparisons are report-only.",
            "",
            "## Head-to-head: selected V2 minus OLD50",
            "",
            "| Segment | Metric | V2−OLD50 | 95% bootstrap CI | V2 events | OLD50 events |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for segment, rows in report["head_to_head"].items():
        for metric_name, row in rows.items():
            ci = row["ci95"]
            ci_text = (
                "—" if ci[0] is None or ci[1] is None else f"[{number(ci[0])}, {number(ci[1])}]"
            )
            lines.append(
                f"| {segment} | {metric_name} | {number(row['difference'])} | "
                f"{ci_text} | {row['left_events']} | {row['right_events']} |"
            )

    lines.extend(
        [
            "",
            "## Data coverage and exclusions",
            "",
            "| Index | Raw OHLC rows | Duplicate rows dropped | Invalid OHLC rows dropped | Valid rows | Date range | Dev / Cal / Test / Live sessions |",
            "|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for symbol, _, _ in INDEX_LIST:
        metadata = report["inputs"]["indexes"][symbol]["daily"]
        index_counts = report["per_index_counts"][symbol]
        counts = index_counts["segments"]
        session_counts = " / ".join(
            [
                *(str(counts[segment]["sessions"]) for segment in SEGMENTS),
                str(index_counts["live_sessions"]),
            ]
        )
        lines.append(
            f"| {symbol} | {metadata['raw_rows']} | {metadata['duplicate_rows_dropped']} | "
            f"{metadata['invalid_ohlc_rows_dropped']} | {metadata['valid_rows']} | "
            f"{metadata['first_date']}–{metadata['last_date']} | {session_counts} |"
        )
    lines.extend(
        [
            "",
            "Candidate diagnostics (DD252 pass days, label-window exclusions, final candidates) and missing V2-score counts are in the JSON per-index ledger. Random-baseline shortfalls are recorded per state/segment/index in the JSON.",
            "",
        ]
    )
    return "\n".join(lines)


def run_study(
    cache_root: Path = DEFAULT_CACHE_ROOT,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> dict[str, Any]:
    started = time.perf_counter()
    inputs_by_index: dict[str, Any] = {}
    per_index_counts: dict[str, Any] = {}
    events_by_state: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = {
        state: {segment: {symbol: [] for symbol, _, _ in INDEX_LIST} for segment in SEGMENTS}
        for state in STATES
    }
    event_ledger: list[dict[str, Any]] = []

    for symbol, _, _ in INDEX_LIST:
        daily, daily_metadata = _load_daily_ohlc(symbol, cache_root)
        frames, frame_metadata = _load_frames(data_dir, symbol)
        dates = daily["date"]
        segment_labels = [segment_for_date(date) for date in dates]
        opens = daily["open"].to_numpy(dtype=float)
        highs = daily["high"].to_numpy(dtype=float)
        lows = daily["low"].to_numpy(dtype=float)
        closes = daily["close"].to_numpy(dtype=float)
        features = compute_features(highs, lows, closes)
        candidates, diagnostics = _candidate_positions(closes, segment_labels)
        old50_flags, old50_scores = _prepare_old50(dates, frames)
        stopfall_flags = np.asarray(
            [
                stopfall_signal(position, closes, lows, features["ema20"])
                for position in range(len(daily))
            ],
            dtype=bool,
        )
        candidate_all = sorted(
            position for positions in candidates.values() for position in positions
        )
        candidate_diagnostics: dict[str, Any] = {}
        for segment in SEGMENTS:
            positions = candidates[segment]
            candidate_diagnostics[segment] = {
                **diagnostics[segment],
                "missing_v2_score_days_by_score": {
                    score_name: sum(
                        not np.isfinite(features["scores"][score_name][position])
                        for position in positions
                    )
                    for score_name in SCORE_NAMES
                },
                "old50_unavailable_or_stale_candidate_days": sum(
                    not old50_flags[position] for position in positions
                ),
                "state_signal_days": {},
                "events": {},
            }

        state_flags: dict[str, np.ndarray] = {}
        score_for_state: dict[str, np.ndarray | None] = {}
        for score_name in SCORE_NAMES:
            for threshold in THRESHOLDS:
                state = f"V2_{score_name}_{threshold}"
                score_array = features["scores"][score_name]
                state_flags[state] = np.isfinite(score_array) & (score_array >= threshold)
                score_for_state[state] = score_array
        state_flags["OLD50"] = old50_flags
        score_for_state["OLD50"] = np.asarray(
            [np.nan if score is None else score for score in old50_scores],
            dtype=float,
        )
        state_flags["STOPFALL"] = stopfall_flags
        score_for_state["STOPFALL"] = None
        state_flags["B0"] = np.ones(len(daily), dtype=bool)
        score_for_state["B0"] = None

        for state in STATES:
            flags = state_flags[state]
            signal_days_by_segment: dict[str, int] = {}
            for segment in SEGMENTS:
                signal_days_by_segment[segment] = sum(
                    bool(flags[position]) for position in candidates[segment]
                )
            for segment in SEGMENTS:
                candidate_diagnostics[segment]["state_signal_days"][state] = signal_days_by_segment[
                    segment
                ]
            event_positions = select_state_positions(candidate_all, flags)
            for position in event_positions:
                segment = segment_labels[position]
                metrics = event_metrics(position, opens, highs, lows, closes)
                if metrics is None:
                    raise AssertionError(
                        f"{symbol}/{state}/{dates.iloc[position].date()}: "
                        "candidate has invalid label window"
                    )
                score_array = score_for_state[state]
                score_value = (
                    None
                    if score_array is None or not np.isfinite(score_array[position])
                    else float(score_array[position])
                )
                event = {
                    "symbol": symbol,
                    "date": dates.iloc[position].strftime("%Y-%m-%d"),
                    "segment": segment,
                    "state": state,
                    "score": score_value,
                    "metrics": metrics,
                }
                events_by_state[state][segment][symbol].append(event)
                event_ledger.append(event)

        for segment in SEGMENTS:
            candidate_diagnostics[segment]["events"] = {
                state: len(events_by_state[state][segment][symbol]) for state in STATES
            }
        inputs_by_index[symbol] = {
            "daily": daily_metadata,
            "weekly_frames": frame_metadata,
        }
        per_index_counts[symbol] = {
            "segments": candidate_diagnostics,
            "live_sessions": int(sum(label == "live" for label in segment_labels)),
        }

    rng = np.random.default_rng(SEED)
    results: dict[str, Any] = {}
    for state in STATES:
        results[state] = {}
        for segment in SEGMENTS:
            state_by_index = events_by_state[state][segment]
            b0_by_index = events_by_state["B0"][segment]
            all_events = [event for symbol, _, _ in INDEX_LIST for event in state_by_index[symbol]]
            results[state][segment] = {
                **_summarize_events(all_events),
                "n_events_by_index": {
                    symbol: len(state_by_index[symbol]) for symbol, _, _ in INDEX_LIST
                },
                "random_baseline": _random_baseline(state_by_index, b0_by_index, rng),
            }

    selection = _select_v2_variant(results)
    verdict_states = (selection["state"], "OLD50", "STOPFALL")
    verdicts = {state: _verdict_for_state(state, results) for state in verdict_states}
    bootstrap_rng = np.random.default_rng(SEED)
    head_to_head: dict[str, Any] = {}
    selected_state = selection["state"]
    for segment in ("dev", "test"):
        selected_by_index = events_by_state[selected_state][segment]
        old50_by_index = events_by_state["OLD50"][segment]
        head_to_head[segment] = {
            "within5_60_share": _bootstrap_difference(
                selected_by_index,
                old50_by_index,
                "within5_60",
                bootstrap_rng,
            ),
            "median_R20": _bootstrap_difference(
                selected_by_index,
                old50_by_index,
                "R20",
                bootstrap_rng,
            ),
        }

    runtime = time.perf_counter() - started
    return {
        "study": "bottom_repair_v2_eval",
        "parameters": {
            "seed": SEED,
            "random_repeats": RANDOM_REPEATS,
            "bootstrap_repeats": BOOTSTRAP_REPEATS,
            "dd_lookback_sessions": DD_LOOKBACK,
            "dd_threshold": DD_THRESHOLD,
            "label_lookback_sessions": LABEL_LOOKBACK,
            "label_forward_sessions": LABEL_FORWARD,
            "event_cooldown_sessions": EVENT_COOLDOWN,
            "old50_max_age_calendar_days": OLD50_MAX_AGE_DAYS,
            "horizons": list(HORIZONS),
            "location_windows": list(LOCATION_WINDOWS),
            "segments": {
                "dev_end_inclusive": "2018-12-31",
                "cal_start": "2019-01-01",
                "cal_end_inclusive": "2021-12-31",
                "test_start": "2022-01-01",
                "test_end_inclusive": "2025-08-29",
                "later": "live",
            },
            "states": list(STATES),
            "v2_thresholds": list(THRESHOLDS),
        },
        "inputs": {
            "cache_root": str(cache_root),
            "weekly_data_dir": str(data_dir),
            "price_source": "research.data.cache.load(adjust='qfq', auto_refresh=False)",
            "price_type": "gross index prices; no costs; indices are not tradable",
            "indexes": inputs_by_index,
        },
        "per_index_counts": per_index_counts,
        "results": results,
        "selection": selection,
        "verdicts": verdicts,
        "head_to_head": head_to_head,
        "event_ledger": sorted(
            event_ledger, key=lambda row: (row["symbol"], row["date"], row["state"])
        ),
        "runtime_seconds": float(runtime),
    }


def write_event_ledger(events: list[dict[str, Any]], path: Path) -> dict[str, Any]:
    ordered_events = sorted(
        events,
        key=lambda row: (row["state"], row["segment"], row["symbol"], row["date"]),
    )
    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        csv_buffer,
        fieldnames=LEDGER_COLUMNS,
        lineterminator="\n",
    )
    writer.writeheader()
    for event in ordered_events:
        row = {
            "state": event["state"],
            "segment": event["segment"],
            "symbol": event["symbol"],
            "date": event["date"],
            "score": event["score"],
            **event["metrics"],
        }
        writer.writerow(row)

    csv_bytes = csv_buffer.getvalue().encode("utf-8")
    compressed_buffer = io.BytesIO()
    with gzip.GzipFile(
        fileobj=compressed_buffer,
        filename="",
        mode="wb",
        compresslevel=9,
        mtime=0,
    ) as compressed_file:
        compressed_file.write(csv_bytes)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(compressed_buffer.getvalue())
    return {
        "path": path.name,
        "row_count": len(ordered_events),
        "sha256_uncompressed_csv": hashlib.sha256(csv_bytes).hexdigest(),
    }


def report_without_event_rows(
    report: dict[str, Any], ledger_reference: dict[str, Any]
) -> dict[str, Any]:
    compact_report = {key: value for key, value in report.items() if key != "event_ledger"}
    compact_report["event_ledger"] = ledger_reference
    return compact_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()

    report = run_study(args.cache_root, args.data_dir)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.report_dir / "bottom_repair_v2_eval.json"
    markdown_path = args.report_dir / "bottom_repair_v2_eval.md"
    ledger_path = args.report_dir / "bottom_repair_v2_eval_events.csv.gz"
    ledger_reference = write_event_ledger(report["event_ledger"], ledger_path)
    report = report_without_event_rows(report, ledger_reference)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_make_markdown_report(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    print(f"Runtime: {report['runtime_seconds']:.3f} seconds")


if __name__ == "__main__":
    main()
