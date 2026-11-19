from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path

from .market_base import EM_DATACENTER_URL, EMClient
from .trading_date import latest_closed_trading_day

ROOT = Path(__file__).resolve().parents[2]
ALIAS_PATH = ROOT / "data" / "lhb_seat_alias.json"
REPORTS = {
    "summary": "RPT_DAILYBILLBOARD_DETAILSNEW",
    "buy": "RPT_BILLBOARD_DAILYDETAILSBUY",
    "sell": "RPT_BILLBOARD_DAILYDETAILSSELL",
}
NOTE = "本内容为每日复盘，仅供研究参考，不构成任何投资建议；游资别名按公开报道整理，可能有误或过时。"


def _number(value, field: str) -> float:
    if value is None or str(value).strip() in ("", "-", "--"):
        return 0.0
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"龙虎榜字段 {field} 不是数值: {value!r}") from exc
    if math.isnan(number):
        return 0.0
    if not math.isfinite(number):
        raise RuntimeError(f"龙虎榜字段 {field} 不是有限数值: {value!r}")
    return number


def _code(value) -> str:
    code = str(value or "").strip()
    if not code:
        raise RuntimeError("龙虎榜行缺少 SECURITY_CODE")
    return code.zfill(6)


def _trade_id(row: dict) -> str:
    value = row.get("TRADE_ID")
    if value is None or not str(value).strip():
        raise RuntimeError("龙虎榜行缺少 TRADE_ID")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _department_code(row: dict) -> str:
    value = row.get("OPERATEDEPT_CODE")
    return "" if value is None else str(value).strip()


def _summary_amount(row: dict, side: str) -> float:
    fields = (f"BILLBOARD_{side}_AMT", f"{side}_AMT", side)
    value = next(
        (
            row[field]
            for field in fields
            if row.get(field) is not None
            and str(row[field]).strip() not in ("", "-", "--")
        ),
        None,
    )
    return _number(value, fields[0])


def _list_type(explanation: str) -> str:
    return (
        "multi"
        if re.search(r"连续\s*([0-9]+|[一二三四五六七八九十]+)\s*个交易日", explanation)
        else "single"
    )


def _seat_kind(name: str, code: str) -> str:
    if code == "0" or "机构专用" in name or name.strip() == "机构":
        return "institution"
    if "深股通专用" in name or "沪股通专用" in name:
        return "northbound"
    if any(label in name for label in ("自然人", "中小投资者", "其他自然人")):
        return "special"
    return "dept"


def _normalize_seat_name(name: str) -> str:
    return re.sub(r"股份有限公司|有限责任公司|有限公司", "", name)


def _load_aliases(path: Path = ALIAS_PATH) -> dict:
    aliases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(aliases, dict):
        raise ValueError("data/lhb_seat_alias.json must be an object")
    for seat, entry in aliases.items():
        if not isinstance(seat, str) or not isinstance(entry, dict):
            raise ValueError("seat aliases must map names to objects")
        if entry.get("alias") is not None and not isinstance(entry["alias"], str):
            raise ValueError(f"alias for {seat!r} must be a string")
        match = entry.get("match")
        if match is not None and (
            not isinstance(match, str) or match not in {"exact", "renamed"}
        ):
            raise ValueError(f"match for {seat!r} must be exact or renamed")
        for field in ("source", "source_url", "source_name"):
            if entry.get(field) is not None and not isinstance(entry[field], str):
                raise ValueError(f"{field} for {seat!r} must be a string")
    return aliases


def _date_badge(asof: str) -> str:
    trading_date = date.fromisoformat(asof)
    weekday = "一二三四五六日"[trading_date.weekday()]
    return f"{trading_date:%Y.%m.%d} / 周{weekday} · 盘后榜单"


def _sample_note(totals: dict) -> str:
    return (
        f"样本 {totals['n_stocks']} 只（其中单日榜 {totals['n_stocks_single']}、"
        f"多日榜 {totals['n_stocks_multi']}） · 历史分位，不是预测"
    )


def _presentation_groups(seats: list[dict]) -> tuple[list[dict], dict, list[dict]]:
    groups = {}
    stock_buys = {}
    for seat in seats:
        if seat["kind"] != "dept" or not seat.get("alias"):
            continue
        alias = seat["alias"]
        group = groups.setdefault(
            alias,
            {
                "alias": alias,
                "depts": set(),
                "buy": 0.0,
                "sell": 0.0,
                "trades": {},
                "sources": {},
            },
        )
        group["depts"].add(seat["seat"])
        group["buy"] += seat["buy"]
        group["sell"] += seat["sell"]
        source_url = seat.get("alias_source_url")
        if source_url:
            source = seat.get("alias_source") or "别名来源"
            group["sources"][(source, source_url)] = {
                "source": source,
                "source_url": source_url,
            }
        for trade in seat["trades"]:
            code = trade["code"]
            period = trade["list"]
            stock = group["trades"].setdefault(
                (code, period),
                {"code": code, "name": trade["name"], "list": period, "buy": 0.0, "sell": 0.0},
            )
            side = "buy" if trade["side"] == "in" else "sell"
            stock[side] += trade["amount"]
            if side == "buy" and period == "single" and trade["amount"] > 0:
                stock_total = stock_buys.setdefault(
                    code, {"code": code, "name": trade["name"], "buy": 0.0}
                )
                stock_total["buy"] += trade["amount"]

    alias_groups = []
    for group in groups.values():
        trades = [
            {
                **trade,
                "buy": round(trade["buy"], 2),
                "sell": round(trade["sell"], 2),
            }
            for trade in group["trades"].values()
        ]
        trades.sort(key=lambda trade: (-(trade["buy"] + trade["sell"]), trade["code"]))
        chips = []
        for trade in trades:
            if trade["buy"]:
                chips.append(
                    {
                        "code": trade["code"],
                        "name": trade["name"],
                        "side": "in",
                        "list": trade["list"],
                        "amount": trade["buy"],
                    }
                )
            if trade["sell"]:
                chips.append(
                    {
                        "code": trade["code"],
                        "name": trade["name"],
                        "side": "out",
                        "list": trade["list"],
                        "amount": trade["sell"],
                    }
                )
        chips.sort(key=lambda item: (-item["amount"], item["code"], item["side"]))
        alias_groups.append(
            {
                "alias": group["alias"],
                "depts": sorted(group["depts"]),
                "buy": round(group["buy"], 2),
                "sell": round(group["sell"], 2),
                "net": round(group["buy"] - group["sell"], 2),
                "n_stocks": len({trade["code"] for trade in trades}),
                "trades": trades,
                "chips": chips[:3],
                "more_trades": max(0, len(chips) - 3),
                "sources": sorted(
                    group["sources"].values(),
                    key=lambda source: (source["source"], source["source_url"]),
                ),
            }
        )
    alias_groups.sort(key=lambda group: (-(group["buy"] + group["sell"]), group["alias"]))
    top_buy = sorted(
        stock_buys.values(), key=lambda stock: (-stock["buy"], stock["code"])
    )[:6]
    summary = {
        "n_aliases": len(alias_groups),
        "n_stocks": len(stock_buys),
        "top_buy": [
            {**stock, "buy": round(stock["buy"], 2)}
            for stock in top_buy
        ],
    }
    other_seats = [
        {
            "seat": seat["seat"],
            "kind": seat["kind"],
            "buy": seat["buy"],
            "sell": seat["sell"],
            "net": seat["net"],
        }
        for seat in seats
        if seat["kind"] in {"dept", "institution", "northbound"} and not seat.get("alias")
    ][:10]
    return alias_groups, summary, other_seats


def _fetch_report(client: EMClient, report_name: str, asof: str, sort_column: str = "") -> list[dict]:
    rows = []
    page = 1
    expected_pages = expected_count = None
    while True:
        params = {
            "reportName": report_name,
            "columns": "ALL",
            "filter": f"(TRADE_DATE='{asof}')",
            "pageNumber": str(page),
            "pageSize": "500",
            "sortColumns": sort_column,
            "sortTypes": "-1" if sort_column else "",
            "source": "WEB",
            "client": "WEB",
        }
        payload = client.get_json(EM_DATACENTER_URL, params=params)
        code = payload.get("code")
        if code == 9201 and page == 1:
            return []
        if code not in (0, "0") or not isinstance(payload.get("result"), dict):
            raise RuntimeError(
                f"Eastmoney {report_name} failed: {code} {payload.get('message', '')}"
            )
        result = payload["result"]
        page_count, row_count, data = (
            result.get("pages"),
            result.get("count"),
            result.get("data"),
        )
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise RuntimeError(f"Eastmoney {report_name} page {page} has invalid data")
        if (
            isinstance(page_count, bool)
            or not isinstance(page_count, int)
            or isinstance(row_count, bool)
            or not isinstance(row_count, int)
            or page_count < 1
            or row_count < 0
        ):
            raise RuntimeError(f"Eastmoney {report_name} lacks valid pagination metadata")
        if expected_pages is None:
            expected_pages, expected_count = page_count, row_count
        elif (page_count, row_count) != (expected_pages, expected_count):
            raise RuntimeError(f"Eastmoney {report_name} changed pagination while fetching")
        if page < page_count and len(data) != 500:
            raise RuntimeError(f"Eastmoney {report_name} page {page} is incomplete")
        if not data and page < page_count:
            raise RuntimeError(f"Eastmoney {report_name} page {page} is empty")
        rows.extend(data)
        if page >= page_count:
            if len(rows) != row_count:
                raise RuntimeError(
                    f"Eastmoney {report_name} returned {len(rows)} rows; expected {row_count}"
                )
            return rows
        page += 1


def aggregate_lhb_seats(
    asof: str,
    summary_rows: list[dict],
    buy_rows: list[dict],
    sell_rows: list[dict],
    aliases: dict | None = None,
) -> dict:
    if not summary_rows:
        totals = {
            "buy": 0.0,
            "sell": 0.0,
            "institution_net": 0.0,
            "n_stocks": 0,
            "n_stocks_single": 0,
            "n_stocks_multi": 0,
        }
        youzi, youzi_summary, other_seats = _presentation_groups([])
        return {
            "schema": "lhb_seats.v1",
            "totals_basis": "single_preferred_per_stock",
            "ranking_basis": "single_only",
            "asof": asof,
            "date_badge": _date_badge(asof),
            "totals": totals,
            "sample_note": _sample_note(totals),
            "youzi": youzi,
            "youzi_summary": youzi_summary,
            "other_seats": other_seats,
            "seats": [],
            "note": NOTE,
        }
    if not buy_rows or not sell_rows:
        raise RuntimeError("龙虎榜汇总非空，但买入或卖出席位明细为空")

    names = {}
    stock_types: dict[str, set[str]] = defaultdict(set)
    selected_trade_ids = {}
    disclosure_types: dict[tuple[str, str], set[str]] = defaultdict(set)
    selected_totals = {}
    for row in summary_rows:
        code = _code(row.get("SECURITY_CODE"))
        names[code] = str(row.get("SECURITY_NAME_ABBR") or "")
        list_type = _list_type(str(row.get("EXPLANATION") or ""))
        stock_types[code].add(list_type)
        trade_id = _trade_id(row)
        disclosure_key = (code, trade_id)
        disclosure_types[disclosure_key].add(list_type)
        key = (code, list_type)
        total = _summary_amount(row, "BUY") + _summary_amount(row, "SELL")
        # Keep the largest summary BUY+SELL TRADE_ID per stock/list; ties keep the first.
        if key not in selected_totals or total > selected_totals[key]:
            selected_totals[key] = total
            selected_trade_ids[key] = trade_id

    records = {}
    detail_codes = set()
    for row in (*buy_rows, *sell_rows):
        code = _code(row.get("SECURITY_CODE"))
        trade_id = _trade_id(row)
        list_types = disclosure_types.get((code, trade_id))
        if not list_types:
            raise RuntimeError(f"龙虎榜席位明细 TRADE_ID 不在汇总中: {code} {trade_id}")
        explanation = str(row.get("EXPLANATION") or "").strip()
        if len(list_types) == 1:
            list_type = next(iter(list_types))
        elif _list_type(explanation) == "multi":
            list_type = "multi"
        elif re.search(r"(?:单日|当日|首日|日(?:收盘|涨|跌|换手|价格|振幅))", explanation):
            list_type = "single"
        else:
            raise RuntimeError(f"龙虎榜席位明细 TRADE_ID 榜单类型不明确: {code} {trade_id}")
        if selected_trade_ids[(code, list_type)] != trade_id:
            continue
        seat = str(row.get("OPERATEDEPT_NAME") or "").strip()
        if not seat:
            raise RuntimeError("龙虎榜席位行缺少 OPERATEDEPT_NAME")
        seat_code = _department_code(row)
        buy = _number(row.get("BUY"), "BUY")
        sell = _number(row.get("SELL"), "SELL")
        identity = (trade_id, seat_code or seat, buy, sell, list_type)
        entry = records.get(identity)
        if entry is not None:
            if entry["code"] != code:
                raise RuntimeError(f"龙虎榜席位行身份冲突: {identity!r}")
            continue
        records[identity] = {
            "code": code,
            "name": names.get(code) or str(row.get("SECURITY_NAME_ABBR") or ""),
            "seat": seat,
            "seat_code": seat_code,
            "list": list_type,
            "buy": buy,
            "sell": sell,
        }
        detail_codes.add(code)

    cross_list_records = {}
    unique_records = {}
    for identity, record in records.items():
        overlap_key = (
            record["code"],
            record["seat_code"] or record["seat"],
            record["buy"],
            record["sell"],
        )
        previous_identity = cross_list_records.get(overlap_key)
        if previous_identity is None:
            cross_list_records[overlap_key] = identity
            unique_records[identity] = record
            continue
        previous = unique_records[previous_identity]
        if previous["list"] == record["list"]:
            unique_records[identity] = record
        elif previous["list"] == "multi" and record["list"] == "single":
            del unique_records[previous_identity]
            cross_list_records[overlap_key] = identity
            unique_records[identity] = record
    records = unique_records

    missing_codes = set(names) - detail_codes
    if missing_codes:
        raise RuntimeError(
            "龙虎榜汇总股票缺少买卖席位明细: " + ", ".join(sorted(missing_codes))
        )

    alias_map = aliases if aliases is not None else _load_aliases()
    seats = {}
    # A multi-day disclosure includes the daily amount. For totals choose one
    # period per security across all seats; retain both periods in drill-downs.
    preferred = {code: "single" if "single" in kinds else "multi" for code, kinds in stock_types.items()}
    selected = [row for row in records.values() if row["list"] == preferred[row["code"]]]
    for trade in records.values():
        seat = trade["seat"]
        kind = _seat_kind(seat, trade["seat_code"])
        alias_entry = {}
        if kind == "dept":
            normalized_seat = _normalize_seat_name(seat)
            alias_entry = alias_map.get(normalized_seat)
            if alias_entry is None:
                alias_entry = alias_map.get(seat)
            alias_entry = alias_entry or {}
        alias = alias_entry.get("alias")
        aggregate = seats.setdefault(
            seat,
            {
                "seat": seat,
                "alias": alias or None,
                "alias_source": alias_entry.get("source") if alias else None,
                "alias_source_url": alias_entry.get("source_url") if alias else None,
                "kind": kind,
                "buy": 0.0,
                "sell": 0.0,
                "net": 0.0,
                "trades": [],
            },
        )
        if trade["list"] == preferred[trade["code"]]:
            aggregate["buy"] += trade["buy"]
            aggregate["sell"] += trade["sell"]
        for side, amount in (("in", trade["buy"]), ("out", trade["sell"])):
            if amount:
                aggregate["trades"].append(
                    {
                        "code": trade["code"],
                        "name": trade["name"],
                        "side": side,
                        "amount": amount,
                        "list": trade["list"],
                    }
                )

    buy_total = sum(record["buy"] for record in selected)
    sell_total = sum(record["sell"] for record in selected)
    institution_net = sum(
        record["buy"] - record["sell"]
        for record in selected
        if _seat_kind(record["seat"], record["seat_code"]) == "institution"
    )
    for seat in seats.values():
        seat["buy"] = round(seat["buy"], 2)
        seat["sell"] = round(seat["sell"], 2)
        seat["net"] = round(seat["buy"] - seat["sell"], 2)
        seat["trades"].sort(key=lambda trade: (-trade["amount"], trade["code"], trade["side"]))
    ordered_seats = sorted(
        seats.values(), key=lambda seat: (-(seat["buy"] + seat["sell"]), seat["seat"])
    )
    youzi, youzi_summary, other_seats = _presentation_groups(ordered_seats)
    totals = {
        "buy": round(buy_total, 2),
        "sell": round(sell_total, 2),
        "institution_net": round(institution_net, 2),
        "n_stocks": len(names),
        "n_stocks_single": len(
            {code for code, kinds in stock_types.items() if "single" in kinds}
        ),
        "n_stocks_multi": len(
            {code for code, kinds in stock_types.items() if "multi" in kinds}
        ),
    }
    return {
        "schema": "lhb_seats.v1",
        "totals_basis": "single_preferred_per_stock",
        "ranking_basis": "single_only",
        "asof": asof,
        "date_badge": _date_badge(asof),
        "totals": totals,
        "sample_note": _sample_note(totals),
        "youzi": youzi,
        "youzi_summary": youzi_summary,
        "other_seats": other_seats,
        "seats": ordered_seats,
        "note": NOTE,
    }


def fetch_lhb_seats(asof: str, client=None, alias_path: Path = ALIAS_PATH) -> dict:
    client = client or EMClient()
    summary = _fetch_report(client, REPORTS["summary"], asof, "BILLBOARD_NET_AMT")
    aliases = _load_aliases(alias_path)
    if not summary:
        return aggregate_lhb_seats(asof, summary, [], [], aliases)
    buys = _fetch_report(client, REPORTS["buy"], asof, "BUY")
    sells = _fetch_report(client, REPORTS["sell"], asof, "SELL")
    return aggregate_lhb_seats(asof, summary, buys, sells, aliases)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build daily LHB seat review JSON")
    parser.add_argument("--date", default=None, help="Snapshot date YYYY-MM-DD")
    parser.add_argument("--out", default="out/market/lhb_seats_latest.json")
    parser.add_argument("--previous", default=None)
    parser.add_argument("--alias", default=str(ALIAS_PATH))
    args = parser.parse_args(argv)
    asof = args.date or latest_closed_trading_day()
    output = Path(args.out)
    try:
        payload = fetch_lhb_seats(asof, alias_path=Path(args.alias))
        _write_json(output, payload)
    except Exception:
        if args.previous and Path(args.previous).is_file():
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(args.previous, output)
        raise
    print(f"{asof} 龙虎榜席位: {len(payload['seats'])} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
