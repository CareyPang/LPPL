from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .market_base import EM_DATACENTER_URL, EMClient

DATA_DIR = Path("web/mock/data/events")
PROVIDER = "datacenter-web.eastmoney.com"
PAGE_SIZE = 500
DESCRIPTIVE_NOTE = (
    "公告事件是事实记录，仅作描述，不进入 LPPLS 报警或任何模型。"
)
UNITS_NOTE = (
    "单位核对：CURRENT_FREE_SHARES 按东财原始值直接作为万股；FREE_SHARES 保留原值，口径未核实；"
    "LIFT_MARKET_CAP 为万元，实测 002202、002209 与 CURRENT_FREE_SHARES（万股）乘对应股价吻合，"
    "但不与 FREE_SHARES 乘股价吻合。PRETAX_BONUS_RMB 为元/10股，与 IMPL_PLAN_PROFILE 文本相符。"
)

LIFT_SORT_COLUMNS = (
    "FREE_DATE",
    "SECURITY_CODE",
    "FREE_SHARES_TYPE",
    "CURRENT_FREE_SHARES",
)
DIVIDEND_SORT_COLUMNS = (
    "EX_DIVIDEND_DATE",
    "SECURITY_CODE",
    "REPORT_DATE",
    "PRETAX_BONUS_RMB",
    "ASSIGN_PROGRESS",
    "IMPL_PLAN_PROFILE",
)
FORECAST_SORT_COLUMNS = (
    "NOTICE_DATE",
    "SECURITY_CODE",
    "REPORT_DATE",
    "PREDICT_TYPE",
    "PREDICT_FINANCE_CODE",
)


def _as_date(value: str | date) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"日期须为 YYYY-MM-DD: {value!r}") from exc


def _source_day(value: object, field: str) -> str:
    if value is None:
        raise RuntimeError(f"东财事件行缺少日期字段 {field}")
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise RuntimeError(f"东财事件字段 {field} 不是有效日期: {value!r}") from exc


def _number(value: object, field: str) -> float | None:
    if value is None or str(value).strip() in ("", "-", "--", "None", "nan", "NaN"):
        return None
    if isinstance(value, bool):
        raise RuntimeError(f"东财事件字段 {field} 不是数值: {value!r}")
    try:
        result = float(str(value).replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"东财事件字段 {field} 不是数值: {value!r}") from exc
    if not math.isfinite(result):
        raise RuntimeError(f"东财事件字段 {field} 不是有限数值: {value!r}")
    return result


def _text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _code(row: dict) -> str:
    value = str(row.get("SECURITY_CODE") or "").strip()
    if not re.fullmatch(r"\d{6}", value):
        raise RuntimeError(f"东财事件行证券代码无效: {value!r}")
    return value


def _require_name(row: dict) -> str:
    value = _text(row.get("SECURITY_NAME_ABBR"))
    if not value:
        raise RuntimeError("东财事件行缺少 SECURITY_NAME_ABBR")
    return value


def _fetch_rows(
    client: EMClient,
    report_name: str,
    filter_str: str,
    sort_columns: tuple[str, ...],
    sort_types: tuple[str, ...],
    page_size: int = PAGE_SIZE,
) -> list[dict]:
    if not 1 <= page_size <= PAGE_SIZE:
        raise ValueError(f"page_size 须在 1–{PAGE_SIZE} 之间")
    if len(sort_columns) != len(sort_types) or len(sort_columns) < 2:
        raise ValueError("sortColumns 和 sortTypes 必须等长且包含日期及证券代码")
    if sort_columns[1] != "SECURITY_CODE":
        raise ValueError("SECURITY_CODE 必须作为第二排序字段")

    rows = []
    seen_rows = set()
    seen_sort_keys = set()
    expected = None
    page = 1
    while True:
        payload = client.get_json(
            EM_DATACENTER_URL,
            params={
                "reportName": report_name,
                "columns": "ALL",
                "filter": filter_str,
                "pageNumber": str(page),
                "pageSize": str(page_size),
                "sortColumns": ",".join(sort_columns),
                "sortTypes": ",".join(sort_types),
                "source": "WEB",
                "client": "WEB",
            },
        )
        if not isinstance(payload, dict):
            raise RuntimeError(f"东财 {report_name} 返回的不是 JSON 对象")
        code = payload.get("code")
        if code == 9201:
            if page == 1:
                return []
            raise RuntimeError(f"东财 {report_name} 第 {page} 页返回空数据，分页不完整")
        if isinstance(code, bool) or code != 0:
            raise RuntimeError(
                f"东财 {report_name} 返回错误: {code!r} {payload.get('message')}"
            )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"东财 {report_name} result 不是对象")
        data = result.get("data")
        if data is None:
            data = []
        pages, count = result.get("pages"), result.get("count")
        if (
            not isinstance(data, list)
            or not all(isinstance(row, dict) for row in data)
            or isinstance(pages, bool)
            or not isinstance(pages, int)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or pages < 0
            or count < 0
        ):
            raise RuntimeError(f"东财 {report_name} 分页字段或 data 格式无效")
        if count == 0 and not data and page == 1:
            if pages not in (0, 1):
                raise RuntimeError(f"东财 {report_name} 空结果的 pages={pages}")
            return []
        if count <= 0 or pages < 1:
            raise RuntimeError(f"东财 {report_name} 返回了不一致的 count/pages")
        if pages != max(1, math.ceil(count / page_size)):
            raise RuntimeError(
                f"东财 {report_name} 页数不匹配: count={count}, pages={pages}"
            )
        if expected is None:
            expected = (pages, count)
        elif expected != (pages, count):
            raise RuntimeError(f"东财 {report_name} 翻页时 count/pages 发生变化")
        if not data or len(data) > page_size:
            raise RuntimeError(f"东财 {report_name} 第 {page} 页数据长度异常")
        if page < pages and len(data) != page_size:
            raise RuntimeError(f"东财 {report_name} 第 {page} 页非末页且未满页")

        for row in data:
            sort_key = tuple(row.get(field) for field in sort_columns)
            if any(value is None for value in sort_key):
                raise RuntimeError(
                    f"东财 {report_name} 排序字段缺失: {sort_columns!r}"
                )
            if sort_key in seen_sort_keys:
                raise RuntimeError(f"东财 {report_name} 排序字段不唯一，分页结果不可信")
            seen_sort_keys.add(sort_key)
            serialized = json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False)
            if serialized in seen_rows:
                raise RuntimeError(f"东财 {report_name} 翻页返回重复行")
            seen_rows.add(serialized)
            rows.append(row)
        if page == pages:
            if len(rows) != count:
                raise RuntimeError(
                    f"东财 {report_name} 翻页后 {len(rows)} 条，与总数 {count} 不符"
                )
            return rows
        page += 1


def _validate_window(
    rows: list[dict], field: str, start: date, end: date
) -> list[tuple[dict, str]]:
    output = []
    for row in rows:
        day = _source_day(row.get(field), field)
        parsed = date.fromisoformat(day)
        if not start <= parsed <= end:
            raise RuntimeError(
                f"东财 {field}={day} 超出请求区间 {start.isoformat()}~{end.isoformat()}"
            )
        output.append((row, day))
    return output


def _normalize_lift(rows: list[dict], start: date, end: date) -> list[dict]:
    normalized = []
    for row, day in _validate_window(rows, "FREE_DATE", start, end):
        current_free_shares = _number(row.get("CURRENT_FREE_SHARES"), "CURRENT_FREE_SHARES")
        normalized.append(
            {
                "code": _code(row),
                "name": _require_name(row),
                "free_date": day,
                "free_shares_raw": _number(row.get("FREE_SHARES"), "FREE_SHARES"),
                "free_shares_raw_label": "东财 FREE_SHARES（口径未核实）",
                "current_free_shares_10k": current_free_shares,
                "lift_market_cap_10k": _number(row.get("LIFT_MARKET_CAP"), "LIFT_MARKET_CAP"),
                "free_ratio": _number(row.get("FREE_RATIO"), "FREE_RATIO"),
                "free_shares_type": _text(row.get("FREE_SHARES_TYPE")),
                "batch_holder_num": _number(row.get("BATCH_HOLDER_NUM"), "BATCH_HOLDER_NUM"),
            }
        )
    return normalized


def _normalize_dividend(rows: list[dict], start: date, end: date) -> list[dict]:
    normalized = []
    for row, day in _validate_window(rows, "EX_DIVIDEND_DATE", start, end):
        normalized.append(
            {
                "code": _code(row),
                "name": _require_name(row),
                "ex_dividend_date": day,
                "equity_record_date": (
                    _source_day(row["EQUITY_RECORD_DATE"], "EQUITY_RECORD_DATE")
                    if row.get("EQUITY_RECORD_DATE")
                    else None
                ),
                "pretax_bonus_rmb_10": _number(
                    row.get("PRETAX_BONUS_RMB"), "PRETAX_BONUS_RMB"
                ),
                "bonus_ratio": _number(row.get("BONUS_RATIO"), "BONUS_RATIO"),
                "it_ratio": _number(row.get("IT_RATIO"), "IT_RATIO"),
                "assign_progress": _text(row.get("ASSIGN_PROGRESS")),
                "report_date": (
                    _source_day(row["REPORT_DATE"], "REPORT_DATE")
                    if row.get("REPORT_DATE")
                    else None
                ),
                "plan_text": _text(row.get("IMPL_PLAN_PROFILE")),
            }
        )
    return normalized


def _indicator(row: dict) -> dict:
    code = str(row.get("PREDICT_FINANCE_CODE") or "").strip()
    if code.isdigit():
        code = code.zfill(3)
    reason = _text(row.get("CHANGE_REASON_EXPLAIN"))
    return {
        "indicator_code": code or None,
        "indicator": _text(row.get("PREDICT_FINANCE")),
        "amount_lower": _number(row.get("PREDICT_AMT_LOWER"), "PREDICT_AMT_LOWER"),
        "amount_upper": _number(row.get("PREDICT_AMT_UPPER"), "PREDICT_AMT_UPPER"),
        "change_pct_lower": _number(row.get("ADD_AMP_LOWER"), "ADD_AMP_LOWER"),
        "change_pct_upper": _number(row.get("ADD_AMP_UPPER"), "ADD_AMP_UPPER"),
        "content": _text(row.get("PREDICT_CONTENT")),
        "reason": reason[:200] if reason is not None else None,
    }


def _normalize_forecast(rows: list[dict], start: date, end: date) -> list[dict]:
    grouped = {}
    for row, day in _validate_window(rows, "NOTICE_DATE", start, end):
        code = _code(row)
        report_date = (
            _source_day(row["REPORT_DATE"], "REPORT_DATE")
            if row.get("REPORT_DATE")
            else None
        )
        predict_type = _text(row.get("PREDICT_TYPE"))
        key = (code, day, report_date, predict_type)
        event = grouped.setdefault(
            key,
            {
                "code": code,
                "name": _require_name(row),
                "notice_date": day,
                "report_date": report_date,
                "predict_type": predict_type,
                "headline": None,
                "other_indicators": [],
            },
        )
        indicator = _indicator(row)
        if indicator["indicator_code"] == "004":
            if event["headline"] is not None:
                raise RuntimeError(f"业绩预告 {key} 有多个 004 归母净利润行")
            event["headline"] = indicator
        else:
            event["other_indicators"].append(indicator)
    return list(grouped.values())


def _by_date(lift: list[dict], dividend: list[dict]) -> dict:
    daily = defaultdict(lambda: {"lift_n": 0, "dividend_n": 0, "_caps": [], "_missing_cap": False})
    for row in lift:
        item = daily[row["free_date"]]
        item["lift_n"] += 1
        cap = row.get("lift_market_cap_10k")
        if cap is None:
            item["_missing_cap"] = True
        else:
            item["_caps"].append(cap)
    for row in dividend:
        daily[row["ex_dividend_date"]]["dividend_n"] += 1
    return {
        day: {
            "lift_n": item["lift_n"],
            "lift_cap": (
                sum(item["_caps"])
                if item["_caps"] and not item["_missing_cap"]
                else None
            ),
            "dividend_n": item["dividend_n"],
        }
        for day, item in sorted(daily.items())
    }


def _read_previous(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _source_meta(
    ok: bool,
    n: int,
    source_rows_n: int,
    stale: bool = False,
    error: str | None = None,
) -> dict:
    result = {
        "ok": ok,
        "provider": PROVIDER,
        "n": n,
        "source_rows_n": source_rows_n,
        "stale": stale,
        "fetched_at": datetime.now().astimezone().isoformat(),
    }
    if error:
        result["error"] = error
    return result


def fetch_events(
    asof: str | date | None = None,
    client: EMClient | None = None,
    previous_path: Path | None = DATA_DIR / "events_latest.json",
) -> dict:
    day = _as_date(asof or datetime.now(ZoneInfo("Asia/Shanghai")).date())
    lift_start, lift_end = day, day + timedelta(days=30)
    forecast_start, forecast_end = day - timedelta(days=30), day
    em = client or EMClient()
    previous = _read_previous(previous_path)
    previous_sources = previous.get("sources", {}) if isinstance(previous, dict) else {}
    if not isinstance(previous_sources, dict):
        previous_sources = {}
    sections = {}
    sources = {}

    configs = [
        (
            "lift",
            "RPT_LIFT_STAGE",
            f"(FREE_DATE>='{lift_start}')(FREE_DATE<='{lift_end}')",
            LIFT_SORT_COLUMNS,
            ("1",) * len(LIFT_SORT_COLUMNS),
            lift_start,
            lift_end,
            _normalize_lift,
        ),
        (
            "dividend",
            "RPT_SHAREBONUS_DET",
            f"(EX_DIVIDEND_DATE>='{lift_start}')(EX_DIVIDEND_DATE<='{lift_end}')",
            DIVIDEND_SORT_COLUMNS,
            ("1",) * len(DIVIDEND_SORT_COLUMNS),
            lift_start,
            lift_end,
            _normalize_dividend,
        ),
        (
            "forecast",
            "RPT_PUBLIC_OP_NEWPREDICT",
            f"(NOTICE_DATE>='{forecast_start}')(NOTICE_DATE<='{forecast_end}')",
            FORECAST_SORT_COLUMNS,
            ("-1", "1", "-1", "1", "1"),
            forecast_start,
            forecast_end,
            _normalize_forecast,
        ),
    ]
    for name, report, filter_str, sort_columns, sort_types, start, end, normalize in configs:
        try:
            raw_rows = _fetch_rows(
                em, report, filter_str, sort_columns, sort_types, page_size=PAGE_SIZE
            )
            rows = normalize(raw_rows, start, end)
            sections[name] = rows
            sources[name] = _source_meta(True, len(rows), len(raw_rows))
        except Exception as exc:
            old_rows = previous.get(name, [])
            if not isinstance(old_rows, list):
                old_rows = []
            old_meta = previous_sources.get(name, {})
            if not isinstance(old_meta, dict):
                old_meta = {}
            old_source_rows_n = old_meta.get("source_rows_n", old_meta.get("n", len(old_rows)))
            try:
                old_source_rows_n = int(old_source_rows_n)
            except (TypeError, ValueError):
                old_source_rows_n = len(old_rows)
            sections[name] = old_rows
            sources[name] = _source_meta(
                False,
                len(old_rows),
                old_source_rows_n,
                stale=True,
                error=f"{type(exc).__name__}: {exc}",
            )

    return {
        "asof": day.isoformat(),
        "generated": datetime.now().astimezone().isoformat(),
        "window": {
            "lift": [lift_start.isoformat(), lift_end.isoformat()],
            "dividend": [lift_start.isoformat(), lift_end.isoformat()],
            "forecast": [forecast_start.isoformat(), forecast_end.isoformat()],
        },
        "sources": sources,
        "lift": sections["lift"],
        "dividend": sections["dividend"],
        "forecast": sections["forecast"],
        "by_date": _by_date(sections["lift"], sections["dividend"]),
        "evidence": "descriptive",
        "note": UNITS_NOTE + DESCRIPTIVE_NOTE,
    }


def write_snapshot(payload: dict, out: Path) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    latest_path = out / "events_latest.json"
    dated_path = out / f"events_{payload['asof']}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    latest_path.write_text(text, encoding="utf-8")
    dated_path.write_text(text, encoding="utf-8")
    return latest_path, dated_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        default=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
    )
    parser.add_argument("--out", type=Path, default=DATA_DIR)
    parser.add_argument("--previous", type=Path, default=DATA_DIR / "events_latest.json")
    args = parser.parse_args(argv)
    asof = _as_date(args.date)
    payload = fetch_events(asof, previous_path=args.previous)
    latest, dated = write_snapshot(payload, args.out)
    print(
        json.dumps(
            {
                "latest": str(latest),
                "dated": str(dated),
                "asof": payload["asof"],
                "counts": {
                    name: {
                        "events": len(payload[name]),
                        "source_rows": payload["sources"][name]["source_rows_n"],
                    }
                    for name in ("lift", "dividend", "forecast")
                },
                "sources": payload["sources"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
