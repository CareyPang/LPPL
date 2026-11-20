from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import io
import json
import math
import os
import re
import struct
import tempfile
import time
import zipfile
import zlib
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import numpy as np
import pandas as pd
import requests

from research.data.breadth_alerts import build_trend_ledger

TDX_PACKAGE_URL = "https://www.tdx.com.cn/products/data/data/g4day/{ymd}.zip"
TDX_BJ_FIRST_DAY = "20220506"
TDX_MIN_PRICED = {"sh": 10000, "sz": 3000, "bj": 50}
CFFEX_DAILY_URL = "http://www.cffex.com.cn/fzjy/mrhq/{ym}/{dd}/{ymd}_1.csv"
CFFEX_DAILY_XML = "http://www.cffex.com.cn/fzjy/mrhq/{ym}/{dd}/index.xml"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}
BASIS_SPOT_CODES = {
    "IF": ("hs300", "000300"),
    "IH": ("sz50", "000016"),
    "IC": ("zz500", "000905"),
    "IM": ("zz1000", "000852"),
}
NOTE = (
    "全A按沪60/68、深00/30、京4/8/9（排除90开头）筛选；剔除无成交、"
    "前收盘非正或收盘非正记录。均线使用不复权收盘价；涨跌停按价格推断，"
    "可能含ST误差。基差年化按自然日计算，交割日遇节假日暂不顺延。"
)
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "breadth"
DEFAULT_OUT = Path("out/market/breadth_latest.json")
ROW_FIELDS = (
    "date",
    "sh",
    "n",
    "adv",
    "dec",
    "red",
    "amt_up",
    "trin_amt",
    "trin_vol",
    "up_mean_amount",
    "down_mean_amount",
    "up_mean_volume",
    "down_mean_volume",
    "lu",
    "ld",
    "amount_yi",
    "top50_share",
    "top100_share",
    "amount_ratio20",
    "P20",
    "P60",
    "P250",
    "MCL",
    "basis_json",
    "basis_ann_mean",
)


def _rounded_limit_prices(
    prev_close: np.ndarray, limits: np.ndarray, *, up: bool
) -> np.ndarray:
    one = Decimal("1")
    cent = Decimal("0.01")

    def rounded(previous, limit):
        rate = Decimal(str(limit))
        multiplier = one + rate if up else one - rate
        return float(
            (Decimal(str(previous)) * multiplier).quantize(
                cent, rounding=ROUND_HALF_UP
            )
        )

    return np.fromiter(
        (
            rounded(previous, limit)
            for previous, limit in zip(prev_close, limits, strict=True)
        ),
        dtype=float,
        count=len(prev_close),
    )


def _date_text(value: str | dt.date | dt.datetime) -> str:
    if isinstance(value, dt.datetime):
        value = value.date()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value).strip()
    parsed = dt.date.fromisoformat(text)
    if parsed.isoformat() != text:
        raise ValueError(f"invalid ISO date: {text!r}")
    return text


def _request(
    url: str,
    *,
    session: Any = None,
    timeout: tuple[int, int] = (10, 60),
    allow_status: tuple[int, ...] = (),
    allow_redirects: bool = True,
) -> Any:
    client = session or requests
    try:
        response = client.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=timeout,
            allow_redirects=allow_redirects,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"request failed: {url}: {type(exc).__name__}: {exc}") from exc
    if response.status_code not in allow_status:
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"request failed: {url}: {type(exc).__name__}: {exc}"
            ) from exc
    return response


def _tdx_parse_package(content: bytes, ymd: str) -> list[dict[str, Any]]:
    """Parse TDX daily increment files: 150-byte .cod records and 512-byte .md1 blocks."""
    archive = zipfile.ZipFile(io.BytesIO(content))
    names = set(archive.namelist())
    rows: list[dict[str, Any]] = []
    for market in ("sh", "sz", "bj"):
        cod_name, md1_name = f"{market}{ymd[2:]}.cod", f"{market}{ymd[2:]}.md1"
        if (
            market == "bj"
            and ymd < TDX_BJ_FIRST_DAY
            and cod_name not in names
            and md1_name not in names
        ):
            continue
        if cod_name not in names or md1_name not in names:
            raise RuntimeError(
                f"TDX package missing {cod_name}/{md1_name}; format may have changed"
            )
        cod, md1 = archive.read(cod_name), archive.read(md1_name)
        if len(cod) % 150 or len(md1) % 512:
            raise RuntimeError(f"{market} code or quote file is truncated")
        if len(cod) // 150 != len(md1) // 512:
            raise RuntimeError(
                f"{market} has {len(cod) // 150} codes but "
                f"{len(md1) // 512} quote blocks"
            )
        before, codes, seqs = len(rows), set(), set()
        for offset in range(0, len(cod), 150):
            record = cod[offset : offset + 150]
            code = record[0:6].rstrip(b"\x00 ").decode("ascii", "replace")
            seq = struct.unpack("<H", record[32:34])[0]
            if not re.fullmatch(r"[0-9]{6}", code):
                raise RuntimeError(f"TDX {market} contains invalid code {code!r}")
            if code in codes or seq in seqs:
                raise RuntimeError(
                    f"TDX {market} has duplicate code or quote block index "
                    f"({code!r}, seq={seq})"
                )
            codes.add(code)
            seqs.add(seq)
            block = md1[seq * 512 : (seq + 1) * 512]
            if len(block) != 512:
                raise RuntimeError(f"TDX {market}{code} quote block is out of range")
            prev_close = struct.unpack("<d", block[4:12])[0]
            open_, high, low, close = struct.unpack("<4d", block[12:44])
            amount = struct.unpack("<d", block[72:80])[0]
            if not all(
                math.isfinite(value)
                for value in (prev_close, open_, high, low, close, amount)
            ):
                raise RuntimeError(f"TDX {market}{code} contains non-finite values")
            if close <= 0:
                continue
            volume = struct.unpack("<Q", block[56:64])[0]
            raw_name = record[40:72].split(b"\x00")[0]
            try:
                name = raw_name.decode("gbk").strip()
            except UnicodeDecodeError as exc:
                raise RuntimeError(
                    f"TDX {market}{code} name is not valid GBK"
                ) from exc
            if not name:
                raise RuntimeError(f"TDX {market}{code} has a price but no name")
            rows.append(
                {
                    "date": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}",
                    "market": market,
                    "code": code,
                    "name": name,
                    "prev_close": round(prev_close, 4),
                    "open": round(open_, 4),
                    "high": round(high, 4),
                    "low": round(low, 4),
                    "close": round(close, 4),
                    "volume": volume,
                    "amount": round(amount, 2),
                }
            )
        if len(rows) - before < TDX_MIN_PRICED[market]:
            raise RuntimeError(
                f"TDX {market} has only {len(rows) - before} priced rows "
                f"(minimum {TDX_MIN_PRICED[market]})"
            )
    if not rows:
        raise RuntimeError(f"TDX package for {ymd} contains no priced rows")
    return rows


def tdx_daily_package(
    date: str | dt.date | dt.datetime, session: Any = None
) -> pd.DataFrame:
    """Download and validate one TDX after-market package; a 404 is a ValueError."""
    day = _date_text(date)
    ymd = day.replace("-", "")
    url = TDX_PACKAGE_URL.format(ymd=ymd)
    response = _request(
        url, session=session, timeout=(10, 90), allow_status=(404,)
    )
    if response.status_code == 404:
        raise ValueError(f"TDX daily package not found: {url}")
    try:
        rows = _tdx_parse_package(response.content, ymd)
    except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
        raise RuntimeError(
            f"TDX package cannot be decompressed: {type(exc).__name__}: {exc}"
        ) from exc
    return pd.DataFrame(rows)


def _source_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise RuntimeError(f"source numeric field contains a boolean: {value!r}")
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).replace(",", "").strip()
        if text in ("", "-", "--", "None", "null"):
            return None
        try:
            number = float(text)
        except ValueError as exc:
            raise RuntimeError(f"unrecognized source number: {value!r}") from exc
    return number if math.isfinite(number) else None


def _cffex_csv(url: str, session: Any = None) -> list[list[str]]:
    response = _request(
        url,
        session=session,
        timeout=(10, 60),
        allow_status=(302, 404),
        allow_redirects=False,
    )
    if response.status_code in (302, 404):
        raise ValueError(f"CFFEX daily file not found (non-trading day or unpublished): {url}")
    try:
        return list(csv.reader(io.StringIO(response.content.decode("gbk"))))
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"CFFEX CSV is not valid GBK: {url}") from exc


def _cffex_daily_table(
    ymd: str, session: Any = None
) -> tuple[list[list[str]], str]:
    """Cross-check the CFFEX daily CSV against the same-directory index.xml."""
    url = CFFEX_DAILY_URL.format(ym=ymd[:6], dd=ymd[6:], ymd=ymd)
    table = _cffex_csv(url, session)
    if not table or table[0][:3] != ["合约代码", "今开盘", "最高价"]:
        raise RuntimeError("CFFEX daily CSV header changed")
    xml_url = CFFEX_DAILY_XML.format(ym=ymd[:6], dd=ymd[6:])
    response = _request(
        xml_url,
        session=session,
        timeout=(10, 60),
        allow_status=(302, 404),
        allow_redirects=False,
    )
    if response.status_code in (302, 404):
        raise RuntimeError(f"CFFEX {ymd} has a CSV but no index.xml: {xml_url}")
    xml_upper = response.content.upper()
    if b"<!DOCTYPE" in xml_upper or b"<!ENTITY" in xml_upper:
        raise RuntimeError(f"CFFEX index.xml contains DOCTYPE or ENTITY: {xml_url}")
    try:
        nodes = ElementTree.fromstring(response.content).findall("dailydata")
    except ElementTree.ParseError as exc:
        raise RuntimeError(f"CFFEX index.xml cannot be parsed: {exc}") from exc
    witness: dict[str, tuple[float | None, ...]] = {}
    for node in nodes:
        values = {
            field: (node.findtext(field) or "").strip()
            for field in (
                "instrumentid",
                "tradingday",
                "volume",
                "closeprice",
                "openinterest",
            )
        }
        if values["tradingday"] != ymd:
            raise RuntimeError(
                f"CFFEX index.xml trading day is {values['tradingday']}, not {ymd}"
            )
        witness[values["instrumentid"]] = tuple(
            _source_number(values[field])
            for field in ("volume", "closeprice", "openinterest")
        )
    header = [cell.strip() for cell in table[0]]
    csv_rows: dict[str, tuple[float | None, ...]] = {}
    for record in table[1:]:
        code = record[0].strip() if record else ""
        if not code or code in ("小计", "合计", "总计"):
            continue
        row = dict(zip(header, record, strict=True))
        csv_rows[code] = tuple(
            _source_number(row.get(field))
            for field in ("成交量", "今收盘", "持仓量")
        )
    if not witness or len(witness) != len(nodes) or csv_rows != witness:
        differences = sorted(set(csv_rows) ^ set(witness)) or sorted(
            code for code in csv_rows if csv_rows[code] != witness.get(code)
        )
        raise RuntimeError(
            f"CFFEX {ymd} CSV and index.xml disagree "
            f"({len(csv_rows)} / {len(witness)} contracts; e.g. {differences[:3]})"
        )
    return table, url


def futures_daily(
    date: str | dt.date | dt.datetime, exchange: str = "CFFEX", session: Any = None
) -> list[dict[str, Any]]:
    """Return validated daily futures rows from the official CFFEX CSV/XML pair."""
    if exchange.upper() != "CFFEX":
        raise ValueError(f"unsupported exchange: {exchange!r}")
    ymd = _date_text(date).replace("-", "")
    table, _ = _cffex_daily_table(ymd, session)
    header = [cell.strip() for cell in table[0]]
    rows = []
    for record in table[1:]:
        if not record:
            continue
        values = dict(zip(header, record, strict=True))
        symbol = str(values.get("合约代码", "")).strip().upper()
        match = re.fullmatch(r"(IF|IH|IC|IM)(\d{4})", symbol)
        if match is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "product": match.group(1),
                "close": _source_number(values.get("今收盘")),
                "volume": _source_number(values.get("成交量")),
            }
        )
    return rows


def filter_a_shares(records: pd.DataFrame | list[dict[str, Any]]) -> pd.DataFrame:
    frame = records.copy() if isinstance(records, pd.DataFrame) else pd.DataFrame(records)
    required = {
        "market",
        "code",
        "prev_close",
        "close",
        "low",
        "volume",
        "amount",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"TDX rows missing required columns: {missing}")
    frame["market"] = frame["market"].astype(str).str.lower()
    frame["code"] = frame["code"].astype(str).str.zfill(6)
    for column in ("prev_close", "close", "low", "volume", "amount"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    sh = frame["market"].eq("sh") & frame["code"].str.startswith(("60", "68"))
    sz = frame["market"].eq("sz") & frame["code"].str.startswith(("00", "30"))
    bj = (
        frame["market"].eq("bj")
        & frame["code"].str.startswith(("4", "8", "9"))
        & ~frame["code"].str.startswith("90")
    )
    eligible = (
        (sh | sz | bj)
        & frame["volume"].gt(0)
        & frame["prev_close"].gt(0)
        & frame["close"].gt(0)
    )
    return frame.loc[eligible].copy().reset_index(drop=True)


def compute_daily_metrics(
    date: str | dt.date | dt.datetime,
    records: pd.DataFrame | list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, float]]:
    day = _date_text(date)
    all_rows = records.copy() if isinstance(records, pd.DataFrame) else pd.DataFrame(records)
    stocks = filter_a_shares(all_rows)
    if stocks.empty:
        raise RuntimeError(f"{day} has no eligible A-share rows")
    up = stocks["close"] > stocks["prev_close"]
    down = stocks["close"] < stocks["prev_close"]
    amount_total = float(stocks["amount"].sum())
    amount_up = float(stocks.loc[up, "amount"].sum())
    amount_down = float(stocks.loc[down, "amount"].sum())
    ordered_amounts = stocks["amount"].fillna(0).sort_values(ascending=False)
    volume_up = float(stocks.loc[up, "volume"].sum())
    volume_down = float(stocks.loc[down, "volume"].sum())
    adv, dec = int(up.sum()), int(down.sum())
    trin_amt = (
        (adv / dec) / (amount_up / amount_down)
        if dec > 0 and amount_down > 0 and amount_up > 0
        else None
    )
    trin_vol = (
        (adv / dec) / (volume_up / volume_down)
        if dec > 0 and volume_down > 0 and volume_up > 0
        else None
    )
    codes = stocks["code"]
    limits = np.where(
        codes.str[:2].isin(("30", "68")),
        0.2,
        np.where(stocks["market"].eq("bj"), 0.3, 0.1),
    )
    prev_close = stocks["prev_close"].to_numpy(dtype=float)
    close = stocks["close"].to_numpy(dtype=float)
    low = stocks["low"].to_numpy(dtype=float)
    up_price_limit = _rounded_limit_prices(prev_close, limits, up=True)
    down_price_limit = _rounded_limit_prices(prev_close, limits, up=False)
    st_down_price_limit = _rounded_limit_prices(
        prev_close, np.full_like(limits, 0.05), up=False
    )
    down_limit = (
        (close <= down_price_limit + 0.001)
        | (
            (close <= st_down_price_limit + 0.001)
            & (close <= low + 0.001)
            & (limits == 0.1)
            & ((close / prev_close - 1) < -0.045)
        )
    )
    up_limit = close >= up_price_limit - 0.001
    spots = {}
    index_codes = ("000001", *(code for _, code in BASIS_SPOT_CODES.values()))
    for code in index_codes:
        values = all_rows.loc[
            all_rows.get("market", pd.Series(dtype=str)).astype(str).str.lower().eq("sh")
            & all_rows.get("code", pd.Series(dtype=str)).astype(str).str.zfill(6).eq(code),
            "close",
        ]
        spots[code] = float(values.iloc[-1]) if not values.empty else None
    result = {
        "date": day,
        "sh": spots.get("000001"),
        "n": int(len(stocks)),
        "adv": adv,
        "dec": dec,
        "red": adv / len(stocks),
        "amt_up": amount_up / amount_total if amount_total > 0 else None,
        "trin_amt": trin_amt,
        "trin_vol": trin_vol,
        "up_mean_amount": amount_up / adv if adv else None,
        "down_mean_amount": amount_down / dec if dec else None,
        "up_mean_volume": volume_up / adv if adv else None,
        "down_mean_volume": volume_down / dec if dec else None,
        "lu": int(up_limit.sum()),
        "ld": int(down_limit.sum()),
        "amount_yi": amount_total / 100_000_000,
        "top50_share": (
            float(ordered_amounts.head(50).sum() / amount_total)
            if amount_total > 0
            else None
        ),
        "top100_share": (
            float(ordered_amounts.head(100).sum() / amount_total)
            if amount_total > 0
            else None
        ),
    }
    spot_by_name = {
        label: spots.get(code) for label, code in BASIS_SPOT_CODES.values()
    }
    return result, spot_by_name


def _third_friday(year: int, month: int) -> dt.date:
    first = dt.date(year, month, 1)
    first_friday = first + dt.timedelta(days=(4 - first.weekday()) % 7)
    return first_friday + dt.timedelta(days=14)


def _contract_expiry(symbol: str) -> dt.date | None:
    match = re.fullmatch(r"(?:IF|IH|IC|IM)(\d{2})(\d{2})", symbol.upper())
    if match is None:
        return None
    year, month = 2000 + int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return _third_friday(year, month)


def compute_basis(
    date: str | dt.date | dt.datetime,
    spot_prices: dict[str, float | None],
    futures: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], float | None]:
    day = dt.date.fromisoformat(_date_text(date))
    result: dict[str, dict[str, Any]] = {}
    annualized: list[float] = []
    for product, (spot_label, _) in BASIS_SPOT_CODES.items():
        candidates = []
        for row in futures:
            if str(row.get("product", "")).upper() != product:
                continue
            symbol = str(row.get("symbol", "")).upper()
            expiry = _contract_expiry(symbol)
            close = _source_number(row.get("close"))
            volume = _source_number(row.get("volume")) or 0.0
            if expiry is None or expiry < day or close is None or close <= 0:
                continue
            candidates.append((volume, symbol, close, (expiry - day).days))
        spot = _source_number(spot_prices.get(spot_label))
        if not candidates or spot is None or spot <= 0:
            result[product] = {
                "symbol": "",
                "close": None,
                "spot": spot,
                "spread": None,
                "pct": None,
                "ann": None,
                "days": None,
            }
            continue
        volume, symbol, close, days = max(candidates, key=lambda item: item[0])
        pct = (close / spot - 1) * 100
        ann = pct * 365 / max(days, 5)
        result[product] = {
            "symbol": symbol,
            "close": close,
            "spot": spot,
            "spread": close - spot,
            "pct": pct,
            "ann": ann,
            "days": days,
        }
        annualized.append(ann)
    mean = float(np.mean(annualized)) if annualized else None
    return result, mean


def compute_price_breadth(
    close_matrix: pd.DataFrame, windows: tuple[int, ...] = (20, 60, 250)
) -> pd.DataFrame:
    closes = close_matrix.apply(pd.to_numeric, errors="coerce")
    result = pd.DataFrame(index=closes.index)
    for window in windows:
        moving_average = closes.rolling(window, min_periods=window).mean()
        eligible = moving_average.notna()
        denominator = eligible.sum(axis=1).replace(0, np.nan)
        above = (closes > moving_average) & eligible
        result[f"P{window}"] = above.sum(axis=1).div(denominator)
    return result


def compute_mcl(adv: pd.Series, dec: pd.Series) -> pd.Series:
    difference = pd.to_numeric(adv, errors="coerce") - pd.to_numeric(
        dec, errors="coerce"
    )
    return difference.ewm(alpha=0.10, adjust=False).mean() - difference.ewm(
        alpha=0.05, adjust=False
    ).mean()


def _trend_days(values: pd.Series) -> int:
    changes = pd.to_numeric(values, errors="coerce").dropna().diff().dropna()
    if changes.empty or changes.iloc[-1] == 0:
        return 0
    direction = 1 if changes.iloc[-1] > 0 else -1
    count = 0
    for change in reversed(changes.to_list()):
        if (change > 0) != (direction > 0) or change == 0:
            break
        count += 1
    return direction * count


def _load_rows(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame(columns=ROW_FIELDS)
    frame = pd.read_csv(path)
    for field in ROW_FIELDS:
        if field not in frame.columns:
            frame[field] = None
    return frame.loc[:, ROW_FIELDS]


def _load_close_matrix(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    frame = pd.read_parquet(path)
    if "date" in frame.columns:
        frame = frame.set_index("date")
    frame.index = pd.to_datetime(frame.index).strftime("%Y-%m-%d")
    frame.index.name = "date"
    return frame.apply(pd.to_numeric, errors="coerce")


def _close_series(records: pd.DataFrame, day: str) -> pd.Series:
    stocks = filter_a_shares(records)
    keys = stocks["market"] + stocks["code"]
    return pd.Series(stocks["close"].to_numpy(dtype=float), index=keys, name=day)


def _trading_dates(asof: str) -> pd.DatetimeIndex:
    from research.pipeline import stock

    cutoff = pd.Timestamp(asof)
    calendar = stock._reference_calendar(cutoff)
    dates = pd.DatetimeIndex(pd.to_datetime(calendar)).normalize()
    return dates[dates <= cutoff].drop_duplicates().sort_values()


def _fetch_day(
    day: str,
    retries: int,
    sleep: Any = time.sleep,
) -> tuple[str, pd.DataFrame, list[dict[str, Any]]]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return day, tdx_daily_package(day), futures_daily(day, "CFFEX")
        except Exception as exc:  # retries include source 404s and validation failures
            last_error = exc
            if attempt < retries:
                sleep(0.5 * attempt)
    raise RuntimeError(
        f"failed to fetch breadth inputs for {day} after {retries} attempts: {last_error}"
    ) from last_error


def _json_scalar(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _row_with_basis(
    day: str,
    records: pd.DataFrame,
    futures: list[dict[str, Any]],
) -> tuple[dict[str, Any], pd.Series]:
    base, spots = compute_daily_metrics(day, records)
    basis, basis_mean = compute_basis(day, spots, futures)
    row = {field: None for field in ROW_FIELDS}
    row.update(base)
    row["basis_json"] = json.dumps(
        basis, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    row["basis_ann_mean"] = basis_mean
    return row, _close_series(records, day)


def _normalize_rows(frame: pd.DataFrame, close_matrix: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise RuntimeError("no breadth rows are available")
    result = frame.copy()
    result["date"] = result["date"].map(_date_text)
    result = (
        result.sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    for field in (
        "sh",
        "red",
        "amt_up",
        "trin_amt",
        "trin_vol",
        "amount_yi",
        "top50_share",
        "top100_share",
    ):
        result[field] = pd.to_numeric(result[field], errors="coerce")
    result["adv"] = pd.to_numeric(result["adv"], errors="coerce").fillna(0).astype(int)
    result["dec"] = pd.to_numeric(result["dec"], errors="coerce").fillna(0).astype(int)
    result["amount_ratio20"] = pd.to_numeric(
        result["amount_ratio20"], errors="coerce"
    )
    amounts = result["amount_yi"]
    previous_mean = amounts.shift(1).rolling(20, min_periods=20).mean()
    result["amount_ratio20"] = amounts.div(previous_mean)
    result["MCL"] = compute_mcl(result["adv"], result["dec"]).to_numpy()
    if not close_matrix.empty:
        prices = compute_price_breadth(close_matrix)
        for field in ("P20", "P60", "P250"):
            values = result["date"].map(prices[field].to_dict())
            result[field] = values.where(values.notna(), result[field])
    for field in ("P20", "P60", "P250", "MCL", "basis_ann_mean"):
        result[field] = pd.to_numeric(result[field], errors="coerce")
    return result.loc[:, ROW_FIELDS]


def _build_output(frame: pd.DataFrame) -> dict[str, Any]:
    latest = frame.iloc[-1].to_dict()
    basis = json.loads(str(latest.get("basis_json") or "{}"))
    latest_data = {
        field: _json_scalar(latest.get(field))
        for field in (
            "date",
            "sh",
            "n",
            "adv",
            "dec",
            "red",
            "amt_up",
            "trin_amt",
            "trin_vol",
            "up_mean_amount",
            "down_mean_amount",
            "up_mean_volume",
            "down_mean_volume",
            "lu",
            "ld",
            "amount_yi",
            "top50_share",
            "top100_share",
            "amount_ratio20",
            "P20",
            "P60",
            "P250",
            "MCL",
        )
    }
    latest_data["mcl_trend_days"] = _trend_days(frame["MCL"])
    latest_data["basis"] = basis
    latest_data["basis_ann_mean"] = _json_scalar(latest.get("basis_ann_mean"))
    history_fields = (
        "date",
        "sh",
        "red",
        "P20",
        "P60",
        "P250",
        "MCL",
        "trin_amt",
        "trin_vol",
        "up_mean_amount",
        "down_mean_amount",
        "up_mean_volume",
        "down_mean_volume",
        "amount_yi",
        "top50_share",
        "top100_share",
        "amount_ratio20",
        "basis_ann_mean",
    )
    history = []
    for _, row in frame.tail(60).iterrows():
        item = {field: _json_scalar(row.get(field)) for field in history_fields}
        item["basis"] = json.loads(_json_scalar(row.get("basis_json")) or "{}")
        history.append(item)
    risk_history = []
    for _, row in frame.tail(260).iterrows():
        risk_history.append(
            {
                field: _json_scalar(row.get(field))
                for field in ("date", "MCL", "top50_share", "top100_share")
            }
        )
    return {
        "schema": "breadth.v1",
        "asof": str(latest_data["date"]),
        "source": "通达信盘后包（沪深京A股）+ 中金所日行情",
        "note": NOTE,
        "mcl_warmup_days": int(len(frame)),
        "latest": latest_data,
        "trend_alerts": build_trend_ledger(frame.to_dict("records"), evidence="experimental")[-1],
        "history": history,
        "risk_history": risk_history,
        "warnings": [],
    }


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _save_cache(
    cache_dir: Path, rows: pd.DataFrame, close_matrix: pd.DataFrame
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    rows_bytes = rows.to_csv(index=False, columns=ROW_FIELDS).encode("utf-8")
    _atomic_write(cache_dir / "rows.csv", rows_bytes)
    recent = close_matrix.sort_index().tail(260).copy()
    recent.index.name = "date"
    with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".parquet", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        recent.to_parquet(temporary)
        os.replace(temporary, cache_dir / "close_matrix.parquet")
    finally:
        temporary.unlink(missing_ok=True)


def collect_breadth(
    asof: str,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    backfill: int = 300,
    workers: int = 3,
    retries: int = 3,
) -> dict[str, Any]:
    day = _date_text(asof)
    if backfill < 1 or workers < 1 or retries < 1:
        raise ValueError("backfill, workers, and retries must be positive")
    cache_dir = Path(cache_dir)
    rows_path = cache_dir / "rows.csv"
    closes_path = cache_dir / "close_matrix.parquet"
    cached_rows = _load_rows(rows_path)
    cached_closes = _load_close_matrix(closes_path)
    if rows_path.is_file():
        cached_columns = set(pd.read_csv(rows_path, nrows=0).columns)
        if not {"top50_share", "top100_share"}.issubset(cached_columns):
            cached_rows = pd.DataFrame(columns=ROW_FIELDS)
            cached_closes = pd.DataFrame()
    if not cached_rows.empty:
        cached_rows = cached_rows.loc[cached_rows["date"].map(_date_text) <= day]
    if not cached_closes.empty:
        cached_closes = cached_closes.loc[cached_closes.index <= day]
    if cached_rows.empty or cached_closes.empty:
        cached_rows = pd.DataFrame(columns=ROW_FIELDS)
        cached_closes = pd.DataFrame()
        history_count = backfill
    else:
        history_count = 0

    calendar = _trading_dates(day)
    if calendar.empty or calendar[-1].date().isoformat() != day:
        raise RuntimeError(f"{day} is not the latest closed trading date in the calendar")
    if history_count:
        fetch_dates = calendar[-history_count:]
        if len(fetch_dates) < history_count:
            raise RuntimeError(
                f"trading calendar has {len(fetch_dates)} days, needs {history_count}"
            )
    else:
        last_day = str(cached_rows["date"].max())
        fetch_dates = calendar[calendar > pd.Timestamp(last_day)]
    date_texts = [pd.Timestamp(value).date().isoformat() for value in fetch_dates]
    fetched_rows: list[dict[str, Any]] = []
    fetched_closes: list[pd.Series] = []
    if date_texts:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(_fetch_day, item, retries) for item in date_texts
            ]
            for future in concurrent.futures.as_completed(futures):
                fetched_day, records, contracts = future.result()
                row, closes = _row_with_basis(fetched_day, records, contracts)
                fetched_rows.append(row)
                fetched_closes.append(closes)
    added = pd.DataFrame(fetched_rows, columns=ROW_FIELDS)
    rows = pd.concat((cached_rows, added), ignore_index=True)
    rows = rows.sort_values("date").drop_duplicates("date", keep="last")
    new_closes = pd.DataFrame(fetched_closes)
    if not new_closes.empty:
        new_closes.index.name = "date"
    close_matrix = pd.concat((cached_closes, new_closes), axis=0, sort=False)
    if not close_matrix.empty:
        close_matrix = (
            close_matrix.sort_index()
            .loc[~close_matrix.sort_index().index.duplicated(keep="last")]
            .tail(max(260, backfill if history_count else 260))
        )
    normalized = _normalize_rows(rows, close_matrix)
    _save_cache(cache_dir, normalized, close_matrix)
    return _build_output(normalized)


def run_pipeline(
    out_path: Path,
    *,
    asof: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    backfill: int = 300,
    previous_path: Path | None = None,
) -> dict[str, Any]:
    out_path = Path(out_path)
    try:
        payload = collect_breadth(asof, cache_dir=cache_dir, backfill=backfill)
        content = (
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode("utf-8")
        _atomic_write(out_path, content)
    except Exception:
        if previous_path is not None and Path(previous_path).is_file():
            _atomic_write(out_path, Path(previous_path).read_bytes())
        raise
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the daily market breadth snapshot")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--date", help="snapshot date; defaults to trading_date helper")
    parser.add_argument("--backfill", type=int, default=300)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args(argv)
    if args.date:
        asof = _date_text(args.date)
    else:
        from research.data.trading_date import latest_closed_trading_day

        asof = latest_closed_trading_day()
    run_pipeline(
        args.out,
        asof=asof,
        cache_dir=args.cache_dir,
        backfill=args.backfill,
        previous_path=args.previous,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
