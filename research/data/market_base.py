from __future__ import annotations

import argparse
import json
import math
import random
import re
import tempfile
import time
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

from .margin import CACHE as MARGIN_CACHE
from .margin import SZSE_RENAME, fetch_sse, fetch_szse, load_margin

EM_BOARD_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
EM_BOARD_FALLBACK_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EM_HISTORY_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
EM_POOL_URL = "https://push2ex.eastmoney.com"
HKEX_URL = "https://www.hkex.com.hk/chi/csm/DailyStat/data_tab_daily_{date}c.js"
CSINDEX_URL = (
    "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/"
    "autofile/indicator/{code}indicator.xls"
)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"
BOARD_FS = {"industry": "m:90+t:2", "concept": "m:90+t:3", "region": "m:90+t:1"}
PERIODS = {
    "today": {
        "fid": "f62",
        "change": "f3",
        "main": "f62",
        "main_pct": "f184",
        "leader": "f204",
        "fields": ("f12", "f14", "f3", "f62", "f184", "f204", "f66", "f72", "f78", "f84"),
    },
    "5d": {
        "fid": "f164",
        "change": "f109",
        "main": "f164",
        "main_pct": "f165",
        "leader": "f257",
        "fields": ("f12", "f14", "f109", "f164", "f165", "f257"),
    },
    "10d": {
        "fid": "f174",
        "change": "f160",
        "main": "f174",
        "main_pct": "f175",
        "fields": ("f12", "f14", "f160", "f174", "f175"),
    },
}
BOARD_COLUMNS = (
    "code",
    "name",
    "pct_chg",
    "main_net",
    "main_pct",
    "super_net",
    "large_net",
    "medium_net",
    "small_net",
    "pct_5d",
    "main_net_5d",
    "main_pct_5d",
    "pct_10d",
    "main_net_10d",
    "main_pct_10d",
)
INDEX_CODES = ("000300", "000905", "000016", "000852")
INDEX_FIELDS = {
    "市盈率1（总股本）P/E1": "pe1",
    "市盈率2（计算用股本）P/E2": "pe2",
    "股息率1（总股本）D/P1": "dy1",
    "股息率2（计算用股本）D/P2": "dy2",
}
LIMIT_POOLS = (
    ("zt", "getTopicZTPool", "fbt:asc"),
    ("zb", "getTopicZBPool", "fbt:asc"),
    ("dt", "getTopicDTPool", "fund:asc"),
)
LIMIT_UT = "7eea3edcaed734bea9cbfc24409ed989"
DESCRIPTIVE_NOTE = "只作市场背景，不进入 LPPLS 报警或任何模型。"


class EMBlocked(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


def _number(value):
    if value is None or str(value).strip() in ("", "-", "--", "None", "nan"):
        return None
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"非数值字段: {value!r}") from exc
    return number if pd.notna(number) else None


def _int(value, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"字段 {field} 不是整数: {value!r}") from exc


class EMClient:
    def __init__(self, session=None, sleep=time.sleep, jitter=random.uniform):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": UA})
        self.sleep = sleep
        self.jitter = jitter
        self.last_call = None
        self.last_url = ""

    def _request_once(self, url, params=None, headers=None):
        if self.last_call is not None:
            elapsed = time.monotonic() - self.last_call
            delay = max(0.0, 0.6 - elapsed) + self.jitter(0.0, 0.4)
            self.sleep(delay)
        try:
            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=15,
                allow_redirects=True,
            )
        finally:
            self.last_call = time.monotonic()
        if response.status_code == 403:
            raise EMBlocked(f"Eastmoney returned HTTP 403 for {url}")
        response.raise_for_status()
        self.last_url = response.url
        return response

    def get(self, url, params=None, headers=None, fallback_url=None):
        retry_url = fallback_url or url
        try:
            return self._request_once(url, params, headers)
        except EMBlocked:
            raise
        except Exception as first:
            self.sleep(3.0)
            try:
                return self._request_once(retry_url, params, headers)
            except EMBlocked:
                raise
            except Exception as second:
                raise RuntimeError(
                    f"Eastmoney request failed after one retry: {type(first).__name__}; "
                    f"{type(second).__name__}: {second}"
                ) from second

    def get_json(self, url, params=None, headers=None, fallback_url=None):
        response = self.get(url, params, headers, fallback_url)
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Eastmoney response is not a JSON object")
        return payload

    @property
    def url_host(self):
        return urlparse(self.last_url).hostname or "unknown"


def _parse_board_page(payload: dict, period: str) -> tuple[list[dict], int]:
    if period not in PERIODS:
        raise ValueError(f"unknown board-flow period: {period}")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("diff"), list):
        raise RuntimeError("Eastmoney board response lacks data.diff")
    if "total" not in data:
        raise RuntimeError("Eastmoney board response lacks data.total")
    total = _int(data["total"], "data.total")
    fields = PERIODS[period]["fields"]
    rows = []
    for item in data["diff"]:
        if not isinstance(item, dict):
            raise RuntimeError("Eastmoney board row is not an object")
        missing = set(fields) - set(item)
        if missing:
            raise RuntimeError("Eastmoney board fields missing: " + ", ".join(sorted(missing)))
        row = {"code": str(item["f12"]), "name": str(item["f14"])}
        if period == "today":
            row.update(
                pct_chg=_number(item["f3"]),
                main_net=_number(item["f62"]),
                main_pct=_number(item["f184"]),
                super_net=_number(item["f66"]),
                large_net=_number(item["f72"]),
                medium_net=_number(item["f78"]),
                small_net=_number(item["f84"]),
            )
        elif period == "5d":
            row.update(
                pct_5d=_number(item["f109"]),
                main_net_5d=_number(item["f164"]),
                main_pct_5d=_number(item["f165"]),
            )
        else:
            row.update(
                pct_10d=_number(item["f160"]),
                main_net_10d=_number(item["f174"]),
                main_pct_10d=_number(item["f175"]),
            )
        rows.append(row)
    return rows, total


def _fetch_board_period(kind: str, period: str, client: EMClient) -> list[dict]:
    params = {
        "pz": "200",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": PERIODS[period]["fid"],
        "fs": BOARD_FS[kind],
        "fields": ",".join(PERIODS[period]["fields"]),
    }
    rows = []
    expected_total = None
    page = 1
    while True:
        payload = client.get_json(
            EM_BOARD_URL,
            {**params, "pn": str(page)},
            fallback_url=EM_BOARD_FALLBACK_URL,
        )
        page_rows, total = _parse_board_page(payload, period)
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise RuntimeError(f"Eastmoney board total changed during pagination: {total}")
        rows.extend(page_rows)
        if len(rows) >= expected_total:
            break
        if not page_rows:
            raise RuntimeError("Eastmoney board pagination ended before data.total")
        page += 1
    if len(rows) != expected_total:
        raise RuntimeError(f"Eastmoney board returned {len(rows)} rows; expected {expected_total}")
    codes = [row["code"] for row in rows]
    if len(codes) != len(set(codes)):
        raise RuntimeError("Eastmoney board response contains duplicate codes")
    return rows


def board_flow_snapshot(kind: str, client: EMClient | None = None) -> pd.DataFrame:
    if kind not in BOARD_FS:
        raise ValueError(f"kind must be one of {tuple(BOARD_FS)}")
    client = client or EMClient()
    merged = {}
    order = []
    for period in ("today", "5d", "10d"):
        for row in _fetch_board_period(kind, period, client):
            code = row["code"]
            if code not in merged:
                merged[code] = {"code": code, "name": row["name"]}
                order.append(code)
            merged[code].update(row)
    frame = pd.DataFrame([merged[code] for code in order], columns=BOARD_COLUMNS)
    frame = frame.astype(object).where(pd.notna(frame), None)
    frame.attrs["url_host"] = client.url_host
    return frame


def _parse_board_history(payload: dict) -> pd.DataFrame:
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("klines"), list):
        raise RuntimeError("Eastmoney board-history response lacks data.klines")
    rows = []
    for line in data["klines"]:
        parts = str(line).split(",")
        if len(parts) != 7:
            raise RuntimeError(f"Eastmoney board-history row has {len(parts)} fields; expected 7")
        try:
            stamp = pd.Timestamp(parts[0])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"invalid board-history date: {parts[0]!r}") from exc
        rows.append(
            {
                "date": stamp.date().isoformat(),
                "main_net": _number(parts[1]),
                "small_net": _number(parts[2]),
                "medium_net": _number(parts[3]),
                "large_net": _number(parts[4]),
                "super_net": _number(parts[5]),
            }
        )
    frame = pd.DataFrame(
        rows, columns=("date", "main_net", "small_net", "medium_net", "large_net", "super_net")
    )
    if frame["date"].duplicated().any():
        raise RuntimeError("Eastmoney board-history response contains duplicate dates")
    return frame.sort_values("date").reset_index(drop=True)


def _verify_history_order(snapshot: dict, history: pd.DataFrame, asof: str) -> list[str]:
    if history.empty or history.iloc[-1]["date"] != asof:
        raise RuntimeError("board-history latest row does not match the snapshot as-of date")
    latest = history.iloc[-1]
    pairs = (
        ("main_net", "main_net"),
        ("small_net", "small_net"),
        ("medium_net", "medium_net"),
        ("large_net", "large_net"),
        ("super_net", "super_net"),
    )
    matched = []
    for field, snapshot_field in pairs:
        historic = _number(latest[field])
        current = _number(snapshot[snapshot_field])
        if historic is None or current is None:
            continue
        if not math.isclose(historic, current, rel_tol=1e-5, abs_tol=1.0):
            raise RuntimeError(
                f"board-history {field}={historic} does not match snapshot "
                f"{snapshot_field}={current} on {asof}"
            )
        matched.append(field)
    if len(matched) != 5:
        raise RuntimeError(
            f"board-history column order verification matched {len(matched)}/5 flow fields"
        )
    return matched


def board_flow_history(bk: str, client: EMClient | None = None) -> pd.DataFrame:
    if not re.fullmatch(r"BK[0-9A-Za-z]+", str(bk)):
        raise ValueError(f"invalid Eastmoney board code: {bk!r}")
    client = client or EMClient()
    payload = client.get_json(
        EM_HISTORY_URL,
        {
            "secid": f"90.{bk}",
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
            "lmt": "0",
            "klt": "101",
        },
    )
    frame = _parse_board_history(payload)
    frame.attrs["url_host"] = client.url_host
    frame.attrs["board_code"] = bk
    return frame


def _parse_pool(payload: dict, date_value: str) -> list[dict]:
    if "data" not in payload:
        raise RuntimeError("Eastmoney limit-pool response lacks data")
    data = payload["data"]
    if data is None:
        raise RuntimeError(f"Eastmoney limit-pool data=null for {date_value}")
    if not isinstance(data, dict) or not isinstance(data.get("pool"), list):
        raise RuntimeError("Eastmoney limit-pool response lacks data.pool")
    if any(not isinstance(row, dict) for row in data["pool"]):
        raise RuntimeError("Eastmoney limit-pool row is not an object")
    return data["pool"]


def _fmt_limit_time(value) -> str | None:
    if value is None:
        return None
    digits = str(value).zfill(6)
    if not digits.isdigit() or len(digits) != 6:
        raise RuntimeError(f"invalid limit time: {value!r}")
    return f"{digits[:2]}:{digits[2:4]}:{digits[4:]}"


def _limit_display_row(row: dict, pool: str) -> dict:
    required = {"c", "n"}
    time_field = "lbt" if pool == "dt" else "fbt"
    required.add(time_field)
    if pool == "zt":
        required.add("lbc")
    missing = required - set(row)
    if missing:
        raise RuntimeError("Eastmoney limit-pool fields missing: " + ", ".join(sorted(missing)))
    if pool == "zt":
        streak = _int(row["lbc"], "lbc")
    elif pool == "dt":
        streak = _int(row["days"], "days") if row.get("days") is not None else None
    else:
        streak = None
        zttj = row.get("zttj")
        if isinstance(zttj, dict) and zttj.get("ct") is not None:
            streak = _int(zttj["ct"], "zttj.ct")
    return {
        "code": str(row["c"]),
        "name": str(row["n"]),
        "streak": streak,
        "limit_time": _fmt_limit_time(row[time_field]),
    }


def limit_pools(date_value: str, client: EMClient | None = None) -> dict:
    compact_date = date_value.replace("-", "")
    if not re.fullmatch(r"\d{8}", compact_date):
        raise ValueError(f"date must be YYYY-MM-DD or YYYYMMDD: {date_value!r}")
    client = client or EMClient()
    pools = {}
    for kind, endpoint, sort in LIMIT_POOLS:
        url = f"{EM_POOL_URL}/{endpoint}"
        params = {
            "ut": LIMIT_UT,
            "dpt": "wz.ztzt",
            "Pageindex": 0,
            "pagesize": 10000,
            "sort": sort,
            "date": compact_date,
        }
        payload = client.get_json(
            url, params, headers={"Referer": "https://quote.eastmoney.com/"}
        )
        pools[kind] = _parse_pool(payload, compact_date)
    zt, zb, dt = (pools[k] for k in ("zt", "zb", "dt"))
    streak_dist: dict[str, int] = {}
    for row in zt:
        streak = _int(row["lbc"], "lbc")
        key = str(streak)
        streak_dist[key] = streak_dist.get(key, 0) + 1
    total = len(zt) + len(zb)
    return {
        "date": compact_date,
        "zt": len(zt),
        "zb": len(zb),
        "dt": len(dt),
        "break_rate": len(zb) / total if total else None,
        "max_streak": max((int(row["lbc"]) for row in zt), default=0),
        "streak_dist": dict(sorted(streak_dist.items(), key=lambda item: int(item[0]))),
        "top20": {
            kind: [_limit_display_row(row, kind) for row in pool[:20]]
            for kind, pool in pools.items()
        },
    }


def _json_from_js(text: str) -> dict | list:
    starts = [(text.find(mark), mark) for mark in ("{", "[") if text.find(mark) >= 0]
    if not starts:
        raise RuntimeError("HKEX response does not contain a JSON object")
    start, opening = min(starts)
    closing = "}" if opening == "{" else "]"
    end = text.rfind(closing)
    if end <= start:
        raise RuntimeError("HKEX response does not contain a complete JSON value")
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("HKEX JavaScript payload is not valid JSON") from exc
    if not isinstance(value, (dict, list)):
        raise RuntimeError("HKEX JavaScript payload is not an object or array")
    return value


def _norm_label(value) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value).lower())


def _hkex_pairs(payload: dict) -> list[tuple[str, str, object]]:
    pairs = []

    def walk(node, path=()):
        if isinstance(node, dict):
            label = node.get("label", node.get("name", node.get("title")))
            value = node.get("value", node.get("amount"))
            if label is not None and value is not None:
                pairs.append(("/".join((*path, str(label))), str(label), value))
            for key, child in node.items():
                if key not in {"label", "name", "title", "value", "amount"}:
                    if isinstance(child, (str, int, float)) and not isinstance(child, bool):
                        pairs.append(("/".join(path), str(key), child))
                    walk(child, (*path, str(key)))
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    pairs.append(("/".join(path), str(item[0]), item[-1]))
                else:
                    walk(item, path)

    walk(payload)
    return pairs


def _parse_northbound(text: str) -> dict:
    payload = _json_from_js(text)
    fields = {}
    if isinstance(payload, list):
        for market in payload:
            name = str(market.get("market", "")) if isinstance(market, dict) else ""
            market_norm = _norm_label(name)
            if "northbound" not in market_norm or "southbound" in market_norm:
                continue
            exchange = "sse" if "sse" in market_norm else "szse" if "szse" in market_norm else None
            if exchange is None:
                continue
            for content in market.get("content", []):
                table = content.get("table", {}) if isinstance(content, dict) else {}
                if table.get("classname") != "tradingTable":
                    continue
                schema = table.get("schema")
                rows = table.get("tr")
                if not isinstance(schema, list) or not schema or not isinstance(schema[0], list):
                    raise RuntimeError("HKEX Northbound trading table lacks schema")
                if not isinstance(rows, list) or len(rows) != len(schema[0]):
                    raise RuntimeError("HKEX Northbound trading table schema/row count mismatch")
                for label, row in zip(schema[0], rows, strict=True):
                    metric = _northbound_metric(label)
                    if metric is None:
                        continue
                    cells = row.get("td") if isinstance(row, dict) else None
                    if not isinstance(cells, list) or len(cells) != 1:
                        raise RuntimeError(f"HKEX Northbound row has unexpected shape for {label}")
                    cell = cells[0]
                    if not isinstance(cell, list) or not cell:
                        raise RuntimeError(f"HKEX Northbound row has no value for {label}")
                    raw_value = cell[0]
                    fields[f"{exchange}_{metric}"] = (
                        _int(str(raw_value).replace(",", ""), metric)
                        if metric == "trades"
                        else _number(raw_value)
                    )
    else:
        for path, label, value in _hkex_pairs(payload):
            combined = _norm_label(f"{path}/{label}")
            if any(token in combined for token in ("southbound", "南向", "港股通")):
                continue
            exchange = None
            if any(token in combined for token in ("shanghai", "sse", "沪股通")):
                exchange = "sse"
            elif any(token in combined for token in ("shenzhen", "szse", "深股通")):
                exchange = "szse"
            metric = _northbound_metric(label)
            if exchange and metric:
                fields[f"{exchange}_{metric}"] = (
                    _int(str(value).replace(",", ""), metric)
                    if metric == "trades"
                    else _number(value)
                )

    required = {
        "sse_turnover",
        "szse_turnover",
        "sse_trades",
        "szse_trades",
        "sse_etf_turnover",
        "szse_etf_turnover",
    }
    missing = required - set(fields)
    if missing:
        raise RuntimeError(
            "HKEX response lacks expected Northbound turnover/trade fields: "
            + ", ".join(sorted(missing))
        )
    return {
        "sse_nb_turnover": fields["sse_turnover"],
        "szse_nb_turnover": fields["szse_turnover"],
        "sse_nb_trades": fields["sse_trades"],
        "szse_nb_trades": fields["szse_trades"],
        "sse_nb_etf_turnover": fields["sse_etf_turnover"],
        "szse_nb_etf_turnover": fields["szse_etf_turnover"],
    }


def _northbound_metric(label: str) -> str | None:
    label_norm = _norm_label(label)
    if "etfturnover" in label_norm or "etf成交额" in label_norm:
        return "etf_turnover"
    if "tradecount" in label_norm or "numberoftrades" in label_norm or "成交笔数" in label_norm:
        return "trades"
    if "totalturnover" in label_norm or "总成交额" in label_norm:
        return "turnover"
    return None


def hkex_northbound(date_value: str, session=None) -> dict | None:
    compact_date = date_value.replace("-", "")
    if not re.fullmatch(r"\d{8}", compact_date):
        raise ValueError(f"date must be YYYY-MM-DD or YYYYMMDD: {date_value!r}")
    url = HKEX_URL.format(date=compact_date)
    response = (session or requests.Session()).get(
        url, headers={"User-Agent": UA}, timeout=15, allow_redirects=True
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return _parse_northbound(response.text)


def _parse_index_valuation(frame: pd.DataFrame, code: str) -> dict:
    frame = frame.copy()
    frame.columns = [re.sub(r"\s+", "", str(col)) for col in frame.columns]
    required = {"日期Date", "指数代码IndexCode", *INDEX_FIELDS}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError("CSIndex valuation columns missing: " + ", ".join(sorted(missing)))
    rows = []
    for row in frame.to_dict("records"):
        code_value = str(row["指数代码IndexCode"]).strip()
        if code_value.endswith(".0"):
            code_value = code_value[:-2]
        actual_code = code_value.zfill(6)
        if actual_code != code:
            raise RuntimeError(f"CSIndex returned code {actual_code}, expected {code}")
        raw_date = row["日期Date"]
        if isinstance(raw_date, (int, float)) and not pd.isna(raw_date):
            stamp = pd.to_datetime(raw_date, unit="D", origin="1899-12-30")
        else:
            stamp = pd.to_datetime(raw_date, errors="raise")
        rows.append(
            {
                "date": stamp.date().isoformat(),
                "pe1": _number(row["市盈率1（总股本）P/E1"]),
                "pe2": _number(row["市盈率2（计算用股本）P/E2"]),
                "dy1": _number(row["股息率1（总股本）D/P1"]),
                "dy2": _number(row["股息率2（计算用股本）D/P2"]),
            }
        )
    if not rows:
        raise RuntimeError("CSIndex valuation file is empty")
    values = pd.DataFrame(rows).sort_values("date")
    if values["date"].duplicated().any():
        raise RuntimeError("CSIndex valuation file has duplicate dates")
    latest = values.iloc[-1]
    pe_pct_10y = None
    if latest["pe1"] is not None and pd.notna(latest["pe1"]):
        cutoff = pd.Timestamp(latest["date"]) - pd.DateOffset(years=10)
        history = values.loc[
            (pd.to_datetime(values["date"]) >= cutoff) & values["pe1"].notna(), "pe1"
        ].astype(float)
        if len(history) > 1 and pd.to_datetime(values["date"]).min() <= cutoff:
            pe_pct_10y = float((history <= float(latest["pe1"])).mean())
    return {
        "date": latest["date"],
        "pe1": latest["pe1"],
        "pe2": latest["pe2"],
        "dy1": latest["dy1"],
        "dy2": latest["dy2"],
        "pe1_pct_10y": pe_pct_10y,
        "history_rows": len(values),
    }


def csindex_valuation(code: str, session=None) -> dict:
    if code not in INDEX_CODES:
        raise ValueError(f"unsupported CSIndex code: {code}")
    url = CSINDEX_URL.format(code=code)
    response = (session or requests.Session()).get(
        url, headers={"User-Agent": UA}, timeout=(10, 40)
    )
    response.raise_for_status()
    try:
        frame = pd.read_excel(BytesIO(response.content), dtype=str)
    except (ImportError, ValueError, OSError) as exc:
        raise RuntimeError("CSIndex did not return a parseable valuation workbook") from exc
    return _parse_index_valuation(frame, code)


def _cached_margin_frame(cache: Path) -> pd.DataFrame:
    required = (cache / "sse_margin.parquet", cache / "szse_margin.parquet")
    if not all(path.exists() for path in required):
        return pd.DataFrame()
    return load_margin(cache)


def _merge_margin_frames(base: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    if base.empty:
        merged = fresh.copy()
    elif fresh.empty:
        merged = base.copy()
    else:
        base = base.copy()
        fresh = fresh.copy()
        base["date"] = pd.to_datetime(base["date"]).dt.normalize()
        fresh["date"] = pd.to_datetime(fresh["date"]).dt.normalize()
        dates = pd.DatetimeIndex(sorted(set(base["date"]) | set(fresh["date"])))
        merged = base.set_index("date").reindex(dates)
        merged.update(fresh.set_index("date").reindex(dates))
        merged.index.name = "date"
        merged = merged.reset_index()
    if not merged.empty:
        merged["date"] = pd.to_datetime(merged["date"]).dt.normalize()
        merged = merged.sort_values("date").drop_duplicates("date", keep="last")
        merged["avail_date"] = merged["date"].shift(-1)
        merged = merged.reset_index(drop=True)
    return merged


def _refresh_margin_frame(asof: str, cache: Path) -> tuple[pd.DataFrame, str | None, pd.DatetimeIndex]:
    cache = Path(cache)
    try:
        base = _cached_margin_frame(cache)
    except Exception as exc:
        base = pd.DataFrame()
        cache_error = _error(exc)
    else:
        cache_error = None

    asof_date = pd.Timestamp(asof).normalize()
    available = 0
    if not base.empty:
        base["avail_date"] = pd.to_datetime(base["avail_date"], errors="coerce")
        available = int((base["avail_date"].notna() & (base["avail_date"] <= asof_date)).sum())
    lookback_days = 60 if base.empty or available < 21 else 30
    start_date = asof_date - pd.Timedelta(days=lookback_days)
    calendar = pd.DatetimeIndex([])
    try:
        recent_sse = fetch_sse(start_date.strftime("%Y%m%d"), asof_date.strftime("%Y%m%d"))
        if recent_sse.empty or "date" not in recent_sse:
            raise RuntimeError(
                f"SSE margin fetcher returned no rows from {start_date.date()} to {asof_date.date()}"
            )
        recent_sse["date"] = pd.to_datetime(recent_sse["date"]).dt.normalize()
        recent_sse = recent_sse.loc[
            (recent_sse["date"] >= start_date) & (recent_sse["date"] <= asof_date)
        ].sort_values("date").drop_duplicates("date", keep="last")
        if recent_sse.empty:
            raise RuntimeError(
                f"SSE margin fetcher returned no rows from {start_date.date()} to {asof_date.date()}"
            )
        calendar = pd.DatetimeIndex(recent_sse["date"])
        errors = []
        if cache_error:
            errors.append(f"cached margin read failed: {cache_error}")

        with tempfile.TemporaryDirectory(prefix="market-margin-") as directory:
            temp_cache = Path(directory)
            recent_sse.to_parquet(temp_cache / "sse_margin.parquet", index=False)
            szse_path = temp_cache / "szse_margin.parquet"
            try:
                fetch_szse(calendar, szse_path, pause=0.8)
            except Exception as exc:
                errors.append(f"SZSE margin fetcher failed: {_error(exc)}")

            if not szse_path.exists():
                pd.DataFrame(columns=["date", *SZSE_RENAME]).to_parquet(szse_path, index=False)
                errors.append("SZSE margin fetcher returned no rows")
            szse = pd.read_parquet(szse_path)
            latest_sse_date = calendar.max()
            if "date" not in szse or latest_sse_date not in set(
                pd.to_datetime(szse.get("date", pd.Series(dtype="datetime64[ns]")), errors="coerce")
                .dt.normalize()
                .dropna()
            ):
                errors.append(
                    f"SZSE margin fetcher returned no row for latest SSE date {latest_sse_date.date()}"
                )
            failed_path = szse_path.with_suffix(".failed.json")
            if failed_path.exists():
                failed = json.loads(failed_path.read_text(encoding="utf-8"))
                if failed:
                    details = ", ".join(f"{row[0]}:{row[1]}" for row in failed)
                    errors.append(f"SZSE margin fetcher failed dates: {details}")
            fresh = load_margin(temp_cache)
            latest = fresh.loc[pd.to_datetime(fresh["date"]).dt.normalize() == latest_sse_date]
            required_balances = ("fin_balance_all", "total_balance_all")
            if latest.empty or any(
                _number(latest.iloc[-1][field]) is None for field in required_balances
            ):
                errors.append(
                    f"margin refresh lacks required SSE/SZSE balances for {latest_sse_date.date()}"
                )

        merged = _merge_margin_frames(base, fresh)
        return merged, "; ".join(errors) or None, calendar
    except Exception as exc:
        return base, "; ".join(part for part in (cache_error, _error(exc)) if part), calendar


def _margin_snapshot(asof: str, cache: Path = MARGIN_CACHE) -> dict:
    frame, refresh_error, trading_dates = _refresh_margin_frame(asof, cache)
    if frame.empty:
        reason = f"margin data unavailable after refresh: {refresh_error}" if refresh_error else "margin cache contains no rows"
        raise RuntimeError(reason)
    frame = frame.sort_values("date").reset_index(drop=True)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["avail_date"] = pd.to_datetime(frame["avail_date"])
    asof_date = pd.Timestamp(asof).normalize()
    eligible = frame.loc[
        frame["avail_date"].notna()
        & (frame["avail_date"] <= asof_date)
        & (frame["date"] <= asof_date)
    ]
    if eligible.empty:
        raise RuntimeError(f"margin cache has no T+1-available rows as of {asof}")
    if len(eligible) < 21:
        coverage_error = (
            f"margin has {len(eligible)} T+1-available rows; "
            "at least 21 are required for a 20-trading-day change"
        )
        refresh_error = "; ".join(part for part in (refresh_error, coverage_error) if part)
    latest = eligible.iloc[-1]
    prior = eligible.iloc[-21] if len(eligible) >= 21 else None
    fields = ("fin_balance_all", "total_balance_all")
    result = {
        "date": latest["date"].date().isoformat(),
        "latest_date": latest["date"].date().isoformat(),
        "available_date": latest["avail_date"].date().isoformat(),
        "rows_available": len(eligible),
    }
    for field in ("fin_balance_sse", "fin_balance_szse"):
        result[field] = _number(latest[field])
    calendar = trading_dates
    if len(calendar) == 0:
        calendar = pd.DatetimeIndex(frame["date"].dropna().unique())
    if len(calendar) == 0 or (
        latest["avail_date"] < asof_date
        and not ((calendar > latest["avail_date"]) & (calendar <= asof_date)).any()
    ):
        calendar = pd.bdate_range(latest["avail_date"] + pd.Timedelta(days=1), asof_date)
    trading_days_stale = int(((calendar > latest["avail_date"]) & (calendar <= asof_date)).sum())
    result["stale"] = trading_days_stale > 5
    result["trading_days_stale"] = trading_days_stale
    if refresh_error:
        result["_refresh_error"] = refresh_error
    for field in fields:
        value = _number(latest[field])
        result[field] = value
        prior_value = _number(prior[field]) if prior is not None else None
        result[f"{field}_change_20d"] = value - prior_value if value is not None and prior_value is not None else None
        result[f"{field}_change_20d_pct"] = (
            (value / prior_value - 1) if value is not None and prior_value not in (None, 0) else None
        )
    return result


def _source_meta(url_host: str, ok: bool, error: str | None = None) -> dict:
    result = {"url_host": url_host, "fetched_at": _now(), "ok": ok}
    if error:
        result["error"] = error
    return result


def _error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def fetch_market(asof: str, em_client: EMClient | None = None, http_session=None) -> dict:
    em = em_client or EMClient()
    session = http_session or requests.Session()
    sources = {}
    board_flow = {
        "evidence": "descriptive",
        "note": "东财板块资金流为订单规模分类估算，非交易所官方数据；" + DESCRIPTIVE_NOTE,
        **{kind: [] for kind in BOARD_FS},
    }
    board_frames = []
    for kind in BOARD_FS:
        host = "push2delay.eastmoney.com"
        try:
            frame = board_flow_snapshot(kind, em)
            board_flow[kind] = frame.to_dict("records")
            board_frames.append(frame)
            sources[f"board_flow_{kind}"] = _source_meta(
                frame.attrs.get("url_host", host), True
            )
        except Exception as exc:
            sources[f"board_flow_{kind}"] = _source_meta(host, False, _error(exc))

    history_sample = None
    try:
        industry = board_flow["industry"]
        if not industry:
            raise RuntimeError("industry board snapshot unavailable; cannot verify history fields")
        snapshot = industry[0]
        bk = snapshot["code"]
        history = board_flow_history(bk, em)
        verified_fields = _verify_history_order(snapshot, history, asof)
        history_sample = {
            "code": bk,
            "rows": history.to_dict("records"),
            "column_order_verified": True,
            "verified_asof": asof,
            "matched_fields": verified_fields,
        }
        sources["board_flow_history"] = _source_meta(
            history.attrs.get("url_host", "push2his.eastmoney.com"), True
        )
    except Exception as exc:
        sources["board_flow_history"] = _source_meta(
            "push2his.eastmoney.com", False, _error(exc)
        )
    board_flow["history_sample"] = history_sample

    limit_section = {"evidence": "descriptive", "note": DESCRIPTIVE_NOTE}
    try:
        limit_section.update(limit_pools(asof, em))
        sources["limit_pools"] = _source_meta(em.url_host, True)
    except Exception as exc:
        limit_section["data"] = None
        sources["limit_pools"] = _source_meta(
            "push2ex.eastmoney.com", False, _error(exc)
        )

    northbound = {
        "evidence": "descriptive",
        "note": "HKEX 仅列成交额、交易笔数与 ETF 成交额；2024-08 后不提供买卖额或净流入。"
        + DESCRIPTIVE_NOTE,
    }
    try:
        value = hkex_northbound(asof, session)
        northbound["data"] = value
        sources["northbound"] = _source_meta(
            "www.hkex.com.hk", True
        )
    except Exception as exc:
        northbound["data"] = None
        sources["northbound"] = _source_meta("www.hkex.com.hk", False, _error(exc))

    valuation = {
        "evidence": "descriptive",
        "note": "中证官方文件中的 PE1/PE2 与股息率；PE1 分位只用文件自带历史计算。"
        + DESCRIPTIVE_NOTE,
        "indices": {},
    }
    for code in INDEX_CODES:
        try:
            value = csindex_valuation(code, session)
            valuation["indices"][code] = value
            sources[f"index_valuation_{code}"] = _source_meta(
                "oss-ch.csindex.com.cn", True
            )
        except Exception as exc:
            valuation["indices"][code] = None
            sources[f"index_valuation_{code}"] = _source_meta(
                "oss-ch.csindex.com.cn", False, _error(exc)
            )

    margin_section = {
        "evidence": "descriptive",
        "note": "使用上交所与深交所官方两融日报刷新，余额按 T+1 可用日期展示；超过 5 个交易日标记 stale。"
        + DESCRIPTIVE_NOTE,
    }
    try:
        margin_data = _margin_snapshot(asof)
        refresh_error = margin_data.pop("_refresh_error", None)
        margin_section["data"] = margin_data
        errors = []
        if refresh_error:
            errors.append(f"margin refresh failed: {refresh_error}")
        if margin_data["stale"]:
            errors.append(
                "margin stale: latest_date="
                f"{margin_data['latest_date']}, "
                f"{margin_data['trading_days_stale']} trading days since availability"
            )
        balance_sse = margin_data.get("fin_balance_sse")
        balance_szse = margin_data.get("fin_balance_szse")
        if balance_sse is not None and balance_szse is not None:
            ratio = balance_szse / balance_sse if balance_sse > 0 else float("inf")
            if not 0.3 <= ratio <= 3:
                errors.append(f"SZSE/SSE ratio out of range: {ratio:.4f}")
        sources["margin"] = _source_meta("sse.szse.official", not errors, "; ".join(errors) or None)
    except Exception as exc:
        margin_section["data"] = None
        sources["margin"] = _source_meta("sse.szse.official", False, _error(exc))

    return {
        "asof": asof,
        "generated_at": _now(),
        "sources": sources,
        "board_flow": board_flow,
        "limit_pools": limit_section,
        "northbound": northbound,
        "valuation": valuation,
        "margin": margin_section,
        "notes": [DESCRIPTIVE_NOTE],
        "_board_frames": board_frames,
    }


def write_snapshot(
    payload: dict,
    out: Path,
    board_dir: Path = Path("data/market/board_flow"),
) -> tuple[Path, Path, Path | None]:
    out.mkdir(parents=True, exist_ok=True)
    asof = payload["asof"]
    latest_path = out / "market_latest.json"
    dated_path = out / f"market_{asof}.json"
    public_payload = {key: value for key, value in payload.items() if not key.startswith("_")}
    text = json.dumps(public_payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    latest_path.write_text(text, encoding="utf-8")
    dated_path.write_text(text, encoding="utf-8")

    frames = payload.get("_board_frames", [])
    if frames:
        board_frame = pd.concat(frames, ignore_index=True)
    else:
        board_frame = pd.DataFrame(columns=BOARD_COLUMNS)
    board_path = None
    if len(board_frame) > 0:
        board_dir.mkdir(parents=True, exist_ok=True)
        board_path = board_dir / f"{asof}.csv.gz"
        board_frame.to_csv(
            board_path,
            index=False,
            columns=BOARD_COLUMNS,
            compression="gzip",
        )
    return latest_path, dated_path, board_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--out", type=Path, default=Path("web/mock/data/market"))
    args = parser.parse_args(argv)
    pd.Timestamp(args.date)
    payload = fetch_market(args.date)
    latest, dated, board = write_snapshot(payload, args.out)
    public = {key: value for key, value in payload.items() if not key.startswith("_")}
    row_counts = {
        kind: len(payload["board_flow"][kind]) for kind in BOARD_FS
    }
    print(
        json.dumps(
            {
                "latest": str(latest),
                "dated": str(dated),
                "board_csv": str(board) if board is not None else None,
                "board_rows": row_counts,
                "limit_pool_counts": {
                    key: public["limit_pools"].get(key)
                    for key in ("zt", "zb", "dt")
                    if key in public["limit_pools"]
                },
                "sources": public["sources"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
