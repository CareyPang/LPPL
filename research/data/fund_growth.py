from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd
import requests
from scipy.optimize import nnls

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = ROOT / "data" / "cache" / "fund_growth"
DEFAULT_OUT = Path("out/growth/fund_growth_sample.json")
MAX_API_CALLS = 6000
MIN_CALL_INTERVAL = 0.3
RETRIES = 2
QUARTERLY_SOURCE = "天天基金季报持仓；申万一级行业分类"
CURRENT_COMPONENT_SOURCE = "申万一级当前成分股（当前成分近似，非 PIT）"
CNINFO_PIT_SOURCE = "巨潮申银万国行业分类变更（季度末 PIT）"
WEEKLY_ANALYSIS_SOURCE = "申万指数周度分析"
WEEKLY_REALTIME_SOURCE = "申万实时指数周度累积"
PROXY_SOURCE = "中证偏股型基金指数 930950；申万一级行业周线；非负最小二乘回归"
RULE = (
    "普通股票型与偏股混合型基金，剔除指数/ETF/联接并合并份额；"
    "前十重仓股按基金估算净资产加权，公募成长仓位（正式季度值）低于 60%。"
    "周度代理为回归估算，不参与状态判定。"
)

GROWTH_INDEX_NAMES = {
    "801080": "电子",
    "801750": "计算机",
    "801770": "通信",
    "801760": "传媒",
    "801730": "电力设备",
    "801740": "国防军工",
    "801150": "医药生物",
}
NON_GROWTH_INDEX_NAMES = {
    "801120": "食品饮料",
    "801780": "银行",
    "801790": "非银金融",
    "801050": "有色金属",
    "801890": "机械设备",
}
INDEX_NAMES = {**GROWTH_INDEX_NAMES, **NON_GROWTH_INDEX_NAMES}
GROWTH_INDUSTRIES = frozenset(GROWTH_INDEX_NAMES.values())
FUND_TYPES = frozenset({"股票型", "混合型-偏股"})
EXCLUDED_NAME_PARTS = ("指数", "ETF", "联接")
CACHE_COLUMNS = (
    "fund_code",
    "fund_name",
    "nav_est",
    "growth_fraction",
    "industry_weights",
    "unmapped_stocks",
    "mapping_source",
    "mapping_note",
)
INDUSTRY_CACHE_COLUMNS = ("stock_code", "industry", "classification_date")
WEEKLY_CACHE_COLUMNS = ("date", "code", "name", "close")


class CallLimitExceeded(RuntimeError):
    pass


class SwIndexMismatchError(RuntimeError):
    pass


class RateLimitedClient:
    def __init__(
        self,
        module=None,
        *,
        max_calls: int = MAX_API_CALLS,
        min_interval: float = MIN_CALL_INTERVAL,
        retries: int = RETRIES,
        sleep=None,
        clock=None,
    ):
        self.module = module or ak
        self.max_calls = max_calls
        self.min_interval = min_interval
        self.retries = retries
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        self.calls = 0
        self.network_calls = 0
        self.last_call_at: float | None = None
        self.last_network_call_at: float | None = None

    def call(self, method: str, *args, **kwargs):
        function = getattr(self.module, method)
        for attempt in range(self.retries + 1):
            if self.calls >= self.max_calls or self.network_calls >= self.max_calls:
                raise CallLimitExceeded(
                    f"已达到 AkShare 调用上限 {self.max_calls}，停止继续取数。"
                )
            if self.last_call_at is not None:
                elapsed = self.clock() - self.last_call_at
                if elapsed < self.min_interval:
                    self.sleep(self.min_interval - elapsed)
            self.last_call_at = self.clock()
            self.calls += 1
            original_get = requests.get
            original_post = requests.post

            def verified_request(original):
                def request(*request_args, **request_kwargs):
                    if self.network_calls >= self.max_calls:
                        raise CallLimitExceeded(
                            f"已达到 HTTP 调用上限 {self.max_calls}，停止继续取数。"
                        )
                    if self.last_network_call_at is not None:
                        elapsed = self.clock() - self.last_network_call_at
                        if elapsed < self.min_interval:
                            self.sleep(self.min_interval - elapsed)
                    self.last_network_call_at = self.clock()
                    self.network_calls += 1
                    request_kwargs["verify"] = True
                    request_kwargs.setdefault("timeout", (10, 20))
                    return original(*request_args, **request_kwargs)

                return request

            requests.get = verified_request(original_get)
            requests.post = verified_request(original_post)
            try:
                return function(*args, **kwargs)
            except Exception as exc:
                if isinstance(exc, CallLimitExceeded):
                    raise
                if attempt >= self.retries:
                    raise
                self.sleep(max(self.min_interval, 0.5 * (attempt + 1)))
            finally:
                requests.get = original_get
                requests.post = original_post
        raise RuntimeError(f"AkShare 调用失败: {method}")


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _number(value) -> float | None:
    text = _text(value).replace(",", "").replace("%", "")
    if not text or text in {"-", "--", "—", "None", "nan"}:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str:
    for name in candidates:
        if name in frame.columns:
            return name
    raise ValueError(f"缺少字段 {candidates!r}，实际字段：{list(frame.columns)!r}")


def _fund_code(value) -> str:
    text = _text(value)
    if text.endswith(".0"):
        text = text[:-2]
    digits = re.sub(r"\D", "", text)
    return digits.zfill(6) if digits else ""


def _stock_code(value) -> str:
    return _fund_code(value)


def _industry_code(value) -> str:
    return re.sub(r"\D", "", _text(value))


def _quarter_value(value) -> tuple[str, str] | None:
    text = _text(value)
    match = re.search(r"(20\d{2})\D*([1-4一二三四])\s*季度", text)
    if not match:
        match = re.search(r"(20\d{2})\s*[Qq]\s*([1-4])", text)
    if match:
        year = int(match.group(1))
        quarter_text = match.group(2)
        quarter = int({"一": 1, "二": 2, "三": 3, "四": 4}.get(quarter_text, quarter_text))
    else:
        date_match = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", text)
        if not date_match:
            return None
        year, month = int(date_match.group(1)), int(date_match.group(2))
        quarter = (month - 1) // 3 + 1
    month = quarter * 3
    end_day = calendar.monthrange(year, month)[1]
    return f"{year}Q{quarter}", date(year, month, end_day).isoformat()


def _quarter_order(label: str) -> int:
    year, quarter = label.split("Q")
    return int(year) * 4 + int(quarter)


def _latest_quarter(frame: pd.DataFrame, asof: str) -> tuple[str, str] | None:
    quarter_column = _column(frame, ("季度", "报告期", "quarter"))
    cutoff = date.fromisoformat(asof)
    options = []
    for value in frame[quarter_column].tolist():
        parsed = _quarter_value(value)
        if parsed and date.fromisoformat(parsed[1]) <= cutoff:
            options.append(parsed)
    return max(options, key=lambda item: _quarter_order(item[0])) if options else None


def select_fund_universe(frame: pd.DataFrame) -> list[dict]:
    code_column = _column(frame, ("基金代码", "代码", "fund_code"))
    name_column = _column(frame, ("基金简称", "基金名称", "name"))
    type_column = _column(frame, ("基金类型", "类型", "fund_type"))
    selected = []
    seen_names = set()
    for _, row in frame.iterrows():
        fund_type = _text(row[type_column])
        name = _text(row[name_column])
        code = _fund_code(row[code_column])
        if fund_type not in FUND_TYPES or not name or not code:
            continue
        if any(part in name for part in EXCLUDED_NAME_PARTS):
            continue
        base_name = re.sub(r"\s*[（(]LOF[）)]$", "", name, flags=re.IGNORECASE).strip()
        base_name = re.sub(r"[ABCEHIY]$", "", base_name).strip()
        if not base_name or base_name in seen_names:
            continue
        seen_names.add(base_name)
        selected.append({"code": code, "name": name, "base_name": base_name})
    return selected


def verify_sw_index_codes(index_info: pd.DataFrame) -> dict[str, str]:
    code_column = _column(index_info, ("行业代码", "指数代码", "code"))
    name_column = _column(index_info, ("行业名称", "指数名称", "name"))
    actual = {
        _industry_code(row[code_column]): _text(row[name_column])
        for _, row in index_info.iterrows()
    }
    mismatches = {
        code: {"expected": expected, "actual": actual.get(code)}
        for code, expected in INDEX_NAMES.items()
        if actual.get(code) != expected
    }
    if mismatches:
        raise SwIndexMismatchError(f"申万指数代码与已确认名称不一致：{mismatches!r}")
    return actual


def _parse_date(value) -> date | None:
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.date() if isinstance(value, datetime | pd.Timestamp) else value
    text = _text(value)
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return date.fromisoformat(text[:10].replace("/", "-"))
    except ValueError:
        return None


def build_current_component_map(
    components: dict[str, pd.DataFrame], stock_codes: set[str]
) -> dict[str, str]:
    output = {}
    for code, industry in INDEX_NAMES.items():
        frame = components[code]
        if frame.empty:
            raise ValueError(f"申万 {code} {industry} 当前成分为空。")
        stock_column = _column(frame, ("证券代码", "股票代码", "symbol", "code"))
        for value in frame[stock_column].tolist():
            stock = _stock_code(value)
            if not stock:
                continue
            previous = output.get(stock)
            if previous and previous != industry:
                raise ValueError(f"股票 {stock} 同时属于 {previous} 与 {industry}。")
            output[stock] = industry
    for stock in stock_codes:
        output.setdefault(stock, "其他非成长")
    return output


def _cninfo_pit_industry(frame: pd.DataFrame, quarter_end: str) -> tuple[str | None, str | None]:
    if frame.empty:
        return None, None
    standard_column = _column(frame, ("分类标准", "行业分类标准"))
    industry_column = _column(frame, ("行业门类", "行业名称"))
    date_column = _column(frame, ("变更日期", "生效日期", "日期"))
    cutoff = date.fromisoformat(quarter_end)
    candidates = []
    for _, row in frame.iterrows():
        standard = _text(row[standard_column]).replace(" ", "")
        if "申银万国" not in standard and "申万" not in standard:
            continue
        changed = _parse_date(row[date_column])
        industry = _text(row[industry_column])
        if changed and changed <= cutoff and industry:
            candidates.append((changed, industry))
    if not candidates:
        return None, None
    changed, industry = max(candidates, key=lambda item: item[0])
    return industry, changed.isoformat()


def build_pit_industry_map(
    histories: dict[str, pd.DataFrame], quarter_end: str
) -> tuple[dict[str, str | None], dict[str, str | None]]:
    mapping = {}
    dates = {}
    for stock, frame in histories.items():
        industry, changed = _cninfo_pit_industry(frame, quarter_end)
        mapping[stock] = industry
        dates[stock] = changed
    return mapping, dates


def _industry_cache_path(cache_dir: Path, quarter: str) -> Path:
    return Path(cache_dir) / f"industry_{quarter}.parquet"


def _weekly_cache_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / "weekly_sw.parquet"


def _write_parquet_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, suffix=".parquet", delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_pit_industry_cache(path: Path) -> tuple[dict[str, str | None], dict[str, str | None]]:
    if not path.is_file():
        return {}, {}
    frame = pd.read_parquet(path)
    if not set(INDUSTRY_CACHE_COLUMNS).issubset(frame.columns):
        raise ValueError(f"申万 PIT 行业缓存字段不完整：{path}")
    mapping = {
        _text(row["stock_code"]): _text(row["industry"]) or None
        for _, row in frame.iterrows()
    }
    dates = {
        _text(row["stock_code"]): _text(row["classification_date"]) or None
        for _, row in frame.iterrows()
    }
    return mapping, dates


def _save_pit_industry_cache(
    path: Path,
    mapping: dict[str, str | None],
    dates: dict[str, str | None],
) -> None:
    records = [
        {
            "stock_code": stock,
            "industry": mapping.get(stock) or "",
            "classification_date": dates.get(stock) or "",
        }
        for stock in sorted(mapping)
    ]
    _write_parquet_atomic(path, pd.DataFrame(records, columns=INDUSTRY_CACHE_COLUMNS))


def _holding_rows(frame: pd.DataFrame, quarter: str) -> list[dict]:
    quarter_column = _column(frame, ("季度", "报告期", "quarter"))
    code_column = _column(frame, ("股票代码", "证券代码", "代码", "stock_code"))
    name_column = _column(frame, ("股票名称", "证券名称", "name"))
    ratio_column = _column(frame, ("占净值比例", "净值占比", "holding_ratio"))
    value_column = _column(frame, ("持仓市值", "市值", "market_value"))
    rows = []
    for _, row in frame.iterrows():
        parsed = _quarter_value(row[quarter_column])
        if not parsed or parsed[0] != quarter:
            continue
        code = _stock_code(row[code_column])
        ratio = _number(row[ratio_column])
        market_value = _number(row[value_column])
        if code and ratio is not None and ratio > 0:
            rows.append(
                {
                    "code": code,
                    "name": _text(row[name_column]),
                    "ratio": ratio,
                    "market_value": market_value,
                }
            )
    rows.sort(key=lambda item: item["ratio"], reverse=True)
    unique = {}
    for row in rows:
        unique.setdefault(row["code"], row)
    return list(unique.values())[:10]


def build_fund_row(
    fund: dict,
    holdings: pd.DataFrame,
    quarter: str,
    industry_map: dict[str, str | None],
) -> dict | None:
    top = _holding_rows(holdings, quarter)
    if not top:
        return None
    top_total = sum(row["ratio"] for row in top)
    largest = top[0]
    if top_total <= 0 or largest["market_value"] is None:
        return None
    nav_est = largest["market_value"] / (largest["ratio"] / 100)
    if not np.isfinite(nav_est) or nav_est <= 0:
        return None
    industry_ratios: dict[str, float] = {}
    unmapped = []
    for row in top:
        industry = industry_map.get(row["code"])
        if not industry:
            industry = "未映射"
            unmapped.append(row["code"])
        industry_ratios[industry] = industry_ratios.get(industry, 0.0) + row["ratio"]
    industry_weights = {
        name: ratio / top_total for name, ratio in industry_ratios.items()
    }
    growth_fraction = sum(
        weight
        for name, weight in industry_weights.items()
        if name in GROWTH_INDUSTRIES
    )
    return {
        "fund_code": fund["code"],
        "fund_name": fund["name"],
        "nav_est": float(nav_est),
        "growth_fraction": float(growth_fraction),
        "industry_weights": industry_weights,
        "unmapped_stocks": sorted(set(unmapped)),
    }


def aggregate_official(
    rows: list[dict],
    *,
    quarter: str,
    quarter_end: str,
    universe_funds: int,
    mapping_source: str = "",
    mapping_note: str = "",
) -> dict:
    valid = [row for row in rows if row.get("nav_est", 0) > 0]
    if not valid:
        raise ValueError(f"{quarter} 没有可用于规模加权的基金持仓。")
    total_nav = sum(row["nav_est"] for row in valid)
    if total_nav <= 0:
        raise ValueError(f"{quarter} 基金估算净资产合计无效。")
    value = (
        sum(row["nav_est"] * row["growth_fraction"] for row in valid)
        / total_nav
        * 100
    )
    industries: dict[str, float] = {}
    unmapped = set()
    for row in valid:
        for name, weight in row["industry_weights"].items():
            industries[name] = industries.get(name, 0.0) + row["nav_est"] * weight
        unmapped.update(row.get("unmapped_stocks") or [])
    return {
        "quarter": quarter,
        "data_asof": quarter_end,
        "value": round(value, 2),
        "n_funds": len(valid),
        "universe_funds": universe_funds,
        "coverage": round(len(valid) / universe_funds * 100, 1) if universe_funds else 0,
        "industry_weights": {
            name: round(amount / total_nav * 100, 2)
            for name, amount in sorted(
                industries.items(), key=lambda item: item[1], reverse=True
            )
        },
        "unmapped_stock_count": len(unmapped),
        "industry_mapping_source": mapping_source,
        "source": f"{QUARTERLY_SOURCE}；{mapping_source}".strip("；"),
        "note": mapping_note,
    }


def _cache_path(cache_dir: Path, quarter: str) -> Path:
    return Path(cache_dir) / f"{quarter}_v2.parquet"


def _save_quarter_cache(
    path: Path,
    rows: list[dict],
    universe_funds: int,
    mapping_source: str = "",
    mapping_note: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for row in rows:
        records.append(
            {
                **{key: row[key] for key in CACHE_COLUMNS[:4]},
                "industry_weights": json.dumps(
                    row["industry_weights"], ensure_ascii=False, sort_keys=True
                ),
                "unmapped_stocks": json.dumps(row["unmapped_stocks"]),
                "universe_funds": universe_funds,
                "mapping_source": mapping_source,
                "mapping_note": mapping_note,
            }
        )
    frame = pd.DataFrame(records)
    _write_parquet_atomic(path, frame)


def _load_quarter_cache(path: Path) -> tuple[list[dict], int, str, str]:
    frame = pd.read_parquet(path)
    required = {*CACHE_COLUMNS, "universe_funds"}
    if not required.issubset(frame.columns):
        raise ValueError(f"季度缓存字段不完整：{path}")
    if frame.empty:
        raise ValueError(f"季度缓存为空：{path}")
    universe_funds = int(frame["universe_funds"].iloc[0])
    mapping_source = _text(frame["mapping_source"].iloc[0])
    mapping_note = _text(frame["mapping_note"].iloc[0])
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            {
                "fund_code": _text(row["fund_code"]),
                "fund_name": _text(row["fund_name"]),
                "nav_est": float(row["nav_est"]),
                "growth_fraction": float(row["growth_fraction"]),
                "industry_weights": json.loads(row["industry_weights"]),
                "unmapped_stocks": json.loads(row["unmapped_stocks"]),
            }
        )
    return rows, universe_funds, mapping_source, mapping_note


def _reference_holdings(
    client: RateLimitedClient, asof: str
) -> tuple[pd.DataFrame, str, str]:
    years = (date.fromisoformat(asof).year, date.fromisoformat(asof).year - 1)
    last_error = None
    for year in years:
        try:
            frame = client.call(
                "fund_portfolio_hold_em", symbol="005827", date=str(year)
            )
        except Exception as exc:
            last_error = exc
            continue
        quarter = _latest_quarter(frame, asof) if isinstance(frame, pd.DataFrame) else None
        if quarter:
            return frame, quarter[0], quarter[1]
    if last_error:
        raise RuntimeError(f"005827 最新季报季度检查失败：{type(last_error).__name__}: {last_error}")
    raise ValueError("005827 未返回不晚于数据截止日的有效季度字段。")


def _pit_industry_map(
    stock_codes: set[str],
    quarter: str,
    quarter_end: str,
    cache_dir: Path,
    client: RateLimitedClient,
) -> tuple[dict[str, str | None], int]:
    path = _industry_cache_path(cache_dir, quarter)
    mapping, dates = _load_pit_industry_cache(path)
    new_mapping = {}
    new_dates = {}
    errors = 0
    end_date = quarter_end.replace("-", "")
    for stock in sorted(stock_codes - mapping.keys()):
        try:
            history = client.call(
                "stock_industry_change_cninfo",
                symbol=stock,
                start_date="20091227",
                end_date=end_date,
            )
        except CallLimitExceeded:
            raise
        except Exception:
            errors += 1
            continue
        if not isinstance(history, pd.DataFrame) or history.empty:
            errors += 1
            continue
        try:
            industry, changed = _cninfo_pit_industry(history, quarter_end)
        except ValueError:
            errors += 1
            continue
        new_mapping[stock] = industry
        new_dates[stock] = changed
    if new_mapping:
        mapping.update(new_mapping)
        dates.update(new_dates)
        _save_pit_industry_cache(path, mapping, dates)
    return {stock: mapping.get(stock) for stock in stock_codes}, errors


def _resolve_industry_map(
    stock_codes: set[str],
    quarter: str,
    quarter_end: str,
    cache_dir: Path,
    client: RateLimitedClient,
) -> tuple[dict[str, str | None], str, str, int]:
    try:
        components = {
            code: client.call("index_component_sw", symbol=code)
            for code in INDEX_NAMES
        }
        verify_sw_index_codes(
            client.call("index_realtime_sw", symbol="一级行业")
        )
        mapping = build_current_component_map(components, stock_codes)
        return (
            mapping,
            CURRENT_COMPONENT_SOURCE,
            "申万一级指数当前成分近似，非季报时点行业分类。",
            0,
        )
    except (CallLimitExceeded, SwIndexMismatchError):
        raise
    except Exception as component_error:
        mapping, errors = _pit_industry_map(
            stock_codes, quarter, quarter_end, cache_dir, client
        )
        note = (
            f"申万当前成分源不可用（{type(component_error).__name__}）；"
            "改用巨潮申银万国行业分类，取季度末前最近记录。"
        )
        return mapping, CNINFO_PIT_SOURCE, note, errors


def _collect_official(
    asof: str,
    cache_dir: Path,
    client: RateLimitedClient,
    limit: int | None,
) -> dict:
    reference, quarter, quarter_end = _reference_holdings(client, asof)
    path = _cache_path(cache_dir, quarter)
    if limit is None and path.is_file():
        rows, universe_funds, mapping_source, mapping_note = _load_quarter_cache(path)
        cached = aggregate_official(
            rows,
            quarter=quarter,
            quarter_end=quarter_end,
            universe_funds=universe_funds,
            mapping_source=mapping_source,
            mapping_note=mapping_note,
        )
        cached["available_universe_funds"] = universe_funds
        return cached

    universe = select_fund_universe(client.call("fund_name_em"))
    available_universe_funds = len(universe)
    if limit is not None:
        if limit < 1:
            raise ValueError("样本基金数量必须大于 0。")
        universe = universe[:limit]
    universe_count = len(universe)
    if not universe:
        raise ValueError("筛选后没有符合口径的基金样本。")

    holdings_cache = {"005827": reference}
    holdings_by_fund = {}
    stock_codes = set()
    errors = []
    for fund in universe:
        if fund["code"] in holdings_cache:
            holdings = holdings_cache[fund["code"]]
        else:
            try:
                holdings = client.call(
                    "fund_portfolio_hold_em",
                    symbol=fund["code"],
                    date=quarter.split("Q", 1)[0],
                )
            except CallLimitExceeded:
                raise
            except Exception as exc:
                errors.append(f"{fund['code']}: {type(exc).__name__}: {exc}")
                continue
        try:
            top = _holding_rows(holdings, quarter)
        except Exception as exc:
            errors.append(f"{fund['code']}: {type(exc).__name__}: {exc}")
            continue
        if top:
            holdings_by_fund[fund["code"]] = (fund, holdings)
            stock_codes.update(row["code"] for row in top)
    if not stock_codes:
        raise ValueError(f"{quarter} 没有包含前十大持仓的基金。")

    industry_map, mapping_source, mapping_note, industry_errors = _resolve_industry_map(
        stock_codes, quarter, quarter_end, cache_dir, client
    )
    rows = []
    for fund, holdings in holdings_by_fund.values():
        row = build_fund_row(fund, holdings, quarter, industry_map)
        if row:
            rows.append(row)
    if limit is None and rows:
        _save_quarter_cache(
            path, rows, universe_count, mapping_source, mapping_note
        )
    official = aggregate_official(
        rows,
        quarter=quarter,
        quarter_end=quarter_end,
        universe_funds=universe_count,
        mapping_source=mapping_source,
        mapping_note=mapping_note,
    )
    official["available_universe_funds"] = available_universe_funds
    official["failed_fund_count"] = len(errors) + industry_errors
    if errors or industry_errors:
        official["note"] += (
            f" {len(errors)} 只基金取数或持仓字段不可用，"
            f"{industry_errors} 只股票行业分类不可用。"
        )
    return official


def _series_close(frame: pd.DataFrame) -> dict[date, float]:
    date_column = _column(
        frame, ("日期", "发布日期", "交易日期", "date", "trade_date")
    )
    close_column = _column(frame, ("收盘", "收盘指数", "收盘价", "close", "close_price"))
    daily = {}
    for _, row in frame.iterrows():
        day = _parse_date(row[date_column])
        close = _number(row[close_column])
        if day and close is not None and close > 0:
            daily[day] = close
    weekly = {}
    for day, close in sorted(daily.items()):
        monday = day - timedelta(days=day.weekday())
        weekly[monday] = close
    return weekly


def _weekly_returns(closes: dict[date, float], cutoff_monday: date) -> dict[date, float]:
    available = {week: value for week, value in closes.items() if week <= cutoff_monday}
    output = {}
    for week in sorted(available):
        previous_week = week - timedelta(days=7)
        if previous_week not in available:
            continue
        previous = available[previous_week]
        if previous:
            output[week] = available[week] / previous - 1
    return output


def compute_weekly_proxy(
    target_frame: pd.DataFrame,
    industry_frames: dict[str, pd.DataFrame],
    *,
    asof: str,
) -> dict:
    index_info = industry_frames.pop("__index_info__")
    verify_sw_index_codes(index_info)
    target_closes = _series_close(target_frame)
    series = {"930950": target_closes}
    for code in INDEX_NAMES:
        series[code] = _series_close(industry_frames[code])

    asof_date = date.fromisoformat(asof)
    monday = asof_date - timedelta(days=asof_date.weekday())
    if asof_date.weekday() < 4:
        monday -= timedelta(days=7)
    returns = {
        code: _weekly_returns(closes, monday) for code, closes in series.items()
    }
    common = set.intersection(*(set(values) for values in returns.values()))
    weeks = sorted(common)[-52:]
    if len(weeks) < 52:
        raise ValueError(f"周度回归仅有 {len(weeks)} 个完整共同周，至少需要 52 周。")
    if (monday - weeks[-1]).days > 14:
        raise ValueError(
            f"申万周线数据截至 {(weeks[-1] + timedelta(days=4)).isoformat()}，"
            f"晚于最近完整周 {monday.isoformat()} 超过两周。"
        )
    x = np.column_stack(
        [[returns[code][week] for week in weeks] for code in INDEX_NAMES]
    )
    y = np.array([returns["930950"][week] for week in weeks], dtype=float)
    weights, _ = nnls(x, y)
    total = float(weights.sum())
    if total <= 0:
        raise ValueError("周度回归未得到正权重。")
    weights /= total
    fitted = x @ weights
    residual_sum = float(np.square(y - fitted).sum())
    total_sum = float(np.square(y - y.mean()).sum())
    r2 = 1 - residual_sum / total_sum if total_sum > 0 else None
    growth_weight = sum(
        weights[index]
        for index, code in enumerate(INDEX_NAMES)
        if code in GROWTH_INDEX_NAMES
    )
    window_start = (weeks[0] + timedelta(days=4)).isoformat()
    window_end = (weeks[-1] + timedelta(days=4)).isoformat()
    return {
        "asof": window_end,
        "value": round(float(growth_weight) * 100, 2),
        "r2": round(float(r2), 4) if r2 is not None else None,
        "n_weeks": len(weeks),
        "coverage": round(len(weeks) / 52 * 100, 1),
        "window": {"start": window_start, "end": window_end},
        "weights": {
            INDEX_NAMES[code]: round(float(weights[index]) * 100, 2)
            for index, code in enumerate(INDEX_NAMES)
        },
        "source": PROXY_SOURCE,
    }


def _weekly_report_rows(frame: pd.DataFrame) -> list[dict]:
    date_column = _column(frame, ("发布日期", "日期", "date"))
    code_column = _column(frame, ("指数代码", "行业代码", "code"))
    name_column = _column(frame, ("指数名称", "行业名称", "name"))
    close_column = _column(frame, ("收盘指数", "收盘", "close"))
    rows = []
    for _, row in frame.iterrows():
        code = _industry_code(row[code_column])
        day = _parse_date(row[date_column])
        close = _number(row[close_column])
        if code in INDEX_NAMES and day and close and close > 0:
            rows.append(
                {
                    "date": day.isoformat(),
                    "code": code,
                    "name": _text(row[name_column]),
                    "close": close,
                }
            )
    verify_sw_index_codes(
        pd.DataFrame(
            [{"指数代码": row["code"], "指数名称": row["name"]} for row in rows]
        )
    )
    return rows


def _collect_weekly_analysis(
    asof: str, cache_dir: Path, client: RateLimitedClient
) -> dict:
    path = _weekly_cache_path(cache_dir)
    if path.is_file():
        cached = pd.read_parquet(path)
        if not set(WEEKLY_CACHE_COLUMNS).issubset(cached.columns):
            raise ValueError(f"申万周报缓存字段不完整：{path}")
        records = cached[list(WEEKLY_CACHE_COLUMNS)].to_dict("records")
    else:
        records = []
    date_list = client.call("index_analysis_week_month_sw", symbol="week")
    date_column = _column(date_list, ("date", "日期", "bargaindate"))
    asof_date = date.fromisoformat(asof)
    monday = asof_date - timedelta(days=asof_date.weekday())
    if asof_date.weekday() < 4:
        monday -= timedelta(days=7)
    cutoff = monday + timedelta(days=4)
    available = sorted(
        {
            parsed
            for value in date_list[date_column].tolist()
            if (parsed := _parse_date(value)) and parsed <= cutoff
        }
    )
    if len(available) < 53:
        raise ValueError(f"申万周报仅有 {len(available)} 个可用周，至少需要 53 周。")
    wanted = available[-53:]
    for report_date in wanted:
        day = report_date.isoformat()
        present = {
            _industry_code(row["code"])
            for row in records
            if _parse_date(row["date"]) == report_date
        }
        if set(INDEX_NAMES).issubset(present):
            continue
        frame = client.call(
            "index_analysis_weekly_sw",
            symbol="一级行业",
            date=report_date.strftime("%Y%m%d"),
        )
        report_rows = _weekly_report_rows(frame)
        if len({row["code"] for row in report_rows}) < len(INDEX_NAMES):
            raise ValueError(f"{day} 的申万周报缺少指定一级行业。")
        records = [row for row in records if _parse_date(row["date"]) != report_date]
        records.extend(report_rows)
        _write_parquet_atomic(
            path,
            pd.DataFrame(records, columns=WEEKLY_CACHE_COLUMNS),
        )
    selected = [
        row for row in records if _parse_date(row["date"]) in set(wanted)
    ]
    info = pd.DataFrame(
        [
            {"指数代码": row["code"], "指数名称": row["name"]}
            for row in selected
            if _parse_date(row["date"]) == wanted[-1]
        ]
    )
    industry_frames = {
        code: pd.DataFrame(
            [
                {"发布日期": row["date"], "收盘指数": row["close"]}
                for row in selected
                if row["code"] == code
            ]
        )
        for code in INDEX_NAMES
    }
    industry_frames["__index_info__"] = info
    target = client.call("stock_zh_index_hist_csindex", symbol="930950")
    result = compute_weekly_proxy(target, industry_frames, asof=asof)
    result["source"] = (
        "ak.index_analysis_weekly_sw（申万一级行业周报；"
        "中证偏股型基金指数 930950；非负最小二乘回归）"
    )
    result["method"] = "weekly_analysis"
    return result


def _collect_realtime_proxy(
    asof: str, cache_dir: Path, client: RateLimitedClient
) -> dict:
    realtime = client.call("index_realtime_sw", symbol="一级行业")
    verify_sw_index_codes(realtime)
    target = client.call("stock_zh_index_hist_csindex", symbol="930950")
    date_column = _column(target, ("日期", "date", "trade_date"))
    close_column = _column(target, ("收盘", "收盘指数", "close"))
    target_rows = [
        (_parse_date(row[date_column]), _number(row[close_column]))
        for _, row in target.iterrows()
    ]
    target_rows = [(day, close) for day, close in target_rows if day and close]
    if not target_rows:
        raise ValueError("930950 没有可用日线收盘数据。")
    target_date, target_close = max(target_rows, key=lambda item: item[0])
    retrieved = date.today()
    week_start = retrieved - timedelta(days=retrieved.weekday())
    code_column = _column(realtime, ("指数代码", "行业代码", "code"))
    name_column = _column(realtime, ("指数名称", "行业名称", "name"))
    value_column = _column(realtime, ("最新价", "收盘", "最新指数"))
    complete = retrieved.weekday() == 4 and target_date == retrieved
    rows = []
    for _, row in realtime.iterrows():
        code = _industry_code(row[code_column])
        value = _number(row[value_column])
        if code in INDEX_NAMES and value:
            rows.append(
                {
                    "week_start": week_start.isoformat(),
                    "asof": retrieved.isoformat(),
                    "code": code,
                    "name": _text(row[name_column]),
                    "close": value,
                    "target_close": target_close,
                    "complete": complete,
                }
            )
    path = Path(cache_dir) / "weekly_realtime.parquet"
    if path.is_file():
        old = pd.read_parquet(path)
        rows = old.to_dict("records") + rows
    frame = pd.DataFrame(rows).drop_duplicates(
        ["week_start", "code"], keep="last"
    )
    _write_parquet_atomic(path, frame)
    complete_rows = frame[frame["complete"] == True]  # noqa: E712
    by_week = complete_rows.groupby("week_start")["code"].nunique()
    complete_weeks = sorted(by_week[by_week == len(INDEX_NAMES)].index)
    count = max(0, len(complete_weeks) - 1)
    if count < 52:
        return {
            "asof": complete_weeks[-1] if complete_weeks else retrieved.isoformat(),
            "value": None,
            "r2": None,
            "n_weeks": count,
            "coverage": round(count / 52 * 100, 1),
            "window": {"start": None, "end": None},
            "weights": {},
            "source": (
                f"ak.index_realtime_sw（{WEEKLY_REALTIME_SOURCE}；申万一级行业；"
                "中证偏股型基金指数 930950；非负最小二乘回归）"
            ),
            "method": "realtime_accumulation",
            "missing_reason": f"代理样本不足：仅有 {count} 个完整周，需 52 周。",
        }
    selected = complete_rows[
        complete_rows["week_start"].isin(complete_weeks[-53:])
    ]
    info = pd.DataFrame(
        [{"指数代码": code, "指数名称": INDEX_NAMES[code]} for code in INDEX_NAMES]
    )
    industry_frames = {}
    for code in INDEX_NAMES:
        rows_for_code = selected[selected["code"] == code]
        industry_frames[code] = pd.DataFrame(
            {"日期": rows_for_code["asof"], "收盘": rows_for_code["close"]}
        )
    industry_frames["__index_info__"] = info
    target_rows = selected.drop_duplicates("week_start")
    target_frame = pd.DataFrame(
        {"日期": target_rows["asof"], "收盘": target_rows["target_close"]}
    )
    result = compute_weekly_proxy(
        target_frame, industry_frames, asof=selected["asof"].max()
    )
    result["source"] = (
        f"ak.index_realtime_sw（{WEEKLY_REALTIME_SOURCE}；申万一级行业；"
        "中证偏股型基金指数 930950；非负最小二乘回归）"
    )
    result["method"] = "realtime_accumulation"
    return result


def _collect_proxy(
    asof: str, cache_dir: Path, client: RateLimitedClient
) -> dict:
    try:
        return _collect_weekly_analysis(asof, cache_dir, client)
    except (SwIndexMismatchError, CallLimitExceeded):
        raise
    except Exception as weekly_error:
        try:
            result = _collect_realtime_proxy(asof, cache_dir, client)
            result["note"] = (
                f"申万周度分析源不可用（{type(weekly_error).__name__}）；"
                "改用实时指数逐周累积。"
            )
            return result
        except (SwIndexMismatchError, CallLimitExceeded):
            raise
        except Exception as realtime_error:
            raise RuntimeError(
                f"申万周度分析失败：{weekly_error}; 实时周度累积失败：{realtime_error}"
            ) from realtime_error


def _empty_official(error: str) -> dict:
    return {
        "quarter": None,
        "data_asof": None,
        "value": None,
        "n_funds": 0,
        "universe_funds": 0,
        "coverage": 0.0,
        "industry_weights": {},
        "unmapped_stock_count": 0,
        "source": "未取得（天天基金季报持仓；申万当前成分股/巨潮 PIT）",
        "missing_reason": error,
    }


def _empty_proxy(error: str) -> dict:
    return {
        "asof": None,
        "value": None,
        "r2": None,
        "n_weeks": 0,
        "coverage": 0.0,
        "window": {"start": None, "end": None},
        "weights": {},
        "source": "未取得（申万指数周度分析/实时指数周度累积）",
        "missing_reason": error,
    }


def collect_fund_growth(
    asof: str,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    limit: int | None = None,
    client: RateLimitedClient | None = None,
) -> dict:
    started = time.monotonic()
    api = client or RateLimitedClient()
    official = None
    official_error = None
    try:
        official = _collect_official(asof, Path(cache_dir), api, limit)
    except SwIndexMismatchError:
        raise
    except Exception as exc:  # noqa: BLE001 — quarterly and weekly sources fail independently
        official_error = f"{type(exc).__name__}: {exc}"

    proxy = None
    proxy_error = None
    try:
        proxy = _collect_proxy(asof, Path(cache_dir), api)
    except SwIndexMismatchError:
        raise
    except Exception as exc:  # noqa: BLE001 — preserve the official quarterly value
        proxy_error = f"{type(exc).__name__}: {exc}"

    if official is None:
        official = _empty_official(official_error or "正式季度数据不可用。")
    if proxy is None:
        proxy = _empty_proxy(proxy_error or "周度代理数据不可用。")
    if proxy.get("value") is None and proxy.get("missing_reason"):
        proxy.setdefault("status", "insufficient")
    value = official["value"]
    status = "missing" if value is None else "met" if value < 60 else "not_met"
    return {
        "status": status,
        "value": value,
        "asof": official["data_asof"] or proxy["asof"],
        "source": f"正式季度：{official['source']}；周度代理：{proxy['source']}",
        "rule": RULE,
        "missing_reason": official.get("missing_reason"),
        "note": official.get("note") or proxy.get("note"),
        "official": official,
        "proxy": proxy,
        "api_calls": api.network_calls,
        "akshare_calls": api.calls,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect official and proxy fund growth position.")
    parser.add_argument("--date", required=True, help="snapshot date")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--limit", type=int, help="limit the fund universe for a sample run")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    result = collect_fund_growth(
        args.date,
        cache_dir=args.cache_dir,
        limit=args.limit,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "out": str(args.out),
                "status": result["status"],
                "official": result["official"],
                "proxy": result["proxy"],
                "api_calls": result["api_calls"],
                "elapsed_seconds": result["elapsed_seconds"],
            },
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
