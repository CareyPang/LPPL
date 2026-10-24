import numpy as np

from research.features.gsadf import bsadf, bsadf_brute, psy_min_window


def test_bsadf_matches_brute_force():
    rng = np.random.default_rng(0)
    y = np.cumsum(0.01 * rng.standard_normal(120))
    y[80:] += 0.02 * np.arange(40) ** 1.5 / 10  # 末端加速
    a = bsadf(y, W=60, minw=20)
    b = bsadf_brute(y, W=60, minw=20)
    m = np.isfinite(b)
    assert np.allclose(a[m], b[m], atol=1e-8)
    assert np.all(np.isnan(a[:20]))


def test_explosive_segment_raises_bsadf():
    rng = np.random.default_rng(1)
    n = 400
    rw = np.cumsum(0.01 * rng.standard_normal(n))
    expl = rw.copy()
    expl[300:] = rw[300] + 0.03 * (1.02 ** np.arange(100) - 1) * 3
    a, b = bsadf(rw, 250, 36), bsadf(expl, 250, 36)
    assert np.nanmean(b[350:]) > np.nanmean(a[350:]) + 1.0


def test_psy_min_window():
    assert psy_min_window(250) == 31
    assert psy_min_window(500) == 46
