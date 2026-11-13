import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from research.data.abnormal import (
    BOARD_TO_BENCHMARK,
    RULES,
    _thresholds,
    board_for_code,
    calculate,
    deviation_pct,
    remaining_to_trigger,
)

FIXTURES = Path(__file__).parent / "fixtures" / "abnormal"


def test_deviation_math_uses_stock_minus_benchmark_return():
    fixture = json.loads((FIXTURES / "qfq_returns.json").read_text(encoding="utf-8"))

    result = deviation_pct(fixture["stock"], fixture["benchmark"], 3)

    assert result == pytest.approx((110 / 100 - 1) * 100 - (105 / 100 - 1) * 100)


def test_deviation_aligns_benchmark_to_stock_dates_across_suspended_day():
    stock = [
        {"date": "2026-11-02", "close": 100.0},
        {"date": "2026-11-03", "close": 104.0},
        {"date": "2026-11-05", "close": 108.0},
        {"date": "2026-11-06", "close": 110.0},
    ]
    benchmark = [
        {"date": "2026-11-02", "close": 100.0},
        {"date": "2026-11-03", "close": 101.0},
        {"date": "2026-11-04", "close": 103.0},
        {"date": "2026-11-05", "close": 104.0},
        {"date": "2026-11-06", "close": 105.0},
    ]

    result = deviation_pct(stock, benchmark, 3)

    assert result == pytest.approx(10.0 - 5.0)


def test_deviation_is_unavailable_when_benchmark_lacks_stock_start_date():
    stock = [
        {"date": "2026-11-02", "close": 100.0},
        {"date": "2026-11-03", "close": 104.0},
        {"date": "2026-11-05", "close": 108.0},
        {"date": "2026-11-06", "close": 110.0},
    ]
    benchmark = [
        {"date": "2026-11-03", "close": 101.0},
        {"date": "2026-11-04", "close": 103.0},
        {"date": "2026-11-05", "close": 104.0},
        {"date": "2026-11-06", "close": 105.0},
    ]

    assert deviation_pct(stock, benchmark, 3) is None


def test_calculate_marks_stock_older_than_benchmark_as_stale():
    start = date(2026, 10, 1)
    stock_rows = [
        {"date": (start + timedelta(days=index)).isoformat(), "close": 100.0 + index}
        for index in range(31)
    ]
    benchmark_rows = [
        {"date": (start + timedelta(days=index)).isoformat(), "close": 100.0 + index}
        for index in range(32)
    ]

    class Client:
        def fetch(self, symbol):
            return benchmark_rows if symbol == "sz399006" else stock_rows

    result = calculate(
        {
            "asof": "2026-10-31",
            "limit_pools": {
                "zt_rows": [{"code": "300123", "name": "测试股"}],
                "zb_rows": [],
                "dt_rows": [],
            },
        },
        client=Client(),
    )

    item = result["items"][0]
    assert item["stale_bar"] is True
    assert item["last_bar_date"] == "2026-10-31"
    assert result["counts"]["stale_bar"] == 1


def test_board_to_benchmark_mapping_and_st_threshold():
    assert board_for_code("600519") == "沪主板"
    assert board_for_code("000001") == "深主板"
    assert board_for_code("300750") == "创业板"
    assert board_for_code("688981") == "科创板"
    assert board_for_code("920157") == "北交所"
    assert BOARD_TO_BENCHMARK == {
        "沪主板": "sh000001",
        "深主板": "sz399001",
        "创业板": "sz399006",
        "科创板": "sh000688",
        "北交所": "bj899050",
    }
    assert _thresholds("沪主板", "*ST 示例")["3d"] == RULES["main_st"]["3d"]
    assert _thresholds("创业板", "ST 示例")["3d"] == RULES["growth"]["3d"]


def test_remaining_distance_handles_up_and_down_triggers():
    thresholds = {"3d": {"up": 20.0, "down": -20.0}}

    up = remaining_to_trigger({"3d": 18.0}, thresholds)
    down = remaining_to_trigger({"3d": -18.0}, thresholds)

    assert up["remaining_pp"] == 2.0
    assert up["threshold"]["direction"] == "up"
    assert down["remaining_pp"] == 2.0
    assert down["threshold"]["direction"] == "down"


def test_missing_candidate_is_counted_not_zero_filled():
    class Client:
        def fetch(self, symbol):
            if symbol == "sz399006":
                return [{"date": "2026-11-09", "close": 100.0}] * 31
            raise RuntimeError("fixture quote unavailable")

    market = {
        "asof": "2026-11-12",
        "limit_pools": {
            "zt_rows": [{"code": "300123", "name": "测试股"}],
            "zb_rows": [],
            "dt_rows": [],
        },
    }

    result = calculate(market, client=Client())

    assert result["source"]["missing"] == 1
    assert result["source"]["missing_codes"][0]["code"] == "300123"
    assert result["items"] == []
