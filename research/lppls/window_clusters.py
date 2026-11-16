"""Research-only window selection and time-axis clusters on stored LPPLS fits.

The 1.5-cycle baseline and all constants below are frozen for this experiment.
This module never fits prices, reads event labels, or changes production gates.
Window support and equal-scale mass are descriptive counts, not probabilities.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .oscillations import OSC_UNITS_VERSION, future_oscillations

RESEARCH_BASELINE_VERSION = "cycles1_5_window_cluster_dev_v1"
MINIMUM_CYCLES = 1.5
SCALE_WINDOWS = {
    "short": tuple(range(30, 61, 5)),
    "mid": tuple(range(65, 126, 5)),
    "medium": tuple(range(130, 251, 5)),
    "long": tuple(range(255, 501, 5)),
}
N_SCALES = 4
THIN_WINDOWS_PER_SCALE = 7
MIN_EXPECTED_WINDOWS = 3
MIN_CLUSTER_WINDOWS = 3
MIN_SCALE_FRACTION = 0.05
MAX_CLUSTER_WIDTH = 10.0
MAX_AHEAD = 90.0
REQUIRED = {"date", "n", "tc", "m", "w", "B"}


def selected_windows(mode: str = "full") -> dict[str, tuple[int, ...]]:
    """Select from the fixed complete grid before seeing any fits or history.

    Thin mode takes seven evenly spaced integer indices with np.rint (ties to
    even). History eligibility is intersected only AFTER this fixed selection.
    """
    if mode not in {"full", "thin"}:
        raise ValueError("window mode must be full or thin")
    if mode == "full":
        return dict(SCALE_WINDOWS)
    return {
        scale: tuple(grid[i] for i in np.rint(
            np.linspace(0, len(grid) - 1, THIN_WINDOWS_PER_SCALE)
        ).astype(int))
        for scale, grid in SCALE_WINDOWS.items()
    }


def prepare(fits: pd.DataFrame) -> pd.DataFrame:
    """Validate one as-of, preserving nonfinite failed fit rows in denominators."""
    missing = REQUIRED - set(fits)
    if missing:
        raise ValueError(f"stored fits missing required columns: {sorted(missing)}")
    d = fits.copy()
    d["date"] = pd.to_datetime(d.date, errors="raise")
    if d.date.isna().any() or d.date.nunique() > 1:
        raise ValueError("fits must contain exactly one nonmissing as-of date, or be empty")
    for key in REQUIRED - {"date"}:
        d[key] = pd.to_numeric(d[key], errors="raise")
    if (not np.isfinite(d.n).all() or (d.n < 2).any()
            or (d.n != np.floor(d.n)).any()):
        raise ValueError("window lengths must be finite integers >= 2")
    d["n"] = d.n.astype(int)
    if d.n.duplicated().any():
        raise ValueError("duplicate window: retain the original one-best-fit choice; seeds are not votes")
    d["ahead"] = d.tc - (d.n - 1)
    d["osc_cycles"], d["osc_cycles_status"] = future_oscillations(d.tc, d.w, t2=d.n - 1)
    d["qualified"] = (
        np.isfinite(d[["tc", "m", "w", "B"]]).all(axis=1)
        & (d.B < 0) & d.m.between(.1, .9) & d.w.between(6, 13)
        & (d.ahead > 0) & (d.ahead <= MAX_AHEAD)
        & (d.osc_cycles_status == "ok") & (d.osc_cycles >= MINIMUM_CYCLES)
    )
    return d.sort_values("n").reset_index(drop=True)


def _expected(values) -> set[int]:
    values = list(values)
    if any(isinstance(n, (bool, np.bool_)) or not np.isfinite(n) or int(n) != n or n < 2
           for n in values):
        raise ValueError("expected_windows must contain integer original window lengths")
    if len(values) != len(set(values)):
        raise ValueError("expected_windows must be unique")
    # Extra source ranges above/below these four bands may be supplied by callers.
    inside = {int(n) for n in values if 30 <= n <= 500}
    allowed = {n for grid in SCALE_WINDOWS.values() for n in grid}
    if not inside <= allowed:
        raise ValueError("expected_windows contains a window outside the frozen step-5 grid")
    return inside


def _finite_number(value):
    return float(value) if np.isfinite(value) else None


def _rank(cluster):
    return (-cluster["mass"], -len(cluster["supported_scales"]),
            -cluster["n_members"], cluster["width"], cluster["lo"],
            tuple(cluster["members"]))


def _clusters(records: list[dict], scales: dict) -> dict:
    """Enumerate fixed-width intervals, never adjacent-distance chains or q-clips."""
    eligible = sorted((r for r in records if r["qualified"]), key=lambda r: (r["ahead"], r["n"]))
    if not eligible:
        return {kind: {"candidates": [], "primary": None} for kind in ("any", "cross")}
    ahead = np.array([r["ahead"] for r in eligible], dtype=float)
    candidates, seen = [], set()
    for left in np.flatnonzero(np.r_[True, ahead[1:] != ahead[:-1]]):
        right = int(np.searchsorted(ahead, ahead[left] + MAX_CLUSTER_WIDTH, side="right"))
        # Respect the literal width bound even at floating-point addition edges.
        while right > left and ahead[right - 1] - ahead[left] > MAX_CLUSTER_WIDTH:
            right -= 1
        members = sorted(eligible[left:right], key=lambda r: r["n"])
        key = tuple(r["n"] for r in members)
        if len(key) < MIN_CLUSTER_WINDOWS or key in seen:
            continue
        seen.add(key)
        counts = {scale: sum(r["scale"] == scale for r in members) for scale in SCALE_WINDOWS}
        fractions = {scale: counts[scale] / scales[scale]["denominator"] for scale in SCALE_WINDOWS}
        supported = [scale for scale in SCALE_WINDOWS if fractions[scale] >= MIN_SCALE_FRACTION]
        if not supported:
            continue
        lo, hi = float(ahead[left]), float(ahead[right - 1])
        candidates.append(dict(
            id="windows_" + "_".join(map(str, key)), members=list(key),
            member_details=[{k: r[k] for k in ("n", "scale", "ahead", "weight")} for r in members],
            scale_counts=counts, scale_fractions=fractions, supported_scales=supported,
            mass=float(sum(r["weight"] for r in members)),
            lo=lo, hi=hi, width=hi - lo, n_members=len(key),
        ))
    candidates.sort(key=_rank)
    cross = [c for c in candidates if len(c["supported_scales"]) >= 2]
    return {
        "any": {"candidates": candidates, "primary": candidates[0] if candidates else None},
        "cross": {"candidates": cross, "primary": cross[0] if cross else None},
    }


def analyze_asof(fits: pd.DataFrame, expected_windows, mode: str = "full") -> dict:
    """Analyze one stored as-of using a separately established original fit grid.

    ``expected_windows`` must come from the original calendar/history/gap rules,
    not from the surviving fits. All four scales must be complete and have >=3
    eligible windows for cluster evaluation. Individual scale statuses remain
    available for the single-scale and two-scale reference arms.
    """
    grids = selected_windows(mode)
    expected = _expected(expected_windows)
    d = prepare(fits)
    scopes, records = {}, []
    for scale, grid in grids.items():
        planned = set(grid) & expected
        # A source window not on the step-5 grid inside a band is an input anomaly.
        lo, hi = SCALE_WINDOWS[scale][0], SCALE_WINDOWS[scale][-1]
        outside_grid = set(d.loc[d.n.between(lo, hi) & ~d.n.isin(SCALE_WINDOWS[scale]), "n"])
        current = d[d.n.isin(grid)]
        actual = set(current.n)
        missing, unexpected = planned - actual, (actual - planned) | outside_grid
        if unexpected:
            status = "incomplete_window_grid"
        elif len(planned) < MIN_EXPECTED_WINDOWS:
            status = "insufficient_window_history"
        elif not actual:
            status = "missing_scan"
        elif missing:
            status = "incomplete_window_grid"
        else:
            status = "ok"
        qualified = current[current.qualified & current.n.isin(planned)]
        fraction = len(qualified) / len(planned) if planned else None
        scopes[scale] = dict(
            status=status, expected_windows=sorted(planned), stored_windows=sorted(actual),
            missing_windows=sorted(missing), unexpected_windows=sorted(unexpected),
            qualified_windows=qualified.n.tolist(), denominator=len(planned),
            qualified_count=len(qualified), fraction=fraction,
            alarm=bool(status == "ok" and fraction >= MIN_SCALE_FRACTION),
        )
        for row in current.itertuples(index=False):
            is_planned = row.n in planned
            records.append(dict(
                n=int(row.n), scale=scale, ahead=_finite_number(row.ahead),
                osc_cycles=_finite_number(row.osc_cycles), osc_cycles_status=row.osc_cycles_status,
                qualified=bool(is_planned and row.qualified), expected=is_planned,
                weight=1 / (N_SCALES * len(planned)) if is_planned and planned else 0.0,
            ))
    records.sort(key=lambda r: r["n"])
    evaluable = all(s["status"] == "ok" for s in scopes.values())
    clusters = _clusters(records, scopes) if evaluable else {
        kind: {"candidates": [], "primary": None} for kind in ("any", "cross")
    }
    return dict(
        baseline_version=RESEARCH_BASELINE_VERSION, osc_units_version=OSC_UNITS_VERSION,
        minimum_cycles=MINIMUM_CYCLES, mode=mode, evaluable=evaluable,
        scales=scopes, fits=records, clusters=clusters,
        interpretation="Stored-fit descriptive support only; not a probability or verified warning lead.",
    )
