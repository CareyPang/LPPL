import json
from datetime import date

import pandas as pd

from research.data import freshness
from research.pipeline import stock


def test_lag_counts_due_trading_days_after_data_day():
    now = pd.Timestamp("2026-11-17 07:00", tz="Asia/Shanghai")
    calendar = [date(2026, 11, 16)]

    assert freshness.lag_trading_days("2026-11-16", now, calendar) == 0
    assert freshness.lag_trading_days("2026-11-13", now, calendar) == 1


def test_monday_0500_does_not_count_weekend():
    now = pd.Timestamp("2026-11-16 05:00", tz="Asia/Shanghai")

    assert freshness.lag_trading_days("2026-11-13", now, None) == 0


def test_calendar_excludes_a_market_holiday():
    now = pd.Timestamp("2026-05-07 07:00", tz="Asia/Shanghai")
    calendar = [date(2026, 5, 4), date(2026, 5, 6)]

    assert freshness.lag_trading_days("2026-05-01", now, calendar) == 2


def test_data_day_prefers_asof_and_converts_generated_utc_to_beijing():
    assert freshness.data_day(
        {
            "asof": "2026-11-13",
            "generated_at": "2026-11-13T17:30:00Z",
        }
    ) == "2026-11-13"
    assert freshness.data_day(
        {
            "asof": "2026-11-16",
            "indicators": [{"id": "us10y", "asof": None}],
        }
    ) is None
    assert freshness.data_day({"generated_at": "2026-11-13T17:30:00Z"}) == "2026-11-14"
    assert freshness.data_day({"generated": "2026-11-13T17:30:00+00:00"}) == "2026-11-14"
    assert freshness.data_day({}) is None


def test_growth_snapshot_freshness_uses_newest_indicator_data_date():
    assert freshness.data_day(
        {
            "asof": "2026-11-16",
            "indicators": [
                {"id": "fund_growth_position", "asof": None},
                {"id": "semi_etf_flow", "asof": "2026-11-13"},
                {"id": "us10y", "asof": "2026-11-13"},
                {"id": "growth_rs", "asof": "2026-11-16"},
            ],
        }
    ) == "2026-11-16"


def test_check_uses_reference_calendar_and_marks_missing_or_invalid_files(
    tmp_path, monkeypatch
):
    path = tmp_path / "market/market_latest.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(
        stock,
        "_reference_calendar",
        lambda cutoff: (_ for _ in ()).throw(RuntimeError("calendar unavailable")),
    )

    report = freshness.check(tmp_path, pd.Timestamp("2026-11-17 07:00"))

    assert report["calendar_source"] == "weekday"
    assert report["items"][0]["status"] == "missing"
    assert report["items"][0]["day"] is None
    assert all(item["status"] == "missing" for item in report["items"])
    assert len(report["stale"]) == len(freshness.DATASETS)


def test_check_counts_trading_days_and_returns_stale_items(tmp_path, monkeypatch):
    path = tmp_path / "market/market_latest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"asof": "2026-11-13"}), encoding="utf-8")
    monkeypatch.setattr(
        stock,
        "_reference_calendar",
        lambda cutoff: pd.DatetimeIndex(["2026-11-16"]),
    )

    report = freshness.check(
        tmp_path, pd.Timestamp("2026-11-17 07:00", tz="Asia/Shanghai")
    )

    market = report["items"][0]
    assert report["calendar_source"] == "trading"
    assert (market["day"], market["lag"], market["status"]) == ("2026-11-13", 1, "late")
    assert len(report["stale"]) == len(freshness.DATASETS)


def test_check_includes_all_index_lppls_datasets(tmp_path, monkeypatch):
    expected = [
        ("index_sh000001", "上证指数 LPPLS", "index/sh000001_latest.json"),
        ("index_sh000016", "上证50 LPPLS", "index/sh000016_latest.json"),
        ("index_sh000300", "沪深300 LPPLS", "index/sh000300_latest.json"),
        ("index_sh000905", "中证500 LPPLS", "index/sh000905_latest.json"),
        ("index_sh000688", "科创50 LPPLS", "index/sh000688_latest.json"),
        ("index_sz399001", "深证成指 LPPLS", "index/sz399001_latest.json"),
        ("index_sz399006", "创业板指 LPPLS", "index/sz399006_latest.json"),
    ]
    for _, _, relative_path in expected:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"asof": "2026-11-16"}), encoding="utf-8")
    monkeypatch.setattr(
        stock,
        "_reference_calendar",
        lambda cutoff: pd.DatetimeIndex(["2026-11-16"]),
    )

    report = freshness.check(
        tmp_path, pd.Timestamp("2026-11-17 07:00", tz="Asia/Shanghai")
    )

    configured = [item for item in freshness.DATASETS if item[0].startswith("index_")]
    index_items = [item for item in report["items"] if item["key"].startswith("index_")]
    assert configured == expected
    assert [(item["key"], item["label"], item["path"]) for item in index_items] == expected
    assert all(
        (item["day"], item["lag"], item["status"]) == ("2026-11-16", 0, "ok")
        for item in index_items
    )


def test_growth_monitor_is_in_published_freshness_checks():
    assert (
        "growth",
        "成长监控",
        "growth/growth_latest.json",
    ) in freshness.DATASETS


def test_markdown_uses_chinese_status_table():
    text = freshness.render_markdown(
        {
            "items": [
                {
                    "label": "市场复盘",
                    "day": "2026-11-16",
                    "lag": 0,
                    "status": "ok",
                },
                {
                    "label": "宏观",
                    "day": None,
                    "lag": None,
                    "status": "missing",
                },
            ]
        }
    )

    assert "| 数据 | 数据日期 | 晚几个交易日 | 状态 |" in text
    assert "| 市场复盘 | 2026-11-16 | 0 | 正常 |" in text
    assert "| 宏观 | — | — | 缺失 |" in text
