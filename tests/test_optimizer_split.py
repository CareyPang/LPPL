import os

import numpy as np
import pandas as pd
import pytest

from research.features import lppls_scan
import research.lppls.trust as trust_module
from research.optim.optimizers import de_lbfgsb
from research.pipeline import daily, stock


def _synthetic_window(n=160):
    t = np.arange(n, dtype=float)
    dt = n + 12.0 - t
    y = 5.0 - 0.02 * dt**0.5 * (1 + 0.05 * np.cos(8.0 * np.log(dt)))
    return y + np.random.default_rng(42).normal(0, 0.002, n)


def _bounds(n):
    bx = lppls_scan.BOXES[lppls_scan.BOX]
    dt = n - 1
    ahead_hi = (
        0.2 * dt
        if bx.get("tc_cap") is None
        else min(0.2 * dt, bx["tc_cap"])
    )
    if lppls_scan.ANCHOR == "start":
        return (
            np.array([-0.2 * dt, bx["m"][0], bx["w"][0]]),
            np.array([-0.5, bx["m"][1], bx["w"][1]]),
        )
    tc_lo = bx["tc"][0]
    return (
        np.array(
            [
                dt + (tc_lo if tc_lo >= 0.5 else tc_lo * dt),
                bx["m"][0],
                bx["w"][0],
            ]
        ),
        np.array([dt + ahead_hi, bx["m"][1], bx["w"][1]]),
    )


def test_de_mode_matches_direct_optimizer_on_synthetic_window():
    y = _synthetic_window()
    fitted_y = -y if lppls_scan.SIGN == "neg" else y
    expected = de_lbfgsb(
        np.arange(len(y), dtype=float), fitted_y, *_bounds(len(y)), seed=0
    )

    row = lppls_scan.fit_one(y, opt="de")

    np.testing.assert_allclose(row[1:4], expected.theta, rtol=0, atol=1e-12)
    assert np.isclose(row[8], expected.sse, rtol=0, atol=1e-12)


def test_g3_sse_is_no_worse_than_tcgrid_on_synthetic_window():
    y = _synthetic_window()

    tcgrid = lppls_scan.fit_one(y, opt="tcgrid")
    g3 = lppls_scan.fit_one(y, opt="g3")

    assert g3[8] <= tcgrid[8] + 1e-12


def test_default_optimizer_preserves_legacy_environment_choice():
    expected = lppls_scan.OPT
    assert expected == os.environ.get(
        "LPPLS_OPT", "g3" if lppls_scan.G3 else "tcgrid"
    )

    implicit = lppls_scan.fit_one(_synthetic_window())
    explicit = lppls_scan.fit_one(_synthetic_window(), opt=expected)
    assert len(implicit) == len(explicit)
    for left, right in zip(implicit, explicit, strict=True):
        if isinstance(left, float) and isinstance(right, float):
            assert left == right or (np.isnan(left) and np.isnan(right))
        else:
            assert left == right


def test_invalid_optimizer_raises():
    with pytest.raises(ValueError, match="optimizer"):
        lppls_scan.fit_one(_synthetic_window(), opt="unknown")


def test_stock_worker_explicitly_uses_de(monkeypatch):
    dates = pd.bdate_range("2024-01-02", periods=160)
    logp = pd.Series(np.linspace(1.0, 2.0, len(dates)), index=dates)
    captured = {}

    def fit_asof(_logp, asof, windows, opt=None):
        captured.update(asof=asof, windows=windows, opt=opt)
        return pd.DataFrame()

    monkeypatch.setattr(stock, "_FIT_LOGP", logp)
    monkeypatch.setattr(stock, "fit_asof", fit_asof)

    stock._fit_worker((dates[-1], 127))

    assert captured == {"asof": dates[-1], "windows": (127,), "opt": "de"}


def test_trust_bootstrap_preserves_explicit_optimizer(monkeypatch):
    dates = pd.bdate_range("2024-01-02", periods=20)
    logp = pd.Series(np.linspace(1.0, 2.0, len(dates)), index=dates)
    captured = []

    def fake_window_trust(_y, _row, _b, _seed, opt=None):
        captured.append(opt)
        return 0.5

    monkeypatch.setattr(trust_module, "window_trust", fake_window_trust)
    trust_module.trust(
        logp, dates[-1], pd.DataFrame({"n": [10]}), b=1, procs=1, opt="de"
    )

    assert captured == ["de"]
