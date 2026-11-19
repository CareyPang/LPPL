from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
import requests

from research.data.fund_growth import (
    CACHE_COLUMNS,
    CNINFO_PIT_SOURCE,
    CURRENT_COMPONENT_SOURCE,
    INDEX_NAMES,
    CallLimitExceeded,
    RateLimitedClient,
    SwIndexMismatchError,
    _collect_realtime_proxy,
    _collect_weekly_analysis,
    _load_quarter_cache,
    _pit_industry_map,
    _resolve_industry_map,
    _save_quarter_cache,
    aggregate_official,
    build_current_component_map,
    build_fund_row,
    build_pit_industry_map,
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


def test_current_component_mapping_marks_unlisted_stocks_as_non_growth():
    components = {
        code: pd.DataFrame({"证券代码": [f"600{index:03d}"]})
        for index, code in enumerate(INDEX_NAMES, start=1)
    }

    result = build_current_component_map(components, {"600001", "699999"})

    assert result["600001"] == "电子"
    assert result["600007"] == "医药生物"
    assert result["699999"] == "其他非成长"


def test_industry_source_prefers_current_components_and_labels_approximation(tmp_path):
    class FakeClient:
        def call(self, method, **kwargs):
            if method == "index_component_sw":
                code = kwargs["symbol"]
                position = list(INDEX_NAMES).index(code)
                return pd.DataFrame({"证券代码": [f"600{position + 1:03d}"]})
            assert method == "index_realtime_sw"
            return _sw_info()

    mapping, source, note, errors = _resolve_industry_map(
        {"600001"}, "2026Q3", "2026-09-30", tmp_path, FakeClient()
    )

    assert mapping["600001"] == "电子"
    assert source == CURRENT_COMPONENT_SOURCE
    assert "当前成分近似" in note
    assert errors == 0


def test_cninfo_pit_mapping_uses_latest_shenwan_record_before_quarter_end():
    histories = {
        "600001": pd.DataFrame(
            [
                {
                    "分类标准": "证监会行业分类标准",
                    "行业门类": "银行",
                    "变更日期": "2026-08-01",
                },
                {
                    "分类标准": "申银万国行业分类标准",
                    "行业门类": "电子",
                    "变更日期": "2025-01-01",
                },
                {
                    "分类标准": "申银万国行业分类标准",
                    "行业门类": "计算机",
                    "变更日期": "2026-10-01",
                },
            ]
        ),
        "600002": pd.DataFrame(
            [
                {
                    "分类标准": "申银万国行业分类标准",
                    "行业门类": "银行",
                    "变更日期": "2026-06-01",
                }
            ]
        ),
    }

    mapping, dates = build_pit_industry_map(histories, "2026-09-30")

    assert mapping == {"600001": "电子", "600002": "银行"}
    assert dates == {"600001": "2025-01-01", "600002": "2026-06-01"}


def test_industry_source_falls_back_to_cninfo_pit(tmp_path):
    class FakeClient:
        def call(self, method, **kwargs):
            if method == "index_component_sw":
                raise ConnectionError("fixture component failure")
            assert method == "stock_industry_change_cninfo"
            return pd.DataFrame(
                [
                    {
                        "分类标准": "申银万国行业分类标准",
                        "行业门类": "电子",
                        "变更日期": "2025-01-01",
                    }
                ]
            )

    mapping, source, note, errors = _resolve_industry_map(
        {"600001"}, "2026Q3", "2026-09-30", tmp_path, FakeClient()
    )

    assert mapping == {"600001": "电子"}
    assert source == CNINFO_PIT_SOURCE
    assert "当前成分源不可用" in note
    assert errors == 0


def test_cninfo_pit_cache_is_keyed_by_stock_and_quarter(tmp_path):
    class FakeClient:
        calls = 0

        def call(self, method, **kwargs):
            assert method == "stock_industry_change_cninfo"
            assert kwargs["symbol"] == "600001"
            self.calls += 1
            return pd.DataFrame(
                [
                    {
                        "分类标准": "申银万国行业分类标准",
                        "行业门类": "电子",
                        "变更日期": "2025-01-01",
                    }
                ]
            )

    client = FakeClient()
    first, errors = _pit_industry_map(
        {"600001"}, "2026Q3", "2026-09-30", tmp_path, client
    )
    second, second_errors = _pit_industry_map(
        {"600001"}, "2026Q3", "2026-09-30", tmp_path, client
    )

    assert first == second == {"600001": "电子"}
    assert errors == second_errors == 0
    assert client.calls == 1


def test_weekly_analysis_fetches_and_caches_53_weekly_reports(tmp_path):
    start = date(2025, 11, 14)
    dates = [start + timedelta(days=7 * index) for index in range(53)]
    rng = np.random.default_rng(12)
    x = rng.normal(0, 0.01, size=(52, len(INDEX_NAMES)))
    weights = np.arange(1, len(INDEX_NAMES) + 1, dtype=float)
    weights /= weights.sum()
    target_returns = x @ weights

    def closes(returns):
        values = [100.0]
        for value in returns:
            values.append(values[-1] * (1 + value))
        return values

    index_closes = {
        code: closes(x[:, index])
        for index, code in enumerate(INDEX_NAMES)
    }
    target_closes = closes(target_returns)

    class FakeClient:
        calls = []

        def call(self, method, **kwargs):
            self.calls.append((method, kwargs))
            if method == "index_analysis_week_month_sw":
                return pd.DataFrame({"date": dates})
            if method == "index_analysis_weekly_sw":
                index = next(
                    i for i, day in enumerate(dates) if day.strftime("%Y%m%d") == kwargs["date"]
                )
                return pd.DataFrame(
                    [
                        {
                            "发布日期": dates[index],
                            "指数代码": code,
                            "指数名称": name,
                            "收盘指数": index_closes[code][index],
                        }
                        for code, name in INDEX_NAMES.items()
                    ]
                )
            assert method == "stock_zh_index_hist_csindex"
            return pd.DataFrame(
                {"日期": dates, "收盘": target_closes}
            )

    client = FakeClient()
    result = _collect_weekly_analysis("2026-11-18", tmp_path, client)
    first_report_calls = sum(
        method == "index_analysis_weekly_sw" for method, _ in client.calls
    )
    cached_result = _collect_weekly_analysis("2026-11-18", tmp_path, client)
    second_report_calls = sum(
        method == "index_analysis_weekly_sw" for method, _ in client.calls
    )

    assert result["n_weeks"] == 52
    assert result["source"].startswith("ak.index_analysis_weekly_sw")
    assert first_report_calls == second_report_calls == 53
    assert cached_result["value"] == result["value"]


def test_realtime_weekly_fallback_reports_insufficient_sample(tmp_path):
    class FakeClient:
        def call(self, method, **kwargs):
            if method == "index_realtime_sw":
                return pd.DataFrame(
                    [
                        {
                            "指数代码": f"{code}.SI",
                            "指数名称": name,
                            "最新价": 1000 + index,
                        }
                        for index, (code, name) in enumerate(INDEX_NAMES.items())
                    ]
                )
            return pd.DataFrame(
                {"日期": [date.today()], "收盘": [100.0]}
            )

    result = _collect_realtime_proxy("2026-11-18", tmp_path, FakeClient())

    assert result["value"] is None
    assert "代理样本不足" in result["missing_reason"]
    assert result["source"].startswith("ak.index_realtime_sw")


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


def test_rate_limiter_forces_tls_verification_for_akshare_requests(monkeypatch):
    seen = []

    class FakeResponse:
        status_code = 200

    class FakeModule:
        def fetch(self):
            return requests.get("https://example.invalid", verify=False)

    def fake_get(url, **kwargs):
        seen.append(kwargs)
        return FakeResponse()

    monkeypatch.setattr(requests, "get", fake_get)
    client = RateLimitedClient(FakeModule(), min_interval=0, retries=0)

    client.call("fetch")

    assert seen == [{"verify": True, "timeout": (10, 20)}]
    assert client.network_calls == 1


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
    restored, universe_count, mapping_source, mapping_note = _load_quarter_cache(path)

    assert universe_count == 50
    assert restored == rows
    assert mapping_source == mapping_note == ""
    assert set(CACHE_COLUMNS).issubset(pd.read_parquet(path).columns)
