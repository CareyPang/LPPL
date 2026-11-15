from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

LOOKBACK_DAYS = 750
MIN_PERIODS = 500
PERCENTILE_THRESHOLD = 0.90
EVENT_GAP_DAYS = 20
EVENT_START_DATE = "2007-01-01"
FORWARD_DAYS = 250
RETURN_DAYS = (120, 250)
DEFAULT_OUT = Path("out/bottom")
ERP_SOURCE = "ak.stock_ebs_lg"
PBN_SOURCE = 'ak.stock_a_below_net_asset_statistics(symbol="全部A股")'
RULE = (
    "以 ak.stock_ebs_lg 的交易日为准，破净股占比按日期去重并向前填充；"
    "股债利差和破净股占比分别使用含当日的过去 750 个交易日滚动秩分位（至少 500 日）；"
    "两项分位均不低于 90% 时记为信号日，前 20 个交易日无信号才计为独立事件，"
    "仅统计 2007-01-01 起的事件；事件后最低取之后 1–250 个交易日沪深300收盘价的最低值，"
    "并计算第 120/250 个交易日收益；下跌日基准为沪深300较 20 个交易日前下跌且之后 250 日可用的交易日。"
)
NOTES = (
    "历史回测，不是预测",
    "2011–2013 熊市中提前约一年触发，之后再跌 12–18%",
    "不是买入指令",
)


def _numeric(values: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(values):
        return pd.to_numeric(values, errors="coerce")
    text = values.astype("string").str.strip().str.replace(",", "", regex=False)
    text = text.str.replace("%", "", regex=False)
    return pd.to_numeric(text, errors="coerce")


def _dated_series(
    frame: pd.DataFrame, date_column: str, value_column: str, name: str
) -> pd.Series:
    missing = [column for column in (date_column, value_column) if column not in frame]
    if missing:
        raise ValueError(f"数据缺少列: {', '.join(missing)}")
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    values = _numeric(frame[value_column])
    rows = pd.DataFrame({"date": dates, name: values}).dropna(subset=["date"])
    rows = rows.sort_values("date", kind="stable").drop_duplicates("date", keep="last")
    return rows.set_index("date")[name].sort_index()


def compute_series(ebs: pd.DataFrame, pbn: pd.DataFrame) -> pd.DataFrame:
    """Align the source frames and compute past-only rolling percentiles and signals."""
    erp = _dated_series(ebs, "日期", "股债利差", "erp")
    close = _dated_series(ebs, "日期", "沪深300指数", "close").reindex(erp.index)
    pbn_ratio = _dated_series(
        pbn, "date", "below_net_asset_ratio", "pbn_ratio"
    )
    for source, values in ((ERP_SOURCE, erp), (PBN_SOURCE, pbn_ratio)):
        count = int(values.count())
        if count < MIN_PERIODS:
            raise ValueError(
                f"{source} has only {count} non-null values; requires {MIN_PERIODS}"
            )
    pbn_aligned = (
        pbn_ratio.reindex(pbn_ratio.index.union(erp.index))
        .sort_index()
        .ffill()
        .reindex(erp.index)
    )
    erp_pct = erp.rolling(LOOKBACK_DAYS, min_periods=MIN_PERIODS).rank(pct=True)
    pbn_pct = pbn_aligned.rolling(LOOKBACK_DAYS, min_periods=MIN_PERIODS).rank(
        pct=True
    )
    signal = (erp_pct >= PERCENTILE_THRESHOLD) & (
        pbn_pct >= PERCENTILE_THRESHOLD
    )
    return pd.DataFrame(
        {
            "erp": erp,
            "erp_pct": erp_pct,
            "pbn_ratio": pbn_aligned,
            "pbn_pct": pbn_pct,
            "close": close,
            "signal": signal.fillna(False).astype(bool),
        },
        index=erp.index,
    )


def _finite(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _ratio_return(base: object, target: object) -> float | None:
    start, end = _finite(base), _finite(target)
    if start is None or end is None or start <= 0:
        return None
    return end / start - 1


def _median(values: list[float]) -> float | None:
    return float(pd.Series(values, dtype="float64").median()) if values else None


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, (float,)):
        return round(value, 4) if math.isfinite(value) else None
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return value


def compute_bottom_signal(ebs: pd.DataFrame, pbn: pd.DataFrame) -> dict:
    series = compute_series(ebs, pbn)
    dates = series.index
    closes = series["close"].tolist()
    signals = series["signal"].tolist()
    event_indices = [
        index
        for index, (day, is_signal) in enumerate(zip(dates, signals, strict=True))
        if is_signal
        and day >= pd.Timestamp(EVENT_START_DATE)
        and not any(signals[max(0, index - EVENT_GAP_DAYS) : index])
    ]

    def outcome(index: int) -> dict:
        base = closes[index]
        future_end = min(index + FORWARD_DAYS + 1, len(closes))
        future_indices = [
            future_index
            for future_index in range(index + 1, future_end)
            if _finite(closes[future_index]) is not None
        ]
        post_min_index = (
            min(future_indices, key=lambda future_index: closes[future_index])
            if future_indices
            else None
        )
        returns = {
            f"ret_{days}": (
                _ratio_return(base, closes[index + days])
                if index + days < len(closes)
                else None
            )
            for days in RETURN_DAYS
        }
        return {
            "post_min": (
                _ratio_return(base, closes[post_min_index])
                if post_min_index is not None
                else None
            ),
            "post_min_date": (
                dates[post_min_index].date().isoformat()
                if post_min_index is not None
                else None
            ),
            "post_min_complete": index + FORWARD_DAYS < len(closes),
            **returns,
        }

    events = []
    for index in event_indices:
        row = series.iloc[index]
        events.append(
            {
                "date": dates[index].date().isoformat(),
                "erp": _finite(row["erp"]),
                "erp_pct": _finite(row["erp_pct"]),
                "pbn_ratio": _finite(row["pbn_ratio"]),
                "pbn_pct": _finite(row["pbn_pct"]),
                **outcome(index),
            }
        )

    with_250 = [event["ret_250"] for event in events if event["ret_250"] is not None]
    post_mins = [
        event["post_min"]
        for event in events
        if event["ret_250"] is not None and event["post_min"] is not None
    ]
    up_250 = sum(value > 0 for value in with_250)
    summary = {
        "n_events": len(events),
        "n_with_250d": len(with_250),
        "n_up_250": up_250,
        "share_up_250": up_250 / len(with_250) if with_250 else None,
        "median_ret_250": _median(with_250),
        "median_post_min": _median(post_mins),
    }

    baseline_returns, baseline_post_mins = [], []
    for index, day in enumerate(dates):
        if day < pd.Timestamp(EVENT_START_DATE) or index < 20 or index + 250 >= len(closes):
            continue
        down_20d = _ratio_return(closes[index - 20], closes[index])
        ret_250 = _ratio_return(closes[index], closes[index + 250])
        if down_20d is None or down_20d >= 0 or ret_250 is None:
            continue
        baseline_returns.append(ret_250)
        baseline_post_min = outcome(index)["post_min"]
        if baseline_post_min is not None:
            baseline_post_mins.append(baseline_post_min)
    baseline = {
        "n_days": len(baseline_returns),
        "share_up_250": (
            sum(value > 0 for value in baseline_returns) / len(baseline_returns)
            if baseline_returns
            else None
        ),
        "median_ret_250": _median(baseline_returns),
        "median_post_min": _median(baseline_post_mins),
    }

    latest = series.iloc[-1] if len(series) else None
    payload = {
        "asof": dates[-1].date().isoformat() if len(dates) else None,
        "rule": RULE,
        "current": {
            "date": dates[-1].date().isoformat() if len(dates) else None,
            "erp": _finite(latest["erp"]) if latest is not None else None,
            "erp_pct": _finite(latest["erp_pct"]) if latest is not None else None,
            "pbn_ratio": _finite(latest["pbn_ratio"]) if latest is not None else None,
            "pbn_pct": _finite(latest["pbn_pct"]) if latest is not None else None,
            "signal": bool(latest["signal"]) if latest is not None else False,
            "last_event_date": events[-1]["date"] if events else None,
        },
        "events": events,
        "summary": summary,
        "baseline": baseline,
        "notes": [*NOTES[:1], f"样本只有 {len(events)} 次", *NOTES[1:]],
        "sources": {
            "erp_and_close": ERP_SOURCE,
            "pbn_ratio": PBN_SOURCE,
        },
    }
    return _json_safe(payload)


def fetch_live() -> dict:
    import akshare as ak

    return compute_bottom_signal(
        ak.stock_ebs_lg(),
        ak.stock_a_below_net_asset_statistics(symbol="全部A股"),
    )


def write_snapshot(payload: dict, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    latest = out / "bottom_signal_latest.json"
    text = json.dumps(
        _json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False
    ) + "\n"
    latest.write_text(text, encoding="utf-8")
    return latest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    result = fetch_live()
    latest = write_snapshot(result, args.out)
    print(
        json.dumps(
            {
                "latest": str(latest),
                "asof": result["asof"],
                "event_dates": [event["date"] for event in result["events"]],
                "summary": result["summary"],
            },
            ensure_ascii=False,
            allow_nan=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
