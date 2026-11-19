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
from scipy.optimize import nnls

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = ROOT / "data" / "cache" / "fund_growth"
DEFAULT_OUT = Path("out/growth/fund_growth_sample.json")
MAX_API_CALLS = 6000
MIN_CALL_INTERVAL = 0.3
RETRIES = 2
QUARTERLY_SOURCE = "天天基金季报持仓；申万一级行业分类"
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
)


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
        self.last_call_at: float | None = None

    def call(self, method: str, *args, **kwargs):
        function = getattr(self.module, method)
        for attempt in range(self.retries + 1):
            if self.calls >= self.max_calls:
                raise CallLimitExceeded(
                    f"已达到 AkShare 调用上限 {self.max_calls}，停止继续取数。"
                )
            if self.last_call_at is not None:
                elapsed = self.clock() - self.last_call_at
                if elapsed < self.min_interval:
                    self.sleep(self.min_interval - elapsed)
            self.last_call_at = self.clock()
            self.calls += 1
            try:
                return function(*args, **kwargs)
            except Exception:
                if attempt >= self.retries:
                    raise
                self.sleep(max(self.min_interval, 0.5 * (attempt + 1)))
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


def build_industry_map(
    history: pd.DataFrame, index_info: pd.DataFrame, quarter_end: str
) -> dict[str, str | None]:
    l1_names = verify_sw_index_codes(index_info)
    stock_column = _column(
        history, ("股票代码", "证券代码", "代码", "stock_code", "symbol")
    )
    industry_column = _column(history, ("行业代码", "申万行业代码", "行业编码", "industry_code"))
    start_column = _column(
        history, ("纳入日期", "生效日期", "开始日期", "start_date", "日期")
    )
    cutoff = date.fromisoformat(quarter_end)
    latest: dict[str, tuple[date, str]] = {}
    for _, row in history.iterrows():
        stock = _stock_code(row[stock_column])
        start = _parse_date(row[start_column])
        industry = _industry_code(row[industry_column])
        if not stock or not start or start > cutoff or not industry:
            continue
        if stock not in latest or start >= latest[stock][0]:
            latest[stock] = (start, industry)

    output: dict[str, str | None] = {}
    level_one = sorted(l1_names, key=len, reverse=True)
    for stock, (_, industry) in latest.items():
        mapped = next(
            (
                name
                for code in level_one
                if industry == code or industry.startswith(code[:5])
                for name in (l1_names[code],)
            ),
            None,
        )
        output[stock] = mapped
    return output


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
        "source": QUARTERLY_SOURCE,
    }


def _cache_path(cache_dir: Path, quarter: str) -> Path:
    return Path(cache_dir) / f"{quarter}.parquet"


def _save_quarter_cache(path: Path, rows: list[dict], universe_funds: int) -> None:
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
            }
        )
    frame = pd.DataFrame(records)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".parquet", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_quarter_cache(path: Path) -> tuple[list[dict], int]:
    frame = pd.read_parquet(path)
    required = {*CACHE_COLUMNS, "universe_funds"}
    if not required.issubset(frame.columns):
        raise ValueError(f"季度缓存字段不完整：{path}")
    if frame.empty:
        raise ValueError(f"季度缓存为空：{path}")
    universe_funds = int(frame["universe_funds"].iloc[0])
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
    return rows, universe_funds


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


def _collect_official(
    asof: str,
    cache_dir: Path,
    client: RateLimitedClient,
    limit: int | None,
) -> tuple[dict, pd.DataFrame | None]:
    reference, quarter, quarter_end = _reference_holdings(client, asof)
    path = _cache_path(cache_dir, quarter)
    if limit is None and path.is_file():
        rows, universe_funds = _load_quarter_cache(path)
        return (
            aggregate_official(
                rows,
                quarter=quarter,
                quarter_end=quarter_end,
                universe_funds=universe_funds,
            ),
            None,
        )

    universe = select_fund_universe(client.call("fund_name_em"))
    if limit is not None:
        if limit < 1:
            raise ValueError("样本基金数量必须大于 0。")
        universe = universe[:limit]
    universe_count = len(universe)
    if not universe:
        raise ValueError("筛选后没有符合口径的基金样本。")

    index_info = client.call("sw_index_first_info")
    verify_sw_index_codes(index_info)
    history = client.call("stock_industry_clf_hist_sw")
    industry_map = build_industry_map(history, index_info, quarter_end)
    holdings_cache = {"005827": reference}
    rows = []
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
            row = build_fund_row(fund, holdings, quarter, industry_map)
        except Exception as exc:
            errors.append(f"{fund['code']}: {type(exc).__name__}: {exc}")
            continue
        if row:
            rows.append(row)
    if limit is None and rows:
        _save_quarter_cache(path, rows, universe_count)
    official = aggregate_official(
        rows,
        quarter=quarter,
        quarter_end=quarter_end,
        universe_funds=universe_count,
    )
    official["failed_fund_count"] = len(errors)
    if errors:
        official["note"] = f"{len(errors)} 只基金取数或持仓字段不可用，已计入覆盖率。"
    return official, index_info


def _series_close(frame: pd.DataFrame) -> dict[date, float]:
    date_column = _column(frame, ("日期", "交易日期", "date", "trade_date"))
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


def _collect_proxy(
    asof: str, client: RateLimitedClient, index_info: pd.DataFrame | None
) -> dict:
    if index_info is None:
        index_info = client.call("sw_index_first_info")
    verify_sw_index_codes(index_info)
    target = client.call("stock_zh_index_hist_csindex", symbol="930950")
    industry_frames = {
        code: client.call("index_hist_sw", symbol=code, period="week")
        for code in INDEX_NAMES
    }
    industry_frames["__index_info__"] = index_info
    return compute_weekly_proxy(target, industry_frames, asof=asof)


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
        "source": QUARTERLY_SOURCE,
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
        "source": PROXY_SOURCE,
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
    index_info = None
    try:
        official, index_info = _collect_official(
            asof, Path(cache_dir), api, limit
        )
    except SwIndexMismatchError:
        raise
    except Exception as exc:  # noqa: BLE001 — quarterly and weekly sources fail independently
        official_error = f"{type(exc).__name__}: {exc}"

    proxy = None
    proxy_error = None
    try:
        proxy = _collect_proxy(asof, api, index_info)
    except SwIndexMismatchError:
        raise
    except Exception as exc:  # noqa: BLE001 — preserve the official quarterly value
        proxy_error = f"{type(exc).__name__}: {exc}"

    if official is None:
        official = _empty_official(official_error or "正式季度数据不可用。")
    if proxy is None:
        proxy = _empty_proxy(proxy_error or "周度代理数据不可用。")
    value = official["value"]
    status = "missing" if value is None else "met" if value < 60 else "not_met"
    return {
        "status": status,
        "value": value,
        "asof": official["data_asof"] or proxy["asof"],
        "source": f"正式季度：{official['source']}；周度代理：{proxy['source']}",
        "rule": RULE,
        "missing_reason": official.get("missing_reason"),
        "official": official,
        "proxy": proxy,
        "api_calls": api.calls,
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
