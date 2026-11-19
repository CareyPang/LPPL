from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .engine import EngineConfig, run
from .rules import lppls_target, select_top_risk_variant, top_risk_target

PREREG_DOC = "docs/preregistration_strategy_v1.md"
SEGMENTS = {
    "dev": ("2014-01-01", "2022-12-31"),
    "test": ("2023-01-01", None),
}
TOP_LOOKAHEAD_DAYS = 120
TOP_MERGE_GAP_DAYS = 20
PRICE_STARTS = {"sh000852": "2014-10-17"}


def _segment_dates(
    prices: pd.DataFrame, segment: str, end: str | None = None
) -> tuple[str, str]:
    first = str(prices["date"].iloc[0])
    last = str(prices["date"].iloc[-1])
    start_bound, end_bound = SEGMENTS.get(segment, (first, last))
    return max(first, start_bound), min(last, end or end_bound or last)


def _label_trades(trades: list[dict], segment_ranges: dict[str, list[str]]) -> list[dict]:
    labeled = []
    for trade in trades:
        date = trade["exit"] or trade["entry"]
        segment = next(
            (
                name
                for name, (start, end) in segment_ranges.items()
                if start <= date <= end
            ),
            "all",
        )
        labeled.append({**trade, "segment": segment})
    return labeled


def _price_top_outcomes(
    prices: pd.DataFrame,
) -> tuple[set[str], set[str], list[tuple[str, str]]]:
    dates = prices["date"].tolist()
    closes = pd.to_numeric(prices["close"], errors="coerce").tolist()
    top_days: set[str] = set()
    sample_days: set[str] = set()
    top_positions = []

    for index in range(max(0, len(dates) - TOP_LOOKAHEAD_DAYS)):
        close = closes[index]
        future = closes[index + 1 : index + TOP_LOOKAHEAD_DAYS + 1]
        if not math.isfinite(close) or any(not math.isfinite(value) for value in future):
            continue
        sample_days.add(dates[index])
        if (
            max(future) <= close * 1.05
            and min(future) <= close * 0.90
        ):
            top_days.add(dates[index])
            top_positions.append(index)

    zones = []
    if top_positions:
        start = previous = top_positions[0]
        for position in top_positions[1:]:
            if position - previous <= TOP_MERGE_GAP_DAYS:
                previous = position
                continue
            zones.append((dates[start], dates[previous]))
            start = previous = position
        zones.append((dates[start], dates[previous]))
    return top_days, sample_days, zones


def _signal_quality(
    dates: list[str],
    target: pd.Series,
    top_days: set[str],
    sample_days: set[str],
    zones: list[tuple[str, str]],
    start: str,
    end: str,
) -> dict[str, Any]:
    signals = [
        dates[index]
        for index in range(1, len(dates))
        if target.iloc[index - 1] == 1 and target.iloc[index] == 0
    ]
    sample_dates = [date for date in dates if date in sample_days]
    sample_signals = [signal for signal in signals if signal in sample_days]
    active_zones = [
        (left, right)
        for left, right in zones
        if right >= start and left <= end
    ]
    zone_signals = [
        signal
        for signal in sample_signals
        if start <= signal <= end
        and signal in top_days
    ]
    recalled = sum(
        any(
            start <= signal <= end and left <= signal <= right
            for signal in sample_signals
        )
        for left, right in active_zones
    )
    sample_dates = [date for date in sample_dates if start <= date <= end]
    top_day_count = sum(date in top_days for date in sample_dates)
    return {
        "precision": len(zone_signals) / len(sample_signals)
        if sample_signals
        else None,
        "recall": recalled / len(active_zones) if active_zones else None,
        "baseline": top_day_count / len(sample_dates) if sample_dates else None,
        "n_signals": len(sample_signals),
    }


def _run_rule(
    prices: pd.DataFrame,
    target: pd.Series,
    price_outcomes: tuple[set[str], set[str], list[tuple[str, str]]],
    note: str,
) -> dict[str, Any]:
    top_days, sample_days, zones = price_outcomes
    first, last = str(prices["date"].iloc[0]), str(prices["date"].iloc[-1])
    segment_ranges = {
        name: list(_segment_dates(prices, name))
        for name in ("dev", "test")
        if _segment_dates(prices, name)[0] <= _segment_dates(prices, name)[1]
    }
    segment_ranges["all"] = [first, last]
    metrics: dict[str, dict[str, Any]] = {}
    for segment, (start, end) in segment_ranges.items():
        selected = prices.loc[prices["date"].between(start, end)].copy()
        if selected.empty:
            continue
        selected_target = target.reindex(selected["date"]).fillna(0)
        selected_target.index = selected["date"]
        equity, trades, result = run(selected, selected_target, EngineConfig())
        quality = _signal_quality(
            selected["date"].tolist(),
            selected_target.reset_index(drop=True),
            top_days,
            sample_days,
            zones,
            start,
            end,
        )
        evidence = "dev_only" if segment == "dev" else "descriptive"
        metrics[segment] = {**result, **quality, "evidence": evidence}
        if segment == "all":
            all_equity = equity.to_dict("records")
            all_trades = _label_trades(trades, segment_ranges)
    return {
        "metrics": metrics,
        "equity": all_equity,
        "trades": all_trades,
        "segments": segment_ranges,
        "properties": {
            "t_plus_1": True,
            "limit_lock": True,
            "fee_bps": 2.5,
            "stamp_bps": 5.0,
            "slippage_bps": 5.0,
            "position": "全仓/空仓",
            "benchmark": "买入持有",
        },
        "note": note,
    }


def build_strategy_report(
    code: str,
    prices: pd.DataFrame,
    n_on: pd.Series,
    frames: list[dict],
    *,
    asof: str,
    missing_open_days: int = 0,
) -> dict[str, Any]:
    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.strftime("%Y-%m-%d")
    start_date = PRICE_STARTS.get(code, "2014-01-01")
    prices = (
        prices.loc[prices["date"] >= start_date]
        .sort_values("date")
        .reset_index(drop=True)
    )
    n_on.index = pd.to_datetime(n_on.index).strftime("%Y-%m-%d")
    price_outcomes = _price_top_outcomes(prices)
    selected, variants = select_top_risk_variant(prices, n_on)
    top_days, sample_days, zones = price_outcomes
    dev_prices = prices.loc[
        prices["date"].between(SEGMENTS["dev"][0], SEGMENTS["dev"][1])
    ]
    dev_dates = dev_prices["date"].tolist()
    dev_start, dev_end = (
        (dev_dates[0], dev_dates[-1]) if dev_dates else ("", "")
    )
    for variant in variants.values():
        dev_n_on = n_on.reindex(dev_dates).fillna(0)
        dev_target = top_risk_target(dev_n_on, variant["K"], variant["M"])
        dev_target.index = dev_dates
        variant.update(
            _signal_quality(
                dev_dates,
                dev_target.reset_index(drop=True),
                top_days,
                sample_days,
                zones,
                dev_start,
                dev_end,
            )
        )
    tr1_target = top_risk_target(
        n_on.reindex(prices["date"]).fillna(0), selected["K"], selected["M"]
    )
    tr1_target.index = prices["date"]
    note_parts = []
    if missing_open_days:
        note_parts.append(
            f"开盘价缺失的 {missing_open_days} 个交易日不成交，"
            "订单顺延至下一有效开盘日。"
        )
    if code == "sh000852":
        note_parts.append(
            "中证1000 回测自 2014-10-17 起；2026-11-19 盘中行已排除。"
        )
    elif asof <= "2026-11-18":
        note_parts.append(f"数据截至 {asof}，不含 2026-11-19 盘中行。")
    note = "；".join(note_parts)
    tr1 = _run_rule(prices, tr1_target, price_outcomes, note)
    tr1["rule_id"] = "R-TR1"
    tr1["name"] = "顶部风险区退出"
    tr1["selected_variant"] = selected
    tr1["prereg_doc"] = PREREG_DOC
    tr1["asof"] = asof
    tr1["variants"] = variants

    if frames:
        lc_prices = prices.loc[prices["date"] <= max(frame["asof"] for frame in frames)].copy()
        lc_dates = pd.Series(lc_prices["date"])
        lc_target = lppls_target(lc_dates, frames, scale="6-12m", reentry_days=20)
        lc_target.index = lc_prices["date"]
        lc_price_outcomes = _price_top_outcomes(lc_prices)
        lc = _run_rule(
            lc_prices,
            lc_target,
            lc_price_outcomes,
            "LPPLS 区间为 v2.2 事后重算，不是样本外；周度更新。",
        )
        lc["rule_id"] = "R-LC1"
        lc["name"] = "LPPLS 区间退出"
        lc["prereg_doc"] = PREREG_DOC
        lc["asof"] = str(lc_prices["date"].iloc[-1])
        secondary = lc
    else:
        secondary = {
            "rule_id": "R-LC1",
            "name": "LPPLS 区间退出",
            "skipped": True,
            "note": f"{code} 缺少 LPPLS history 文件，跳过 R-LC1。",
        }
    report = {
        **tr1,
        "rule_id": tr1["rule_id"],
        "rules": [tr1, secondary],
        "asof": asof,
        "note": "；".join(
            text
            for text in (
                note,
                "规则阈值来自用户经验与 2014–2026 全样本时段表；"
                "检验段不是严格样本外。",
            )
            if text
        ),
    }
    return report
