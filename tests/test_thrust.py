import numpy as np
import pandas as pd

from research.features.thrust import breadth, margin_turn, thrust_features


def test_thrust_features_as_of_and_shock():
    rng = np.random.default_rng(0)
    n = 400
    idx = pd.bdate_range("2012-01-01", periods=n)
    r = rng.standard_normal(n) * 0.005
    r[350] = 0.05
    logp = pd.Series(np.cumsum(r), idx)
    amt = pd.Series(np.full(n, 1e9), idx)
    amt.iloc[350] = 3e9
    after = pd.Series(1.0, idx)
    f = thrust_features(logp, amt, after)
    assert f.first_up_shock.iloc[350] == 1 and f.first_up_shock.iloc[354] == 1 and f.first_up_shock.iloc[356] == 0
    assert f.amt_jump.iloc[350] > 1.0
    logp2 = logp.copy()
    logp2.iloc[-10:] += 1
    pd.testing.assert_frame_equal(f.iloc[:-10], thrust_features(logp2, amt, after).iloc[:-10])


def test_margin_turn_and_breadth():
    idx = pd.bdate_range("2012-01-01", periods=30)
    lev = pd.Series(np.r_[np.full(15, -0.01), np.full(15, 0.01)], idx)
    t = margin_turn(lev)
    assert t.iloc[15] == 1 and t.iloc[24] == 1 and t.iloc[25] == 0
    px = pd.DataFrame(np.cumsum(np.ones((30, 4)), axis=0), index=idx)
    b = breadth(np.log(px))
    assert b.br_hi20.iloc[-1] == 1.0 and b.br_up.iloc[-1] == 1.0
