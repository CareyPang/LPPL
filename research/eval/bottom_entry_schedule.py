"""Backtest fixed and confirmation-based entries for B3 bottom events."""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from research.eval.bottom_calibration import (
    DEFAULT_CACHE_ROOT,
    DEFAULT_DATA_DIR,
    DEFAULT_REPORT_DIR,
    EVENT_COOLDOWN_WEEKS,
    SEED,
    SEGMENTS,
    _candidate,
    _load_frames,
    _number,
    _outcome,
    independent_positions,
    score_100,
)
from research.pipeline.overview_export import INDEX_LIST

STRATEGIES = ("S_full", "S_fixed", "S_probe", "S_confirm", "S_confirm_full")
RANDOM_REPEATS = 2000
BOOTSTRAP_REPEATS = 2000
HORIZON_WEEKS = 50
CONFIRMATION_WEEKS = 26


def first_confirmation_position(
    closes: list[float | None], t0: int, max_weeks: int = CONFIRMATION_WEEKS
) -> int | None:
    end = min(t0 + max_weeks, len(closes) - 1)
    for position in range(t0 + 1, end + 1):
        window = closes[position - 9 : position + 1]
        if len(window) != 10 or any(value is None for value in window):
            continue
        close = closes[position]
        if close is not None and close > float(np.mean(window)):
            return position
    return None


def resolve_buy_position(
    closes: list[float | None], planned_position: int, end_position: int
) -> int | None:
    for position in range(planned_position, min(end_position, len(closes) - 1) + 1):
        close = closes[position]
        if close is not None and close > 0:
            return position
    return None


def maximum_drawdown(equity: list[float]) -> float:
    peak = 0.0
    maximum = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            maximum = max(maximum, (peak - value) / peak)
    return maximum


def _planned_purchases(
    strategy: str, t0: int, confirmation_position: int | None
) -> list[tuple[int, float]]:
    if strategy == "S_full":
        return [(t0, 1.0)]
    if strategy == "S_fixed":
        return [(t0, 0.3), (t0 + 4, 0.3), (t0 + 8, 0.4)]
    if strategy == "S_probe":
        return [(t0, 0.3)]
    if strategy == "S_confirm":
        purchases = [(t0, 0.3)]
        if confirmation_position is not None:
            purchases.append((confirmation_position, 0.7))
        return purchases
    if strategy == "S_confirm_full":
        return [(confirmation_position, 1.0)] if confirmation_position is not None else []
    raise ValueError(f"unknown strategy: {strategy}")


def evaluate_strategy(
    strategy: str,
    closes: list[float | None],
    t0: int,
    confirmation_position: int | None = None,
    horizon: int = HORIZON_WEEKS,
) -> dict[str, Any]:
    end_position = t0 + horizon
    planned = _planned_purchases(strategy, t0, confirmation_position)
    resolved: list[tuple[int, float, float]] = []
    for planned_position, weight in planned:
        buy_position = resolve_buy_position(closes, planned_position, end_position)
        if buy_position is None:
            continue
        buy_price = closes[buy_position]
        if buy_price is None or buy_price <= 0:
            continue
        resolved.append((buy_position, weight, buy_price))

    active_positions: list[tuple[float, float]] = []
    invested = 0.0
    last_close: float | None = None
    equity: list[float] = []
    occupied: list[float] = []
    purchase_index = 0

    for position in range(t0, end_position + 1):
        close = closes[position]
        if close is not None and close > 0:
            last_close = close
        while purchase_index < len(resolved) and resolved[purchase_index][0] == position:
            _, weight, buy_price = resolved[purchase_index]
            active_positions.append((weight, buy_price))
            invested += weight
            purchase_index += 1
        if last_close is None:
            raise ValueError(f"{strategy}: no close available to mark at position {position}")
        equity.append(
            1.0
            + math.fsum(
                weight * (last_close / buy_price - 1.0)
                for weight, buy_price in active_positions
            )
        )
        occupied.append(invested)

    total_return = equity[-1] - 1.0
    return {
        "total_return": float(total_return),
        "max_drawdown": float(maximum_drawdown(equity)),
        "average_capital_occupied": float(np.mean(occupied)),
        "invested_fraction": float(invested),
        "return_on_invested_capital": (
            float(total_return / invested) if invested > 0 else None
        ),
        "equity": equity,
        "weekly_capital_occupied": occupied,
    }


def eligible_event_positions(
    frames: list[dict[str, Any]],
    closes: list[float | None],
    candidate_positions: list[int],
    segment: str,
    horizon: int = HORIZON_WEEKS,
) -> list[int]:
    in_segment = sorted(
        position
        for position in candidate_positions
        if frames[position].get("split") == segment
    )
    independent = independent_positions(in_segment, cooldown=EVENT_COOLDOWN_WEEKS)
    eligible: list[int] = []
    for position in independent:
        result = _outcome(frames, closes, position, horizon)
        end_position = position + horizon
        if result is None or end_position >= len(frames):
            continue
        if any(
            frames[index].get("split") != segment
            for index in range(position, end_position + 1)
        ):
            continue
        eligible.append(position)
    return eligible


def _event_result(
    symbol: str,
    position: int,
    frames: list[dict[str, Any]],
    closes: list[float | None],
) -> dict[str, Any]:
    confirmation_position = first_confirmation_position(closes, position)
    strategies = {
        name: evaluate_strategy(name, closes, position, confirmation_position)
        for name in STRATEGIES
    }
    return {
        "symbol": symbol,
        "position": position,
        "asof": str(frames[position]["asof"]),
        "confirmation_weeks": (
            confirmation_position - position if confirmation_position is not None else None
        ),
        "strategies": strategies,
    }


def _quantiles(values: list[float], probabilities: tuple[float, ...]) -> list[float | None]:
    if not values:
        return [None for _ in probabilities]
    return [float(value) for value in np.quantile(values, probabilities)]


def _strategy_summary(events: list[dict[str, Any]], strategy: str) -> dict[str, Any]:
    results = [event["strategies"][strategy] for event in events]
    if not results:
        return {
            "n_events": 0,
            "mean_return": None,
            "median_return": None,
            "win_rate": None,
            "median_max_drawdown": None,
            "p90_max_drawdown": None,
            "average_capital_occupied": None,
            "median_return_on_invested_capital": None,
            "n_invested": 0,
            "confirmation_trigger_rate": None,
            "n_confirmed": 0,
            "median_confirmation_weeks": None,
        }

    returns = [result["total_return"] for result in results]
    drawdowns = [result["max_drawdown"] for result in results]
    occupancies = [result["average_capital_occupied"] for result in results]
    invested_returns = [
        result["return_on_invested_capital"]
        for result in results
        if result["return_on_invested_capital"] is not None
    ]
    confirmation_weeks = [
        event["confirmation_weeks"]
        for event in events
        if event["confirmation_weeks"] is not None
    ]
    return {
        "n_events": len(results),
        "mean_return": float(np.mean(returns)),
        "median_return": float(np.median(returns)),
        "win_rate": float(np.mean(np.asarray(returns) > 0)),
        "median_max_drawdown": float(np.median(drawdowns)),
        "p90_max_drawdown": float(np.quantile(drawdowns, 0.9)),
        "average_capital_occupied": float(np.mean(occupancies)),
        "median_return_on_invested_capital": (
            float(np.median(invested_returns)) if invested_returns else None
        ),
        "n_invested": len(invested_returns),
        "confirmation_trigger_rate": (
            float(len(confirmation_weeks) / len(events))
            if strategy in ("S_confirm", "S_confirm_full")
            else None
        ),
        "n_confirmed": (
            len(confirmation_weeks)
            if strategy in ("S_confirm", "S_confirm_full")
            else 0
        ),
        "median_confirmation_weeks": (
            float(np.median(confirmation_weeks))
            if confirmation_weeks and strategy in ("S_confirm", "S_confirm_full")
            else None
        ),
    }


def _random_baseline(
    pools_by_index: dict[str, list[dict[str, Any]]],
    event_counts: dict[str, int],
    rng: np.random.Generator,
) -> dict[str, dict[str, list[float | None]]]:
    samples: dict[str, dict[str, list[float]]] = {
        strategy: {"win_rate": [], "median_return": []} for strategy in STRATEGIES
    }
    for _ in range(RANDOM_REPEATS):
        selected: list[dict[str, Any]] = []
        for symbol, pool in pools_by_index.items():
            count = event_counts.get(symbol, 0)
            if count == 0:
                continue
            if count > len(pool):
                raise ValueError(
                    f"{symbol}: requested {count} random weeks from a pool of {len(pool)}"
                )
            indices = rng.choice(len(pool), size=count, replace=False)
            selected.extend(pool[int(index)] for index in indices)
        for strategy in STRATEGIES:
            returns = [
                event["strategies"][strategy]["total_return"] for event in selected
            ]
            if not returns:
                continue
            samples[strategy]["win_rate"].append(
                float(np.mean(np.asarray(returns) > 0))
            )
            samples[strategy]["median_return"].append(float(np.median(returns)))

    return {
        strategy: {
            "win_rate_5_50_95": _quantiles(values["win_rate"], (0.05, 0.5, 0.95)),
            "median_return_5_50_95": _quantiles(
                values["median_return"], (0.05, 0.5, 0.95)
            ),
        }
        for strategy, values in samples.items()
    }


def _paired_comparison(
    events_by_index: dict[str, list[dict[str, Any]]],
    strategy: str,
    rng: np.random.Generator,
) -> dict[str, Any]:
    paired_by_index: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for symbol, events in events_by_index.items():
        if not events:
            continue
        return_diffs = np.asarray(
            [
                event["strategies"][strategy]["total_return"]
                - event["strategies"]["S_full"]["total_return"]
                for event in events
            ],
            dtype=float,
        )
        drawdown_improvements = np.asarray(
            [
                event["strategies"]["S_full"]["max_drawdown"]
                - event["strategies"][strategy]["max_drawdown"]
                for event in events
            ],
            dtype=float,
        )
        paired_by_index[symbol] = (return_diffs, drawdown_improvements)

    if not paired_by_index:
        return {
            "n_events": 0,
            "mean_return_difference": None,
            "return_difference_ci95": [None, None],
            "mean_max_drawdown_improvement": None,
            "max_drawdown_improvement_ci95": [None, None],
        }

    all_return_diffs = np.concatenate([pair[0] for pair in paired_by_index.values()])
    all_drawdown_improvements = np.concatenate(
        [pair[1] for pair in paired_by_index.values()]
    )
    bootstrap_returns = np.empty(BOOTSTRAP_REPEATS, dtype=float)
    bootstrap_drawdowns = np.empty(BOOTSTRAP_REPEATS, dtype=float)
    for iteration in range(BOOTSTRAP_REPEATS):
        sampled_returns: list[np.ndarray] = []
        sampled_drawdowns: list[np.ndarray] = []
        for return_diffs, drawdown_improvements in paired_by_index.values():
            indices = rng.integers(0, len(return_diffs), size=len(return_diffs))
            sampled_returns.append(return_diffs[indices])
            sampled_drawdowns.append(drawdown_improvements[indices])
        bootstrap_returns[iteration] = float(np.mean(np.concatenate(sampled_returns)))
        bootstrap_drawdowns[iteration] = float(
            np.mean(np.concatenate(sampled_drawdowns))
        )

    return {
        "n_events": int(len(all_return_diffs)),
        "mean_return_difference": float(np.mean(all_return_diffs)),
        "return_difference_ci95": [
            float(value) for value in np.quantile(bootstrap_returns, (0.025, 0.975))
        ],
        "mean_max_drawdown_improvement": float(np.mean(all_drawdown_improvements)),
        "max_drawdown_improvement_ci95": [
            float(value)
            for value in np.quantile(bootstrap_drawdowns, (0.025, 0.975))
        ],
    }


def _decision(
    segments: dict[str, dict[str, Any]], strategy: str
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    passed = True
    for segment in ("dev", "test"):
        summary = segments[segment]["strategies"][strategy]
        full = segments[segment]["strategies"]["S_full"]
        paired = segments[segment]["paired_comparisons"][strategy]
        drawdown_lower = paired["max_drawdown_improvement_ci95"][0]
        win_rate_gap = (
            summary["win_rate"] - full["win_rate"]
            if summary["win_rate"] is not None and full["win_rate"] is not None
            else None
        )
        drawdown_ok = drawdown_lower is not None and drawdown_lower > 0
        win_rate_ok = win_rate_gap is not None and win_rate_gap >= -0.05
        checks[segment] = {
            "max_drawdown_improvement_ci_lower": drawdown_lower,
            "max_drawdown_condition": bool(drawdown_ok),
            "win_rate_difference_vs_S_full": win_rate_gap,
            "win_rate_condition": bool(win_rate_ok),
            "passes": bool(drawdown_ok and win_rate_ok),
        }
        passed = passed and checks[segment]["passes"]
    return {
        "decision": "成立" if passed else "不成立",
        "checks": checks,
        "cal_role": "仅报告，不参与判定",
    }


def run_study(data_dir: Path, cache_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    market_data: dict[str, dict[str, Any]] = {}
    coverage: dict[str, dict[str, Any]] = {}
    names: dict[str, str] = {}

    for symbol, name, _ in INDEX_LIST:
        frames, metadata = _load_frames(data_dir, symbol)
        unknown_splits = {
            frame.get("split")
            for frame in frames
            if frame.get("split") not in (*SEGMENTS, "live")
        }
        if unknown_splits:
            raise ValueError(f"{symbol}: unexpected split labels {sorted(unknown_splits)}")
        closes = [_number(frame.get("close")) for frame in frames]
        coverage[symbol] = {
            "history_path": metadata["path"],
            "frame_counts": {
                segment: sum(frame.get("split") == segment for frame in frames)
                for segment in (*SEGMENTS, "live")
            },
            "missing_close_counts": {
                segment: sum(
                    frame.get("split") == segment and closes[position] is None
                    for position, frame in enumerate(frames)
                )
                for segment in (*SEGMENTS, "live")
            },
            "excluded_live_frames": sum(frame.get("split") == "live" for frame in frames),
        }
        by_segment: dict[str, Any] = {}
        for segment in SEGMENTS:
            candidate_positions = [
                position
                for position, frame in enumerate(frames)
                if frame.get("split") == segment
                and _candidate(frame, position, closes)
            ]
            b3_candidate_positions = [
                position
                for position in candidate_positions
                if (score := score_100(frames[position])) is not None and score >= 50
            ]
            event_positions = eligible_event_positions(
                frames, closes, b3_candidate_positions, segment
            )
            b0_positions = [
                position
                for position in candidate_positions
                if _outcome(frames, closes, position, HORIZON_WEEKS) is not None
                and all(
                    frames[index].get("split") == segment
                    for index in range(position, position + HORIZON_WEEKS + 1)
                )
            ]
            results_by_position = {
                position: _event_result(symbol, position, frames, closes)
                for position in b0_positions
            }
            by_segment[segment] = {
                "b3_candidate_count": len(b3_candidate_positions),
                "event_positions": event_positions,
                "b0_positions": b0_positions,
                "results_by_position": results_by_position,
            }
        market_data[symbol] = {"frames": frames, "closes": closes, "segments": by_segment}
        names[symbol] = name

    random_rng = np.random.default_rng(SEED)
    bootstrap_rng = np.random.default_rng(SEED)
    segment_results: dict[str, dict[str, Any]] = {}
    for segment in SEGMENTS:
        events_by_index: dict[str, list[dict[str, Any]]] = {}
        pools_by_index: dict[str, list[dict[str, Any]]] = {}
        for symbol, *_ in INDEX_LIST:
            data = market_data[symbol]["segments"][segment]
            results = data["results_by_position"]
            events_by_index[symbol] = [
                results[position] for position in data["event_positions"]
            ]
            pools_by_index[symbol] = [
                results[position] for position in data["b0_positions"]
            ]
        all_events = [
            event
            for symbol, *_ in INDEX_LIST
            for event in events_by_index[symbol]
        ]
        summaries = {
            strategy: _strategy_summary(all_events, strategy) for strategy in STRATEGIES
        }
        random_baselines = _random_baseline(
            pools_by_index,
            {
                symbol: len(events_by_index[symbol])
                for symbol, *_ in INDEX_LIST
            },
            random_rng,
        )
        paired = {
            strategy: _paired_comparison(events_by_index, strategy, bootstrap_rng)
            for strategy in ("S_confirm", "S_fixed")
        }
        segment_results[segment] = {
            "n_events": len(all_events),
            "n_events_by_index": {
                symbol: len(events_by_index[symbol]) for symbol, *_ in INDEX_LIST
            },
            "n_b0_random_candidates_by_index": {
                symbol: len(pools_by_index[symbol]) for symbol, *_ in INDEX_LIST
            },
            "strategies": summaries,
            "random_baseline": random_baselines,
            "paired_comparisons": paired,
        }

    decisions = {
        strategy: _decision(segment_results, strategy)
        for strategy in ("S_confirm", "S_fixed")
    }
    runtime = time.perf_counter() - started
    return {
        "study": "bottom_entry_schedule",
        "seed": SEED,
        "random_repeats": RANDOM_REPEATS,
        "bootstrap_repeats": BOOTSTRAP_REPEATS,
        "cooldown_weeks": EVENT_COOLDOWN_WEEKS,
        "horizon_weeks": HORIZON_WEEKS,
        "confirmation_window_weeks": CONFIRMATION_WEEKS,
        "strategies": list(STRATEGIES),
        "inputs": {
            "weekly_data_dir": str(data_dir),
            "cache_root_argument": str(cache_root),
            "daily_cache_used": False,
            "indexes": [
                {"symbol": symbol, "name": name}
                for symbol, name, _ in INDEX_LIST
            ],
            "coverage": coverage,
        },
        "segments": segment_results,
        "decisions": decisions,
        "runtime_seconds": float(runtime),
    }


def _fmt_percent(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _fmt_quantiles(values: list[float | None]) -> str:
    return " / ".join(_fmt_percent(value) for value in values)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 底部分批建仓规则回测",
        "",
        f"- 事件：每指数、每段 B3（未取整 score_100 ≥ 50）候选周，按 {report['cooldown_weeks']} 周冷却独立化；要求同段内有有效 50 周结果。",
        "- 纳入 dev/cal/test；live 不参与。",
        f"- 随机基准：每段、每指数从有效 B0 候选周无放回抽取与 B3 事件等量的周，{report['random_repeats']} 次；seed={report['seed']}。",
        f"- 配对 CI：按指数分层的事件级 bootstrap，{report['bootstrap_repeats']} 次；seed={report['seed']}。",
        "- 收益按初始总资金计算；现金收益为 0。回撤为周收盘权益峰谷最大回撤；资金占用率为 51 个周收盘点上累计投入本金比例的事件均值。",
        "- 投入资金收益为组合收益除以累计投入本金；未投入事件不计入该中位数。",
        f"- Runtime: {report['runtime_seconds']:.3f} seconds。",
        "",
        "## 分段 × 策略结果",
        "",
        "| Segment | Strategy | n_events | Mean return | Median return | Win rate | Median max DD | P90 max DD | Avg capital occupied | Median return on invested capital | Confirm rate | Median confirm weeks |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for segment in SEGMENTS:
        for strategy in STRATEGIES:
            row = report["segments"][segment]["strategies"][strategy]
            lines.append(
                "| "
                + " | ".join(
                    (
                        segment,
                        strategy,
                        str(row["n_events"]),
                        _fmt_percent(row["mean_return"]),
                        _fmt_percent(row["median_return"]),
                        _fmt_percent(row["win_rate"]),
                        _fmt_percent(row["median_max_drawdown"]),
                        _fmt_percent(row["p90_max_drawdown"]),
                        _fmt_percent(row["average_capital_occupied"]),
                        _fmt_percent(row["median_return_on_invested_capital"]),
                        _fmt_percent(row["confirmation_trigger_rate"]),
                        (
                            f"{row['median_confirmation_weeks']:.1f}"
                            if row["median_confirmation_weeks"] is not None
                            else "—"
                        ),
                    )
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "## 随机基准（每次重复的胜率 / 中位收益分布）",
            "",
            "| Segment | Strategy | Win rate P5 / P50 / P95 | Median return P5 / P50 / P95 |",
            "|---|---|---:|---:|",
        ]
    )
    for segment in SEGMENTS:
        for strategy in STRATEGIES:
            row = report["segments"][segment]["random_baseline"][strategy]
            lines.append(
                f"| {segment} | {strategy} | "
                f"{_fmt_quantiles(row['win_rate_5_50_95'])} | "
                f"{_fmt_quantiles(row['median_return_5_50_95'])} |"
            )

    lines.extend(
        [
            "",
            "## 配对比较",
            "",
            "| Segment | Strategy − S_full | Mean return difference (95% CI) | Mean max-DD improvement (95% CI; positive is better) | n_events |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for segment in SEGMENTS:
        for strategy in ("S_confirm", "S_fixed"):
            row = report["segments"][segment]["paired_comparisons"][strategy]
            return_ci = row["return_difference_ci95"]
            drawdown_ci = row["max_drawdown_improvement_ci95"]
            lines.append(
                f"| {segment} | {strategy} | "
                f"{_fmt_percent(row['mean_return_difference'])} "
                f"({_fmt_percent(return_ci[0])} to {_fmt_percent(return_ci[1])}) | "
                f"{_fmt_percent(row['mean_max_drawdown_improvement'])} "
                f"({_fmt_percent(drawdown_ci[0])} to {_fmt_percent(drawdown_ci[1])}) | "
                f"{row['n_events']} |"
            )

    lines.extend(
        [
            "",
            "## 事先判定",
            "",
            "规则须同时满足 dev 与 test 的最大回撤改善 95% CI 下界 > 0，且胜率不比 S_full 低超过 5 个百分点；cal 仅报告。",
            "",
            "| Strategy | Decision | Dev DD-CI lower > 0 | Dev win-rate condition | Test DD-CI lower > 0 | Test win-rate condition |",
            "|---|---|---|---|---|---|",
        ]
    )
    for strategy in ("S_confirm", "S_fixed"):
        decision = report["decisions"][strategy]
        checks = decision["checks"]
        lines.append(
            f"| {strategy} | {decision['decision']} | "
            f"{checks['dev']['max_drawdown_condition']} | "
            f"{checks['dev']['win_rate_condition']} | "
            f"{checks['test']['max_drawdown_condition']} | "
            f"{checks['test']['win_rate_condition']} |"
        )

    lines.extend(
        [
            "",
            "## 数据覆盖",
            "",
            "| Index | Dev | Cal | Test | Live excluded | Missing closes (dev/cal/test) |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for symbol, name, _ in INDEX_LIST:
        row = report["inputs"]["coverage"][symbol]
        counts = row["frame_counts"]
        missing = row["missing_close_counts"]
        lines.append(
            f"| {symbol} ({name}) | {counts['dev']} | {counts['cal']} | "
            f"{counts['test']} | {row['excluded_live_frames']} | "
            f"{missing['dev']}/{missing['cal']}/{missing['test']} |"
        )
    lines.extend(
        [
            "",
            "This study uses weekly frame closes only; the `--cache-root` argument is accepted for CLI consistency but no daily cache is needed.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()

    report = run_study(args.data_dir, args.cache_root)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.report_dir / "bottom_entry_schedule.json"
    markdown_path = args.report_dir / "bottom_entry_schedule.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    print(f"Runtime: {report['runtime_seconds']:.3f} seconds")


if __name__ == "__main__":
    main()
