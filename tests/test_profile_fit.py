import json

import numpy as np

import research.lppls.profile_fit as profile_fit_module
from research.lppls.profile_fit import (
    M_GRID,
    W_GRID,
    _coarse_grid_sse,
    _coarse_profile,
    _linear_fit,
    _tc_grid,
    fit_window,
    profile_fit,
    profile_range,
)


def _lppls_series(n=252, tc=None, m=0.5, omega=8.0, b_scale=-1.0, c_ratio=0.05):
    t = np.arange(n, dtype=float)
    t2 = n - 1
    tc = float(t2 + 20 if tc is None else tc)
    ahead = tc - t2
    b = b_scale * 0.6 / (tc**m - ahead**m)
    distance = np.abs(tc - t)
    c = c_ratio * abs(b)
    y = 4.0 + b * distance**m + c * distance**m * np.cos(
        omega * np.log(distance) - 0.7
    )
    return y, tc, m, omega


def test_noiseless_lppls_recovers_future_parameters():
    y, true_tc, true_m, true_omega = _lppls_series()

    fit = profile_fit(y)

    assert abs(fit.tc - true_tc) <= 1
    assert abs(fit.m - true_m) / true_m <= 0.02
    assert abs(fit.w - true_omega) / true_omega <= 0.02
    assert fit.sse <= np.min(fit.profile)


def test_separable_coarse_sse_matches_lstsq_on_random_grid_points():
    clean, true_tc, _, _ = _lppls_series()
    rng = np.random.default_rng(202607)
    y = clean + rng.normal(0.0, 0.002, size=len(clean))
    t = np.arange(len(y), dtype=float)
    tcs, _ = _tc_grid(len(y))
    tc = float(tcs[np.argmin(np.abs(tcs - true_tc))])
    grid_sse = _coarse_grid_sse(t, y, np.asarray([tc]))[0]
    finite = np.flatnonzero(np.isfinite(grid_sse))
    sampled = rng.permutation(finite)
    compared = 0
    for flat_index in sampled:
        m_index, w_index = np.unravel_index(
            flat_index, (len(M_GRID), len(W_GRID))
        )
        m, w = float(M_GRID[m_index]), float(W_GRID[w_index])
        distance = np.abs(tc - t)
        f = distance**m
        phase = w * np.log(distance)
        design = np.column_stack(
            (np.ones_like(t), f, f * np.cos(phase), f * np.sin(phase))
        )
        beta, _, rank, singular = np.linalg.lstsq(design, y, rcond=None)
        if (
            rank < 4
            or singular[-1]
            <= singular[0] * max(len(y), 4) * np.finfo(float).eps
            or beta[1] >= 0
        ):
            continue
        residual = y - design @ beta
        direct_sse = float(residual @ residual)
        if direct_sse <= 1e-8:
            continue
        relative_error = abs(grid_sse[m_index, w_index] - direct_sse) / direct_sse
        assert relative_error <= 1e-8
        compared += 1
        if compared == 20:
            break
    assert compared == 20


def test_tc_grid_observes_inside_and_future_domain():
    n = 252
    tcs, inside = _tc_grid(n)
    t2 = n - 1
    inside_tcs = tcs[inside]
    future_tcs = tcs[~inside]

    assert len(inside_tcs) <= 60
    assert np.all(np.isclose(inside_tcs - 0.5, np.round(inside_tcs - 0.5)))
    assert np.min(inside_tcs) >= t2 - 0.2 * (n - 1)
    assert np.min(t2 - inside_tcs) >= 1.5
    assert future_tcs[0] == t2 + 1
    assert future_tcs[-1] == t2 + 0.2 * (n - 1)

    long_tcs, long_inside = _tc_grid(1008)
    long_inside_tcs = long_tcs[long_inside]
    all_half_integers = np.arange(0.5, 1008.0, 1.0)
    eligible = all_half_integers[
        (all_half_integers >= 1007 - 0.2 * 1007)
        & (all_half_integers <= 1007 - 1.5)
    ]
    assert len(long_inside_tcs) == 60
    assert long_inside_tcs[0] == eligible[0]
    assert long_inside_tcs[-1] == eligible[-1]


def test_fit_window_uses_log_prices(monkeypatch):
    close = np.asarray([10.0, 12.0, 11.0])
    captured = {}
    marker = object()

    def capture(y):
        captured["y"] = y.copy()
        return marker

    monkeypatch.setattr(profile_fit_module, "profile_fit", capture)

    assert fit_window(close) is marker
    assert np.array_equal(captured["y"], np.log(close))


def test_positive_b_only_series_is_not_selected():
    y, true_tc, true_m, true_omega = _lppls_series(b_scale=1.0, c_ratio=0.0)
    residual, true_beta, true_sse = _linear_fit(
        np.arange(len(y), dtype=float), y, true_tc, true_m, true_omega
    )

    assert true_beta[1] > 0
    assert true_sse < 1e-20
    assert np.allclose(residual, 0.0, atol=1e-10)

    fit = profile_fit(y)

    assert fit.beta[1] < 0 or np.isinf(fit.sse)


def test_refinement_does_not_increase_profile_and_ranges_expand():
    y, _, _, _ = _lppls_series()
    tcs, coarse, *_ = _coarse_profile(y)

    fit = profile_fit(y)
    refined = np.flatnonzero(fit.refined)

    assert len(refined)
    assert np.all(fit.profile[refined] <= coarse[refined] + 1e-12)
    widths = [profile_range(fit.tcs, fit.profile, c)["width"] for c in (0.002, 0.05, 0.2)]
    assert widths[0] <= widths[1] <= widths[2]


def test_all_infinite_profile_has_no_range():
    result = profile_range(np.asarray([10.0, 11.0]), np.asarray([np.inf, np.inf]), 0.05)

    assert np.isnan(result["lo"])
    assert np.isnan(result["hi"])
    assert np.isnan(result["width"])
    assert result["n_components"] == 0
    assert np.isnan(result["ahead_lo"])
    assert np.isnan(result["ahead_hi"])


def test_profile_fit_json_round_trip():
    y, _, _, _ = _lppls_series()
    fit = fit_window(np.exp(y))

    encoded = json.dumps(fit.to_dict(), allow_nan=False)
    restored = type(fit).from_dict(json.loads(encoded))

    assert restored.tc == fit.tc
    assert restored.grid_tc == fit.grid_tc
    assert restored.polished_tc == fit.polished_tc
    assert restored.m == fit.m
    assert restored.w == fit.w
    assert restored.sse == fit.sse
    assert restored.n == fit.n
    assert np.array_equal(restored.tcs, fit.tcs)
    assert np.array_equal(restored.inside, fit.inside)
    assert np.array_equal(restored.refined, fit.refined)
    assert np.array_equal(restored.profile, fit.profile)
    assert np.array_equal(restored.beta, fit.beta)
