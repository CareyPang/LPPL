from __future__ import annotations

import argparse
import copy
import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from .global_macro import fetch_treasury
from .nt_etf import _fetch_shares, _szse_history, flow_yuan
from .tencent_sina import tencent_raw

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "out" / "growth"
NAV_URL = "https://api.fund.eastmoney.com/f10/lsjz"
NAV_HEADERS = {
    "Referer": "https://fundf10.eastmoney.com/",
    "User-Agent": "Mozilla/5.0 (compatible; LPPLGrowthMonitor/1.0)",
}
CNINDEX_URL = (
    "https://hq.cnindex.com.cn/market/market/"
    "getIndexDailyDataWithDataFormat"
)
CNINDEX_HEADERS = {"User-Agent": "Mozilla/5.0"}
ETFS = (
    {"code": "159995", "name": "国证芯片", "exchange": "SZ"},
    {"code": "512480", "name": "中证全指半导体", "exchange": "SH"},
    {"code": "512760", "name": "中华半导体芯片", "exchange": "SH"},
    {"code": "588200", "name": "科创芯片", "exchange": "SH"},
)
RULES = {
    "fund_growth_position": (
        "先固定基金样本、成长行业分类、规模加权份额；不得用主动权益持仓代替；"
        "周度代理、季度正式；统一口径后低于 60%。"
    ),
    "semi_etf_flow": (
        "固定篮子 159995（国证芯片）、512480（中证全指半导体）、"
        "512760（中华半导体芯片）、588200（科创芯片）；日申赎估算 = "
        "(份额_t − 份额_{t−1}) × 单位净值_t；最近两个完整自然周篮子合计净申购都 >0。"
    ),
    "us10y": "最近 5 个有观测的美国交易日收盘收益率全部 < 4.50%。",
    "growth_rs": (
        "RS_t = close(sz980017 国证芯片) / close(sh000300)；"
        "MA20 为 RS 的 20 日简单均线；最近 10 个交易日 RS 全部 > MA20"
        "（重新站上 20 日均线并维持两周）。"
    ),
}


def _number(value) -> float | None:
    if value is None or str(value).strip() in {"", "-", "--", "—"}:
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def parse_nav_payload(payload: dict) -> dict[str, dict]:
    result = payload.get("Data") or payload.get("data") or {}
    rows = result.get("LSJZList") or result.get("lsjzList") or []
    output = {}
    for row in rows:
        day = str(row.get("FSRQ") or "").strip()
        nav = _number(row.get("DWJZ"))
        try:
            date.fromisoformat(day)
        except ValueError:
            continue
        output[day] = {
            "nav": nav,
            "action": bool(str(row.get("FHSP") or "").strip())
            or bool(str(row.get("FHFCZ") or "").strip()),
        }
    return output


def parse_cnindex_payload(payload: dict) -> list[dict]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("CNIndex response lacks data")
    columns = data.get("item")
    rows = data.get("data")
    if not isinstance(columns, list) or "close" not in columns:
        raise ValueError("CNIndex response lacks close column")
    if not isinstance(rows, list):
        raise ValueError("CNIndex response lacks daily rows")
    close_index = columns.index("close")
    by_date = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) <= close_index:
            continue
        try:
            day = date.fromisoformat(str(row[0]).strip()).isoformat()
        except ValueError:
            continue
        close = _number(row[close_index])
        if close is not None:
            by_date.setdefault(day, close)
    return [{"date": day, "close": by_date[day]} for day in sorted(by_date)]


def completed_weekly_flows(
    daily: list[dict], asof: str, codes: tuple[str, ...]
) -> list[dict]:
    asof_date = date.fromisoformat(asof)
    weeks: dict[date, list[dict]] = defaultdict(list)
    for row in daily:
        day = date.fromisoformat(row["date"])
        monday = day - timedelta(days=day.weekday())
        if day <= asof_date:
            weeks[monday].append(row)

    if not weeks:
        return []
    asof_monday = asof_date - timedelta(days=asof_date.weekday())
    last_complete_monday = (
        asof_monday - timedelta(days=7) if asof_date.weekday() < 4 else asof_monday
    )
    output = []
    monday = min(weeks)
    while monday <= last_complete_monday:
        rows = weeks.get(monday, [])
        by_code = {}
        for code in codes:
            values = [
                row.get("flows", {}).get(code)
                for row in rows
                if row.get("flows", {}).get(code) is not None
            ]
            by_code[code] = round(sum(values), 2) if values else None
        available = [value for value in by_code.values() if value is not None]
        output.append(
            {
                "week_start": monday.isoformat(),
                "week_end": (monday + timedelta(days=4)).isoformat(),
                "data_asof": max(
                    (
                        row["date"]
                        for row in rows
                        if any(
                            value is not None
                            for value in row.get("flows", {}).values()
                        )
                    ),
                    default=None,
                ),
                "flow_yuan": round(sum(available), 2) if available else None,
                "etfs": by_code,
                "missing_codes": sorted(
                    {
                        code
                        for row in rows
                        for code in row.get("missing_share_codes", [])
                    }
                ),
            }
        )
        monday += timedelta(days=7)
    return output[-12:]


def share_exclusion_reason(
    previous: float | None, current: float | None, action: bool
) -> str | None:
    if action:
        return "FHSP/FHFCZ 非空，疑似分红/拆分折算"
    if (
        previous not in (None, 0)
        and current is not None
        and abs(current - previous) / abs(previous) > 0.30
    ):
        return "份额单日变动超过 30%，疑似合并/拆分/折算"
    return None


def semi_status(
    weekly: list[dict], missing_codes: list[str], codes: tuple[str, ...]
) -> tuple[str, str | None]:
    if len(missing_codes) == len(codes):
        return "missing", "四只 ETF 均无可用份额数据。"
    if missing_codes:
        return "partial", "份额数据缺失代码：" + "、".join(missing_codes)
    if len(weekly) < 2 or any(row["flow_yuan"] is None for row in weekly[-2:]):
        return "missing", "最近两个完整自然周缺少可计算的篮子合计。"
    return (
        "met" if all(row["flow_yuan"] > 0 for row in weekly[-2:]) else "not_met",
        None,
    )


def evaluate_us10y(rows: list[dict]) -> dict:
    recent = [
        {"date": str(row["date"]), "value": float(row["10y"])}
        for row in rows
        if row.get("10y") is not None
    ][-60:]
    last_five = recent[-5:]
    status = (
        "missing"
        if len(last_five) < 5
        else "met"
        if all(row["value"] < 4.50 for row in last_five)
        else "not_met"
    )
    return {
        "status": status,
        "asof": recent[-1]["date"] if recent else None,
        "value": {
            "last_five": last_five,
            "all_below_4_50": status == "met",
        }
        if recent
        else None,
        "recent": recent,
        "missing_reason": "不足 5 个有观测的美国交易日" if len(last_five) < 5 else None,
    }


def evaluate_growth_rs(chip_bars: list[dict], market_bars: list[dict]) -> dict:
    chip = {
        str(row["date"])[:10]: _number(row.get("close"))
        for row in chip_bars
        if _number(row.get("close")) is not None
    }
    market = {
        str(row["date"])[:10]: _number(row.get("close"))
        for row in market_bars
        if _number(row.get("close")) is not None
    }
    dates = sorted(set(chip) & set(market))
    ratios = [
        (day, chip[day] / market[day])
        for day in dates
        if market[day] != 0
    ]
    recent = []
    for index in range(19, len(ratios)):
        values = [value for _, value in ratios[index - 19 : index + 1]]
        recent.append(
            {
                "date": ratios[index][0],
                "rs": ratios[index][1],
                "ma20": sum(values) / 20,
            }
        )

    last_ten = recent[-10:]
    above = bool(last_ten) and len(last_ten) == 10 and all(
        row["rs"] > row["ma20"] for row in last_ten
    )
    streak = 0
    for row in reversed(recent):
        if row["rs"] <= row["ma20"]:
            break
        streak += 1
    crosses = [
        recent[index]["date"]
        for index in range(1, len(recent))
        if recent[index]["rs"] > recent[index]["ma20"]
        and recent[index - 1]["rs"] <= recent[index - 1]["ma20"]
    ]
    status = (
        "missing"
        if len(last_ten) < 10
        else "met"
        if above
        else "not_met"
    )
    return {
        "status": status,
        "asof": recent[-1]["date"] if recent else None,
        "value": {
            "latest_rs": recent[-1]["rs"],
            "ma20": recent[-1]["ma20"],
            "consecutive_above_days": streak,
            "last_cross_date": crosses[-1] if crosses else None,
        }
        if recent
        else None,
        "recent": recent[-120:],
        "missing_reason": "共同交易日不足 29 个，无法计算最近 10 日判定"
        if len(last_ten) < 10
        else None,
    }


def _indicator(
    indicator_id: str,
    name: str,
    role: str,
    status: str,
    value,
    unit: str,
    asof: str | None,
    source: str,
    rule: str,
    *,
    note: str = "",
    missing_reason: str | None = None,
    recent: list | None = None,
) -> dict:
    return {
        "id": indicator_id,
        "name": name,
        "role": role,
        "status": status,
        "value": value,
        "unit": unit,
        "asof": asof,
        "source": source,
        "rule": rule,
        "note": note,
        "missing_reason": missing_reason,
        "recent": recent or [],
    }


def _pending_position() -> dict:
    return _indicator(
        "fund_growth_position",
        "公募成长仓位",
        "core",
        "pending_definition",
        None,
        "%",
        None,
        "本版未取数",
        RULES["fund_growth_position"],
        note="待统一口径",
        missing_reason="本版不取数，待统一基金样本、成长行业分类与规模加权份额口径。",
    )


def _fallback(
    previous: dict | None, indicator_id: str, name: str, role: str, source: str
) -> dict:
    old = next(
        (
            item
            for item in (previous or {}).get("indicators", [])
            if item.get("id") == indicator_id
        ),
        None,
    )
    if old and old.get("asof"):
        result = copy.deepcopy(old)
        result["status"] = "partial"
        previous_asof = str(result["asof"])
        result["note"] = " ".join(
            part
            for part in (
                result.get("note") or "",
                f"本次取数失败，沿用上次 {previous_asof} 数据",
            )
            if part
        )
        result["missing_reason"] = "本次来源暂不可用，显示上次可用数据。"
        return result
    return _indicator(
        indicator_id,
        name,
        role,
        "missing",
        None,
        "",
        None,
        source,
        RULES[indicator_id],
        missing_reason="数据源本次取数失败，暂无可用历史数据。",
    )


def _fetch_nav(session, code: str, start: str) -> dict[str, dict]:
    output = {}
    for page_index in range(1, 11):
        response = session.get(
            NAV_URL,
            params={"fundCode": code, "pageIndex": page_index, "pageSize": 20},
            headers=NAV_HEADERS,
            timeout=25,
        )
        response.raise_for_status()
        page = parse_nav_payload(response.json())
        if not page:
            break
        output.update(page)
        if min(page) <= start:
            break
        if page_index < 10:
            time.sleep(0.2)
    return {day: row for day, row in output.items() if day >= start}


def _last_complete_week_end(asof: str) -> str:
    asof_date = date.fromisoformat(asof)
    days_since_friday = (asof_date.weekday() + 3) % 7
    return (asof_date - timedelta(days=days_since_friday)).isoformat()


def _share_error_notes(source: str, errors: list[str], cutoff: str) -> list[str]:
    notes = []
    for error in errors:
        prefix = error.split(":", 1)[0]
        try:
            error_date = date.fromisoformat(prefix).isoformat()
        except ValueError:
            error_date = None
        if error_date:
            if error_date > cutoff:
                continue
            note = f"{source}份额 {error_date} 未发布"
        elif prefix.isdigit() and len(prefix) == 6:
            note = f"{source}份额 {prefix} 暂不可用"
        else:
            note = f"{source}份额来源暂不可用"
        if note not in notes:
            notes.append(note)
    return notes


def _fetch_cnindex_980017(start: str, end: str, session) -> list[dict]:
    response = session.get(
        CNINDEX_URL,
        params={
            "indexCode": "980017",
            "startDate": start,
            "endDate": end,
            "frequency": "day",
        },
        headers=CNINDEX_HEADERS,
        timeout=25,
    )
    response.raise_for_status()
    return parse_cnindex_payload(response.json())


def _fetch_szse_with_retry(
    session, item: dict, start: str, end: str
) -> tuple[dict[str, float], str | None]:
    for attempt in range(3):
        try:
            return _szse_history(session, item["code"], start, end), None
        except Exception as exc:  # noqa: BLE001 — retry transient source errors
            error = f"{item['code']}: {type(exc).__name__}: {exc}"
            if attempt == 2:
                return {}, error
            time.sleep(0.25 * (attempt + 1))
    return {}, f"{item['code']}: unknown share-history error"


def _semi_etf_flow(asof: str, start: str, session) -> dict:
    price_maps = {}
    price_errors = []
    for item in ETFS:
        symbol = item["exchange"].lower() + item["code"]
        try:
            frame = tencent_raw(symbol, start=start, end=asof)
            price_maps[item["code"]] = {
                str(row.date)[:10]: _number(row.close)
                for row in frame.itertuples()
                if _number(row.close) is not None
            }
        except Exception as exc:  # noqa: BLE001 — sources fail independently
            price_errors.append(f"{item['code']}: {type(exc).__name__}: {exc}")

    dates = sorted({day for values in price_maps.values() for day in values})
    sh_etfs = tuple(item for item in ETFS if item["exchange"] == "SH")
    try:
        shares_sh, _, sse_errors, _ = _fetch_shares(
            sh_etfs, dates, start, asof, session
        )
    except Exception as exc:  # noqa: BLE001 — keep other indicators available
        shares_sh = {}
        sse_errors = [f"{type(exc).__name__}: {exc}"]
    shares_sz, szse_errors = {}, []
    for item in ETFS:
        if item["exchange"] != "SZ":
            continue
        history, error = _fetch_szse_with_retry(session, item, start, asof)
        shares_sz[item["code"]] = history
        if error:
            szse_errors.append(error)

    nav_maps = {}
    nav_errors = []
    for item in ETFS:
        try:
            nav_maps[item["code"]] = _fetch_nav(session, item["code"], start)
        except Exception as exc:  # noqa: BLE001 — use market close when possible
            nav_maps[item["code"]] = {}
            nav_errors.append(f"{item['code']}: {type(exc).__name__}: {exc}")

    daily = []
    notes_by_code = {item["code"]: [] for item in ETFS}
    available_share_days = {item["code"]: set() for item in ETFS}
    all_days = sorted(
        set(dates)
        | {day for values in shares_sz.values() for day in values}
        | set(shares_sh)
    )
    previous_shares = {item["code"]: None for item in ETFS}
    for day in all_days:
        flows = {}
        exclusions = {}
        missing_share_codes = []
        for item in ETFS:
            code = item["code"]
            if item["exchange"] == "SH":
                share_10k = (shares_sh.get(day, {}).get(code) or {}).get("shares_10k")
            else:
                share_10k = shares_sz.get(code, {}).get(day)
            shares = _number(share_10k) / 10000 if _number(share_10k) is not None else None
            if shares is not None:
                available_share_days[code].add(day)
            else:
                missing_share_codes.append(code)
            nav_row = nav_maps[code].get(day)
            close = (
                nav_row["nav"]
                if nav_row and nav_row["nav"] is not None
                else price_maps.get(code, {}).get(day)
            )
            if (
                (not nav_row or nav_row["nav"] is None)
                and close is not None
                and day <= _last_complete_week_end(asof)
            ):
                reason = f"{day} 净值缺失，用收盘价近似"
                if reason not in notes_by_code[code]:
                    notes_by_code[code].append(reason)
            exclusion = share_exclusion_reason(
                previous_shares[code], shares, bool(nav_row and nav_row["action"])
            )
            if exclusion:
                reason = exclusion
                exclusions[code] = reason
                note = f"{day}：{reason}，当日剔除"
                if note not in notes_by_code[code]:
                    notes_by_code[code].append(note)
                flows[code] = None
            else:
                flows[code] = flow_yuan(shares, previous_shares[code], close)
            previous_shares[code] = shares
        daily.append(
            {
                "date": day,
                "flows": flows,
                "excluded": exclusions,
                "missing_share_codes": missing_share_codes,
            }
        )

    codes = tuple(item["code"] for item in ETFS)
    weekly = completed_weekly_flows(daily, asof, codes)
    latest_share_day = max(
        (day for days in available_share_days.values() for day in days), default=None
    )
    missing_codes = [
        code
        for code, days in available_share_days.items()
        if not latest_share_day or latest_share_day not in days
    ]
    recent_weeks = weekly[-2:]
    missing_codes = sorted(
        set(missing_codes)
        | {
            code
            for row in recent_weeks
            for code in row["missing_codes"]
        }
    )
    status, reason = semi_status(weekly, missing_codes, codes)

    latest_daily = max(
        (
            row["date"]
            for row in daily
            if any(value is not None for value in row["flows"].values())
        ),
        default=None,
    )
    notes = []
    if missing_codes:
        notes.append("份额缺失代码：" + "、".join(missing_codes))
    for code in codes:
        if notes_by_code[code]:
            notes.append(f"{code}：{'；'.join(notes_by_code[code][-4:])}")
    for label, errors in (
        ("ETF 行情", price_errors),
        ("ETF 净值", nav_errors),
        ("上交所份额", sse_errors),
        ("深交所份额", szse_errors),
    ):
        if errors:
            print(f"{label}取数错误：" + "；".join(errors))
    if price_errors:
        codes_with_price_errors = [
            error.split(":", 1)[0] for error in price_errors
        ]
        notes.append("行情来源暂不可用：" + "、".join(codes_with_price_errors))
    if nav_errors:
        codes_with_nav_errors = [error.split(":", 1)[0] for error in nav_errors]
        notes.append(
            "单位净值来源暂不可用，相关日期已用收盘价近似："
            + "、".join(codes_with_nav_errors)
        )
    last_complete_week_end = _last_complete_week_end(asof)
    notes.extend(_share_error_notes("上交所", sse_errors, last_complete_week_end))
    notes.extend(_share_error_notes("深交所", szse_errors, last_complete_week_end))
    indicator_asof = next(
        (row["data_asof"] for row in reversed(weekly) if row["data_asof"]),
        latest_daily or latest_share_day,
    )
    return _indicator(
        "semi_etf_flow",
        "半导体 ETF 资金",
        "core",
        status,
        {
            "last_two_complete_weeks": weekly[-2:],
            "missing_codes": missing_codes,
        }
        if weekly or missing_codes
        else None,
        "亿元",
        indicator_asof,
        "上交所/深交所基金份额；东财单位净值；腾讯 ETF 收盘价近似",
        RULES["semi_etf_flow"],
        note="；".join(notes),
        missing_reason=reason,
        recent=weekly,
    )


def _rows_from_frame(frame) -> list[dict]:
    return [
        {"date": str(row.date)[:10], "close": float(row.close)}
        for row in frame.itertuples()
    ]


def _realize_indicator(previous: dict | None, indicator_id: str, name: str, role: str, source: str, callback) -> dict:
    try:
        result = callback()
    except Exception as exc:  # noqa: BLE001 — each source fails independently
        if indicator_id == "semi_etf_flow":
            print(f"半导体 ETF 采集错误：{type(exc).__name__}: {exc}")
        fallback = _fallback(previous, indicator_id, name, role, source)
        if fallback["status"] == "missing":
            fallback["note"] = (
                "半导体 ETF 数据源本次取数失败。"
                if indicator_id == "semi_etf_flow"
                else f"{type(exc).__name__}: {exc}"
            )
        return fallback
    if result["status"] == "missing":
        fallback = _fallback(previous, indicator_id, name, role, source)
        if fallback["status"] == "partial":
            details = result.get("note") or result.get("missing_reason") or ""
            fallback["note"] = f"{fallback['note']} {details}".strip()
            return fallback
    return result


def fetch(asof: str, previous: dict | None = None, session=None) -> dict:
    date.fromisoformat(asof)
    session = session or requests.Session()
    etf_start = (date.fromisoformat(asof) - timedelta(days=112)).isoformat()
    rs_start = (date.fromisoformat(asof) - timedelta(days=150)).isoformat()
    indicators = [_pending_position()]

    def semi():
        return _semi_etf_flow(asof, etf_start, session)

    indicators.append(
        _realize_indicator(
            previous,
            "semi_etf_flow",
            "半导体 ETF 资金",
            "core",
            "上交所/深交所基金份额；东财单位净值；腾讯 ETF 日线",
            semi,
        )
    )

    def treasury():
        snapshot = fetch_treasury(session, asof)
        evaluated = evaluate_us10y(snapshot.get("series_250d", []))
        return _indicator(
            "us10y",
            "美债 10 年",
            "core",
            evaluated["status"],
            evaluated["value"],
            "%",
            evaluated["asof"],
            "美国财政部 daily treasury yield curve（10 Yr）",
            RULES["us10y"],
            missing_reason=evaluated["missing_reason"],
            recent=evaluated["recent"],
        )

    indicators.append(
        _realize_indicator(
            previous,
            "us10y",
            "美债 10 年",
            "core",
            "美国财政部 daily treasury yield curve（10 Yr）",
            treasury,
        )
    )

    def growth_rs():
        chip = _fetch_cnindex_980017(rs_start, asof, session)
        market = tencent_raw("sh000300", start=rs_start, end=asof)
        evaluated = evaluate_growth_rs(chip, _rows_from_frame(market))
        return _indicator(
            "growth_rs",
            "成长相对强弱",
            "confirm",
            evaluated["status"],
            evaluated["value"],
            "RS",
            evaluated["asof"],
            "国证指数官网（980017 国证芯片）；腾讯日线（sh000300 沪深300）",
            RULES["growth_rs"],
            note=(
                f"已连续站上 {evaluated['value']['consecutive_above_days']} 日；"
                f"最近一次上穿 {evaluated['value']['last_cross_date'] or '暂无'}。"
                if evaluated["value"]
                else ""
            ),
            missing_reason=evaluated["missing_reason"],
            recent=evaluated["recent"],
        )

    indicators.append(
        _realize_indicator(
            previous,
            "growth_rs",
            "成长相对强弱",
            "confirm",
            "国证指数官网（980017 国证芯片）；腾讯日线（sh000300 沪深300）",
            growth_rs,
        )
    )
    core = [item for item in indicators if item["role"] == "core"]
    return {
        "schema": 1,
        "asof": asof,
        "generated_at": datetime.now().astimezone().isoformat(),
        "summary": {
            "core_met": sum(item["status"] == "met" for item in core),
            "core_total": 3,
            "core_pending": sum(
                item["status"] in {"pending_definition", "missing"} for item in core
            ),
            "confirm_status": indicators[-1]["status"],
        },
        "indicators": indicators,
    }


def write_snapshot(snapshot: dict, out: Path) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    latest = out / "growth_latest.json"
    dated = out / f"growth_{snapshot['asof']}.json"
    text = json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    latest.write_text(text, encoding="utf-8")
    dated.write_text(text, encoding="utf-8")
    return latest, dated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch descriptive growth-market monitor data.")
    parser.add_argument("--asof", required=True)
    parser.add_argument("--out", type=Path, default=DATA_DIR)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args(argv)
    previous = None
    if args.previous and args.previous.is_file():
        previous = json.loads(args.previous.read_text(encoding="utf-8"))
    snapshot = fetch(args.asof, previous)
    latest, dated = write_snapshot(snapshot, args.out)
    print(
        json.dumps(
            {
                "latest": str(latest),
                "dated": str(dated),
                "summary": snapshot["summary"],
                "indicators": [
                    {
                        "id": item["id"],
                        "status": item["status"],
                        "value": item["value"],
                        "asof": item["asof"],
                        "missing_reason": item["missing_reason"],
                    }
                    for item in snapshot["indicators"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
