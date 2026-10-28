import numpy as np
import pandas as pd

from research.features.wells import LOOK, rolling_wells, well_features_at


def _bars(close):
    return pd.DataFrame(dict(high=close * 1.01, low=close * 0.99, close=close, volume=np.full(len(close), 1e6)),
                        index=pd.bdate_range("2010-01-01", periods=len(close)))


def test_price_sitting_in_long_consolidation_has_deep_well():
    rng = np.random.default_rng(0)
    flat = 100 * np.exp(0.002 * rng.standard_normal(500).cumsum() * 0.1)
    x = np.log(flat)
    F, depth, _ = well_features_at(x, np.full(500, 1e-5), np.full(500, 1e6), x[-1])
    assert F < 0.5 and depth > 0.04


def test_rolling_wells_is_as_of_and_filled():
    rng = np.random.default_rng(1)
    close = 100 * np.exp(rng.standard_normal(LOOK + 40).cumsum() * 0.01)
    w = rolling_wells(_bars(close))
    assert w.iloc[: LOOK - 1].isna().all().all()
    assert w.well_F.iloc[LOOK - 1 :].notna().all()
    # 修改未来价格不影响过去的值
    close2 = close.copy()
    close2[-20:] *= 1.5
    w2 = rolling_wells(_bars(close2))
    pd.testing.assert_frame_equal(w.iloc[: LOOK + 10], w2.iloc[: LOOK + 10])
