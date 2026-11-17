from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

DATASETS = [
    ("market", "市场复盘", "market/market_latest.json"),
    ("events", "事件日历", "events/events_latest.json"),
    ("abnormal", "异动提醒", "market/abnormal_latest.json"),
    ("range", "区间统计", "market/range_latest.json"),
    ("macro", "全球宏观", "macro/macro_latest.json"),
    ("growth", "成长监控", "growth/growth_latest.json"),
    ("nt_etf", "国家队 ETF", "nt_etf/nt_etf_latest.json"),
    ("dip_env", "指数/ETF 环境", "stock/_dip_env.json"),
    ("breadth_sh000300", "沪深300 个股批量", "stock/breadth_sh000300.json"),
    ("breadth_sh000905", "中证500 个股批量", "stock/breadth_sh000905.json"),
    ("index_sh000001", "上证指数 LPPLS", "index/sh000001_latest.json"),
    ("index_sh000016", "上证50 LPPLS", "index/sh000016_latest.json"),
    ("index_sh000300", "沪深300 LPPLS", "index/sh000300_latest.json"),
    ("index_sh000905", "中证500 LPPLS", "index/sh000905_latest.json"),
    ("index_sh000688", "科创50 LPPLS", "index/sh000688_latest.json"),
    ("index_sz399001", "深证成指 LPPLS", "index/sz399001_latest.json"),
    ("index_sz399006", "创业板指 LPPLS", "index/sz399006_latest.json"),
]


def _beijing_time(value: pd.Timestamp) -> pd.Timestamp:
    current = pd.Timestamp(value)
    if current.tzinfo is None:
        return current.tz_localize("Asia/Shanghai")
    return current.tz_convert("Asia/Shanghai")


def data_day(payload: dict) -> str | None:
    indicators = payload.get("indicators")
    if isinstance(indicators, list):
        dates = []
        for item in indicators:
            if not isinstance(item, dict) or not item.get("asof"):
                continue
            try:
                dates.append(date.fromisoformat(str(item["asof"])))
            except ValueError:
                continue
        return max(dates).isoformat() if dates else None

    asof = payload.get("asof")
    if asof:
        try:
            return date.fromisoformat(str(asof)).isoformat()
        except ValueError:
            pass

    for field in ("generated_at", "generated"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            generated = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            continue
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=UTC)
        return generated.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    return None


def lag_trading_days(
    day: str, now: pd.Timestamp, calendar: Sequence[date] | None
) -> int:
    data_date = date.fromisoformat(day)
    end = _reference_end(now)
    if data_date >= end:
        return 0

    if calendar is not None:
        trading_days = {pd.Timestamp(value).date() for value in calendar}
        return sum(data_date < trading_day <= end for trading_day in trading_days)

    lag = 0
    current = data_date + timedelta(days=1)
    while current <= end:
        if current.weekday() < 5:
            lag += 1
        current += timedelta(days=1)
    return lag


def _reference_end(now: pd.Timestamp) -> date:
    return (_beijing_time(pd.Timestamp(now)) - pd.Timedelta(hours=30)).date()


def _trading_days_between(
    first_day: date, end_day: date, calendar: Sequence[date] | None
) -> list[date]:
    if calendar is not None:
        return sorted(
            {
                pd.Timestamp(value).date()
                for value in calendar
                if first_day < pd.Timestamp(value).date() < end_day
            }
        )

    days = []
    current = first_day + timedelta(days=1)
    while current < end_day:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _forward_log_item(
    path: str | Path,
    now: pd.Timestamp,
    calendar: Sequence[date] | None,
) -> dict:
    from research.pipeline.forward_log import SYMS

    item = {
        "key": "forward_log",
        "label": "前瞻日志封存",
        "path": str(path),
        "day": None,
        "lag": None,
        "status": "missing",
        "missing_days": [],
    }
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return item

    expected_symbols = set(SYMS)
    symbols_by_day: dict[str, set[str]] = {}
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        symbol = record.get("symbol")
        asof = record.get("asof")
        if not isinstance(symbol, str) or symbol not in expected_symbols:
            continue
        if not isinstance(asof, str):
            continue
        try:
            sealed_day = date.fromisoformat(asof).isoformat()
        except ValueError:
            continue
        symbols_by_day.setdefault(sealed_day, set()).add(symbol)

    if not symbols_by_day:
        return item

    complete_days = sorted(
        day for day, symbols in symbols_by_day.items() if expected_symbols <= symbols
    )
    latest_day = complete_days[-1] if complete_days else None
    end_day = _reference_end(now)
    first_day = date.fromisoformat(min(symbols_by_day))
    complete_day_set = set(complete_days)
    item["missing_days"] = [
        day.isoformat()
        for day in _trading_days_between(first_day, end_day, calendar)
        if day.isoformat() not in complete_day_set
    ]

    if latest_day is not None:
        lag = lag_trading_days(latest_day, now, calendar)
        item.update(
            {
                "day": latest_day,
                "lag": lag,
                "status": "ok" if lag == 0 else "late",
            }
        )
    return item


def render_markdown(report: dict) -> str:
    status_labels = {"ok": "正常", "late": "过期", "missing": "缺失"}
    rows = [
        "| 数据 | 数据日期 | 晚几个交易日 | 状态 |",
        "| --- | --- | ---: | --- |",
    ]
    for item in report["items"]:
        day = item["day"] or "—"
        lag = str(item["lag"]) if item["lag"] is not None else "—"
        status = status_labels.get(item["status"], item["status"])
        label = item["label"]
        if item.get("key") == "forward_log":
            missing_days = item.get("missing_days", [])
            label += f"（缺 {len(missing_days)} 天"
            if missing_days:
                label += "：" + "、".join(missing_days[:10])
                if len(missing_days) > 10:
                    label += "…，最多列 10 个"
            label += "）"
        rows.append(f"| {label} | {day} | {lag} | {status} |")
    return "\n".join(rows)


def check(
    root: Path,
    now: pd.Timestamp | None = None,
    forward_log: str | Path | None = None,
) -> dict:
    from research.pipeline import stock

    current = _beijing_time(stock._now() if now is None else pd.Timestamp(now))
    try:
        reference = stock._reference_calendar(stock._close_cutoff(current))
        calendar = [pd.Timestamp(value).date() for value in reference]
        if not calendar:
            raise ValueError("reference calendar is empty")
        calendar_source = "trading"
    except Exception:
        calendar = None
        calendar_source = "weekday"

    items = []
    root = Path(root)
    for key, label, relative_path in DATASETS:
        path = root / relative_path
        day = None
        lag = None
        status = "missing"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                day = data_day(payload)
            if day is not None:
                lag = lag_trading_days(day, current, calendar)
                status = "ok" if lag == 0 else "late"
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
        items.append(
            {
                "key": key,
                "label": label,
                "path": relative_path,
                "day": day,
                "lag": lag,
                "status": status,
            }
        )

    if forward_log is not None:
        items.append(_forward_log_item(forward_log, current, calendar))

    stale = [
        item
        for item in items
        if item["status"] != "ok"
        or (item.get("key") == "forward_log" and item.get("missing_days"))
    ]
    return {
        "checked_at": current.isoformat(),
        "calendar_source": calendar_source,
        "items": items,
        "stale": stale,
    }


def _write_text(path: str, content: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check published data freshness.")
    parser.add_argument("--root", required=True, help="Path to the stock-results snapshot")
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--markdown", dest="markdown_path")
    parser.add_argument("--forward-log", help="Path to the forward-log ledger")
    args = parser.parse_args(argv)

    report = check(Path(args.root), forward_log=args.forward_log)
    json_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.json_path:
        _write_text(args.json_path, json_text)
    else:
        print(json_text, end="")
    if args.markdown_path:
        _write_text(args.markdown_path, render_markdown(report) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
