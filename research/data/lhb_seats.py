from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile
from collections import defaultdict
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
MULTI_DAY_LABELS = ("连续三个交易日", "连续30个交易日")
NOTE = (
    "金额单位为人民币元。席位标签依据公开报道，不等于实际账户身份；"
    "仅描述当日盘后榜单，不构成建议。"
)


def _number(value, field: str) -> float:
    if value is None or str(value).strip() in ("", "-", "--"):
        return 0.0
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"龙虎榜字段 {field} 不是数值: {value!r}") from exc
    if not math.isfinite(number):
        raise RuntimeError(f"龙虎榜字段 {field} 不是有限数值: {value!r}")
    return number


def _code(value) -> str:
    code = str(value or "").strip()
    if not code:
        raise RuntimeError("龙虎榜行缺少 SECURITY_CODE")
    return code.zfill(6)


def _list_type(explanation: str) -> str:
    return "multi" if any(label in explanation for label in MULTI_DAY_LABELS) else "single"


def _seat_kind(name: str, code: str) -> str:
    if code == "0" or "机构专用" in name:
        return "institution"
    if "深股通专用" in name or "沪股通专用" in name:
        return "northbound"
    if any(label in name for label in ("自然人", "中小投资者", "其他自然人")):
        return "special"
    return "dept"


def _load_aliases(path: Path = ALIAS_PATH) -> dict:
    aliases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(aliases, dict):
        raise ValueError("data/lhb_seat_alias.json must be an object")
    for seat, entry in aliases.items():
        if not isinstance(seat, str) or not isinstance(entry, dict):
            raise ValueError("seat aliases must map names to objects")
        if entry.get("alias") is not None and not isinstance(entry["alias"], str):
            raise ValueError(f"alias for {seat!r} must be a string")
    return aliases


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
    names = {}
    stock_types: dict[str, set[str]] = defaultdict(set)
    for row in summary_rows:
        code = _code(row.get("SECURITY_CODE"))
        names[code] = str(row.get("SECURITY_NAME_ABBR") or "")
        stock_types[code].add(_list_type(str(row.get("EXPLANATION") or "")))

    records = {}
    seen = {"in": set(), "out": set()}
    for rows, side, field in ((buy_rows, "in", "BUY"), (sell_rows, "out", "SELL")):
        for row in rows:
            code = _code(row.get("SECURITY_CODE"))
            seat = str(row.get("OPERATEDEPT_NAME") or "").strip()
            if not seat:
                raise RuntimeError("龙虎榜席位行缺少 OPERATEDEPT_NAME")
            explanation = str(row.get("EXPLANATION") or "")
            list_type = _list_type(explanation) if explanation else (
                "multi" if "multi" in stock_types.get(code, set()) else "single"
            )
            key = (code, seat, list_type)
            if key in seen[side]:
                continue
            seen[side].add(key)
            entry = records.setdefault(
                key,
                {
                    "code": code,
                    "name": names.get(code) or str(row.get("SECURITY_NAME_ABBR") or ""),
                    "seat": seat,
                    "seat_code": str(row.get("OPERATEDEPT_CODE") or ""),
                    "list": list_type,
                    "buy": 0.0,
                    "sell": 0.0,
                },
            )
            entry["name"] = entry["name"] or names.get(code, "")
            entry["buy" if side == "in" else "sell"] = _number(row.get(field), field)

    alias_map = aliases if aliases is not None else _load_aliases()
    seats = {}
    for trade in records.values():
        seat = trade["seat"]
        kind = _seat_kind(seat, trade["seat_code"])
        alias = alias_map.get(seat, {}).get("alias") if kind == "dept" else None
        aggregate = seats.setdefault(
            seat,
            {
                "seat": seat,
                "alias": alias or None,
                "kind": kind,
                "buy": 0.0,
                "sell": 0.0,
                "net": 0.0,
                "trades": [],
            },
        )
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

    buy_total = sum(record["buy"] for record in records.values())
    sell_total = sum(record["sell"] for record in records.values())
    institution_net = sum(
        record["buy"] - record["sell"]
        for record in records.values()
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
    return {
        "schema": "lhb_seats.v1",
        "asof": asof,
        "totals": {
            "buy": round(buy_total, 2),
            "sell": round(sell_total, 2),
            "institution_net": round(institution_net, 2),
            "n_stocks_single": len(
                {code for code, kinds in stock_types.items() if "single" in kinds}
            ),
            "n_stocks_multi": len(
                {code for code, kinds in stock_types.items() if "multi" in kinds}
            ),
        },
        "seats": ordered_seats,
        "note": NOTE,
    }


def fetch_lhb_seats(asof: str, client=None, alias_path: Path = ALIAS_PATH) -> dict:
    client = client or EMClient()
    summary = _fetch_report(client, REPORTS["summary"], asof, "BILLBOARD_NET_AMT")
    buys = _fetch_report(client, REPORTS["buy"], asof, "BUY")
    sells = _fetch_report(client, REPORTS["sell"], asof, "SELL")
    return aggregate_lhb_seats(asof, summary, buys, sells, _load_aliases(alias_path))


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
