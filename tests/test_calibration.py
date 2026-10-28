import numpy as np

from research.eval.calibration import Platt, conformal_scale


def test_platt_corrects_overconfidence():
    rng = np.random.default_rng(0)
    z = rng.normal(0, 1.5, 5000)
    p_true = 1 / (1 + np.exp(-z))
    y = (rng.random(5000) < p_true).astype(int)
    p_over = 1 / (1 + np.exp(-3 * z))
    pl = Platt().fit(p_over, y)
    assert 0.25 < pl.a < 0.45
    before = np.mean((p_over - y) ** 2)
    after = np.mean((pl.transform(p_over) - y) ** 2)
    assert after < before


def test_conformal_scale_reaches_coverage():
    rng = np.random.default_rng(1)
    c = rng.normal(size=2000)
    hw = np.full(2000, 0.5)
    t = c + rng.normal(size=2000)
    s = conformal_scale(c, hw, t, level=0.8)
    assert np.mean(np.abs(t - c) <= s * hw) >= 0.8
    assert 2.4 < s < 2.8  # 0.8 分位 ≈ 1.28σ / 0.5
