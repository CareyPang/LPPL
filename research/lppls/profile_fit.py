"""Profile the LPPLS critical time over the registered v2 search domain."""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

N_IN = 60
N_FUT = 60
TOPK = 5
C_GRID = (0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2)
M_GRID = np.geomspace(0.01, 2.0, 16)
W_GRID = np.linspace(1.0, 50.0, 197)
M_BOUNDS = (0.01, 2.0)
W_BOUNDS = (1.0, 50.0)
COARSE_TC_BATCH = 8


def _json_scalar(value: float, *, nonfinite=None):
    number = float(value)
    return number if np.isfinite(number) else nonfinite


def _json_array(values: np.ndarray, *, nonfinite=None):
    array = np.asarray(values)
    if array.dtype.kind == "b":
        return array.tolist()
    return [_json_scalar(value, nonfinite=nonfinite) for value in array.ravel()]


@dataclass
class ProfileFit:
    tc: float
    grid_tc: float
    polished_tc: float | None
    m: float
    w: float
    beta: np.ndarray
    sse: float
    tcs: np.ndarray
    inside: np.ndarray
    profile: np.ndarray
    refined: np.ndarray
    pm: np.ndarray
    pw: np.ndarray
    n: int
    seconds: float

    def to_dict(self) -> dict:
        return {
            "tc": _json_scalar(self.tc),
            "grid_tc": _json_scalar(self.grid_tc),
            "polished_tc": _json_scalar(self.polished_tc),
            "m": _json_scalar(self.m),
            "w": _json_scalar(self.w),
            "beta": _json_array(self.beta),
            "sse": _json_scalar(self.sse),
            "tcs": _json_array(self.tcs),
            "inside": _json_array(self.inside),
            "profile": _json_array(self.profile),
            "refined": _json_array(self.refined),
            "pm": _json_array(self.pm),
            "pw": _json_array(self.pw),
            "n": int(self.n),
            "seconds": float(self.seconds),
        }

    @classmethod
    def from_dict(cls, value: dict) -> ProfileFit:
        def scalar(name: str, missing: float) -> float:
            item = value[name]
            return missing if item is None else float(item)

        def array(name: str, missing: float = np.nan, dtype=float) -> np.ndarray:
            items = value[name]
            return np.asarray(
                [missing if item is None else item for item in items], dtype=dtype
            )

        return cls(
            tc=scalar("tc", np.nan),
            grid_tc=scalar("grid_tc", np.nan),
            polished_tc=(
                None if value.get("polished_tc") is None else float(value["polished_tc"])
            ),
            m=scalar("m", np.nan),
            w=scalar("w", np.nan),
            beta=array("beta"),
            sse=scalar("sse", np.inf),
            tcs=array("tcs"),
            inside=array("inside", dtype=bool),
            profile=array("profile", missing=np.inf),
            refined=array("refined", dtype=bool),
            pm=array("pm"),
            pw=array("pw"),
            n=int(value["n"]),
            seconds=float(value["seconds"]),
        )


def _tc_grid(n: int) -> tuple[np.ndarray, np.ndarray]:
    t2 = n - 1
    dt = n - 1
    in_lo, in_hi = t2 - 0.2 * dt, t2 - 1.5
    half = np.arange(0.5, float(n), 1.0)
    inside_tc = half[(half >= in_lo) & (half <= in_hi)]
    if len(inside_tc) > N_IN:
        indices = np.rint(np.linspace(0, len(inside_tc) - 1, N_IN)).astype(int)
        inside_tc = inside_tc[indices]
    if 0.2 * dt < 1:
        future_tc = np.asarray([t2 + 1.0])
    else:
        future_tc = np.linspace(t2 + 1.0, t2 + 0.2 * dt, N_FUT)
    tcs = np.concatenate((inside_tc, future_tc))
    inside = np.concatenate(
        (np.ones(len(inside_tc), dtype=bool), np.zeros(len(future_tc), dtype=bool))
    )
    order = np.argsort(tcs, kind="stable")
    return tcs[order], inside[order]


def _coarse_grid_sse(t: np.ndarray, y: np.ndarray, tcs: np.ndarray) -> np.ndarray:
    tcs = np.asarray(tcs, dtype=float)
    result = np.full((len(tcs), len(M_GRID), len(W_GRID)), np.inf)
    if len(y) < 4:
        return result
    y2 = float(y @ y)
    y_sum = float(y.sum())
    for start in range(0, len(tcs), COARSE_TC_BATCH):
        selected_tcs = tcs[start : start + COARSE_TC_BATCH]
        log_distance = np.log(np.abs(selected_tcs[:, None] - t[None, :]))
        f = np.exp(M_GRID[None, :, None] * log_distance[:, None, :])
        f2 = f * f
        angles = W_GRID[None, :, None] * log_distance[:, None, :]
        cosine = np.cos(angles)
        sine = np.sin(angles)
        cosine_2 = cosine * cosine - sine * sine
        sine_2 = 2.0 * cosine * sine

        f_cos = f @ np.swapaxes(cosine, -1, -2)
        f_sin = f @ np.swapaxes(sine, -1, -2)
        f2_cos = f2 @ np.swapaxes(cosine, -1, -2)
        f2_sin = f2 @ np.swapaxes(sine, -1, -2)
        f2_cos_2 = f2 @ np.swapaxes(cosine_2, -1, -2)
        f2_sin_2 = f2 @ np.swapaxes(sine_2, -1, -2)
        fy = f * y[None, None, :]
        fy_cos = fy @ np.swapaxes(cosine, -1, -2)
        fy_sin = fy @ np.swapaxes(sine, -1, -2)
        sum_f = f.sum(axis=2)[:, :, None]
        sum_f2 = f2.sum(axis=2)[:, :, None]
        gram = np.empty(
            (len(selected_tcs), len(M_GRID), len(W_GRID), 4, 4), dtype=float
        )
        gram[..., 0, 0] = len(y)
        gram[..., 0, 1] = gram[..., 1, 0] = sum_f
        gram[..., 0, 2] = gram[..., 2, 0] = f_cos
        gram[..., 0, 3] = gram[..., 3, 0] = f_sin
        gram[..., 1, 1] = sum_f2
        gram[..., 1, 2] = gram[..., 2, 1] = f2_cos
        gram[..., 1, 3] = gram[..., 3, 1] = f2_sin
        gram[..., 2, 2] = 0.5 * (sum_f2 + f2_cos_2)
        gram[..., 2, 3] = gram[..., 3, 2] = 0.5 * f2_sin_2
        gram[..., 3, 3] = 0.5 * (sum_f2 - f2_cos_2)
        rhs = np.empty(
            (len(selected_tcs), len(M_GRID), len(W_GRID), 4), dtype=float
        )
        rhs[..., 0] = y_sum
        rhs[..., 1] = (f @ y)[:, :, None]
        rhs[..., 2] = fy_cos
        rhs[..., 3] = fy_sin

        scales = np.sqrt(np.diagonal(gram, axis1=-2, axis2=-1))
        with np.errstate(divide="ignore", invalid="ignore"):
            scaled_gram = gram / scales[..., :, None] / scales[..., None, :]
            scaled_rhs = rhs / scales
            eigenvalues = np.linalg.eigvalsh(scaled_gram)
            condition = eigenvalues[..., -1] / eigenvalues[..., 0]
        valid = (
            np.all(np.isfinite(scales) & (scales > 0), axis=-1)
            & np.isfinite(condition)
            & (eigenvalues[..., 0] > 0)
            & (condition <= 1e12)
        )
        gram_flat = scaled_gram.reshape((-1, 4, 4))
        rhs_flat = scaled_rhs.reshape((-1, 4))
        valid_flat = valid.ravel()
        scaled_beta = np.full((len(valid_flat), 4), np.nan)
        scaled_beta[valid_flat] = np.linalg.solve(
            gram_flat[valid_flat], rhs_flat[valid_flat, :, None]
        )[:, :, 0]
        scale_flat = scales.reshape((-1, 4))
        rhs_unscaled = rhs.reshape((-1, 4))
        with np.errstate(divide="ignore", invalid="ignore"):
            beta = scaled_beta / scale_flat
        sse = y2 - np.einsum(
            "bi,bi->b", beta, rhs_unscaled, optimize=True
        )
        sse = np.maximum(sse, 0.0)
        valid_flat &= np.isfinite(sse) & (beta[:, 1] < 0)
        sse[~valid_flat] = np.inf
        result[start : start + len(selected_tcs)] = sse.reshape(
            (len(selected_tcs), len(M_GRID), len(W_GRID))
        )
    return result


def _coarse_at_tcs(
    t: np.ndarray, y: np.ndarray, tcs: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    grid_sse = _coarse_grid_sse(t, y, tcs)
    profile = np.full(len(tcs), np.inf)
    pm = np.full(len(tcs), np.nan)
    pw = np.full(len(tcs), np.nan)
    betas = np.full((len(tcs), 4), np.nan)
    for index, tc in enumerate(tcs):
        flat_sse = grid_sse[index].ravel()
        for candidate in np.argsort(flat_sse, kind="stable"):
            if not np.isfinite(flat_sse[candidate]):
                break
            m_index, w_index = np.unravel_index(
                candidate, (len(M_GRID), len(W_GRID))
            )
            m, w = float(M_GRID[m_index]), float(W_GRID[w_index])
            _, beta, sse = _linear_fit(t, y, float(tc), m, w)
            if beta is not None and beta[1] < 0:
                profile[index], pm[index], pw[index], betas[index] = (
                    sse,
                    m,
                    w,
                    beta,
                )
                break
    return profile, pm, pw, betas


def _coarse_at_tc(
    t: np.ndarray, y: np.ndarray, tc: float
) -> tuple[float, float, float, np.ndarray]:
    profile, pm, pw, beta = _coarse_at_tcs(t, y, np.asarray([tc]))
    return float(profile[0]), float(pm[0]), float(pw[0]), beta[0]


def _linear_fit(
    t: np.ndarray, y: np.ndarray, tc: float, m: float, w: float
) -> tuple[np.ndarray, np.ndarray | None, float]:
    distance = np.abs(tc - t)
    log_distance = np.log(distance)
    f = np.exp(m * log_distance)
    phase = w * log_distance
    design = np.column_stack(
        (np.ones_like(t), f, f * np.cos(phase), f * np.sin(phase))
    )
    beta, _, rank, singular = np.linalg.lstsq(design, y, rcond=None)
    if (
        rank < 4
        or singular[-1]
        <= singular[0] * max(len(y), 4) * np.finfo(float).eps
    ):
        return np.full_like(y, np.nan), None, np.inf
    residual = y - design @ beta
    return residual, beta, float(residual @ residual)


def _crossing_neighbors(values: np.ndarray, threshold: float) -> set[int]:
    below = np.isfinite(values) & (values <= threshold)
    crossings = np.flatnonzero(below[:-1] != below[1:])
    return {int(index + offset) for index in crossings for offset in (0, 1)}


def _refine_at_tc(
    t: np.ndarray,
    y: np.ndarray,
    tc: float,
    initial_m: float,
    initial_w: float,
    coarse_sse: float,
) -> tuple[float, float, float, np.ndarray]:
    def residual(parameters):
        values, beta, _ = _linear_fit(t, y, tc, parameters[0], parameters[1])
        if beta is None or not np.all(np.isfinite(values)):
            return np.full_like(y, 1e6)
        return values

    result = least_squares(
        residual,
        x0=np.asarray([initial_m, initial_w]),
        method="trf",
        x_scale="jac",
        bounds=([M_BOUNDS[0], W_BOUNDS[0]], [M_BOUNDS[1], W_BOUNDS[1]]),
        ftol=1e-12,
        xtol=1e-12,
        gtol=1e-10,
        max_nfev=200,
    )
    refined_m, refined_w = map(float, result.x)
    _, beta, sse = _linear_fit(t, y, tc, refined_m, refined_w)
    if beta is None or beta[1] >= 0 or not sse < coarse_sse:
        return coarse_sse, initial_m, initial_w, np.full(4, np.nan)
    return sse, refined_m, refined_w, beta


def _local_grid_spacing(tcs: np.ndarray, index: int) -> float:
    neighbors = []
    if index > 0:
        neighbors.append(float(tcs[index] - tcs[index - 1]))
    if index + 1 < len(tcs):
        neighbors.append(float(tcs[index + 1] - tcs[index]))
    positive = [spacing for spacing in neighbors if spacing > 0]
    return min(positive) if positive else 0.0


def _polish_best(
    t: np.ndarray,
    y: np.ndarray,
    tcs: np.ndarray,
    inside: np.ndarray,
    profile: np.ndarray,
    pm: np.ndarray,
    pw: np.ndarray,
    betas: np.ndarray,
    index: int,
) -> tuple[float, float, float, np.ndarray, float, float | None]:
    grid_tc = float(tcs[index])
    grid_sse = float(profile[index])
    grid_m, grid_w = float(pm[index]), float(pw[index])
    grid_beta = betas[index].copy()
    t2 = len(y) - 1
    dt = t2
    spacing = _local_grid_spacing(tcs, index)
    lower = max(grid_tc - spacing, t2 - 0.2 * dt)
    upper = min(grid_tc + spacing, t2 + 0.2 * dt)
    if inside[index]:
        upper = min(upper, t2 - 1.5)
    else:
        lower = max(lower, t2 + 1.0)
    if not np.isfinite(grid_sse) or not lower < upper:
        return grid_tc, grid_m, grid_w, grid_beta, grid_sse, None

    def residual(parameters):
        values, beta, _ = _linear_fit(
            t, y, parameters[0], parameters[1], parameters[2]
        )
        if beta is None or not np.all(np.isfinite(values)):
            return np.full_like(y, 1e6)
        return values

    result = least_squares(
        residual,
        x0=np.asarray([grid_tc, grid_m, grid_w]),
        method="trf",
        x_scale="jac",
        bounds=(
            [lower, M_BOUNDS[0], W_BOUNDS[0]],
            [upper, M_BOUNDS[1], W_BOUNDS[1]],
        ),
        ftol=1e-12,
        xtol=1e-12,
        gtol=1e-10,
        max_nfev=200,
    )
    polished_tc, polished_m, polished_w = map(float, result.x)
    _, polished_beta, polished_sse = _linear_fit(
        t, y, polished_tc, polished_m, polished_w
    )
    if (
        polished_beta is None
        or polished_beta[1] >= 0
        or polished_sse > grid_sse
    ):
        return grid_tc, grid_m, grid_w, grid_beta, grid_sse, None
    return (
        polished_tc,
        polished_m,
        polished_w,
        polished_beta,
        polished_sse,
        polished_tc if polished_tc != grid_tc else None,
    )


def _coarse_profile(y: np.ndarray) -> tuple[np.ndarray, ...]:
    t = np.arange(len(y), dtype=float)
    tcs, _ = _tc_grid(len(y))
    profile, pm, pw, beta = _coarse_at_tcs(t, y, tcs)
    return tcs, profile, pm, pw, beta


def profile_fit(y: np.ndarray) -> ProfileFit:
    started = time.perf_counter()
    values = np.asarray(y, dtype=float)
    if values.ndim != 1 or len(values) < 4 or not np.all(np.isfinite(values)):
        raise ValueError("y must be a finite one-dimensional series with at least 4 values")
    t = np.arange(len(values), dtype=float)
    tcs, inside = _tc_grid(len(values))
    coarse, pm, pw, betas = _coarse_at_tcs(t, values, tcs)
    profile = coarse.copy()
    refined = np.zeros(len(tcs), dtype=bool)

    finite = np.flatnonzero(np.isfinite(coarse))
    selected: set[int] = set()
    if len(finite):
        order = finite[np.argsort(coarse[finite], kind="stable")]
        selected.update(map(int, order[:TOPK]))
        minimum = float(coarse[order[0]])
        for c in C_GRID:
            selected.update(_crossing_neighbors(coarse, (1.0 + c) * minimum))

    def refine(indices: set[int]) -> None:
        for index in sorted(indices):
            if not np.isfinite(coarse[index]):
                continue
            refined[index] = True
            profile[index], pm[index], pw[index], beta = _refine_at_tc(
                t, values, float(tcs[index]), float(pm[index]), float(pw[index]),
                float(coarse[index]),
            )
            if np.isfinite(beta).all():
                betas[index] = beta

    refine(selected)
    finite_profile = np.flatnonzero(np.isfinite(profile))
    if len(finite_profile):
        minimum = float(np.min(profile[finite_profile]))
        additional = set()
        for c in C_GRID:
            additional.update(
                _crossing_neighbors(profile, (1.0 + c) * minimum)
            )
        refine(additional - selected)

    best = int(np.argmin(profile))
    tc, m, w, beta, sse, polished_tc = _polish_best(
        t, values, tcs, inside, profile, pm, pw, betas, best
    )
    seconds = time.perf_counter() - started
    return ProfileFit(
        tc=tc,
        grid_tc=float(tcs[best]),
        polished_tc=polished_tc,
        m=m,
        w=w,
        beta=beta,
        sse=sse,
        tcs=tcs,
        inside=inside,
        profile=profile,
        refined=refined,
        pm=pm,
        pw=pw,
        n=len(values),
        seconds=seconds,
    )


def fit_window(close_slice) -> ProfileFit:
    close = np.asarray(close_slice, dtype=float)
    if close.ndim != 1 or not np.all(np.isfinite(close)) or np.any(close <= 0):
        raise ValueError("close_slice must contain positive finite prices")
    return profile_fit(np.log(close))


def profile_range(tcs, profile, c: float) -> dict:
    tcs = np.asarray(tcs, dtype=float)
    profile = np.asarray(profile, dtype=float)
    if tcs.ndim != 1 or profile.ndim != 1 or len(tcs) != len(profile):
        raise ValueError("tcs and profile must be one-dimensional arrays of equal length")
    finite = np.isfinite(profile)
    if not finite.any():
        return {
            "lo": np.nan,
            "hi": np.nan,
            "width": np.nan,
            "n_components": 0,
            "ahead_lo": np.nan,
            "ahead_hi": np.nan,
        }
    if not np.isfinite(c) or c < 0:
        raise ValueError("c must be a finite nonnegative value")
    future_count = N_FUT if len(tcs) >= N_FUT else 1
    t2 = float(tcs[-future_count] - 1.0)
    selected = finite & (profile <= (1.0 + c) * float(np.min(profile[finite])))
    indices = np.flatnonzero(selected)
    lo = float(tcs[indices[0]])
    hi = float(tcs[indices[-1]])
    components = 1 + int(np.count_nonzero(np.diff(indices) > 1))
    return {
        "lo": lo,
        "hi": hi,
        "width": hi - lo,
        "n_components": components,
        "ahead_lo": lo - t2,
        "ahead_hi": hi - t2,
    }
