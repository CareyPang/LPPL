"""A 股日线数据源与统一请求限速。"""
from __future__ import annotations

import os
import random
import re
import threading
import time
from collections.abc import Callable
from typing import Any

import pandas as pd
import requests

COLS = ["date", "open", "high", "low", "close", "volume", "amount"]
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    )
}


class SourceError(RuntimeError):
    pass


_rate_lock = threading.Lock()
_ak_lock = threading.Lock()
_last_request: float | None = None


def rate_limit() -> None:
    """Wait between outbound requests; CP_MIN_INTERVAL overrides the 1.5s default."""
    global _last_request
    interval = max(0.0, float(os.environ.get("CP_MIN_INTERVAL", "1.5")))
    delay = interval + random.uniform(0.0, 0.5)
    with _rate_lock:
        now = time.monotonic()
        if _last_request is not None:
            wait = max(0.0, delay - (now - _last_request))
            if wait:
                time.sleep(wait)
        _last_request = time.monotonic()


def parse_code(code: str) -> tuple[str, str, bool]:
    """'600519' / 'sh600519' / '000300' / 'sh000001' -> (market, code6, is_index)."""
    c = code.strip().lower()
    m = re.fullmatch(r"(sh|sz)?(\d{6})", c)
    if not m:
        raise ValueError(f"无法识别代码: {code}")
    pre, six = m.group(1), m.group(2)
    if pre:
        is_index = (pre == "sh" and six.startswith("000")) or (
            pre == "sz" and six.startswith("399")
        )
        return pre, six, is_index
    if six.startswith("399"):
        return "sz", six, True
    if six in INDEX_HINT:
        return "sh", six, True
    if six[0] in "69":
        return "sh", six, False
    if six[0] in "03":
        return "sz", six, False
    raise ValueError(f"不支持的市场/代码: {code}")


INDEX_HINT = {"000001", "000016", "000300", "000688", "000905", "000852"}


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    for col in COLS[1:]:
        if col not in out:
            out[col] = float("nan")
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out[COLS].dropna(subset=["close"]).sort_values("date").drop_duplicates("date")
    return out.reset_index(drop=True)


def _rename_ak_columns(df: pd.DataFrame) -> pd.DataFrame:
    names = {
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
        "date": "date",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "amount": "amount",
    }
    return df.rename(
        columns=lambda col: names.get(str(col).strip().lower(), names.get(str(col).strip(), col))
    )


class _LimitedRequests:
    def __init__(self, original: Any, timeout: float):
        self._original = original
        self._timeout = timeout

    def get(self, *args: Any, **kwargs: Any) -> Any:
        rate_limit()
        timeout = kwargs.get("timeout")
        if isinstance(timeout, tuple):
            kwargs["timeout"] = tuple(
                min(value, self._timeout) if value else self._timeout for value in timeout
            )
        else:
            kwargs["timeout"] = min(timeout, self._timeout) if timeout else self._timeout
        return self._original.get(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


def _ak_call(function: Callable[..., pd.DataFrame], timeout: float, **kwargs: Any) -> pd.DataFrame:
    """Call AkShare with request-level throttling and a bounded HTTP timeout."""
    namespace = function.__globals__
    with _ak_lock:
        original = namespace.get("requests")
        if original is not None and hasattr(original, "get"):
            namespace["requests"] = _LimitedRequests(original, timeout)
        try:
            return function(**kwargs)
        finally:
            if original is not None and hasattr(original, "get"):
                namespace["requests"] = original


def _ak_source(
    function: Callable[..., pd.DataFrame],
    name: str,
    request_timeout: float,
    **kwargs: Any,
):
    df = _ak_call(function, request_timeout, **kwargs)
    if df is None or df.empty:
        raise SourceError(f"{name} 无数据")
    return _norm(_rename_ak_columns(df))


def fetch_eastmoney(
    market: str, six: str, is_index: bool, adjust: str = "qfq", timeout: float = 15
) -> pd.DataFrame:
    """东方财富 push2his K 线。"""
    secid = f"{1 if market == 'sh' else 0}.{six}"
    fqt = {"": 0, "qfq": 1, "hfq": 2}[adjust if not is_index else ""]
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "klt": 101,
        "fqt": fqt,
        "beg": "19900101",
        "end": "20500101",
        "lmt": 100000,
    }
    rate_limit()
    response = requests.get(url, params=params, headers=UA, timeout=min(timeout, 15))
    response.raise_for_status()
    klines = (response.json().get("data") or {}).get("klines")
    if not klines:
        raise SourceError(f"eastmoney 无数据: {secid}")
    rows = [line.split(",") for line in klines]
    df = pd.DataFrame(
        rows, columns=["date", "open", "close", "high", "low", "volume", "amount"]
    )
    return _norm(df)


def fetch_tencent(
    market: str, six: str, is_index: bool, adjust: str = "qfq", timeout: float = 15
) -> pd.DataFrame:
    """腾讯 ifzq 日线，按年分段拉取（接口单次上限约 640 条）。"""
    symbol = f"{market}{six}"
    fq = "" if is_index else {"": "", "qfq": "qfq", "hfq": "hfq"}[adjust]
    key = f"{fq}day" if fq else "day"
    frames = []
    year = 1990
    end_year = pd.Timestamp.today().year
    while year <= end_year:
        end_year_for_request = min(year + 1, end_year)
        param = f"{symbol},day,{year}-01-01,{end_year_for_request}-12-31,640,{fq}"
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        rate_limit()
        response = requests.get(
            url, params={"param": param}, headers=UA, timeout=min(timeout, 15)
        )
        response.raise_for_status()
        data = (response.json().get("data") or {}).get(symbol) or {}
        rows = data.get(key) or data.get("day") or []
        if rows:
            parsed = [
                [row[0], row[1], row[3], row[4], row[2], row[5], None] for row in rows
            ]
            frames.append(
                pd.DataFrame(
                    parsed,
                    columns=["date", "open", "high", "low", "close", "volume", "amount"],
                )
            )
        year = end_year_for_request + 1
    if not frames:
        raise SourceError(f"tencent 无数据: {symbol}")
    return _norm(pd.concat(frames))


def fetch_ak_em_index(
    market: str, six: str, is_index: bool, adjust: str = "qfq", timeout: float = 15
) -> pd.DataFrame:
    import akshare as ak

    return _ak_source(
        ak.stock_zh_index_daily_em,
        "ak_em_index",
        timeout,
        symbol=f"{market}{six}",
    )


def fetch_ak_tx_index(
    market: str, six: str, is_index: bool, adjust: str = "qfq", timeout: float = 15
) -> pd.DataFrame:
    import akshare as ak

    return _ak_source(
        ak.stock_zh_index_daily_tx,
        "ak_tx_index",
        timeout,
        symbol=f"{market}{six}",
    )


def fetch_ak_sina_index(
    market: str, six: str, is_index: bool, adjust: str = "qfq", timeout: float = 15
) -> pd.DataFrame:
    import akshare as ak

    return _ak_source(
        ak.stock_zh_index_daily,
        "ak_sina_index",
        timeout,
        symbol=f"{market}{six}",
    )


def fetch_ak_em_stock(
    market: str, six: str, is_index: bool, adjust: str = "qfq", timeout: float = 15
) -> pd.DataFrame:
    import akshare as ak

    return _ak_source(
        ak.stock_zh_a_hist,
        "ak_em_stock",
        timeout,
        symbol=six,
        period="daily",
        adjust=adjust,
        timeout=min(timeout, 15),
    )


def fetch_ak_sina_stock(
    market: str, six: str, is_index: bool, adjust: str = "qfq", timeout: float = 15
) -> pd.DataFrame:
    import akshare as ak

    return _ak_source(
        ak.stock_zh_a_daily,
        "ak_sina_stock",
        timeout,
        symbol=f"{market}{six}",
        adjust=adjust,
    )


def fetch_ak_tx_stock(
    market: str, six: str, is_index: bool, adjust: str = "qfq", timeout: float = 15
) -> pd.DataFrame:
    import akshare as ak

    return _ak_source(
        ak.stock_zh_a_hist_tx,
        "ak_tx_stock",
        timeout,
        symbol=f"{market}{six}",
        adjust=adjust,
        timeout=min(timeout, 15),
    )


def fetch_sina(
    market: str, six: str, is_index: bool, adjust: str = "qfq", timeout: float = 15
) -> pd.DataFrame:
    """兼容旧来源名的新浪 AkShare 来源。"""
    if is_index:
        return fetch_ak_sina_index(market, six, is_index, adjust, timeout)
    return fetch_ak_sina_stock(market, six, is_index, adjust, timeout)


SOURCES: dict[str, Callable[..., pd.DataFrame]] = {
    "ak_em_index": fetch_ak_em_index,
    "ak_tx_index": fetch_ak_tx_index,
    "ak_sina_index": fetch_ak_sina_index,
    "ak_em_stock": fetch_ak_em_stock,
    "ak_sina_stock": fetch_ak_sina_stock,
    "ak_tx_stock": fetch_ak_tx_stock,
    "eastmoney": fetch_eastmoney,
    "tencent": fetch_tencent,
    "sina": fetch_sina,
}
DEFAULT_ORDER = ("ak_em_index", "ak_tx_index", "ak_sina_index", "eastmoney", "tencent")
STOCK_ORDER = ("ak_em_stock", "ak_sina_stock", "eastmoney", "ak_tx_stock", "tencent")
