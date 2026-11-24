import numpy as np
import pandas as pd

from research.features.bottom_feats import (
    BASE_W,
    SHOCK_LOOK,
    _freeze_sigma_ref,
    bear_state,
    liquidity,
    omori,
)


def _series(n=900, seed=0):
    rng = np.random.default_rng(seed)
    r = rng.standard_normal(n) * 0.003  # 主震前低波动，确保无其他主震
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


def test_early_shock_without_finite_sigma_keeps_omori_metrics_nan():
    returns = np.zeros(320)
    returns[100] = -0.12
    logp = pd.Series(np.cumsum(returns), pd.bdate_range("2010-01-01", periods=len(returns)))

    result = omori(logp, 2.0)

    assert result.days_since_shock_20.iloc[100] == 0
    assert result.days_since_shock_20.iloc[115] == 15
    assert result.after_ratio_20.iloc[100:130].isna().all()
    assert result.omori_p_20.iloc[100:130].isna().all()


def test_omori_freezes_pre_shock_sigma_through_high_volatility_episode():
    logp, _ = _series()
    returns = logp.diff()
    sigma = returns.rolling(BASE_W).std().shift(1)
    drawdown = logp - logp.rolling(SHOCK_LOOK).max()
    shocks = (drawdown <= -0.10) & (drawdown.shift(1) > -0.10)
    frozen = _freeze_sigma_ref(sigma, shocks)
    reference = sigma.iloc[600]

    assert np.isfinite(reference)
    assert frozen.iloc[600:640].eq(reference).all()
    old_count = (returns.abs().iloc[601:640] > 2.0 * sigma.iloc[601:640]).sum()
    frozen_count = (returns.abs().iloc[601:640] > 2.0 * frozen.iloc[601:640]).sum()
    assert frozen_count > old_count


def test_omori_sigma_updates_only_at_the_next_accepted_shock():
    sigma = pd.Series(np.arange(1.0, 101.0))
    shocks = pd.Series(False, index=sigma.index)
    shocks.iloc[10] = True
    shocks.iloc[10 + SHOCK_LOOK] = True

    frozen = _freeze_sigma_ref(sigma, shocks)

    assert frozen.iloc[10 : 10 + SHOCK_LOOK].eq(sigma.iloc[10]).all()
    assert frozen.iloc[10 + SHOCK_LOOK :].eq(sigma.iloc[10 + SHOCK_LOOK]).all()


def test_liquidity_and_state_are_as_of():
    logp, amt = _series()
    rv20 = logp.diff().rolling(20).std() * np.sqrt(250)
    a = pd.concat([liquidity(logp, amt), bear_state(logp, rv20)], axis=1)
    logp2 = logp.copy()
    logp2.iloc[-50:] += 0.5
    b = pd.concat([liquidity(logp2, amt), bear_state(logp2, rv20)], axis=1)
    pd.testing.assert_frame_equal(a.iloc[:-50], b.iloc[:-50])
    assert a.rv20_pct.dropna().between(0, 1).all()
