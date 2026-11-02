import numpy as np
import pytest

from research.lppls.core import K_POWER, default_bounds, lin_fit, qualifies, sse, unpack
from research.optim.optimizers import METHODS
from research.synth.lppls_synth import sample


def test_noise_free_recovery_of_linear_params():
    t, y, tr = sample(n=200, sigma=0.0, seed=3)
    s, beta = lin_fit(t, y, tr.tc, tr.m, tr.w)
    assert s < 1e-20
    np.testing.assert_allclose(beta, [tr.A, tr.B, tr.C1, tr.C2], rtol=1e-8, atol=1e-12)


def test_infeasible_tc_is_inf():
    t = np.arange(10.0)
    y = np.zeros(10)
    assert sse([5.0, 0.5, 8.0], t, y) == np.inf


def test_power_law_nested_sse_not_lower():
    t, y, tr = sample(n=200, sigma=0.01, seed=5)
    s4, _ = lin_fit(t, y, tr.tc, tr.m, tr.w)
    s2, _ = lin_fit(t, y, tr.tc, tr.m, tr.w, K_POWER)
    assert s2 >= s4


def test_unpack_and_rules_on_truth():
    t, y, tr = sample(n=250, sigma=0.005, seed=11)
    f = unpack(tr.theta(), t, y)
    assert f.r2 > 0.95 and f.B < 0
    ok, why = qualifies(f)
    assert ok, why


@pytest.mark.parametrize("name", list(METHODS))
def test_each_optimizer_recovers_tc_low_noise(name):
    t, y, tr = sample(n=250, sigma=0.005, seed=21)
    lo, hi = default_bounds(250, (1, 90))
    r = METHODS[name](t, y, lo, hi, seed=0)
    assert r.sse <= 1.05 * sse(tr.theta(), t, y)
    assert abs(r.theta[0] - tr.tc) < 5


def test_grid_profile_covers_inside_tc_when_allow_inside(monkeypatch):
    """v2（ALLOW_INSIDE=True）下 t_c 网格必须覆盖 t2 之前的半域，并与 lin_fit 同解；v1 下仍为 inf。"""
    from research.lppls import core
    from research.optim.optimizers import grid_profile

    rng = np.random.default_rng(3)
    t = np.arange(120.0)
    tc_true = 110.0
    X = core.design(t, tc_true, 0.5, 8.0, allow_inside=True)
    y = X @ np.array([5.0, -0.3, 0.02, 0.01]) + 0.002 * rng.standard_normal(len(t))
    tcs = np.array([100.0, 110.0, 119.0, 130.0])
    ms, ws = np.array([0.5]), np.array([8.0])

    monkeypatch.setattr(core, "ALLOW_INSIDE", False)
    g1 = grid_profile(t, y, tcs, ms, ws)
    assert np.all(np.isinf(g1[:3, 0, 0])) and np.isfinite(g1[3, 0, 0])

    monkeypatch.setattr(core, "ALLOW_INSIDE", True)
    g2 = grid_profile(t, y, tcs, ms, ws)
    assert np.all(np.isfinite(g2[:, 0, 0]))
    assert int(np.argmin(g2[:, 0, 0])) == 1
    for i, tc in enumerate(tcs):
        assert g2[i, 0, 0] == pytest.approx(core.lin_fit(t, y, tc, 0.5, 8.0)[0], rel=1e-6, abs=1e-12)
    g_pow = grid_profile(t, y, tcs, ms, ws, k=core.K_POWER)
    assert np.all(np.isfinite(g_pow[:, 0, 0]))
