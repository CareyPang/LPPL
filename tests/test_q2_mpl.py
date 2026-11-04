import numpy as np
import pytest

from research.lppls import core, mpl, q2


def _bubble(n=127, sigma=0.01, seed=0, tc_rel=0.05, w0=9.0):
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)
    dt = n - 1
    tc0 = dt + tc_rel * dt
    X = core.design(t, tc0, 0.5, w0, allow_inside=True)
    B = -0.6 / abs(tc0) ** 0.5
    return t, X @ np.array([8.0, B, 0.1 * abs(B), 0.1 * abs(B)]) + rng.normal(0, sigma, n), tc0


def test_stationary_block_resample_shape_and_values():
    e = np.arange(50.0)
    out = q2.stationary_block_resample(e, np.random.default_rng(0), mean_block=5)
    assert out.shape == e.shape and set(out) <= set(e)


def test_lr_stat_and_nested_test_on_bubble(monkeypatch):
    monkeypatch.setattr(core, "ALLOW_INSIDE", True)
    t, y, _ = _bubble()
    dt = len(t) - 1
    lo, hi = np.array([dt - 0.2 * dt, 0.01, 1.0]), np.array([dt + 0.2 * dt, 2.0, 50.0])
    fit = q2.fit_both(t, y, lo, hi, budget=q2.FAST_BUDGET)
    assert fit["sse"] < fit["sse_pl"] and q2.lr_stat(len(t), fit["sse_pl"], fit["sse"]) > 0
    lr = q2.nested_lr_test(t, y, lo, hi, block=10, B=5, fit=fit)
    assert 0 < lr["p"] <= 1 and lr["B"] == 5 and lr["block"] == 10


def test_lomb_test_recovers_omega_and_rejects_random_walk(monkeypatch):
    monkeypatch.setattr(core, "ALLOW_INSIDE", True)
    t, y, _ = _bubble(n=252)
    dt = len(t) - 1
    lo, hi = np.array([dt - 0.2 * dt, 0.01, 1.0]), np.array([dt + 0.2 * dt, 2.0, 50.0])
    fit = q2.fit_both(t, y, lo, hi, budget=q2.FAST_BUDGET)
    lb = q2.lomb_test(t, y, fit["theta"], fit["beta"], n_sim=100, seed=1)
    assert lb["freq_ok"] and lb["p"] <= 0.05 and abs(lb["w_peak"] - 9.0) <= 1.0
    yn = np.cumsum(np.random.default_rng(3).normal(0, 0.02, 252))
    fn = q2.fit_both(t, yn, lo, hi, budget=q2.FAST_BUDGET)
    lbn = q2.lomb_test(t, yn, fn["theta"], fn["beta"], n_sim=100, seed=1)
    assert 0 < lbn["p"] <= 1 and lb["p"] < lbn["p"]
    assert q2.q2_pass(dict(p=0.01), lb, 0.05, 0.05) and not q2.q2_pass(dict(p=0.5), lb, 0.05, 0.05)


def test_mpl_profile_interval_covers_true_tc(monkeypatch):
    monkeypatch.setattr(core, "ALLOW_INSIDE", True)
    t, y, tc0 = _bubble(n=127, sigma=0.01, seed=4)
    pr = mpl.mpl_profile(t, y, mpl.tc_grid(127, step=1.0))
    assert np.isfinite(pr["lm"]).sum() > 10
    lo, hi = mpl.interval(pr, 0.9, "lm")
    assert lo <= hi and abs(pr["tc_hat"] - tc0) < 3
    assert lo - 1.0 <= tc0 <= hi + 1.0
    lo2, hi2 = mpl.interval(pr, 0.8, "lm")
    assert hi2 - lo2 <= hi - lo + 1e-9


def test_interval_interpolates_between_grid_points():
    g = np.arange(0.0, 10.01, 0.1)
    ll = -0.5 * (g - 5.0) ** 2
    prof = dict(tc_grid=g, lm=ll)
    lo, hi = mpl.interval(prof, 0.9, "lm")
    # chi2_1(0.9)=2.7055 → 2[ℓmax−ℓ] ≤ 2.7055 ⇔ |x−5| ≤ sqrt(2.7055)
    assert lo == pytest.approx(5 - np.sqrt(2.7055), abs=0.05) and hi == pytest.approx(5 + np.sqrt(2.7055), abs=0.05)
