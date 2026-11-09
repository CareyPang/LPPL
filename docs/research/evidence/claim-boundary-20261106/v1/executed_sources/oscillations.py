"""Explicit oscillation units for audits of stored LPPLS fits (no fitting).

``osc_cycles`` counts complete log-periodic cycles in a window [t1, t2]
strictly before tc. A past/in-window tc is not a new advance forecast and
receives NaN, not an absolute-value extension across the singularity.

Historical research ``osc`` is a half-phase statistic, nominally pi times
the cycle count. Its abs()/1e-3 clipping is retained at its original call
sites. In the future domain with clipping inactive, old ``osc >= 2.5``
corresponds to cycles >= 2.5/pi, NOT 2.5 cycles. Even a pure unit conversion
can round a value across a floating-point threshold: reproduce the legacy
decision in the original units and expose converted comparisons separately.
"""
from __future__ import annotations

import numpy as np

OSC_UNITS_VERSION = "future_cycles_v1"
LEGACY_OSC_VERSION = "legacy_abs_clipped_half_phase_v1"
LEGACY_HALF_PHASE_THRESHOLD = 2.5
LEGACY_EQUIVALENT_CYCLE_THRESHOLD = LEGACY_HALF_PHASE_THRESHOLD / np.pi


def future_oscillations(tc, omega, t1=0.0, *, t2) -> tuple[np.ndarray, np.ndarray]:
    """Return broadcast arrays (cycles, status); scalar inputs give 0-D arrays.

    N = omega/(2*pi) * log((tc-t1)/(tc-t2)). Inputs must be finite,
    omega > 0, and t1 < t2 < tc. Status is ``ok`` or one of
    ``nonfinite_input``, ``invalid_window``, ``nonpositive_frequency``,
    ``not_future``, ``numerical_failure`` (in that validation order).
    Invalid counts are NaN. ``log1p`` avoids cancellation for distant tc;
    no denominator floor or absolute-value continuation is applied.
    """
    tc, omega, t1, t2 = np.broadcast_arrays(
        *[np.asarray(value, dtype=float) for value in (tc, omega, t1, t2)]
    )
    cycles = np.full(tc.shape, np.nan, dtype=float)
    status = np.full(tc.shape, "nonfinite_input", dtype="U24")
    remaining = np.isfinite(tc) & np.isfinite(omega) & np.isfinite(t1) & np.isfinite(t2)
    status[remaining] = "invalid_window"
    remaining = remaining & (t1 < t2)
    status[remaining] = "nonpositive_frequency"
    remaining = remaining & (omega > 0)
    status[remaining] = "not_future"
    remaining = remaining & (tc > t2)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore", under="ignore"):
        candidate = omega[remaining] / (2 * np.pi) * np.log1p(
            (t2[remaining] - t1[remaining]) / (tc[remaining] - t2[remaining])
        )
    cycles[remaining] = candidate
    status[remaining] = "ok"
    failure = remaining & (~np.isfinite(cycles) | (cycles < 0))
    cycles[failure] = np.nan
    status[failure] = "numerical_failure"
    return cycles, status


def _threshold(value: float) -> float:
    value = float(value)
    if not np.isfinite(value) or value < 0:
        raise ValueError("minimum oscillation threshold must be finite and nonnegative")
    return value


def future_cycle_gate(tc, omega, t1=0.0, *, t2, minimum_cycles: float) -> np.ndarray:
    """Inclusive cycle threshold, with every invalid/nonfuture fit rejected."""
    threshold = _threshold(minimum_cycles)
    cycles, status = future_oscillations(tc, omega, t1, t2=t2)
    return (status == "ok") & np.isfinite(cycles) & (cycles >= threshold)


def legacy_half_phase_gate(values, threshold: float = LEGACY_HALF_PHASE_THRESHOLD) -> np.ndarray:
    """Reproduce old half-phase >= threshold exactly, without unit conversion.

    NaN is false; +inf is true, as in the historical comparison. This helper
    does NOT assert forecast eligibility. Use the ``legacy_future`` result
    below when a valid future-domain observation is required.
    """
    return np.asarray(values, dtype=float) >= _threshold(threshold)


def compare_cycle_thresholds(tc, omega, t1=0.0, *, t2, legacy_half_phase) -> dict[str, np.ndarray]:
    """Compare oscillation gates on identical stored fits; do not refit.

    Other shape/quality gates and alert aggregation belong to the caller.
    ``legacy`` preserves the original half-phase comparison, including
    historical inside-window candidates. ``legacy_future`` additionally
    requires a valid canonical future count. ``legacy_converted_naive`` is
    diagnostic only: ``conversion_disagreement`` flags rounding differences
    from the exact original comparison, not a reason to replace that result.
    Canonical 1.5/2.5-cycle gates use the un-clipped future count and exclude
    invalid or already-past tc. None of these masks estimates a probability.
    """
    cycles, status = future_oscillations(tc, omega, t1, t2=t2)
    cycles, status, half_phase = np.broadcast_arrays(
        cycles, status, np.asarray(legacy_half_phase, dtype=float)
    )
    valid = (status == "ok") & np.isfinite(cycles)
    legacy = legacy_half_phase_gate(half_phase)
    legacy_cycles = half_phase / np.pi
    converted = legacy_cycles >= LEGACY_EQUIVALENT_CYCLE_THRESHOLD
    return {
        "osc_cycles": cycles,
        "osc_cycles_status": status,
        "osc_legacy_half_phase": half_phase,
        "osc_legacy_cycles": legacy_cycles,
        "legacy": legacy,
        "legacy_future": legacy & valid,
        "legacy_converted_naive": converted,
        "conversion_disagreement": legacy != converted,
        "cycles_1_5": valid & (cycles >= 1.5),
        "cycles_2_5": valid & (cycles >= 2.5),
    }
