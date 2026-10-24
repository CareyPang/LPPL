import numpy as np
import pandas as pd

from research.eval.run_interval import block_ci


def test_block_ci_contains_mean_and_sign():
    cal = pd.bdate_range("2010-01-01", periods=400)
    dates = pd.Series(cal[::5])
    delta = np.full(len(dates), -2.0)
    d, lo, hi = block_ci(delta, dates, cal, block_days=80, B=200)
    assert d == -2.0 and lo <= d <= hi and hi < 0
