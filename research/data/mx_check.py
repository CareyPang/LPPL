"""将妙想近 10 个交易日收盘价与本地缓存/冻结数据交叉比较。"""
from __future__ import annotations

import argparse
import os
import re
from typing import Any

import pandas as pd
import requests

from . import sources
from .cache import load

URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        import json

        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _mx_close_rows(response: dict) -> pd.DataFrame:
    if response.get("status") != 0:
        raise RuntimeError(
            f"妙想 API 返回错误: {response.get('status')} {response.get('message', '')}"
        )
    search_result = (
        response.get("data", {})
        .get("data", {})
        .get("searchDataResultDTO", {})
    )
    tables = search_result.get("dataTableDTOList", [])
    rows = []
    for block in tables:
        table = block.get("table") or {}
        dates = table.get("headName") or []
        name_map = block.get("nameMap") or {}
        if isinstance(name_map, list):
            name_map = {str(index): value for index, value in enumerate(name_map)}
        if not isinstance(name_map, dict):
            name_map = {}
        code_map = (
            block.get("returnCodeMap")
            or block.get("returnCodeNameMap")
            or block.get("codeMap")
            or {}
        )
        for key, values in table.items():
            if key == "headName":
                continue
            label = name_map.get(key, name_map.get(str(key)))
            if label in (None, ""):
                label = code_map.get(key, code_map.get(str(key), key))
            if "收盘" not in str(label) and "close" not in str(label).lower():
                continue
            if not isinstance(values, list):
                values = [values]
            for index, date in enumerate(dates):
                if index >= len(values):
                    continue
                value = _flatten(values[index]).replace(",", "").strip()
                value = re.sub(r"[^0-9.+\-eE]", "", value)
                date_text = str(date).split("（", maxsplit=1)[0].split("(", maxsplit=1)[0]
                parsed_date = pd.to_datetime(date_text, errors="coerce")
                try:
                    close = float(value)
                except ValueError:
                    continue
                if pd.notna(parsed_date):
                    rows.append(
                        {"date": parsed_date.normalize(), "mx_close": close}
                    )
    result = pd.DataFrame(rows)
    if result.empty:
        raise RuntimeError("妙想响应中未找到日期与收盘价")
    return result.drop_duplicates("date").sort_values("date").reset_index(drop=True)


def _query(code: str) -> str:
    if code.lower().endswith("000001"):
        return "上证指数近10个交易日收盘价"
    if code.endswith("600519"):
        return "贵州茅台近10个交易日收盘价"
    return f"{code} 近10个交易日收盘价"


def compare(code: str, frozen: str | None = None) -> dict:
    api_key = os.environ.get("MX_APIKEY")
    if not api_key:
        raise RuntimeError("未设置 MX_APIKEY")
    if frozen:
        local = load(code, frozen=frozen)
    else:
        local = load(code)
    headers = {"Content-Type": "application/json", "apikey": api_key}
    sources.rate_limit()
    response = requests.post(
        URL,
        headers=headers,
        json={"toolQuery": _query(code)},
        timeout=30,
    )
    response.raise_for_status()
    mx = _mx_close_rows(response.json())
    comparison = local[["date", "close"]].copy()
    comparison["date"] = pd.to_datetime(comparison["date"]).dt.normalize()
    matched = comparison.merge(mx, on="date", how="inner")
    if matched.empty:
        max_diff = None
    else:
        matched["relative_diff"] = (
            (matched["close"] - matched["mx_close"]).abs()
            / matched["mx_close"].abs()
        )
        max_diff = float(matched["relative_diff"].max())
    return {
        "symbol": local.attrs.get("symbol", code),
        "matched_dates": len(matched),
        "max_abs_relative_diff": max_diff,
        "reference": "mx unadjusted",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code")
    parser.add_argument("--frozen")
    args = parser.parse_args()
    result = compare(args.code, args.frozen)
    if result["max_abs_relative_diff"] is None:
        print(result["symbol"], "no overlapping dates with 妙想")
    else:
        print(
            result["symbol"],
            f"matched={result['matched_dates']}",
            f"max_abs_relative_diff={result['max_abs_relative_diff']:.6%}",
            f"reference={result['reference']}",
        )


if __name__ == "__main__":
    main()
