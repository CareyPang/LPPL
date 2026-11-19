from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from research.data.fund_growth import (
    CACHE_COLUMNS,
    INDEX_NAMES,
    CallLimitExceeded,
    RateLimitedClient,
    SwIndexMismatchError,
    _load_quarter_cache,
    _save_quarter_cache,
    aggregate_official,
    build_fund_row,
    build_industry_map,
    compute_weekly_proxy,
    select_fund_universe,
    verify_sw_index_codes,
)


def _sw_info():
    return pd.DataFrame(
        [
            {"行业代码": f"{code}.SI", "行业名称": name}
            for code, name in INDEX_NAMES.items()
        ]
    )


def test_universe_filters_index_funds_and_deduplicates_share_classes():
    funds = pd.DataFrame(
        [
            {"基金代码": "000001", "基金简称": "主动成长A", "基金类型": "股票型"},
            {"基金代码": "000002", "基金简称": "主动成长C", "基金类型": "股票型"},
            {"基金代码": "000003", "基金简称": "指数增强A", "基金类型": "股票型"},
            {"基金代码": "000004", "基金简称": "ETF联接", "基金类型": "混合型-偏股"},
            {"基金代码": "000005", "基金简称": "量化增强LOF（LOF）", "基金类型": "混合型-偏股"},
            {"基金代码": "000006", "基金简称": "债券基金", "基金类型": "债券型"},
        ]
    )

    result = select_fund_universe(funds)

    assert [row["code"] for row in result] == ["000001", "000005"]
    assert result[1]["base_name"] == "量化增强LOF"


def test_sw_index_mapping_matches_confirmed_codes_and_stops_on_mismatch():
    info = _sw_info()

    result = verify_sw_index_codes(info)

    assert result["801080"] == "电子"
    assert result["801890"] == "机械设备"
    info.loc[info["行业代码"] == "801080.SI", "行业名称"] = "错误名称"
    with pytest.raises(SwIndexMismatchError, match="801080"):
        verify_sw_index_codes(info)


def test_pit_industry_mapping_uses_latest_record_not_after_quarter_end():
    history = pd.DataFrame(
        [
            {"股票代码": "600001", "行业代码": "801081.SI", "纳入日期": "2025-01-01"},
            {"股票代码": "600001", "行业代码": "801750.SI", "纳入日期": "2026-10-01"},
            {"股票代码": "600002", "行业代码": "801780.SI", "纳入日期": "2026-06-01"},
        ]
    )

    result = build_industry_map(history, _sw_info(), "2026-09-30")

    assert result == {"600001": "电子", "600002": "银行"}


def test_pit_mapping_accepts_akshare_history_columns():
    history = pd.DataFrame(
        [
            {
                "symbol": "600001",
                "industry_code": "801081",
                "start_date": date(2025, 1, 1),
            }
        ]
    )

    assert build_industry_map(history, _sw_info(), "2026-09-30") == {
        "600001": "电子"
    }


def test_fund_row_uses_top_ten_percentages_and_largest_holding_nav_estimate():
    holdings = pd.DataFrame(
        [
            {"季度": "2026年3季度股票投资明细", "股票代码": "600001", "股票名称": "甲", "占净值比例": 8, "持仓市值": 800},
            {"季度": "2026年3季度股票投资明细", "股票代码": "600002", "股票名称": "乙", "占净值比例": 5, "持仓市值": 500},
            {"季度": "2026年3季度股票投资明细", "股票代码": "600003", "股票名称": "丙", "占净值比例": 2, "持仓市值": 200},
            {"季度": "2026年2季度股票投资明细", "股票代码": "600004", "股票名称": "丁", "占净值比例": 90, "持仓市值": 9000},
        ]
    )

    result = build_fund_row(
        {"code": "000001", "name": "成长基金"},
        holdings,
        "2026Q3",
        {"600001": "电子", "600002": "银行"},
    )

    assert result["nav_est"] == 10000
    assert result["growth_fraction"] == pytest.approx(8 / 15)
    assert result["industry_weights"] == pytest.approx(
        {"电子": 8 / 15, "银行": 5 / 15, "未映射": 2 / 15}
    )
    assert result["unmapped_stocks"] == ["600003"]


def test_official_position_is_nav_weighted_and_reports_coverage():
    rows = [
        {
            "fund_code": "000001",
            "fund_name": "甲",
            "nav_est": 100,
            "growth_fraction": 0.5,
            "industry_weights": {"电子": 0.5, "银行": 0.5},
            "unmapped_stocks": ["600001"],
        },
        {
            "fund_code": "000002",
            "fund_name": "乙",
            "nav_est": 300,
            "growth_fraction": 0.2,
            "industry_weights": {"计算机": 0.2, "银行": 0.8},
            "unmapped_stocks": ["600002"],
        },
    ]

    result = aggregate_official(
        rows, quarter="2026Q3", quarter_end="2026-09-30", universe_funds=4
    )

    assert result["value"] == 27.5
    assert result["n_funds"] == 2
    assert result["coverage"] == 50
    assert result["industry_weights"] == {
        "银行": 72.5,
        "计算机": 15.0,
        "电子": 12.5,
    }
    assert result["unmapped_stock_count"] == 2


def test_weekly_proxy_uses_52_complete_weeks_and_nonnegative_weights():
    start = date(2025, 11, 10)
    weeks = [start + timedelta(days=7 * index) for index in range(53)]
    rng = np.random.default_rng(7)
    x = rng.normal(0, 0.01, size=(52, len(INDEX_NAMES)))
    weights = np.array([0.12] * 7 + [0.032] * 5)
    weights /= weights.sum()
    y = x @ weights

    def frame_from_returns(values):
        closes = [100.0]
        for value in values:
            closes.append(closes[-1] * (1 + value))
        return pd.DataFrame(
            {
                "日期": [(week + timedelta(days=4)).isoformat() for week in weeks],
                "收盘指数": closes,
            }
        )

    industry_frames = {
        code: frame_from_returns(x[:, index])
        for index, code in enumerate(INDEX_NAMES)
    }
    industry_frames["__index_info__"] = _sw_info()

    result = compute_weekly_proxy(
        frame_from_returns(y), industry_frames, asof="2026-11-13"
    )

    assert result["n_weeks"] == 52
    assert result["coverage"] == 100
    assert result["r2"] == pytest.approx(1, abs=1e-8)
    assert sum(result["weights"].values()) == pytest.approx(100)
    assert result["value"] == pytest.approx(84, abs=1)


def test_weekly_proxy_rejects_stale_common_history():
    weeks = [
        date(2023, 5, 15) + timedelta(days=7 * index)
        for index in range(53)
    ]
    stale_frame = pd.DataFrame(
        {
            "日期": [(week + timedelta(days=4)).isoformat() for week in weeks],
            "收盘指数": list(range(100, 153)),
        }
    )
    industry_frames = {code: stale_frame for code in INDEX_NAMES}
    industry_frames["__index_info__"] = _sw_info()

    with pytest.raises(ValueError, match="超过两周"):
        compute_weekly_proxy(
            stale_frame, industry_frames, asof="2026-11-18"
        )


def test_rate_limiter_retries_enforces_call_cap_and_interval():
    now = [0.0]
    delays = []
    attempts = []

    class FakeModule:
        def fetch(self):
            attempts.append(1)
            if len(attempts) == 1:
                raise ConnectionError("temporary")
            return "ok"

    def sleep(seconds):
        delays.append(seconds)
        now[0] += seconds

    client = RateLimitedClient(
        FakeModule(),
        max_calls=2,
        min_interval=0.3,
        retries=1,
        sleep=sleep,
        clock=lambda: now[0],
    )

    assert client.call("fetch") == "ok"
    assert client.calls == 2
    assert delays[0] >= 0.3
    with pytest.raises(CallLimitExceeded):
        client.call("fetch")


def test_quarter_cache_round_trips_per_fund_rows(tmp_path):
    rows = [
        {
            "fund_code": "000001",
            "fund_name": "成长基金",
            "nav_est": 1000.0,
            "growth_fraction": 0.4,
            "industry_weights": {"电子": 0.4, "银行": 0.6},
            "unmapped_stocks": ["600001"],
        }
    ]
    path = tmp_path / "2026Q3.parquet"

    _save_quarter_cache(path, rows, 50)
    restored, universe_count = _load_quarter_cache(path)

    assert universe_count == 50
    assert restored == rows
    assert set(CACHE_COLUMNS).issubset(pd.read_parquet(path).columns)
