import numpy as np

from research.lppls.core import default_bounds
from research.lppls.intervals import bootstrap_interval, profile_interval
from research.synth.hard import SCENARIOS, sample_hard
from research.synth.nulls import NULLS, sample_null


def test_hard_scenarios_finite_and_truth_consistent():
    for sc in SCENARIOS:
        for noise in ("iid", "ar1", "garch"):
            t, y, tr = sample_hard(sc, noise=noise, seed=1)
            assert len(t) == len(y) == tr.n
            assert np.all(np.isfinite(y))
            assert tr.tc > t[-1]
            assert 0 < tr.m < 1 and 2 < tr.w < 25


def test_hard_short_and_boundary_respect_design():
    _, _, tr = sample_hard("short", seed=2)
    assert tr.n in (60, 90)
    _, _, tb = sample_hard("boundary", seed=2)
    assert tb.m <= 0.15 or tb.m >= 0.85
    assert tb.w <= 6.5 or tb.w >= 12.5


def test_nulls_finite_and_reproducible():
    for kind in NULLS:
        t, y = sample_null(kind, n=120, seed=3)
        _, y2 = sample_null(kind, n=120, seed=3)
        assert len(y) == 120 and np.all(np.isfinite(y))
        np.testing.assert_array_equal(y, y2)


def test_profile_interval_contains_point_estimate_and_is_ordered():
    t, y, tr = sample_hard("base", seed=4, sigma=0.01)
    lo, hi = default_bounds(tr.n, (1, 90))
    a, b, hat = profile_interval(t, y, lo, hi, level=0.9, step=2.0)
    assert lo[0] <= a <= hat <= b <= hi[0]


def test_bootstrap_interval_small_B_runs():
    t, y, tr = sample_hard("base", seed=5, sigma=0.01, n=120)
    lo, hi = default_bounds(tr.n, (1, 60))
    a, b, hat = bootstrap_interval(t, y, lo, hi, level=0.9, B=4, block=10)
    assert a <= b and lo[0] <= hat <= hi[0]


def test_grid_profile_matches_lin_fit():
    import numpy as np

    from research.lppls.core import K_POWER, lin_fit
    from research.optim.optimizers import grid_profile

    rng = np.random.default_rng(1)
    t = np.arange(200.0)
    y = 0.001 * t + 0.02 * rng.standard_normal(200)
    tcs, ms, ws = [210.0, 240.0], [0.3, 0.8], [6.0, 12.0]
    g = grid_profile(t, y, tcs, ms, ws)
    for i, tc in enumerate(tcs):
        for j, m in enumerate(ms):
            for k, w in enumerate(ws):
                assert abs(g[i, j, k] - lin_fit(t, y, tc, m, w)[0]) < 1e-9
    gp = grid_profile(t, y, tcs, ms, None, K_POWER)
    assert abs(gp[0, 0, 0] - lin_fit(t, y, tcs[0], ms[0], 0.0, K_POWER)[0]) < 1e-9
