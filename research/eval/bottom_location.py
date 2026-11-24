"""Evaluate whether bottom-score buckets locate trough-price regions."""
from __future__ import annotations

import argparse
import json
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
    bucket_membership,
    independent_positions,
    score_100,
)
from research.pipeline.overview_export import INDEX_LIST

GROUPS = ("B0", "B1", "B2", "B3")
WINDOWS = (13, 26)
RANDOM_REPEATS = 2000


def window_metrics(
    closes: list[float | None], t0: int, window: int
) -> dict[str, Any] | None:
    start = t0 - window
    end = t0 + window
    if start < 0 or end >= len(closes):
        return None
    values = closes[start : end + 1]
    if any(value is None for value in values):
        return None

    numeric_values = [float(value) for value in values if value is not None]
    minimum = min(numeric_values)
    maximum = max(numeric_values)
    close = closes[t0]
    if close is None:
        return None
    if minimum <= 0:
        raise ValueError(f"non-positive close in trough window at position {t0}")
    trough_position = start + numeric_values.index(minimum)
    trough_offset = trough_position - t0
    range_position = (
        None if maximum == minimum else (float(close) - minimum) / (maximum - minimum)
    )
    return {
        "dist_to_trough": float(float(close) / minimum - 1.0),
        "range_pos": float(range_position) if range_position is not None else None,
        "in_bottom_zone": (
            bool(range_position <= 0.20) if range_position is not None else None
        ),
        "trough_offset": int(trough_offset),
        "trough_ahead": bool(trough_offset > 0),
        "within_4_weeks": bool(abs(trough_offset) <= 4),
    }


def valid_window(
    frames: list[dict[str, Any]],
    closes: list[float | None],
    t0: int,
    segment: str,
    window: int,
) -> bool:
    start = t0 - window
    end = t0 + window
    if start < 0 or end >= len(frames):
        return False
    return all(
        frames[position].get("split") == segment and closes[position] is not None
        for position in range(start, end + 1)
    )


def eligible_group_positions(
    frames: list[dict[str, Any]],
    closes: list[float | None],
    candidate_positions: list[int],
    segment: str,
    window: int,
) -> list[int]:
    positions = sorted(
        position
        for position in candidate_positions
        if 0 <= position < len(frames) and frames[position].get("split") == segment
    )
    independent = independent_positions(positions, cooldown=EVENT_COOLDOWN_WEEKS)
    return [
        position
        for position in independent
        if valid_window(frames, closes, position, segment, window)
    ]


def _group_candidate_positions(
    frames: list[dict[str, Any]],
    closes: list[float | None],
    segment: str,
) -> dict[str, list[int]]:
    groups = {group: [] for group in GROUPS}
    for position, frame in enumerate(frames):
        if frame.get("split") != segment or not _candidate(frame, position, closes):
            continue
        groups["B0"].append(position)
        memberships = bucket_membership(score_100(frame), omori_green=False)
        for group in GROUPS[1:]:
            if memberships[group]:
                groups[group].append(position)
    return groups


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {
            "n_events": 0,
            "median_dist_to_trough": None,
            "p75_dist_to_trough": None,
            "median_range_pos": None,
            "in_bottom_zone_share": None,
            "median_trough_offset": None,
            "trough_ahead_share": None,
            "within_4_weeks_share": None,
            "n_defined_range_pos": 0,
        }

    distances = [event["dist_to_trough"] for event in events]
    range_positions = [
        event["range_pos"] for event in events if event["range_pos"] is not None
    ]
    zone_values = [
        event["in_bottom_zone"]
        for event in events
        if event["in_bottom_zone"] is not None
    ]
    trough_offsets = [event["trough_offset"] for event in events]
    trough_ahead = [event["trough_ahead"] for event in events]
    within_4_weeks = [event["within_4_weeks"] for event in events]
    return {
        "n_events": len(events),
        "median_dist_to_trough": float(np.median(distances)),
        "p75_dist_to_trough": float(np.quantile(distances, 0.75)),
        "median_range_pos": (
            float(np.median(range_positions)) if range_positions else None
        ),
        "in_bottom_zone_share": (
            float(np.mean(zone_values)) if zone_values else None
        ),
        "median_trough_offset": float(np.median(trough_offsets)),
        "trough_ahead_share": float(np.mean(trough_ahead)),
        "within_4_weeks_share": float(np.mean(within_4_weeks)),
        "n_defined_range_pos": len(range_positions),
    }


def _quantiles(values: list[float], probabilities: tuple[float, ...]) -> list[float | None]:
    if not values:
        return [None for _ in probabilities]
    return [float(value) for value in np.quantile(values, probabilities)]


def random_baseline(
    pools_by_index: dict[str, list[dict[str, Any]]],
    event_counts: dict[str, int],
    rng: np.random.Generator,
    repeats: int = RANDOM_REPEATS,
) -> dict[str, Any]:
    samples: dict[str, list[float]] = {
        "in_bottom_zone_share": [],
        "median_dist_to_trough": [],
        "within_4_weeks_share": [],
    }
    for _ in range(repeats):
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
        summary = summarize_events(selected)
        for metric in samples:
            value = summary[metric]
            if value is not None:
                samples[metric].append(float(value))
    return {
        "n_events": sum(event_counts.values()),
        "in_bottom_zone_share_5_50_95": _quantiles(
            samples["in_bottom_zone_share"], (0.05, 0.5, 0.95)
        ),
        "median_dist_to_trough_5_50_95": _quantiles(
            samples["median_dist_to_trough"], (0.05, 0.5, 0.95)
        ),
        "within_4_weeks_share_5_50_95": _quantiles(
            samples["within_4_weeks_share"], (0.05, 0.5, 0.95)
        ),
    }


def _decision(segments: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    passed = True
    for segment in ("dev", "test"):
        row = segments[segment]["W26"]["groups"]["B3"]
        baseline = row["random_baseline"]
        zone_p95 = baseline["in_bottom_zone_share_5_50_95"][2]
        distance_p5 = baseline["median_dist_to_trough_5_50_95"][0]
        zone_share = row["in_bottom_zone_share"]
        median_distance = row["median_dist_to_trough"]
        zone_ok = zone_share is not None and zone_p95 is not None and zone_share > zone_p95
        distance_ok = (
            median_distance is not None
            and distance_p5 is not None
            and median_distance < distance_p5
        )
        checks[segment] = {
            "b3_in_bottom_zone_share": zone_share,
            "random_in_bottom_zone_share_p95": zone_p95,
            "in_bottom_zone_condition": bool(zone_ok),
            "b3_median_dist_to_trough": median_distance,
            "random_median_dist_to_trough_p5": distance_p5,
            "distance_condition": bool(distance_ok),
            "passes": bool(zone_ok and distance_ok),
        }
        passed = passed and checks[segment]["passes"]
    return {
        "decision": "成立" if passed else "不成立",
        "window_weeks": 26,
        "checks": checks,
        "cal_role": "仅报告，不参与判定",
    }


def _make_segment_window_summary(
    market_data: dict[str, dict[str, Any]],
    segment: str,
    window: int,
    rng: np.random.Generator,
) -> dict[str, Any]:
    events_by_group: dict[str, dict[str, list[dict[str, Any]]]] = {
        group: {} for group in GROUPS
    }
    b0_pools_by_index: dict[str, list[dict[str, Any]]] = {}

    for symbol, *_ in INDEX_LIST:
        market = market_data[symbol]
        candidates = market["candidate_positions"][segment]
        frames = market["frames"]
        closes = market["closes"]
        for group in GROUPS:
            positions = eligible_group_positions(
                frames, closes, candidates[group], segment, window
            )
            events_by_group[group][symbol] = [
                metrics
                for position in positions
                if (metrics := window_metrics(closes, position, window)) is not None
            ]
        b0_pools_by_index[symbol] = [
            metrics
            for position in candidates["B0"]
            if valid_window(frames, closes, position, segment, window)
            and (metrics := window_metrics(closes, position, window)) is not None
        ]

    groups: dict[str, dict[str, Any]] = {}
    b1_worse_than_random: bool | None = None
    for group in GROUPS:
        event_counts = {
            symbol: len(events_by_group[group][symbol]) for symbol, *_ in INDEX_LIST
        }
        events = [
            event
            for symbol, *_ in INDEX_LIST
            for event in events_by_group[group][symbol]
        ]
        summary = summarize_events(events)
        if group == "B0":
            summary["random_baseline"] = None
            summary["significantly_worse_than_random"] = None
        else:
            baseline = random_baseline(b0_pools_by_index, event_counts, rng)
            summary["random_baseline"] = baseline
            summary["n_events_by_index"] = event_counts
            if group == "B1":
                random_zone_p5 = baseline["in_bottom_zone_share_5_50_95"][0]
                observed_zone = summary["in_bottom_zone_share"]
                b1_worse_than_random = (
                    bool(observed_zone < random_zone_p5)
                    if observed_zone is not None and random_zone_p5 is not None
                    else None
                )
                summary["significantly_worse_than_random"] = b1_worse_than_random
            else:
                summary["significantly_worse_than_random"] = None
        groups[group] = summary

    return {
        "groups": groups,
        "b1_significantly_worse_than_random": b1_worse_than_random,
    }


def run_study(data_dir: Path, cache_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    market_data: dict[str, dict[str, Any]] = {}
    coverage: dict[str, dict[str, Any]] = {}
    for symbol, _, _ in INDEX_LIST:
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
        market_data[symbol] = {
            "frames": frames,
            "closes": closes,
            "candidate_positions": {
                segment: _group_candidate_positions(frames, closes, segment)
                for segment in SEGMENTS
            },
        }

    rng = np.random.default_rng(SEED)
    segment_results: dict[str, Any] = {}
    for segment in SEGMENTS:
        segment_results[segment] = {
            f"W{window}": _make_segment_window_summary(
                market_data, segment, window, rng
            )
            for window in WINDOWS
        }
    decisions = {
        "b3_locates_bottom_zone_W26": _decision(segment_results),
        "b1_worse_than_random": {
            segment: {
                f"W{window}": segment_results[segment][f"W{window}"][
                    "b1_significantly_worse_than_random"
                ]
                for window in WINDOWS
            }
            for segment in SEGMENTS
        },
    }
    runtime = time.perf_counter() - started
    return {
        "study": "bottom_location",
        "seed": SEED,
        "random_repeats": RANDOM_REPEATS,
        "cooldown_weeks": EVENT_COOLDOWN_WEEKS,
        "windows": list(WINDOWS),
        "groups": list(GROUPS),
        "inputs": {
            "weekly_data_dir": str(data_dir),
            "cache_root_argument": str(cache_root),
            "daily_cache_used": False,
            "indexes": [
                {"symbol": symbol, "name": name} for symbol, name, _ in INDEX_LIST
            ],
            "coverage": coverage,
        },
        "segments": segment_results,
        "decisions": decisions,
        "runtime_seconds": float(runtime),
    }


def _fmt_percent(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _fmt_number(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _fmt_quantiles(values: list[float | None], percent: bool) -> str:
    formatter = _fmt_percent if percent else _fmt_number
    return " / ".join(formatter(value) for value in values)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 底分能否定位底部价格区域",
        "",
        f"- 事件：复用底部候选定义，每指数、每段、每组独立化（cooldown={report['cooldown_weeks']} 周）；live 排除。",
        "- 窗口有效条件：t0−W 至 t0+W 每帧均存在、收盘非空且 split 与 t0 相同。",
        f"- 随机基准：每段、每指数从有效 B0 候选周无放回抽取与该组事件数相同的周，{report['random_repeats']} 次；seed={report['seed']}。B0 不做随机比较。",
        "- `range_pos` 在 max==min 时为 None；最低价并列时取窗口内最早一周。",
        f"- Runtime: {report['runtime_seconds']:.3f} seconds。",
    ]
    for window in WINDOWS:
        lines.extend(
            [
                "",
                f"## W={window}",
                "",
                "| Segment | Group | n_events | Median dist_to_trough | P75 dist_to_trough | Median range_pos | In-bottom-zone share | Median trough_offset | Trough-ahead share | \\|offset\\|≤4 share |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for segment in SEGMENTS:
            for group in GROUPS:
                row = report["segments"][segment][f"W{window}"]["groups"][group]
                lines.append(
                    f"| {segment} | {group} | {row['n_events']} | "
                    f"{_fmt_percent(row['median_dist_to_trough'])} | "
                    f"{_fmt_percent(row['p75_dist_to_trough'])} | "
                    f"{_fmt_number(row['median_range_pos'])} | "
                    f"{_fmt_percent(row['in_bottom_zone_share'])} | "
                    f"{_fmt_number(row['median_trough_offset'], 1)} | "
                    f"{_fmt_percent(row['trough_ahead_share'])} | "
                    f"{_fmt_percent(row['within_4_weeks_share'])} |"
                )
        lines.extend(
            [
                "",
                "### 随机基准（B1–B3，P5 / P50 / P95）",
                "",
                "| Segment | Group | In-bottom-zone share | Median dist_to_trough | \\|offset\\|≤4 share |",
                "|---|---|---:|---:|---:|",
            ]
        )
        for segment in SEGMENTS:
            for group in GROUPS[1:]:
                row = report["segments"][segment][f"W{window}"]["groups"][group]
                baseline = row["random_baseline"]
                lines.append(
                    f"| {segment} | {group} | "
                    f"{_fmt_quantiles(baseline['in_bottom_zone_share_5_50_95'], True)} | "
                    f"{_fmt_quantiles(baseline['median_dist_to_trough_5_50_95'], True)} | "
                    f"{_fmt_quantiles(baseline['within_4_weeks_share_5_50_95'], True)} |"
                )

    decision = report["decisions"]["b3_locates_bottom_zone_W26"]
    lines.extend(
        [
            "",
            "## 判定",
            "",
            "W=26 下 dev 与 test 的 B3 `in_bottom_zone` share 均须严格高于随机 P95，且 `median dist_to_trough` 均须严格低于随机 P5；cal 只报告。",
            "",
            f"**B3 能定位底部区域：{decision['decision']}**",
            "",
            "| Segment | B3 zone share | Random P95 | Zone condition | B3 median distance | Random P5 | Distance condition |",
            "|---|---:|---:|---|---:|---:|---|",
        ]
    )
    for segment in ("dev", "test"):
        row = decision["checks"][segment]
        lines.append(
            f"| {segment} | {_fmt_percent(row['b3_in_bottom_zone_share'])} | "
            f"{_fmt_percent(row['random_in_bottom_zone_share_p95'])} | "
            f"{row['in_bottom_zone_condition']} | "
            f"{_fmt_percent(row['b3_median_dist_to_trough'])} | "
            f"{_fmt_percent(row['random_median_dist_to_trough_p5'])} | "
            f"{row['distance_condition']} |"
        )
    lines.extend(
        [
            "",
            "### B1 是否显著差于随机",
            "",
            "| W | Segment | B1 zone share | Random P5 | Significantly worse |",
            "|---:|---|---:|---:|---|",
        ]
    )
    for window in WINDOWS:
        for segment in SEGMENTS:
            row = report["segments"][segment][f"W{window}"]["groups"]["B1"]
            baseline = row["random_baseline"]
            lines.append(
                f"| {window} | {segment} | {_fmt_percent(row['in_bottom_zone_share'])} | "
                f"{_fmt_percent(baseline['in_bottom_zone_share_5_50_95'][0])} | "
                f"{row['significantly_worse_than_random']} |"
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
            "This study uses weekly frame closes only; no daily cache data is required.",
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
    json_path = args.report_dir / "bottom_location.json"
    markdown_path = args.report_dir / "bottom_location.md"
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
