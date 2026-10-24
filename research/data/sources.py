"""日线数据源：东方财富（主）→ 腾讯（备）→ 新浪（备）。

每个源返回统一列：date, open, high, low, close, volume, amount（缺失填 NaN）。
所有源都是公开接口，不需要密钥。调用方（cache.py）负责重试与落盘。
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable

import pandas as pd
import requests

COLS = ["date", "open", "high", "low", "close", "volume", "amount"]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


class SourceError(RuntimeError):
    pass


def parse_code(code: str) -> tuple[str, str, bool]:
    """'600519' / 'sh600519' / '000300' / 'sh000001' -> (market, code6, is_index)。

    指数判定：显式前缀 sh000xxx / sz399xxx，或六位 000xxx 且被 INDEX_HINT 命中。
    纯六位代码默认按个股：6/9 开头上海，0/3 开头深圳，4/8 开头北交所（北交所不支持）。
    """
    c = code.strip().lower()
    m = re.fullmatch(r"(sh|sz)?(\d{6})", c)
    if not m:
        raise ValueError(f"无法识别代码: {code}")
    pre, six = m.group(1), m.group(2)
    if pre:
        is_index = (pre == "sh" and six.startswith("000")) or (pre == "sz" and six.startswith("399"))
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
    for c in COLS[1:]:
        if c not in out:
            out[c] = float("nan")
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out[COLS].dropna(subset=["close"]).sort_values("date").drop_duplicates("date")
    return out.reset_index(drop=True)


def fetch_eastmoney(market: str, six: str, is_index: bool, adjust: str = "qfq", timeout: float = 15) -> pd.DataFrame:
    """东方财富 push2his K 线。fqt: 0 不复权 1 前复权 2 后复权。"""
    secid = f"{1 if market == 'sh' else 0}.{six}"
    fqt = {"": 0, "qfq": 1, "hfq": 2}[adjust if not is_index else ""]
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57", "klt": 101, "fqt": fqt,
        "beg": "19900101", "end": "20500101", "lmt": 100000,
    }
    r = requests.get(url, params=params, headers=UA, timeout=timeout)
    r.raise_for_status()
    js = r.json()
    kl = (js.get("data") or {}).get("klines")
    if not kl:
        raise SourceError(f"eastmoney 无数据: {secid}")
    rows = [k.split(",") for k in kl]
    df = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume", "amount"])
    return _norm(df)


def fetch_tencent(market: str, six: str, is_index: bool, adjust: str = "qfq", timeout: float = 20) -> pd.DataFrame:
    """腾讯 ifzq 日线，按年分段拉取（接口单次上限约 640 条）。"""
    sym = f"{market}{six}"
    fq = "" if is_index else {"": "", "qfq": "qfq", "hfq": "hfq"}[adjust]
    key = f"{fq}day" if fq else "day"
    frames = []
    year = 1990
    end_year = pd.Timestamp.today().year
    while year <= end_year:
        y2 = min(year + 1, end_year)
        param = f"{sym},day,{year}-01-01,{y2}-12-31,640,{fq}"
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        r = requests.get(url, params={"param": param}, headers=UA, timeout=timeout)
        r.raise_for_status()
        js = r.json()
        d = (js.get("data") or {}).get(sym) or {}
        arr = d.get(key) or d.get("day") or []
        if arr:
            rows = [[a[0], a[1], a[3], a[4], a[2], a[5], None] for a in arr]  # date,open,close,high,low,vol
            frames.append(pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount"]))
        year = y2 + 1
        time.sleep(0.2)
    if not frames:
        raise SourceError(f"tencent 无数据: {sym}")
    return _norm(pd.concat(frames))


def fetch_sina(market: str, six: str, is_index: bool, adjust: str = "qfq", timeout: float = 20) -> pd.DataFrame:
    """新浪：指数走 akshare.stock_zh_index_daily；个股走 stock_zh_a_daily（含复权）。"""
    import akshare as ak

    sym = f"{market}{six}"
    if is_index:
        df = ak.stock_zh_index_daily(symbol=sym)
    else:
        df = ak.stock_zh_a_daily(symbol=sym, adjust=adjust)
    if df is None or df.empty:
        raise SourceError(f"sina 无数据: {sym}")
    return _norm(df.rename(columns=str.lower))


SOURCES: dict[str, Callable[..., pd.DataFrame]] = {
    "eastmoney": fetch_eastmoney,
    "tencent": fetch_tencent,
    "sina": fetch_sina,
}
# 指数：腾讯不复权即可；个股：腾讯 qfq 对长历史返回“加法前复权”，早年价格为负，所以个股优先新浪（乘法复权）。
DEFAULT_ORDER = ("eastmoney", "tencent", "sina")
STOCK_ORDER = ("eastmoney", "sina", "tencent")
