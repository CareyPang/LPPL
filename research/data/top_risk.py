from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .market_base import EM_DATACENTER_URL, EMClient
from .tencent_sina import tencent_raw

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EPISODES = ROOT / "data" / "top_risk_episodes.json"
DEFAULT_BREADTH = Path("out/market/breadth_latest.json")
DEFAULT_OUT = Path("out/market/top_risk_latest.json")
MARGIN_REPORT = "RPTA_RZRQ_LSHJ"
MARGIN_PAGE_SIZE = 500
MIN_OBSERVATIONS = 120
LOOKBACK = 252
GAIN_LOOKBACK = 250
INDEXES = (
    ("sh000001", "上证指数"),
    ("sh000300", "沪深300"),
    ("sh000852", "中证1000"),
    ("sh000688", "科创50"),
)
SOURCE = "通达信全市场盘后包、东方财富两融历史、腾讯指数日线"
NOTE = "历史状态描述；历史分位不是概率，也不是预测或买卖信号。"


def _date_text(value: str | dt.date | dt.datetime) -> str:
    if isinstance(value, dt.datetime):
        value = value.date()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value).strip()
    parsed = dt.date.fromisoformat(text[:10])
    return parsed.isoformat()


def _number(value: Any, field: str) -> float:
    if value is None or str(value).strip() in ("", "-", "--"):
        raise ValueError(f"{field} is missing")
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} is not finite: {value!r}")
    return number


def _response_rows(
    payload: dict[str, Any], page: int
) -> tuple[list[dict], int, int]:
    code = payload.get("code")
    result = payload.get("result")
    if code not in (0, "0") or not isinstance(result, dict):
        raise RuntimeError(
            f"Eastmoney {MARGIN_REPORT} failed: {code} {payload.get('message', '')}"
        )
    rows = result.get("data")
    pages = result.get("pages")
    count = result.get("count")
    if (
        isinstance(pages, bool)
        or not isinstance(pages, int)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or pages < 1
        or count < 0
    ):
        raise RuntimeError(f"Eastmoney {MARGIN_REPORT} page {page} lacks valid count/pages")
    expected_pages = max(1, math.ceil(count / MARGIN_PAGE_SIZE))
    if pages != expected_pages:
        raise RuntimeError(
            f"Eastmoney {MARGIN_REPORT} reports pages={pages}, expected {expected_pages}"
        )
    if not isinstance(rows, list) or not all(
        isinstance(row, dict) for row in rows
    ):
        raise RuntimeError(f"Eastmoney {MARGIN_REPORT} page {page} has invalid data")
    if count < len(rows):
        raise RuntimeError(
            f"Eastmoney {MARGIN_REPORT} page {page} contains more rows than count"
        )
    return rows, pages, count


def _eligible_margin_rows(rows: list[dict], asof: str) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        date_value = row.get("DIM_DATE", row.get("date"))
        if date_value is None:
            raise RuntimeError(f"Eastmoney {MARGIN_REPORT} row lacks DIM_DATE")
        day = _date_text(date_value)
        if day >= asof:
            continue
        balance = row.get("RZYE", row.get("rzye"))
        result.append({"date": day, "rzye": _number(balance, "RZYE")})
    deduped = {row["date"]: row for row in result}
    return [deduped[day] for day in sorted(deduped)]


def fetch_margin_history(
    asof: str,
    client: EMClient | None = None,
) -> list[dict[str, Any]]:
    day = _date_text(asof)
    client = client or EMClient()
    rows: list[dict] = []
    expected_pages: int | None = None
    expected_count: int | None = None
    page = 1
    while expected_pages is None or page <= expected_pages:
        params = {
            "reportName": MARGIN_REPORT,
            "columns": "DIM_DATE,RZYE,RZMRE",
            "filter": f"(DIM_DATE<'{day}')",
            "pageNumber": str(page),
            "pageSize": str(MARGIN_PAGE_SIZE),
            "sortColumns": "DIM_DATE",
            "sortTypes": "-1",
            "source": "WEB",
            "client": "WEB",
        }
        payload = client.get_json(EM_DATACENTER_URL, params=params)
        page_rows, page_count, count = _response_rows(payload, page)
        if expected_pages is None:
            expected_pages = page_count
            expected_count = count
        elif page_count != expected_pages or count != expected_count:
            raise RuntimeError(f"Eastmoney {MARGIN_REPORT} changed count/pages")
        if page < page_count and len(page_rows) != MARGIN_PAGE_SIZE:
            raise RuntimeError(
                f"Eastmoney {MARGIN_REPORT} page {page}/{page_count} returned "
                f"{len(page_rows)} rows, expected {MARGIN_PAGE_SIZE}"
            )
        if page == page_count and len(rows) + len(page_rows) != count:
            raise RuntimeError(
                f"Eastmoney {MARGIN_REPORT} final page does not match reported count"
            )
        rows.extend(page_rows)
        if len(_eligible_margin_rows(rows, day)) >= LOOKBACK:
            break
        page += 1
    eligible = _eligible_margin_rows(rows, day)
    if len(eligible) < MIN_OBSERVATIONS:
        raise RuntimeError(
            f"Eastmoney {MARGIN_REPORT} returned only {len(eligible)} pre-{day} observations"
        )
    return eligible[-LOOKBACK:]


def fetch_index_history(symbol: str, asof: str) -> list[dict[str, Any]]:
    day = _date_text(asof)
    start = (dt.date.fromisoformat(day) - dt.timedelta(days=730)).isoformat()
    frame = tencent_raw(symbol, start=start, end=day)
    if not {"date", "close"}.issubset(frame.columns):
        raise RuntimeError(f"Tencent {symbol} history lacks date/close")
    data = frame.loc[:, ["date", "close"]].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    data["close"] = pd.to_numeric(data["close"], errors="coerce")
    data = data.dropna(subset=["date", "close"])
    data = data[(data["date"] <= day) & (data["close"] > 0)]
    data = data.sort_values("date").drop_duplicates("date", keep="last")
    if data.empty or data.iloc[-1]["date"] != day:
        raise RuntimeError(f"Tencent {symbol} has no close for {day}")
    return [
        {"date": row.date, "close": float(row.close)}
        for row in data.itertuples(index=False)
    ]


def percentile_rank(values: list[float] | np.ndarray) -> float:
    data = np.asarray(values, dtype=float)
    data = data[np.isfinite(data)]
    if len(data) < MIN_OBSERVATIONS:
        raise ValueError(f"252-day percentile requires at least {MIN_OBSERVATIONS} values")
    return float(np.mean(data[-LOOKBACK:] <= data[-1]))


def margin_metrics(rows: list[dict[str, Any]], asof: str) -> dict[str, Any]:
    history = _eligible_margin_rows(rows, _date_text(asof))
    if len(history) < MIN_OBSERVATIONS:
        raise ValueError(
            f"margin percentile requires at least {MIN_OBSERVATIONS} observations"
        )
    window = history[-LOOKBACK:]
    current = window[-1]
    pct252 = percentile_rank([row["rzye"] for row in window])
    threshold = 0.80
    return {
        "date": current["date"],
        "rzye_yi": current["rzye"] / 100_000_000,
        "pct252": pct252,
        "threshold": threshold,
        "on": pct252 >= threshold,
    }


def _clean_breadth_history(breadth: dict[str, Any], asof: str) -> list[dict[str, Any]]:
    if breadth.get("schema") != "breadth.v1":
        raise ValueError("breadth snapshot schema is not breadth.v1")
    history = breadth.get("risk_history")
    if not isinstance(history, list):
        raise ValueError("breadth snapshot has no risk_history")
    cleaned = []
    for row in history:
        if not isinstance(row, dict) or row.get("date") is None:
            continue
        day = _date_text(row["date"])
        if day <= asof:
            cleaned.append({**row, "date": day})
    cleaned.sort(key=lambda row: row["date"])
    deduped = {row["date"]: row for row in cleaned}
    result = [deduped[day] for day in sorted(deduped)]
    if not result or result[-1]["date"] != asof:
        raise ValueError(f"breadth history does not include {asof}")
    return result


def concentration_metrics(
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(history) < 5:
        raise ValueError("concentration requires five days of breadth history")
    current = history[-1]
    last_five = [_number(row.get("top100_share"), "top100_share") for row in history[-5:]]
    top50 = _number(current.get("top50_share"), "top50_share")
    top100 = _number(current.get("top100_share"), "top100_share")
    top100_5d = float(np.mean(last_five))
    threshold = 0.30
    return {
        "top50": top50,
        "top100": top100,
        "top100_5d": top100_5d,
        "threshold": threshold,
        "on": top100_5d >= threshold,
    }


def breadth_drop_metrics(history: list[dict[str, Any]]) -> dict[str, Any]:
    mcl = np.asarray(
        [_number(row.get("MCL"), "MCL") for row in history],
        dtype=float,
    )
    if len(mcl) < GAIN_LOOKBACK:
        raise ValueError(f"breadth drop requires {GAIN_LOOKBACK} MCL observations")
    current = float(mcl[-1])
    max10 = float(np.max(mcl[-10:]))
    std250 = float(np.std(mcl[-GAIN_LOOKBACK:], ddof=0))
    threshold = max10 - 0.5 * std250
    return {
        "on": current < threshold,
        "mcl": current,
        "mcl_max10": max10,
        "std250": std250,
        "threshold": threshold,
        "mcl_pct250": percentile_rank(mcl[-GAIN_LOOKBACK:]),
    }


def risk_level(n_on: int) -> str:
    if n_on == 3:
        return "顶部风险高"
    if n_on == 2:
        return "偏高"
    return "未触发"


def index_metrics(
    code: str,
    name: str,
    rows: list[dict[str, Any]],
    concentration_on: bool,
    margin_on: bool,
    asof: str,
) -> dict[str, Any]:
    day = _date_text(asof)
    cleaned = []
    for row in rows:
        row_day = _date_text(row["date"])
        close = _number(row.get("close"), f"{code} close")
        if row_day <= day and close > 0:
            cleaned.append({"date": row_day, "close": close})
    cleaned.sort(key=lambda row: row["date"])
    deduped = {row["date"]: row for row in cleaned}
    history = [deduped[key] for key in sorted(deduped)]
    if not history or history[-1]["date"] != day:
        raise ValueError(f"{code} has no close for {day}")
    closes = np.asarray([row["close"] for row in history], dtype=float)
    if len(closes) < GAIN_LOOKBACK:
        raise ValueError(f"{code} requires {GAIN_LOOKBACK} closes for 250-day low")
    pct252 = percentile_rank(closes)
    current = float(closes[-1])
    gain_from_250_low = current / float(np.min(closes[-GAIN_LOOKBACK:])) - 1
    position_threshold = 0.80
    gain_threshold = 0.15
    index_on = pct252 >= position_threshold and gain_from_250_low >= gain_threshold
    n_on = int(concentration_on) + int(margin_on) + int(index_on)
    return {
        "code": code,
        "name": name,
        "close": current,
        "pos_pct252": pct252,
        "pos_threshold": position_threshold,
        "gain_from_250_low": gain_from_250_low,
        "gain_threshold": gain_threshold,
        "on": index_on,
        "level": risk_level(n_on),
        "n_on": n_on,
    }


def _load_research_results(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not {
        "episodes",
        "stats",
        "definition",
        "judge",
    }.issubset(data):
        raise ValueError("top_risk_episodes.json is missing research result fields")
    return data


def build_snapshot(
    asof: str,
    breadth: dict[str, Any],
    margin_rows: list[dict[str, Any]],
    index_histories: dict[str, list[dict[str, Any]]],
    episodes_path: Path = DEFAULT_EPISODES,
) -> dict[str, Any]:
    day = _date_text(asof)
    breadth_history = _clean_breadth_history(breadth, day)
    concentration = concentration_metrics(breadth_history)
    margin = margin_metrics(margin_rows, day)
    breadth_drop = breadth_drop_metrics(breadth_history)
    indices = [
        index_metrics(
            code,
            name,
            index_histories[code],
            concentration["on"],
            margin["on"],
            day,
        )
        for code, name in INDEXES
    ]
    research = _load_research_results(episodes_path)
    return {
        "schema": "top_risk.v1",
        "asof": day,
        "source": SOURCE,
        "note": NOTE,
        "conc": concentration,
        "margin": margin,
        "breadth_drop": breadth_drop,
        "indices": indices,
        "definition": research["definition"],
        "judge": research["judge"],
        "episodes": research["episodes"],
        "stats": research["stats"],
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


def run_pipeline(
    out_path: Path,
    *,
    asof: str,
    breadth_path: Path = DEFAULT_BREADTH,
    episodes_path: Path = DEFAULT_EPISODES,
    previous_path: Path | None = None,
    client: EMClient | None = None,
) -> dict[str, Any]:
    out_path = Path(out_path)
    try:
        breadth = json.loads(Path(breadth_path).read_text(encoding="utf-8"))
        margin_rows = fetch_margin_history(asof, client)
        index_histories = {
            code: fetch_index_history(code, asof) for code, _ in INDEXES
        }
        payload = build_snapshot(
            asof,
            breadth,
            margin_rows,
            index_histories,
            episodes_path,
        )
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
    parser = argparse.ArgumentParser(description="Build the daily top-risk snapshot")
    parser.add_argument("--date", help="snapshot date; defaults to trading_date helper")
    parser.add_argument("--breadth", type=Path, default=DEFAULT_BREADTH)
    parser.add_argument("--episodes", type=Path, default=DEFAULT_EPISODES)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if args.date:
        asof = _date_text(args.date)
    else:
        from research.data.trading_date import latest_closed_trading_day

        asof = latest_closed_trading_day()
    payload = run_pipeline(
        args.out,
        asof=asof,
        breadth_path=args.breadth,
        episodes_path=args.episodes,
        previous_path=args.previous,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
