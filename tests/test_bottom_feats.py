import numpy as np
import pandas as pd

from research.features.bottom_feats import bear_state, liquidity, omori


def _series(n=900, seed=0):
    rng = np.random.default_rng(seed)
    r = rng.standard_normal(n) * 0.01
    r[600] = -0.12  # 主震
    r[601:640] = rng.standard_normal(39) * 0.04  # 余震密集
    idx = pd.bdate_range("2010-01-01", periods=n)
    return pd.Series(np.cumsum(r), idx), pd.Series(np.full(n, 1e9), idx)


def test_omori_marks_shock_and_decays():
    logp, _ = _series()
    o = omori(logp, 2.0)
    assert o.days_since_shock_20.iloc[600] == 0
    assert o.after_ratio_20.iloc[625] > 1.5  # 主震后 20 日余震率远高于基准
    assert o.omori_p_20.iloc[700] > 0  # 余震已衰减
    assert o.days_since_shock_20.iloc[300] == 250  # 无主震时取上限


def test_liquidity_and_state_are_as_of():
    logp, amt = _series()
    rv20 = logp.diff().rolling(20).std() * np.sqrt(250)
    a = pd.concat([liquidity(logp, amt), bear_state(logp, rv20)], axis=1)
    logp2 = logp.copy()
    logp2.iloc[-50:] += 0.5
    b = pd.concat([liquidity(logp2, amt), bear_state(logp2, rv20)], axis=1)
    pd.testing.assert_frame_equal(a.iloc[:-50], b.iloc[:-50])
    assert a.rv20_pct.dropna().between(0, 1).all()
