from __future__ import annotations

import math
import re
import time
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests

from .market_base import EM_DATACENTER_URL, UA, EMClient

CSINDEX_CONSTITUENTS_URL = (
    "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/"
    "autofile/cons/000510cons.xls"
)
BASELINE_HISTORY = (
    Path(__file__).resolve().parents[2] / "data" / "bottom" / "a500_pe_recon.parquet"
)
_EM_CLIENT = EMClient()
_HISTORY_COLUMNS = ("n", "mcap", "earn", "pe_ttm")


def _code(value: object) -> str | None:
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    text = text.split(".", 1)[0]
    if not re.fullmatch(r"\d+", text):
        return None
    return text.zfill(6)


def _codes(values) -> list[str]:
    result = []
    for value in values:
        code = _code(value)
        if code:
            result.append(code)
    return list(dict.fromkeys(result))


def constituents() -> list[str]:
    import akshare as ak

    try:
        frame = ak.index_stock_cons_csindex(symbol="000510")
        column = next(
            (
                name
                for name in ("成分券代码", "成分股代码", "品种代码", "代码", "code")
                if name in frame.columns
            ),
            frame.columns[0] if len(frame.columns) else None,
        )
        values = frame[column].tolist() if column is not None else []
        codes = _codes(values)
        if codes:
            return codes
    except Exception:
        pass

    response = requests.get(
        CSINDEX_CONSTITUENTS_URL,
        headers={"User-Agent": UA},
        timeout=30,
    )
    response.raise_for_status()
    fallback = pd.read_excel(BytesIO(response.content))
    if fallback.shape[1] <= 4:
        raise ValueError("中证A500成分文件缺少第 5 列")
    codes = _codes(fallback.iloc[:, 4].tolist())
    if not codes:
        raise ValueError("未能读取中证A500成分代码")
    return codes


def fetch_recent(code: str, page_size: int = 30) -> pd.DataFrame:
    security_code = _code(code)
    if security_code is None:
        raise ValueError(f"无效的证券代码: {code!r}")
    params = {
        "reportName": "RPT_VALUEANALYSIS_DET",
        "columns": "TRADE_DATE,TOTAL_MARKET_CAP,PE_TTM",
        "filter": f'(SECURITY_CODE="{security_code}")',
        "sortColumns": "TRADE_DATE",
        "sortTypes": "-1",
        "pageSize": str(page_size),
        "pageNumber": "1",
        "source": "WEB",
        "client": "WEB",
    }
    last_error = None
    for attempt in range(4):
        try:
            response = _EM_CLIENT._request_once(
                EM_DATACENTER_URL,
                params=params,
                headers={"User-Agent": UA},
                timeout=30,
            )
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("东财估值响应格式异常")
            result = payload.get("result")
            if result is None:
                return pd.DataFrame(
                    columns=["SECURITY_CODE", "TRADE_DATE", "TOTAL_MARKET_CAP", "PE_TTM"]
                )
            if not isinstance(result, dict):
                raise ValueError("东财估值响应格式异常")
            records = result.get("data") or []
            if not isinstance(records, list):
                raise ValueError("东财估值数据格式异常")
            frame = pd.DataFrame(records)
            if "SECURITY_CODE" not in frame:
                frame["SECURITY_CODE"] = security_code
            return frame
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(3)
    raise RuntimeError(
        f"东财估值查询失败 {security_code}: {type(last_error).__name__}"
    ) from last_error


def fetch_recent_many(
    codes: list[str], deadline_s: float = 1800
) -> tuple[pd.DataFrame, int]:
    frames = []
    failed_count = 0
    consecutive_failures = 0
    deadline = time.monotonic() + deadline_s

    def check_deadline() -> None:
        if time.monotonic() >= deadline:
            raise RuntimeError("东财估值整体获取超过时限")

    for index, code in enumerate(codes):
        check_deadline()
        try:
            frame = fetch_recent(code)
        except Exception as exc:
            failed_count += 1
            consecutive_failures += 1
            check_deadline()
            if consecutive_failures >= 20:
                raise RuntimeError(
                    f"东财估值连续失败：连续 {consecutive_failures} 只"
                ) from exc
        else:
            consecutive_failures = 0
            check_deadline()
            if not frame.empty:
                frames.append(frame)
        if index + 1 < len(codes):
            time.sleep(0.4)
            check_deadline()
    check_deadline()
    if not frames:
        rows = pd.DataFrame(
            columns=["SECURITY_CODE", "TRADE_DATE", "TOTAL_MARKET_CAP", "PE_TTM"]
        )
    else:
        rows = pd.concat(frames, ignore_index=True)
    return rows, failed_count


def _numeric(values: pd.Series) -> pd.Series:
    text = values.astype("string").str.strip().str.replace(",", "", regex=False)
    return pd.to_numeric(text, errors="coerce")


def aggregate(rows: pd.DataFrame) -> pd.DataFrame:
    columns = list(_HISTORY_COLUMNS)
    if rows.empty:
        return pd.DataFrame(columns=columns, index=pd.DatetimeIndex([], name="date"))

    rename = {
        "SECURITY_CODE": "code",
        "TRADE_DATE": "date",
        "TOTAL_MARKET_CAP": "mcap",
        "PE_TTM": "pe_ttm",
    }
    frame = rows.rename(columns=rename).copy()
    required = ("code", "date", "mcap", "pe_ttm")
    missing = [column for column in required if column not in frame]
    if missing:
        raise ValueError("估值数据缺少列: " + ", ".join(missing))

    frame["code"] = frame["code"].map(_code)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["mcap"] = _numeric(frame["mcap"])
    frame["pe_ttm"] = _numeric(frame["pe_ttm"])
    frame = frame.dropna(subset=["code", "date"])
    frame = frame.drop_duplicates(["code", "date"], keep="last")
    frame["earn"] = frame["mcap"].where(frame["pe_ttm"].notna() & frame["pe_ttm"].ne(0))
    frame["earn"] = frame["earn"] / frame["pe_ttm"]

    valid = frame.dropna(subset=["mcap", "earn"])
    counts = valid.groupby("date")["code"].nunique().rename("n")
    totals = valid.groupby("date").agg(mcap=("mcap", "sum"), earn=("earn", "sum"))
    result = counts.to_frame().join(totals, how="left")
    result["pe_ttm"] = result["mcap"] / result["earn"].where(result["earn"].ne(0))
    result.index.name = "date"
    return result[columns].sort_index()


def _normalize_history(history: pd.DataFrame) -> pd.DataFrame:
    frame = history.copy()
    if "date" in frame.columns:
        frame = frame.set_index("date")
    elif "Unnamed: 0" in frame.columns:
        frame = frame.set_index("Unnamed: 0")
    frame.index = pd.to_datetime(frame.index, errors="coerce")
    frame = frame.loc[~frame.index.isna()]
    frame.index = frame.index.normalize()
    frame.index.name = "date"
    missing = [column for column in _HISTORY_COLUMNS if column not in frame]
    if missing:
        raise ValueError("历史估值数据缺少列: " + ", ".join(missing))
    frame = frame.loc[:, list(_HISTORY_COLUMNS)].copy()
    for column in _HISTORY_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_index()


def load_history(path: Path | None = None) -> pd.DataFrame:
    if path is not None and path.exists():
        return _normalize_history(pd.read_csv(path))
    return _normalize_history(pd.read_parquet(BASELINE_HISTORY))


def update(
    hist: pd.DataFrame, n_constituents: int, rows: pd.DataFrame
) -> pd.DataFrame:
    history = _normalize_history(hist)
    if n_constituents <= 0:
        return history
    daily = aggregate(rows)
    if daily.empty:
        return history
    minimum = math.ceil(0.95 * n_constituents)
    last_date = history.index.max() if len(history) else pd.Timestamp.min
    additions = daily.loc[(daily.index > last_date) & daily["n"].ge(minimum)]
    if additions.empty:
        return history
    return pd.concat([history, additions]).sort_index()


def write_history(history: pd.DataFrame, path: Path) -> Path:
    normalized = _normalize_history(history)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_csv(path, index_label="date", date_format="%Y-%m-%d")
    return path
