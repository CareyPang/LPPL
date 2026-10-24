import numpy as np

from research.eval.multiple_testing import deflated_sharpe, expected_max_sharpe, pbo, spa_pvalue


def test_spa_null_vs_alternative():
    rng = np.random.default_rng(1)
    d0 = rng.normal(0, 1, size=(1500, 10))
    p0, _ = spa_pvalue(d0, block=20, B=300, seed=0)
    d1 = d0.copy()
    d1[:, 3] += 0.25
    p1, best = spa_pvalue(d1, block=20, B=300, seed=0)
    assert p0 > 0.05 and p1 < 0.01 and best == 3


def test_pbo_random_vs_dominant():
    rng = np.random.default_rng(2)
    M = rng.normal(0, 1, size=(1600, 20))
    r = pbo(M, S=8)
    assert 0.3 < r["pbo"] < 0.7 and r["n_combos"] == 70
    M[:, 5] += 0.3
    assert pbo(M, S=8)["pbo"] < 0.1


def test_deflated_sharpe_monotone_in_trials():
    assert expected_max_sharpe(100, 0.01) > expected_max_sharpe(10, 0.01) > 0
    d1 = deflated_sharpe(0.1, 1000, 0.0, 3.0, 1, 0.01)
    d100 = deflated_sharpe(0.1, 1000, 0.0, 3.0, 100, 0.01)
    assert d1 > d100 and 0 < d100 < 1
    assert np.isclose(deflated_sharpe(0.0, 1000, 0.0, 3.0, 1, 0.01), 0.5)
