import numpy as np
import pandas as pd

from research.labels.bottom import label_bottom, triple_barrier


def test_triple_barrier_outcomes():
    up = np.log(np.concatenate([[1.0], np.linspace(1.0, 1.3, 30)]))
    assert triple_barrier(up, 0, 0.10, 0.05, look=30)[0] == 1
    dn = np.log(np.concatenate([[1.0], np.linspace(1.0, 0.8, 30)]))
    assert triple_barrier(dn, 0, 0.10, 0.05, look=30)[0] == -1
    flat = np.zeros(31)
    assert triple_barrier(flat, 0, 0.10, 0.05, look=30) == (0, 30)


def test_label_bottom_marks_valid_bottom_only():
    rng = np.random.default_rng(0)
    n = 400
    lp = np.zeros(n)
    lp[:100] = -0.002 * np.arange(100)  # 跌
    lp[100:200] = lp[99] + 0.004 * np.arange(1, 101)  # 真底后反弹 >40%
    lp[200:300] = lp[199] - 0.002 * np.arange(1, 101)  # 再跌
    lp[300:] = lp[299] - 0.002 * np.arange(1, 101)  # 继续跌：300 之前无底
    lp += rng.normal(0, 0.001, n)
    dates = pd.bdate_range("2010-01-01", periods=n)
    out = label_bottom(dates, lp, bottoms=np.array([99, 199]), quant=None)
    assert out.outcome.iloc[99] == 1 and out.outcome.iloc[199] == -1
    assert out.y.iloc[90] == 1.0 and out.y.iloc[60] == 0.0 and out.y.iloc[190] == 0.0
    assert np.isclose(out.attrs["halfway_share"], 0.5)
