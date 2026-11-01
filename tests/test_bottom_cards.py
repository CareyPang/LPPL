import numpy as np
import pandas as pd

from research.eval.alt_labels import lt_turns
from research.price_layer import bottom_cards as bc
from research.price_layer import drawdown_table as dt


def test_lt_state_turns_match_lt_turns_on_real_index():
    logp = dt.load_logp("sh000001")
    state = bc.lt_state(logp.to_numpy(), logp.index)
    peaks, troughs = lt_turns(logp.to_numpy(), l1=bc.LT_L1, l2=bc.LT_L2)
    np.testing.assert_array_equal(state["_peaks"], peaks)
    np.testing.assert_array_equal(state["_troughs"], troughs)


def test_rebound_formula_on_synthetic_prices():
    prices = np.full(252, 60.0)
    prices[0] = 100.0
    prices[2] = 80.0
    logp = pd.Series(np.log(prices), index=pd.bdate_range("2020-01-01", periods=len(prices)))

    event = bc._rebound_event("sh000001", logp, 0, 1)

    assert np.isclose(event["dd"], -0.4)
    assert np.isclose(event["recovery"], 0.5)
    assert event["days_to_high"] == 1


def test_rebound_events_and_dd_rank_are_point_in_time():
    asof = "2015-06-12"
    cards = bc.build("sh000001", asof)
    events, _, _ = bc._rebound_history(asof)
    p1 = dt.build(asof)
    assert cards["cheap"]["dd_rank"]["all"]["n"] == p1["n_events"]
    for event in events:
        logp = dt.load_logp(event["symbol"])
        logp = logp.loc[logp.index <= pd.Timestamp(asof)]
        trough_i = logp.index.get_loc(pd.Timestamp(event["trough_date"]))
        assert trough_i + bc.REBOUND_DAYS <= len(logp) - 1
    mismatch_pe = bc._pe_percentile("sz399006", pd.Timestamp(asof))
    assert mismatch_pe["value"] is None and "口径不一致" in mismatch_pe["note"]


def test_current_rebound_is_null_while_lt_state_is_bear():
    prices = np.r_[np.linspace(90, 100, 50), np.linspace(100, 70, 250)]
    logp = pd.Series(np.log(prices), index=pd.bdate_range("2020-01-01", periods=len(prices)))
    state = bc.lt_state(logp.to_numpy(), logp.index)

    assert state["state"] == "bear"
    assert bc._current_rebound("sh000001", logp, state, []) is None
