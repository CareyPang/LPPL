import json

import pandas as pd
import pytest

from research.backtest.report import (
    _price_top_outcomes,
    _run_rule,
    _signal_quality,
    build_strategy_report,
)


def test_report_keeps_primary_contract_and_explains_missing_lppls_history():
    prices = pd.DataFrame(
        {
            "date": ["2014-10-17", "2014-10-20", "2023-01-03", "2023-01-04"],
            "open": [100.0, 101.0, 102.0, 101.0],
            "high": [101.0, 102.0, 103.0, 102.0],
            "low": [99.0, 100.0, 101.0, 100.0],
            "close": [100.0, 101.0, 102.0, 101.0],
            "prev_close": [100.0, 100.0, 101.0, 102.0],
        }
    )
    dates = pd.to_datetime(prices["date"])
    n_on = pd.Series([0, 0, 0, 0], index=dates)

    report = build_strategy_report(
        "sh000852",
        prices,
        n_on,
        [],
        asof="2023-01-04",
    )

    assert report["rule_id"] == "R-TR1"
    assert report["selected_variant"]["K"] in (2, 3)
    assert len(report["variants"]) == 4
    assert report["segments"]["dev"][0] == "2014-10-17"
    assert all(
        {"precision", "recall", "baseline", "n_signals"} <= variant.keys()
        and variant["evidence"] == "dev_only"
        for variant in report["variants"].values()
    )
    assert report["metrics"]["test"]["evidence"] == "descriptive"
    assert report["metrics"]["test"]["baseline"] is None
    assert report["rules"][1]["rule_id"] == "R-LC1"
    assert report["rules"][1]["skipped"] is True
    assert "缺少 LPPLS history 文件" in report["rules"][1]["note"]
    json.dumps(report, allow_nan=False)


def test_price_top_days_cutoff_and_twenty_day_clustering():
    dates = pd.bdate_range("2014-01-02", periods=173).strftime("%Y-%m-%d").tolist()
    closes = [100.0] * 11 + [80.0] * 19 + [100.0] * 2 + [80.0] * 20
    closes += [100.0] + [80.0] * 120
    prices = pd.DataFrame({"date": dates, "close": closes})

    top_days, sample_days, zones = _price_top_outcomes(prices)
    expected_top_days = {
        *dates[:11],
        dates[30],
        dates[31],
        dates[52],
    }

    assert top_days == expected_top_days
    assert len(sample_days) == 53
    assert dates[52] in sample_days
    assert dates[53] not in sample_days
    assert zones == [(dates[0], dates[31]), (dates[52], dates[52])]

    target = pd.Series([0] * len(dates))
    for exit_position in (1, 11, 53):
        target.iloc[exit_position - 1] = 1
        target.iloc[exit_position] = 0

    quality = _signal_quality(
        dates,
        target,
        top_days,
        sample_days,
        zones,
        dates[0],
        dates[-1],
    )

    assert quality["precision"] == 0.5
    assert quality["baseline"] == 14 / 53
    assert quality["recall"] == 0.5
    assert quality["n_signals"] == 2


def test_segment_uses_existing_position_and_previous_close_at_year_boundary():
    dates = ["2022-12-28", "2022-12-29", "2022-12-30", "2023-01-03", "2023-01-04"]
    values = [100.0, 100.0, 100.0, 80.0, 70.0]
    prices = pd.DataFrame({
        "date": dates, "open": values, "high": values, "low": values,
        "close": values, "prev_close": [100.0, *values[:-1]],
    })
    rule = _run_rule(prices, pd.Series([1, 1, 1, 0, 0], index=dates),
                     (set(), set(dates), []), "")
    ledger = rule["trades"]
    assert [(trade["entry"], trade["exit"], trade["segment"]) for trade in ledger] == [
        ("2022-12-29", "2023-01-04", "test")
    ]
    equity = rule["equity"]
    dev, test = rule["metrics"]["dev"], rule["metrics"]["test"]
    assert dev["n_trades"] == 0 and test["n_trades"] == 1
    assert test["total_return"] == pytest.approx(equity[-1]["nav"] / equity[2]["nav"] - 1)
    assert test["bh_return"] == pytest.approx(-0.30)
    assert test["exposure"] == 0.5
    assert test["n_signals"] == 1 and dev["n_signals"] == 0


def test_segment_start_signal_uses_previous_target():
    dates = ["2022-12-30", "2023-01-03", "2023-01-04"]
    quality = _signal_quality(dates, pd.Series([1, 0, 0]), {dates[1]},
                              set(dates), [(dates[1], dates[1])], dates[1], dates[2])
    assert quality["n_signals"] == 1
    assert quality["precision"] == 1
