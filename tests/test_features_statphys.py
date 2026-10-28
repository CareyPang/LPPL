import numpy as np
import pandas as pd

from research.features.statphys import ar1, dfa_alpha, perm_entropy, rolling_statphys


def test_dfa_white_noise_about_half_and_random_walk_about_one_and_half():
    rng = np.random.default_rng(0)
    wn = rng.standard_normal(4000)
    assert 0.4 < dfa_alpha(wn) < 0.65
    assert 1.3 < dfa_alpha(np.cumsum(wn)) < 1.7


def test_perm_entropy_bounds():
    rng = np.random.default_rng(0)
    assert perm_entropy(rng.standard_normal(2000)) > 0.97
    assert perm_entropy(np.arange(50.0)) == 0.0


def test_ar1_detects_persistence():
    rng = np.random.default_rng(0)
    e = rng.standard_normal(3000)
    x = np.zeros(3000)
    for i in range(1, 3000):
        x[i] = 0.8 * x[i - 1] + e[i]
    assert 0.7 < ar1(x) < 0.9
    assert abs(ar1(e)) < 0.1


def test_rolling_shapes_and_pit():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2010-01-01", periods=400)
    lp = pd.Series(np.cumsum(0.01 * rng.standard_normal(400)), index=idx)
    f = rolling_statphys(lp, windows=(60,))
    assert f.shape == (400, 5)
    assert f.iloc[:60].isna().all().all()
    f2 = rolling_statphys(lp.iloc[:300], windows=(60,))
    assert np.allclose(f.iloc[100:300].to_numpy(), f2.iloc[100:300].to_numpy(), equal_nan=True)
