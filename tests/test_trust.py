import numpy as np
import pandas as pd

from research.features.lppls_rules import _derived
from research.lppls import core
from research.lppls.trust import condition2, trust


def test_trust_runs_on_synthetic_lppls(monkeypatch):
    monkeypatch.setattr(core, "ALLOW_INSIDE", True)
    n, tc, m, w = 150, 160.0, 0.5, 8.0
    t = np.arange(n, dtype=float)
    dt = tc - t
    y = 5.0 - 0.02 * dt**m * (1 + 0.05 * np.cos(w * np.log(dt))) + np.random.default_rng(0).normal(0, 0.002, n)
    idx = pd.bdate_range("2010-01-01", periods=n)
    logp = pd.Series(y, index=idx)
    from research.pipeline.daily import fit_asof
    fits = fit_asof(logp, idx[-1], (n,))
    out = trust(logp, idx[-1], fits, b=2, procs=1)
    assert out["n_windows"] == 1 and out["n_boot"] == 2
    assert out["trust"] is None or 0.0 <= out["trust"] <= 1.0
    assert out["evidence"] == "descriptive"
    assert condition2(_derived(fits.assign(y_std=float(np.std(y))))).dtype == bool
