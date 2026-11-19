import numpy as np
import pandas as pd
import pytest

from research.backtest import rules
from research.backtest.engine import EngineConfig, run


def _prices(opens, closes, prev_closes=None):
    dates = pd.date_range("2024-01-02", periods=len(opens), freq="B")
    if prev_closes is None:
        prev_closes = [opens[0], *closes[:-1]]
    return pd.DataFrame(
        {
            "date": dates,
            "open": opens,
            "high": np.maximum(opens, closes),
            "low": np.minimum(opens, closes),
            "close": closes,
            "prev_close": prev_closes,
        }
    )


def _target(prices, values):
    return pd.Series(values, index=pd.to_datetime(prices["date"]))


def test_close_signal_executes_next_open_and_sell_is_t_plus_one():
    prices = _prices([100, 100, 110, 105, 105], [100, 100, 110, 105, 105])
    _, trades, _ = run(prices, _target(prices, [1, 0, 0, 0, 0]))

    assert len(trades) == 1
    assert trades[0]["entry"] == prices.iloc[1]["date"].strftime("%Y-%m-%d")
    assert trades[0]["exit"] == prices.iloc[2]["date"].strftime("%Y-%m-%d")
    assert trades[0]["bars"] == 1


def test_limit_locked_buy_and_sell_orders_retry_at_later_open():
    prices = _prices(
        [100, 110, 100, 90, 100],
        [100, 110, 100, 90, 100],
        [100, 100, 110, 100, 100],
    )
    _, trades, _ = run(
        prices,
        _target(prices, [1, 1, 0, 0, 0]),
        EngineConfig(limit_pct=0.1),
    )

    assert trades[0]["entry"] == prices.iloc[2]["date"].strftime("%Y-%m-%d")
    assert trades[0]["exit"] == prices.iloc[4]["date"].strftime("%Y-%m-%d")


def test_missing_open_defers_execution_to_next_valid_open():
    prices = _prices([100, 100, 103, 104], [100, 100, 103, 104])
    prices.loc[1, "open"] = np.nan
    prices.loc[1, ["high", "low"]] = np.nan

    _, trades, _ = run(prices, _target(prices, [1, 0, 0, 0]))

    assert trades[0]["entry"] == prices.iloc[2]["date"].strftime("%Y-%m-%d")
    assert trades[0]["exit"] == prices.iloc[3]["date"].strftime("%Y-%m-%d")


def test_commission_stamp_and_slippage_math():
    prices = _prices([100, 100, 110, 110, 110], [100, 100, 110, 110, 110])
    equity, trades, _ = run(prices, _target(prices, [1, 0, 0, 0, 0]))

    buy_cost = 100 * (1 + 5 / 10_000) * (1 + 2.5 / 10_000)
    sell_proceeds = 110 * (1 - 5 / 10_000) * (1 - (2.5 + 5) / 10_000)
    assert trades[0]["ret"] == pytest.approx(sell_proceeds / buy_cost - 1)
    assert equity.iloc[2]["nav"] == pytest.approx(sell_proceeds / buy_cost)


def test_top_risk_reentry_requires_consecutive_zero_days():
    n_on = pd.Series([0, 2, 0, 0, 1, 0, 0, 0])

    assert rules.top_risk_target(n_on, threshold=2, reentry_days=3).tolist() == [
        1, 0, 0, 0, 0, 0, 0, 1
    ]


def test_lppls_target_uses_latest_frame_and_reentry_window():
    dates = pd.Series(pd.date_range("2024-01-01", periods=23, freq="B"))
    frames = [
        {
            "asof": "2024-01-01",
            "clusters": {"6-12m": [{"q20_date": "2024-01-02", "q80_date": "2024-01-03"}]},
        },
        {"asof": "2024-01-03", "clusters": {"6-12m": []}},
    ]

    target = rules.lppls_target(dates, frames, reentry_days=20)

    assert target.iloc[:3].tolist() == [0, 0, 0]
    assert target.iloc[20] == 0
    assert target.iloc[21] == 1


def test_grid_selection_only_sends_development_rows_to_engine(monkeypatch):
    prices = _prices(
        [100, 101, 102, 103, 104],
        [100, 101, 102, 103, 104],
    )
    prices["date"] = [
        "2022-12-28", "2022-12-29", "2022-12-30", "2023-01-03", "2023-01-04"
    ]
    prices.loc[3:, ["open", "high", "low", "close", "prev_close"]] = 999_999
    n_on = pd.Series([0, 0, 2, 0, 0], index=pd.to_datetime(prices["date"]))
    passed_dates = []

    def fake_run(dev_prices, target, cfg=None):
        passed_dates.extend(dev_prices["date"].tolist())
        return pd.DataFrame({"nav": [1, 1], "bh_nav": [1, 1]}), [], {
            "cagr": 0.1,
            "max_drawdown": -0.1,
            "n_trades": 0,
        }

    monkeypatch.setattr(rules, "run", fake_run)
    rules.select_top_risk_variant(prices, n_on)

    assert len(passed_dates) == 4 * 3
    assert max(passed_dates) == "2022-12-30"
    assert all(day <= "2022-12-31" for day in passed_dates)
