import pytest

from research.backtest.stage_etf import simulate


def bar(day, price, *, close=None, volume=10000):
    close = price if close is None else close
    return dict(date=day, open=price, high=close, low=price, close=close, volume=volume)


def action(day, target, episode=1, **extra):
    return dict(date=day, target=target, reason="change", episode_id=episode, **extra)


def run(bars, actions=(), payouts=(), **overrides):
    settings = dict(cash=10005, target=1, commission_rate=0.0002, minimum_fee=5)
    return simulate(bars, actions, payouts, **(settings | overrides))


def test_next_open_lots_fees_weight_buyback_and_unfilled_last_day():
    bars = [
        bar("2025-09-01", 10, close=11),
        bar("2025-09-02", 12, close=15),
        bar("2025-09-03", 13),
        bar("2025-09-04", 10),
    ]
    result = run(
        bars, [action("2025-09-01", 0.5), action("2025-09-03", 1), action("2025-09-04", 0.5)]
    )
    daily, trades = result["daily"], result["trades"]
    assert [(t["side"], t["shares"], t["price"]) for t in trades] == [
        ("buy", 1000, 10),
        ("sell", 500, 12),
        ("buy", 500, 10),
    ]
    assert [t["fee"] for t in trades] == [5, 5, 5]
    assert [d["cash"] for d in daily] == [0, 5995, 5995, 990]
    assert [d["nav"] for d in daily] == [11000, 13495, 12495, 10990]
    assert daily[1]["open_nav_before"] == 12000
    assert daily[1]["open_weight"] == pytest.approx(6000 / 11995)
    assert daily[1]["position_weight"] == pytest.approx(7500 / 13495)
    assert [d["sellable_shares_close"] for d in daily] == [0, 500, 500, 500]
    assert [t["signal_date"] for t in trades] == [None, "2025-09-01", "2025-09-03"]
    assert result["orders"][-1]["status"] == "pending"
    assert run(bars)["daily"][-1]["nav"] == 10000


def test_buy_reserves_commission_and_rounds_to_fund_price_tick():
    result = run(
        [bar("2025-09-01", 10), bar("2025-09-02", 10)],
        [action("2025-09-01", 0)],
        cash=10000,
        commission_rate=0.001,
        minimum_fee=0,
        slippage_bps=1,
    )
    buy, sell = result["trades"]
    assert (buy["shares"], buy["price"], buy["fee"], buy["cash_after"]) == (
        900,
        10.001,
        9.00,
        990.10,
    )
    assert (sell["shares"], sell["price"], sell["fee"], sell["cash_after"]) == (
        900,
        9.999,
        9.00,
        9980.20,
    )


def test_suspended_open_does_not_fill_and_later_instruction_can_replace_pending():
    bars = [
        bar("2025-09-01", 10),
        bar("2025-09-02", 12, volume=0),
        bar("2025-09-03", None, close=11),
        bar("2025-09-04", 10),
    ]
    suspended = run(bars, [action("2025-09-01", 0.5), action("2025-09-02", 0.5)])
    assert [t["date"] for t in suspended["trades"]] == ["2025-09-01", "2025-09-04"]
    assert suspended["trades"][-1]["signal_date"] == "2025-09-01"
    assert suspended["orders"][-1]["status"] == "duplicate"
    canceled = run(bars, [action("2025-09-01", 0.5), action("2025-09-03", 1)])
    assert len(canceled["trades"]) == 1
    assert [o["status"] for o in canceled["orders"]] == ["filled", "superseded", "duplicate"]


def test_explicit_same_close_order_is_deterministic_and_no_repeat_buy():
    bars = [bar("2025-09-01", 10), bar("2025-09-02", 10)]
    same_day = [action("2025-09-01", 1, sequence=1), action("2025-09-01", 0.5, sequence=2)]
    assert run(bars, same_day) == run(list(reversed(bars)), list(reversed(same_day)))
    assert [t["side"] for t in run(bars, same_day)["trades"]] == ["buy", "sell"]
    assert len(run(bars, [action("2025-09-01", 1)] * 2)["trades"]) == 1
    with pytest.raises(ValueError, match="conflicting"):
        run(bars, [action("2025-09-01", 0.5), action("2025-09-01", 1)])


def dividend(record, ex, pay, amount=".2"):
    return dict(type="cash", record_date=record, ex_date=ex, pay_date=pay, cash_per_share=amount)


def test_dividend_follows_record_shares_even_after_ex_date_sale_and_prestart_rights_are_zero():
    bars = [
        bar("2025-09-01", 10),
        bar("2025-09-02", "9.8"),
        bar("2025-09-03", "9.8"),
        bar("2025-09-04", "9.8"),
    ]
    payouts = [
        dividend("2025-08-29", "2025-09-01", "2025-09-02"),
        dividend("2025-09-01", "2025-09-02", "2025-09-04"),
    ]
    result = run(bars, [action("2025-09-01", 0)], payouts)
    assert [d["record_shares"] for d in result["dividends"]] == [0, 1000]
    assert [d["receivable"] for d in result["daily"]] == [0, 200, 200, 0]
    assert [d["cash"] for d in result["daily"]] == [0, 9795, 9795, 9995]
    assert result["daily"][1]["open_nav_before"] == 10000
    assert result["daily"][-1]["fees"] == 10
    assert [d["nav"] for d in run(bars, payouts=payouts)["daily"]] == [10000] * 4


def test_nonbar_corporate_dates_same_date_and_final_receivable():
    bars = [bar("2025-09-05", 10), bar("2025-09-08", "9.8")]
    payouts = [
        dividend("2025-09-05", "2025-09-06", "2025-09-09"),
        dividend("2025-09-05", "2025-09-05", "2025-09-05", ".01"),
    ]
    result = run(bars, payouts=payouts)
    assert result["daily"][-1]["nav"] == 10010
    assert result["daily"][-1]["receivable"] == 200
    assert [d["status"] for d in result["dividends"]] == ["receivable", "paid"]


def test_insufficient_cash_does_not_charge_fees_and_unsupported_action_fails():
    bars = [bar("2025-09-01", 10)]
    result = run(bars, cash=1000)
    assert result["orders"][0]["status"] == "insufficient_cash"
    assert result["trades"] == []
    assert result["daily"][0]["cash"] == 1000
    with pytest.raises(ValueError, match="unsupported corporate action"):
        run(bars, payouts=[{"type": "split"}])
    with pytest.raises(ValueError, match="duplicate ETF bar"):
        run(bars * 2)
