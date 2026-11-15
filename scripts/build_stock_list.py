#!/usr/bin/env python3
"""Build the static stock search index used by the frontend."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from pypinyin import Style, lazy_pinyin

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "web/mock/data/market/stock_list.json"
FIELDS = ["code", "name", "py", "kind"]
MIN_A_ROWS = 4000
RETRY_BACKOFF = (5, 15, 30)
CODE_COLUMNS = ("code", "证券代码", "A股代码", "股票代码", "代码")
NAME_COLUMNS = ("name", "证券简称", "A股简称", "股票简称", "简称", "名称")
INDEXES = (
    ("sh000001", "上证指数"),
    ("sh000016", "上证50"),
    ("sh000300", "沪深300"),
    ("sh000905", "中证500"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
)


def _normalise_frame(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{source} returned {type(frame).__name__}, expected DataFrame")
    print(f"{source} columns: {list(frame.columns)!r}", file=sys.stderr)
    code_col = next((column for column in CODE_COLUMNS if column in frame.columns), None)
    name_col = next((column for column in NAME_COLUMNS if column in frame.columns), None)
    if code_col is None or name_col is None:
        raise ValueError(f"{source} has no recognized code/name columns: {list(frame.columns)!r}")
    return frame[[code_col, name_col]].rename(columns={code_col: "code", name_col: "name"})


def _retry_source(call, source: str) -> pd.DataFrame:
    last_error = None
    for attempt in range(len(RETRY_BACKOFF) + 1):
        try:
            frame = _normalise_frame(call(), source)
            eligible = len(_a_share_rows(frame))
            if eligible < MIN_A_ROWS:
                raise ValueError(f"only {eligible} eligible A-share rows; need {MIN_A_ROWS}")
            return frame
        except Exception as exc:  # noqa: BLE001 — try the endpoint again, then fall back
            last_error = exc
            if attempt == len(RETRY_BACKOFF):
                break
            delay = RETRY_BACKOFF[attempt]
            print(
                f"{source} attempt {attempt + 1} failed: {type(exc).__name__}: {exc}; "
                f"retrying in {delay}s",
                file=sys.stderr,
            )
            time.sleep(delay)
    raise RuntimeError(
        f"{source} failed after {len(RETRY_BACKOFF) + 1} attempts: "
        f"{type(last_error).__name__}: {last_error}"
    ) from last_error


def _retry_exchange_source(call, source: str) -> pd.DataFrame:
    last_error = None
    for attempt in range(len(RETRY_BACKOFF) + 1):
        try:
            return _normalise_frame(call(), source)
        except Exception as exc:  # noqa: BLE001 — retry before trying the next source
            last_error = exc
            if attempt == len(RETRY_BACKOFF):
                break
            delay = RETRY_BACKOFF[attempt]
            print(
                f"{source} attempt {attempt + 1} failed: {type(exc).__name__}: {exc}; "
                f"retrying in {delay}s",
                file=sys.stderr,
            )
            time.sleep(delay)
    raise RuntimeError(
        f"{source} failed after {len(RETRY_BACKOFF) + 1} attempts: "
        f"{type(last_error).__name__}: {last_error}"
    ) from last_error


def _fetch_baostock_frame(bs_module=None) -> pd.DataFrame:
    if bs_module is None:
        import baostock as bs_module

    login = bs_module.login()
    try:
        if login.error_code != "0":
            raise RuntimeError(f"baostock login failed: {login.error_msg}")
        result = bs_module.query_stock_basic()
        if result.error_code != "0":
            raise RuntimeError(f"baostock query_stock_basic failed: {result.error_msg}")
        records = []
        while result.next():
            records.append(result.get_row_data())
        frame = pd.DataFrame(records, columns=result.fields)
        frame = frame[(frame["type"] == "1") & (frame["status"] == "1")].copy()
        frame["code"] = frame["code"].astype(str).str.split(".", n=1).str[-1]
        frame["name"] = frame["code_name"]
        return frame[["code", "name"]]
    finally:
        bs_module.logout()


def fetch_stock_frame(ak_module=None) -> tuple[pd.DataFrame, str]:
    if ak_module is None:
        import akshare as ak_module

    primary = "ak.stock_info_a_code_name"
    try:
        return _retry_source(ak_module.stock_info_a_code_name, primary), primary
    except Exception as primary_error:
        fallback_sources = (
            (
                "ak.stock_info_sh_name_code(symbol='主板A股')",
                lambda: ak_module.stock_info_sh_name_code(symbol="主板A股"),
            ),
            (
                "ak.stock_info_sh_name_code(symbol='科创板')",
                lambda: ak_module.stock_info_sh_name_code(symbol="科创板"),
            ),
            (
                "ak.stock_info_sz_name_code(symbol='A股列表')",
                lambda: ak_module.stock_info_sz_name_code(symbol="A股列表"),
            ),
        )
        frames = []
        used_sources = []
        errors = []
        for source, call in fallback_sources:
            try:
                frames.append(_retry_exchange_source(call, source))
                used_sources.append(source)
            except Exception as exc:  # noqa: BLE001 — require a complete exchange fallback
                errors.append(f"{source}: {type(exc).__name__}: {exc}")
        if not errors:
            exchange_frame = pd.concat(frames, ignore_index=True)
            eligible = len(_a_share_rows(exchange_frame))
            if eligible >= MIN_A_ROWS:
                return exchange_frame, "+".join(used_sources)
            errors.append(f"per-exchange fallback: only {eligible} eligible A-share rows")

        full_sources = (
            (
                "ak.stock_zh_a_spot_em",
                lambda: ak_module.stock_zh_a_spot_em(),
            ),
            (
                "baostock.query_stock_basic(type='1', status='1')",
                _fetch_baostock_frame,
            ),
        )
        for source, call in full_sources:
            try:
                return _retry_source(call, source), source
            except Exception as exc:  # noqa: BLE001 — try the next full-market source
                errors.append(f"{source}: {type(exc).__name__}: {exc}")
        detail = "; ".join(errors)
        raise RuntimeError(
            f"{primary} and all fallbacks failed; primary error: "
            f"{type(primary_error).__name__}: {primary_error}; fallback errors: {detail}"
        ) from primary_error


def pinyin_initials(name: str) -> str:
    return "".join(
        character.lower()
        for token in lazy_pinyin(name, style=Style.FIRST_LETTER)
        for character in token
        if character.isascii() and character.isalnum()
    )


def _a_share_rows(frame: pd.DataFrame) -> list[list[str]]:
    normalised = _normalise_frame(frame, "A-share data")
    rows = []
    seen = set()
    for raw_code, raw_name in normalised.itertuples(index=False, name=None):
        if pd.isna(raw_code) or pd.isna(raw_name):
            continue
        if isinstance(raw_code, float) and raw_code.is_integer():
            code = str(int(raw_code))
        else:
            code = str(raw_code).strip()
        if not code.isdigit() or len(code) > 6:
            continue
        code = code.zfill(6)
        # Only 0/3/6 A-share codes are routed; exclude 4/8/9 BSE/B-share prefixes and 2xxxx B shares.
        if code[0] not in "036" or code in seen:
            continue
        name = str(raw_name).strip()
        if not name:
            continue
        seen.add(code)
        rows.append([code, name, pinyin_initials(name), "a"])
    return rows


def build_document(frame: pd.DataFrame, source: str, asof: str | None = None) -> dict:
    a_rows = _a_share_rows(frame)
    if len(a_rows) < MIN_A_ROWS:
        raise ValueError(f"仅取得 {len(a_rows)} 个可查询 A 股代码，至少需要 {MIN_A_ROWS}")

    from research.data.us_watchlist import US_NAMES, US_WATCHLIST

    rows = a_rows
    rows.extend(
        [f"US_{ticker}", US_NAMES.get(ticker, ticker), pinyin_initials(US_NAMES.get(ticker, ticker)), "us"]
        for ticker in US_WATCHLIST
    )
    rows.extend([symbol, name, pinyin_initials(name), "index"] for symbol, name in INDEXES)
    return {
        "asof": asof or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        "source": source,
        "fields": FIELDS,
        "rows": rows,
    }


def write_document(path: Path, document: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def generate(out: Path = DEFAULT_OUTPUT, ak_module=None) -> dict:
    frame, source = fetch_stock_frame(ak_module)
    document = build_document(frame, source)
    write_document(out, document)
    counts = {kind: sum(row[3] == kind for row in document["rows"]) for kind in ("a", "us", "index")}
    print(f"source={source}; rows={counts}; output={out}")
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        generate(args.out)
    except Exception as exc:
        raise SystemExit(f"stock list generation failed: {exc}") from exc


if __name__ == "__main__":
    main()
