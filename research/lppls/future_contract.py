from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Literal, Sequence

import numpy as np

from ..optim.optimizers import tcgrid_lm
from .core import K_LPPLS, MIN_DT, design, lin_fit

CONTRACT_VERSION = "future_fullcycles_1p5_v1"
FIT_HORIZON_FRACTION = 0.2
EVAL_H = 63


def log_price_from_price(price: Sequence[float] | np.ndarray) -> np.ndarray:
    values = np.asarray(price, dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("price must contain only finite positive values")
    return np.log(values)


@dataclass(frozen=True)
class LogPrice:
    values: tuple[float, ...]
    constructed_from: Literal["price", "log_price"]
    source_field: str | None = None
    adjustment_type: str | None = None

    @classmethod
    def from_price(
        cls,
        price: Sequence[float] | np.ndarray,
        *,
        source_field: str | None = None,
        adjustment_type: str | None = None,
    ) -> LogPrice:
        values = log_price_from_price(price)
        if values.ndim != 1:
            raise ValueError("price must be one-dimensional")
        return cls(tuple(float(value) for value in values), "price", source_field, adjustment_type)

    @classmethod
    def from_log_price(
        cls,
        log_price: Sequence[float] | np.ndarray,
        *,
        source_field: str | None = None,
        adjustment_type: str | None = None,
    ) -> LogPrice:
        values = np.asarray(log_price, dtype=float)
        if values.ndim != 1 or not np.isfinite(values).all():
            raise ValueError("log_price must be one-dimensional and finite")
        return cls(tuple(float(value) for value in values), "log_price", source_field, adjustment_type)

    def as_array(self) -> np.ndarray:
        return np.asarray(self.values, dtype=float)

    def to_dict(self) -> dict[str, Any]:
        return {
            "values": list(self.values),
            "constructed_from": self.constructed_from,
            "source_field": self.source_field,
            "adjustment_type": self.adjustment_type,
        }


def cycles_full(w: float, tc: float, t1: float, t2: float) -> float:
    if not all(math.isfinite(value) for value in (w, tc, t1, t2)):
        return math.nan
    if t1 >= t2:
        raise ValueError("t1 must be earlier than t2")
    if tc <= t2:
        return math.nan
    return w / (2.0 * math.pi) * math.log((tc - t1) / (tc - t2))


def legacy_osc_to_full_cycles(osc: float) -> float:
    return osc / math.pi


@dataclass(frozen=True)
class SearchBounds:
    m: tuple[float, float] = (0.01, 2.0)
    omega: tuple[float, float] = (1.0, 50.0)
    tc_min_offset: float = MIN_DT
    tc_max_offset_fraction: float = FIT_HORIZON_FRACTION
    tc_relation: str = "tc > t2"
    allow_inside: bool = False
    solver: str = "tcgrid_lm"
    budget: tuple[int, int, int, int] = (40, 12, 16, 5)
    n_random: int = 10
    seed: int = 0
    boundary_tolerance_fraction: float = 1e-6
    least_squares: tuple[tuple[str, float | int | str], ...] = (
        ("method", "trf"),
        ("x_scale", "jac"),
        ("ftol", 1e-12),
        ("xtol", 1e-12),
        ("gtol", 1e-10),
        ("max_nfev", 400),
    )

    def __post_init__(self) -> None:
        if not self.m[0] < self.m[1] or not self.omega[0] < self.omega[1]:
            raise ValueError("search bounds must be increasing")
        if self.tc_min_offset <= 0 or self.tc_max_offset_fraction <= 0:
            raise ValueError("future tc offsets must be positive")
        if self.allow_inside:
            raise ValueError("future-only search bounds cannot allow inside tc")
        if len(self.budget) != 4 or any(value <= 0 for value in self.budget):
            raise ValueError("tcgrid_lm budget must have four positive values")

    @property
    def budget_dict(self) -> dict[str, int]:
        return dict(zip(("n_tc", "n_m", "n_w", "topk"), self.budget, strict=True))

    def numeric_bounds(self, t1: float, t2: float) -> tuple[np.ndarray, np.ndarray]:
        if t1 >= t2:
            raise ValueError("t1 must be earlier than t2")
        dt = t2 - t1
        tc_lo = t2 + self.tc_min_offset
        tc_hi = t2 + self.tc_max_offset_fraction * dt
        if tc_lo > tc_hi:
            raise ValueError("window is too short for the registered future tc domain")
        return (
            np.asarray([tc_lo, self.m[0], self.omega[0]], dtype=float),
            np.asarray([tc_hi, self.m[1], self.omega[1]], dtype=float),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "m": list(self.m),
            "omega": list(self.omega),
            "tc_lower_formula": "t2 + MIN_DT",
            "tc_upper_formula": "t2 + 0.2 * (t2 - t1)",
            "tc_min_offset": self.tc_min_offset,
            "tc_max_offset_fraction": self.tc_max_offset_fraction,
            "tc_relation": self.tc_relation,
            "allow_inside": self.allow_inside,
            "solver": self.solver,
            "budget": self.budget_dict,
            "n_random": self.n_random,
            "seed": self.seed,
            "boundary_tolerance_fraction": self.boundary_tolerance_fraction,
            "least_squares": dict(self.least_squares),
        }


@dataclass(frozen=True)
class FilterBounds:
    primary_column: str = "g_fco_standard"
    headline_status_field: str = "top.signal_status"
    scales: tuple[tuple[str, int, int], ...] = (
        ("1-3m", 21, 63),
        ("6-12m", 127, 252),
        ("12-24m", 253, 504),
    )
    aggregation: str = "any scale has at least one standard-qualified window"
    direction: str = "B < 0"
    m_min: float = 0.0
    m_min_inclusive: bool = False
    m_max: float = 1.0
    m_max_inclusive: bool = True
    omega: tuple[float, float] = (2.0, 25.0)
    damping_min: float = 0.5
    damping_formula: str = "m * abs(B) / (omega * hypot(C1, C2))"
    zero_amplitude_damping: str = "positive infinity when hypot(C1, C2) == 0, matching _derived"
    tc_relation: str = "tc > t2"
    cycles_full_min: float = 1.5
    cycles_tolerance: float = 1e-12
    r2_min: float | None = None
    rel_err_max: float | None = None
    horizon: tuple[float, float] | None = None
    legacy_osc_min_replaced: float = 2.5
    non_headline_columns: tuple[str, ...] = (
        "g_fco_early",
        "g_fco_end",
        "g_fco_pure",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_column": self.primary_column,
            "headline_status_field": self.headline_status_field,
            "scales": [{"name": name, "L_min": low, "L_max": high} for name, low, high in self.scales],
            "aggregation": self.aggregation,
            "direction": self.direction,
            "m": {
                "min": self.m_min,
                "min_inclusive": self.m_min_inclusive,
                "max": self.m_max,
                "max_inclusive": self.m_max_inclusive,
            },
            "omega": list(self.omega),
            "damping_min": self.damping_min,
            "damping_formula": self.damping_formula,
            "zero_amplitude_damping": self.zero_amplitude_damping,
            "tc_relation": self.tc_relation,
            "cycles_full_min": self.cycles_full_min,
            "cycles_tolerance": self.cycles_tolerance,
            "r2_min": self.r2_min,
            "rel_err_max": self.rel_err_max,
            "horizon": list(self.horizon) if self.horizon is not None else None,
            "legacy_osc_min_replaced": self.legacy_osc_min_replaced,
            "non_headline_columns": list(self.non_headline_columns),
        }


DEFAULT_SEARCH_BOUNDS = SearchBounds()
DEFAULT_FILTER_BOUNDS = FilterBounds()


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def cache_key(
    *,
    data_hash: str,
    asof: str,
    window_start: str | int,
    window_end: str | int,
    lookback_L: int,
    clock_map: Sequence[int],
    search_bounds: SearchBounds = DEFAULT_SEARCH_BOUNDS,
    filter_bounds: FilterBounds = DEFAULT_FILTER_BOUNDS,
    solver: str | None = None,
    budget: dict[str, int] | None = None,
    n_random: int | None = None,
    seed: int | None = None,
) -> str:
    if len(data_hash) != 64 or any(char not in "0123456789abcdefABCDEF" for char in data_hash):
        raise ValueError("data_hash must be a SHA-256 hex digest")
    clock_map_hash = hashlib.sha256(canonical_json(list(clock_map)).encode("utf-8")).hexdigest()
    payload = {
        "data_hash": data_hash.lower(),
        "asof": asof,
        "window": {"start": window_start, "end": window_end, "L": lookback_L},
        "clock_map_hash": clock_map_hash,
        "domain": "future_only",
        "units": "full_cycles",
        "search_bounds": search_bounds.to_dict(),
        "filter_bounds": filter_bounds.to_dict(),
        "solver": {
            "name": solver or search_bounds.solver,
            "budget": budget or search_bounds.budget_dict,
            "n_random": search_bounds.n_random if n_random is None else n_random,
        },
        "contract_version": CONTRACT_VERSION,
        "seed": search_bounds.seed if seed is None else seed,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def session_indices_for_bars(bar_dates: Sequence[str], calendar: Sequence[str]) -> tuple[int, ...]:
    normalized_calendar = [str(value)[:10] for value in calendar]
    if len(set(normalized_calendar)) != len(normalized_calendar):
        raise ValueError("calendar dates must be unique")
    positions = {day: index for index, day in enumerate(normalized_calendar)}
    normalized_bars = [str(value)[:10] for value in bar_dates]
    try:
        result = tuple(positions[day] for day in normalized_bars)
    except KeyError as exc:
        raise ValueError(f"bar date is not present in the session calendar: {exc.args[0]}") from exc
    if any(right <= left for left, right in zip(result, result[1:])):
        raise ValueError("bar dates must map to strictly increasing session indices")
    return result


def inclusive_width_sessions(a: int, b: int) -> int:
    if b < a:
        raise ValueError("session interval end must be >= start")
    return b - a + 1


@dataclass(frozen=True)
class FilterOutcome:
    status: Literal["pass", "reject", "not_evaluated"]
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reasons": list(self.reasons)}


@dataclass(frozen=True)
class Attempt:
    attempt_id: str
    cache_key: str
    seed: int
    retry_idx: int
    status: Literal["success", "invalid", "numerical_failure", "pending"]
    theta: tuple[float, ...] | None
    beta: tuple[float, ...] | None
    sse: float | None
    finite: bool
    boundary_hits: tuple[tuple[str, bool], ...]
    design_rank: int | None
    condition_number: float | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "cache_key": self.cache_key,
            "seed": self.seed,
            "retry_idx": self.retry_idx,
            "status": self.status,
            "theta": list(self.theta) if self.theta is not None else None,
            "beta": list(self.beta) if self.beta is not None else None,
            "sse": self.sse,
            "finite": self.finite,
            "boundary_hits": dict(self.boundary_hits),
            "design_rank": self.design_rank,
            "condition_number": self.condition_number,
            "error": self.error,
        }


@dataclass(frozen=True)
class WindowResult:
    status: Literal["fit_ok", "all_attempts_failed", "pending"]
    attempts: tuple[Attempt, ...]
    filter_outcome: FilterOutcome
    data_hash: str
    asof: str
    window_start: str | int
    window_end: str | int
    lookback_L: int
    fit_horizon: float
    eval_H: int
    label_confirmation_E: int | None
    fit_clock: str
    bar_to_session_index: tuple[int, ...]
    t1: float
    t2: float
    tc_offset_bars: float | None
    input_log_price_source: Literal["price", "log_price"]
    input_source_field: str | None
    input_adjustment_type: str | None
    contract_version: str = CONTRACT_VERSION
    domain: str = "future_only"
    units: str = "full_cycles"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "attempt_count": len(self.attempts),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "filter_outcome": self.filter_outcome.to_dict(),
            "data_hash": self.data_hash,
            "asof": self.asof,
            "window": {"start": self.window_start, "end": self.window_end, "L": self.lookback_L},
            "lookback_L": self.lookback_L,
            "fit_horizon": self.fit_horizon,
            "eval_H": self.eval_H,
            "label_confirmation_E": self.label_confirmation_E,
            "fit_clock": self.fit_clock,
            "bar_to_session_index": list(self.bar_to_session_index),
            "t1": self.t1,
            "t2": self.t2,
            "tc_offset_bars": self.tc_offset_bars,
            "input_log_price_source": self.input_log_price_source,
            "input_source_field": self.input_source_field,
            "input_adjustment_type": self.input_adjustment_type,
            "contract_version": self.contract_version,
            "domain": self.domain,
            "units": self.units,
        }


def _attempt_id(key: str, seed: int, retry_idx: int) -> str:
    return hashlib.sha256(f"{key}:{seed}:{retry_idx}".encode("ascii")).hexdigest()


def _boundary_hits(theta: np.ndarray, lo: np.ndarray, hi: np.ndarray, tolerance_fraction: float) -> tuple[tuple[str, bool], ...]:
    names = ("tc", "m", "omega")
    hits = []
    for index, name in enumerate(names):
        tolerance = tolerance_fraction * max(float(hi[index] - lo[index]), 1.0)
        hits.append((name, bool(abs(theta[index] - lo[index]) <= tolerance or abs(theta[index] - hi[index]) <= tolerance)))
    return tuple(hits)


def _design_diagnostics(t: np.ndarray, theta: np.ndarray) -> tuple[int, float | None]:
    matrix = design(t, float(theta[0]), float(theta[1]), float(theta[2]), allow_inside=False)
    if matrix is None or not np.isfinite(matrix).all():
        return 0, None
    singular_values = np.linalg.svd(matrix, compute_uv=False)
    if not np.isfinite(singular_values).all() or singular_values.size == 0:
        return 0, None
    tolerance = max(matrix.shape) * np.finfo(float).eps * singular_values[0]
    rank = int(np.count_nonzero(singular_values > tolerance))
    condition = float(singular_values[0] / singular_values[-1]) if singular_values[-1] > 0 else None
    if condition is not None and not math.isfinite(condition):
        condition = None
    return rank, condition


def evaluate_filter(
    theta: np.ndarray,
    beta: np.ndarray,
    fit_sse: float,
    t1: float,
    t2: float,
    bounds: FilterBounds,
) -> FilterOutcome:
    tc, m, omega = map(float, theta)
    A, B, C1, C2 = map(float, beta)
    damping_denom = omega * math.hypot(C1, C2)
    damping = m * abs(B) / damping_denom if damping_denom != 0 else math.inf
    cycles = cycles_full(omega, tc, t1, t2)
    values = (tc, m, omega, A, B, C1, C2, fit_sse, cycles)
    reasons: list[str] = []
    if not all(math.isfinite(value) for value in values):
        reasons.append("non_finite")
    if tc <= t2:
        reasons.append("tc_not_future")
    if not B < 0:
        reasons.append("direction")
    if not (m > bounds.m_min if not bounds.m_min_inclusive else m >= bounds.m_min):
        reasons.append("m")
    if not (m <= bounds.m_max if bounds.m_max_inclusive else m < bounds.m_max):
        reasons.append("m")
    if not bounds.omega[0] <= omega <= bounds.omega[1]:
        reasons.append("omega")
    if math.isnan(damping):
        reasons.append("non_finite")
    if damping < bounds.damping_min:
        reasons.append("damping")
    if not math.isfinite(cycles) or (
        cycles < bounds.cycles_full_min
        and not math.isclose(cycles, bounds.cycles_full_min, rel_tol=bounds.cycles_tolerance, abs_tol=bounds.cycles_tolerance)
    ):
        reasons.append("cycles_full")
    unique_reasons = tuple(dict.fromkeys(reasons))
    return FilterOutcome("pass" if not unique_reasons else "reject", unique_reasons)


def fit_window(
    log_price: LogPrice,
    *,
    data_hash: str,
    asof: str,
    window_start: str | int,
    window_end: str | int,
    lookback_L: int,
    bar_to_session_index: Sequence[int],
    search_bounds: SearchBounds = DEFAULT_SEARCH_BOUNDS,
    filter_bounds: FilterBounds = DEFAULT_FILTER_BOUNDS,
    seed_retries: Sequence[tuple[int, int]] = ((0, 0),),
    eval_H: int = EVAL_H,
    label_confirmation_E: int | None = None,
    execute: bool = True,
) -> WindowResult:
    if not isinstance(log_price, LogPrice):
        raise TypeError("fit_window requires LogPrice; choose from_price or from_log_price explicitly")
    values = log_price.as_array()
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all():
        raise ValueError("window log prices must be a non-empty finite vector")
    if lookback_L != len(values) or len(bar_to_session_index) != len(values):
        raise ValueError("lookback_L and session mapping must match the window length")
    session_map = tuple(int(value) for value in bar_to_session_index)
    if any(right <= left for left, right in zip(session_map, session_map[1:])):
        raise ValueError("bar_to_session_index must be strictly increasing")
    t1, t2 = 0.0, float(lookback_L - 1)
    lo, hi = search_bounds.numeric_bounds(t1, t2)
    t = np.arange(lookback_L, dtype=float)
    attempts: list[Attempt] = []
    candidates: list[tuple[Attempt, np.ndarray]] = []
    for seed, retry_idx in seed_retries:
        if retry_idx < 0:
            raise ValueError("retry_idx must be non-negative")
        key = cache_key(
            data_hash=data_hash,
            asof=asof,
            window_start=window_start,
            window_end=window_end,
            lookback_L=lookback_L,
            clock_map=session_map,
            search_bounds=search_bounds,
            filter_bounds=filter_bounds,
            seed=seed,
        )
        attempt_id = _attempt_id(key, seed, retry_idx)
        if not execute:
            attempts.append(
                Attempt(attempt_id, key, seed, retry_idx, "pending", None, None, None, False, (), None, None)
            )
            continue
        try:
            result = tcgrid_lm(
                t,
                values,
                lo,
                hi,
                seed=seed,
                budget=search_bounds.budget_dict,
                k=K_LPPLS,
                n_random=search_bounds.n_random,
                allow_inside=False,
            )
            theta = np.asarray(result.theta, dtype=float)
            fit_sse = float(result.sse)
            if theta.shape != (3,) or not np.isfinite(theta).all() or not math.isfinite(fit_sse):
                stored_sse = fit_sse if math.isfinite(fit_sse) else None
                attempts.append(
                    Attempt(attempt_id, key, seed, retry_idx, "numerical_failure", None, None, stored_sse, False, (), None, None,
                            "optimizer returned non-finite parameters or SSE")
                )
                continue
            if theta[0] <= t2:
                attempts.append(
                    Attempt(attempt_id, key, seed, retry_idx, "invalid", tuple(map(float, theta)), None, fit_sse, True, (), None, None,
                            "optimizer returned tc <= t2 for a future-only fit")
                )
                continue
            beta_sse, beta = lin_fit(t, values, *theta, allow_inside=False)
            if beta is None or not np.isfinite(beta).all() or not math.isfinite(float(beta_sse)):
                attempts.append(
                    Attempt(attempt_id, key, seed, retry_idx, "numerical_failure", tuple(map(float, theta)), None, fit_sse, False, (), None, None,
                            "linear design fit returned non-finite coefficients or SSE")
                )
                continue
            beta = np.asarray(beta, dtype=float)
            rank, condition = _design_diagnostics(t, theta)
            attempt = Attempt(
                attempt_id,
                key,
                seed,
                retry_idx,
                "success",
                tuple(map(float, theta)),
                tuple(map(float, beta)),
                fit_sse,
                True,
                _boundary_hits(theta, lo, hi, search_bounds.boundary_tolerance_fraction),
                rank,
                condition,
            )
            attempts.append(attempt)
            candidates.append((attempt, beta))
        except Exception as exc:  # noqa: BLE001
            attempts.append(
                Attempt(attempt_id, key, seed, retry_idx, "numerical_failure", None, None, None, False, (), None, None,
                        f"{type(exc).__name__}: {exc}")
            )

    best = min(candidates, key=lambda pair: pair[0].sse) if candidates else None
    if best is not None:
        best_attempt, beta = best
        filter_outcome = evaluate_filter(
            np.asarray(best_attempt.theta, dtype=float),
            beta,
            float(best_attempt.sse),
            t1,
            t2,
            filter_bounds,
        )
        status: Literal["fit_ok", "all_attempts_failed", "pending"] = "fit_ok"
        tc_offset_bars = float(best_attempt.theta[0] - t2)
    elif attempts and any(attempt.status == "pending" for attempt in attempts):
        filter_outcome = FilterOutcome("not_evaluated", ())
        status = "pending"
        tc_offset_bars = None
    elif attempts:
        filter_outcome = FilterOutcome("not_evaluated", ())
        status = "all_attempts_failed"
        tc_offset_bars = None
    else:
        filter_outcome = FilterOutcome("not_evaluated", ())
        status = "pending"
        tc_offset_bars = None
    return WindowResult(
        status,
        tuple(attempts),
        filter_outcome,
        data_hash,
        asof,
        window_start,
        window_end,
        lookback_L,
        search_bounds.tc_max_offset_fraction * (t2 - t1),
        eval_H,
        label_confirmation_E,
        "effective_bars",
        session_map,
        t1,
        t2,
        tc_offset_bars,
        log_price.constructed_from,
        log_price.source_field,
        log_price.adjustment_type,
    )
