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
