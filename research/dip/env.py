"""Daily descriptive index and ETF environment snapshot."""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from ..data.tencent_sina import fetch_tencent_sina

ETF_CODES = ("510300", "588000", "510050", "510500")
OPTION_CATEGORIES = {
    "510300": "300ETF",
    "588000": "科创50ETF",
    "510050": "50ETF",
    "510500": "500ETF",
}
SHARE_URL = "https://query.sse.com.cn/commonQuery.do"
OPTION_NAME_URL = (
    "https://stock.finance.sina.com.cn/futures/api/openapi.php/"
    "StockOptionService.getStockName"
)
SINA_HEADERS = {
    "Referer": "https://stock.finance.sina.com.cn/",
    "User-Agent": "Mozilla/5.0",
}
ENV_NOTE = "指数/ETF 环境，不是个股信号"


def _sina_list(param: str) -> list[str]:
    response = requests.get(
        f"https://hq.sinajs.cn/list={param}", headers=SINA_HEADERS, timeout=15
    )
    response.encoding = "gbk"
    text = response.text
    return text.split('"')[1].split(",") if '"' in text else []


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    return value


def _share_history(days: int = 130) -> pd.DataFrame:
    prices = fetch_tencent_sina("sh", "510300", True, "")
    dates = prices.date.astype(str).drop_duplicates().tail(days).tolist()
    rows = []
    for day in dates:
        try:
            response = requests.get(
                SHARE_URL,
                params={
                    "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L",
                    "STAT_DATE": day,
                    "isPagination": "true",
                    "pageHelp.pageSize": 10000,
                    "pageHelp.pageNo": 1,
                    "pageHelp.beginPage": 1,
                    "pageHelp.cacheSize": 1,
                    "pageHelp.endPage": 1,
                },
                headers={"Referer": "https://www.sse.com.cn/"},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            records = payload.get("result", []) if isinstance(payload, dict) else []
            for record in records:
                code = str(record.get("SEC_CODE", ""))
                if code in ETF_CODES and record.get("TOT_VOL") is not None:
                    rows.append(
                        {
                            "date": day,
                            "code": code,
                            "shares": float(record["TOT_VOL"]),
                        }
                    )
        except Exception as exc:
            print(f"ETF share snapshot {day} failed: {type(exc).__name__}: {exc}")
        time.sleep(1.2)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.drop_duplicates(["date", "code"]).sort_values(["code", "date"])
    return frame


def _share_summary(frame: pd.DataFrame, code: str) -> dict:
    data = (
        frame.loc[frame.code == code]
        .sort_values("date")
        .drop_duplicates("date", keep="last")
    )
    if data.empty:
        return {
            "evidence": "descriptive",
            "note": ENV_NOTE,
            "n_days": 0,
            "latest_date": None,
            "latest_shares_yi": None,
            "change_5d": None,
            "change_20d": None,
            "change_60d": None,
            "change_5d_shares_yi": None,
            "change_20d_shares_yi": None,
            "change_60d_shares_yi": None,
            "mad_subscription_dates": [],
        }
    values = data.shares.to_numpy(dtype=float)
    changes = pd.Series(values).diff()
    median = float(changes.dropna().median()) if changes.notna().any() else 0.0
    mad = float((changes.dropna() - median).abs().median()) if changes.notna().any() else 0.0
    scale = 1.4826 * mad
    anomalies = []
    if scale > 0:
        scores = (changes - median) / scale
        for index in np.flatnonzero((scores >= 3.5).to_numpy()):
            anomalies.append(
                {
                    "date": str(data.date.iloc[index].date()),
                    "change": float(changes.iloc[index]),
                    "robust_z": float(scores.iloc[index]),
                }
            )
    summary = {
        "evidence": "descriptive",
        "note": ENV_NOTE,
        "n_days": int(len(data)),
        "latest_date": str(data.date.iloc[-1].date()),
        "latest_shares_yi": float(values[-1] / 1e4),
    }
    for days in (5, 20, 60):
        available = len(values) > days and values[-days - 1] != 0
        summary[f"change_{days}d"] = (
            float(values[-1] / values[-days - 1] - 1) if available else None
        )
        summary[f"change_{days}d_shares_yi"] = (
            float((values[-1] - values[-days - 1]) / 1e4) if available else None
        )
        summary[f"change_{days}d_from"] = (
            str(data.date.iloc[-days - 1].date()) if available else None
        )
    summary["mad_subscription_dates"] = anomalies[-12:]
    return summary


def _option_codes(underlying: str, call: bool, month: str) -> list[str]:
    flag = "OP_UP_" if call else "OP_DOWN_"
    return [
        value.replace("CON_OP_", "")
        for value in _sina_list(f"{flag}{underlying}{month}")
        if value.startswith("CON_OP_")
    ]


def _option_rows(underlying: str, month: str) -> list[dict]:
    rows = []
    for call in (True, False):
        for code in _option_codes(underlying, call, month):
            raw = _sina_list(f"CON_SO_{code}")
            if len(raw) < 16:
                continue
            values = [raw[0]] + raw[4:]
            try:
                rows.append(
                    {
                        "call": call,
                        "strike": float(values[10]),
                        "iv": float(values[6]),
                        "delta": float(values[2]),
                        "volume": float(values[1]),
                    }
                )
            except (ValueError, IndexError):
                continue
            time.sleep(0.05)
    return rows


def _option_summary(underlying: str) -> dict:
    try:
        response = requests.get(
            OPTION_NAME_URL,
            params={"exchange": "null", "cate": OPTION_CATEGORIES[underlying]},
            headers=SINA_HEADERS,
            timeout=15,
        )
        response.raise_for_status()
        months = response.json()["result"]["data"]["contractMonth"]
        month = months[min(2, len(months) - 1)]
        month_code = month.replace("-", "")[2:]
        prices = fetch_tencent_sina("sh", underlying, True, "")
        close = pd.to_numeric(prices.close, errors="coerce").dropna().to_numpy(float)
        if len(close) < 21:
            raise ValueError("fewer than 21 underlying closes")
        log_returns = np.diff(np.log(close))
        rv20 = float(np.std(log_returns[-20:], ddof=1) * math.sqrt(252))
        rv60 = float(np.std(log_returns[-60:], ddof=1) * math.sqrt(252)) if len(log_returns) >= 60 else None
        rv_history = (
            pd.Series(log_returns)
            .rolling(20)
            .std()
            .mul(math.sqrt(252))
            .dropna()
            .tail(1260)
        )
        rows = _option_rows(underlying, month_code)
        atm = [row for row in rows if abs(abs(row["delta"]) - 0.5) < 0.12 and row["iv"] > 0]
        put25 = [row for row in rows if not row["call"] and 0.15 < abs(row["delta"]) < 0.35 and row["iv"] > 0]
        call25 = [row for row in rows if row["call"] and 0.15 < abs(row["delta"]) < 0.35 and row["iv"] > 0]
        iv_atm = float(np.mean([row["iv"] for row in atm])) if atm else None
        iv_put25 = float(np.mean([row["iv"] for row in put25])) if put25 else None
        iv_call25 = float(np.mean([row["iv"] for row in call25])) if call25 else None
        put_volume = sum(row["volume"] for row in rows if not row["call"])
        call_volume = sum(row["volume"] for row in rows if row["call"])
        return {
            "evidence": "descriptive",
            "note": ENV_NOTE,
            "month": month,
            "spot": float(close[-1]),
            "iv_atm": iv_atm,
            "rv20": rv20,
            "iv_minus_rv20": iv_atm - rv20 if iv_atm is not None else None,
            "iv_put25": iv_put25,
            "iv_call25": iv_call25,
            "put_call_skew": iv_put25 - iv_call25 if iv_put25 is not None and iv_call25 is not None else None,
            "put_call_volume": put_volume / call_volume if call_volume else None,
            "iv_pct_rv_history": (
                float((rv_history <= iv_atm).mean()) if iv_atm is not None and len(rv_history) else None
            ),
            "rv60": rv60,
            "n": len(rows),
        }
    except Exception as exc:
        return {
            "evidence": "descriptive",
            "note": ENV_NOTE,
            "n": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }


def collect() -> tuple[dict, dict]:
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    shares = _share_history()
    share_data = {code: _share_summary(shares, code) for code in ETF_CODES}
    options = {code: _option_summary(code) for code in ETF_CODES}
    snapshot = {
        "asof": today,
        "evidence": "descriptive",
        "note": ENV_NOTE,
        "shares": share_data,
        "options": options,
    }
    return _json_safe(snapshot), _json_safe({"asof": today, "options": options})


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect descriptive ETF/index environment")
    parser.add_argument("--out", type=Path, default=Path("out/stock"))
    args = parser.parse_args()
    snapshot, options = collect()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "_dip_env.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    archive = args.out / "dip_env" / "options" / f"{options['asof']}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(
        json.dumps(options, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(args.out / "_dip_env.json")
    print(archive)


if __name__ == "__main__":
    main()
