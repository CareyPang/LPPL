import numpy as np
import pandas as pd

from research.eval import export_contract
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
    prices = np.full(252, 40.0)
    prices[0] = 100.0
    prices[2] = 70.0
    logp = pd.Series(np.log(prices), index=pd.bdate_range("2020-01-01", periods=len(prices)))

    event = bc._rebound_event("sh000001", logp, 0, 1)

    assert np.isclose(event["dd"], -0.6)
    assert np.isclose(event["recovery"], 0.5)
    assert np.isclose(event["recovery_log"], 0.6107, atol=1e-4)
    assert np.isclose(event["rebound_ret"], 0.75)
    assert event["back_to_peak"] is False
    assert event["days_to_peak"] is None
    assert event["days_to_high"] == 1


def test_current_rebound_exposes_new_metrics_without_changing_price_rank():
    prices = np.array([100.0, 40.0, 40.0, 70.0, 80.0])
    logp = pd.Series(np.log(prices), index=pd.bdate_range("2020-01-01", periods=len(prices)))
    state = bc.lt_state(logp.to_numpy(), logp.index)
    history = [{"recovery": 0.4}, {"recovery": 0.8}]

    current = bc._current_rebound("sh000001", logp, state, history)

    assert current["recovery_now"] == round((80 - 40) / (100 - 40), 3)
    assert current["recovery_log_now"] == round(np.log(80 / 40) / np.log(100 / 40), 3)
    assert current["rebound_ret_now"] == 1.0
    assert current["rank_pct"] == 0.5


def test_build_uses_supplied_asof_prices_for_cheap_and_confirm(monkeypatch):
    dates = pd.bdate_range("2024-01-02", periods=6)
    frozen = pd.Series(np.log([100.0, 70.0, 90.0, 105.0]), index=dates[:4])
    supplied = pd.Series(np.log([100.0, 70.0, 90.0, 105.0, 60.0, 1000.0]), index=dates)
    monkeypatch.setattr(dt, "load_logp", lambda sym: frozen)
    monkeypatch.setattr(dt, "build", lambda asof: {"events": []})
    monkeypatch.setattr(bc, "_rebound_history", lambda asof: ([], {"n": 0}, None))
    monkeypatch.setattr(
        bc, "_pe_percentile", lambda sym, asof: {"value": None, "n_months": 0, "pe_date": None}
    )

    cards = bc.build("sh000001", str(dates[4].date()), logp=supplied)

    assert np.isclose(cards["cheap"]["dd_now"], round(60 / 105 - 1, 4))
    assert cards["confirm"]["state"] == "bear"
    assert cards["confirm"]["ref_date"] == str(dates[4].date())
    assert cards["confirm"]["ref_close"] == 60.0


def test_unsupported_symbols_skip_bottom_cards(monkeypatch):
    def unexpected_build(*args, **kwargs):
        raise AssertionError("unsupported symbols must not build bottom cards")

    monkeypatch.setattr(bc, "build", unexpected_build)

    assert export_contract._bottom_objects(
        "sh000928", "2024-01-02", pd.DatetimeIndex([]), pd.DataFrame()
    ) == {}


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
