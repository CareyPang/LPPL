import numpy as np
import pandas as pd

from research.features.regime_bands import classify, monthly_table, regime_bands


def _ohlc(n_months=70, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2010-01-01", periods=n_months * 21)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(dates))))
    df = pd.DataFrame({"date": dates, "open": close, "high": close * 1.01, "low": close * 0.99, "close": close})
    return df


def test_monthly_table_shapes():
    m = monthly_table(_ohlc())
    assert {"ret", "exc", "n_days"} <= set(m.columns)
    assert (m.exc >= 0).all()


def test_first_window_months_unclassified_and_states_valid():
    rb = regime_bands(_ohlc(), window=60)
    assert rb.state.iloc[:60].isna().all()
    assert set(rb.state.dropna()) <= {"HIGH_RISK", "BEARISH", "NEUTRAL", "BULLISH", "RALLY"}


def test_extreme_loss_is_high_risk_channel_1():
    m = monthly_table(_ohlc())
    m.iloc[-1, m.columns.get_loc("ret")] = -0.5
    m.iloc[-1, m.columns.get_loc("exc")] = 0.0
    out = classify(m, window=60)
    assert out.state.iloc[-1] == "HIGH_RISK" and "1" in out.channel.iloc[-1]
