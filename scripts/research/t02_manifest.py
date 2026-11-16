#!/usr/bin/env python3
"""Generate the guarded T02 scoring contract and saved-replay reports."""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from research.eval.top_time.contracts import (
    LABEL_VERSION,
    SCORING_CONTRACT_VERSION,
    LabelBook,
    LabelState,
    Forecast,
    Protocol,
    ScheduledRun,
    TopEvent,
)
from research.eval.top_time.labels import build_labels
from research.eval.top_time.t02 import (
    PRIMARY_CAUSE_PRIORITY,
    AppendOnlyClaimLedger,
    formal_interval_gate,
    score_t02,
    unknown_label_rows,
)
from research.eval.top_time.scoring import evaluate as evaluate_pr50

OUTPUT = ROOT / "reports/lppls_handoff/t02_20261116_a1"
FIXTURE = ROOT / "tests/fixtures/top_time_t02/hand_cases.json"
PR50_SHA = "7f7fe930ab4065295718dfcfe89b87cedcaaf1fb"
PR50_EVIDENCE = "docs/research/evidence/top-time-replay-20261106/v1"
SYMBOLS = ("sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006")
ARMS = (
    "ref_6_12m", "ref_12_24m", "or2_full", "or4_full", "or4_thin",
    "cluster_any_full", "cluster_cross_full", "cluster_cross_thin",
    "cluster_cross_stable2", "calendar_fixed_10",
)
UNAVAILABLE = {"NO_CACHED_FIT", "INPUT_UNAVAILABLE"}
AVAILABLE = {"NO_SIGNAL", "HYPOTHETICAL_INTERVAL"}


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _git_blob(path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{PR50_SHA}:{PR50_EVIDENCE}/{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return result.stdout


def _git_source_blob(path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{PR50_SHA}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return result.stdout


def _json_gz(path: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in gzip.decompress(_git_blob(path)).decode("utf-8").splitlines()
        if line
    ]


def _csv_bytes(content: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content.decode("utf-8"), newline="")))


def _csv_gz(path: str) -> list[dict[str, str]]:
    return _csv_bytes(gzip.decompress(_git_blob(path)))


def _truth(value: str) -> bool:
    if value == "True":
        return True
    if value == "False":
        return False
    raise ValueError(f"saved evidence boolean is not explicit: {value!r}")


def _book_from_saved(row: dict[str, Any]) -> LabelBook:
    events = []
    for saved in row["events"]:
        event = dict(saved)
        event["candidate_sessions"] = tuple(event["candidate_sessions"])
        events.append(TopEvent(**event))
    return LabelBook(
        symbol=row["symbol"],
        sessions=tuple(row["sessions"]),
        asof_session=row["asof_session"],
        events=events,
        known={scale: tuple(values) for scale, values in row["known"].items()},
        pending=row["pending"],
        excluded=row["excluded"],
        metadata=row["metadata"],
    )


def _run_id(symbol: str, arm: str, scope: str, day: str) -> str:
    return f"run:{symbol}:{arm}:{scope}:{day}"


def _evaluate_saved_group(
    key: tuple[str, str, str],
    book: LabelBook,
    forecast_rows: list[dict[str, str]],
    daily_rows: list[dict[str, str]],
    reference: dict[str, Any],
) -> tuple[Any, list[Forecast], list[ScheduledRun]]:
    symbol, arm, scope = key
    scheduled = [row for row in daily_rows if _truth(row["scheduled"])]
    runs = []
    run_by_day: dict[str, ScheduledRun] = {}
    for row in scheduled:
        status = {
            "HYPOTHETICAL_INTERVAL": "ON_TIME_INTERVAL",
            "NO_SIGNAL": "ON_TIME_NO_SIGNAL",
            "NO_CACHED_FIT": "FAILED",
            "INPUT_UNAVAILABLE": "FAILED",
        }.get(row["status"], "FAILED")
        run = ScheduledRun(
            _run_id(symbol, arm, scope, row["date"]),
            symbol,
            int(row["session"]),
            status,
        )
        runs.append(run)
        run_by_day[row["date"]] = run

    forecasts = []
    for row in forecast_rows:
        if row["status"] != "HYPOTHETICAL_INTERVAL" or not row["new_forecast_id"]:
            continue
        run = run_by_day.get(row["date"])
        forecasts.append(Forecast(
            prediction_id=row["new_forecast_id"],
            episode_id=row["episode_id"],
            symbol=symbol,
            scope=scope,
            interval_start=int(row["interval_start"]),
            interval_end=int(row["interval_end"]),
            data_cutoff_session=int(row["session"]),
            published_session=int(row["session"]),
            published_at=row["hypothetical_published_at"],
            action_session=int(row["hypothetical_action_session"]),
            actionability=row["actionability"],
            on_time=True,
            run_id=run.run_id if run else None,
        ))
    result = evaluate_pr50(
        book,
        forecasts,
        runs,
        config=Protocol(),
        mode="diagnostic",
        start_session=int(reference["metadata"]["start_session"]),
        end_session=int(reference["metadata"]["end_session"]),
    )
    return result, forecasts, runs


def _saved_claim_rows(
    rows: list[dict[str, str]],
    scope: str,
    expiry_by_forecast_id: dict[str, int],
) -> list[dict[str, Any]]:
    ordered = sorted(
        (row for row in rows if row["status"] == "HYPOTHETICAL_INTERVAL"),
        key=lambda row: (int(row["session"]), row["new_forecast_id"]),
    )
    first_formal: dict[str, dict[str, Any]] = {}
    last_claim: dict[str, str] = {}
    seen_episode: set[str] = set()
    claims = []
    ledger = AppendOnlyClaimLedger()
    for row in ordered:
        action = int(row["hypothetical_action_session"])
        start, end = int(row["interval_start"]), int(row["interval_end"])
        claim_id = row["new_forecast_id"]
        if claim_id not in expiry_by_forecast_id:
            raise RuntimeError(f"saved replay has no fixed expiry for {claim_id}")
        fixed_expiry = expiry_by_forecast_id[claim_id]
        gate = (
            {"formal": False}
            if end < start
            else formal_interval_gate(action, start, end)
        )
        episode = row["episode_id"]
        if not gate["formal"]:
            kind = "observation"
            first = first_formal.get(episode)
        elif episode not in first_formal:
            kind = "new" if episode not in seen_episode else "formal"
            first = {
                "interval_start": start,
                "interval_end": end,
                "first_clock_session": action,
                "fixed_expiry_session": fixed_expiry,
            }
            first_formal[episode] = first
        else:
            kind = "revision"
            first = first_formal[episode]
        if first is None:
            first_fields = {
                "first_interval_start": start,
                "first_interval_end": end,
                "first_clock_session": action,
                "fixed_expiry_session": max(action, end),
            }
        else:
            first_fields = {
                "first_interval_start": first["interval_start"],
                "first_interval_end": first["interval_end"],
                "first_clock_session": first["first_clock_session"],
                "fixed_expiry_session": first["fixed_expiry_session"],
            }
        previous = last_claim.get(episode)
        claim = {
            "claim_id": claim_id,
            "parent_claim_id": previous,
            "episode_id": episode,
            "kind": kind,
            "scope": scope,
            "interval_start": start,
            "interval_end": end,
            **first_fields,
            "action_session": action,
            "mode": "historical_replay",
            "first_visible_at": None,
            "simulated_available_at": row["hypothetical_published_at"],
            "simulated_action_session": action,
            "delay_assumption": (
                "saved interval assumed available at close of its as-of session; "
                "next observed session is the action session"
            ),
            "vintage_status": "HISTORICAL_VINTAGE_NOT_ESTABLISHED",
        }
        ledger.append(claim)
        claims.append(claim)
        last_claim[episode] = claim_id
        seen_episode.add(episode)
    return ledger.to_list()


def _event_data_evaluable(
    event: TopEvent,
    daily_rows: list[dict[str, str]],
    horizon: int,
) -> bool:
    opportunities = []
    for row in daily_rows:
        if not _truth(row["scheduled"]):
            continue
        action = int(row["session"]) + 1
        if event.peak_session - horizon <= action < event.peak_session:
            opportunities.append(row["status"])
    return bool(opportunities) and all(status in AVAILABLE for status in opportunities)


def _attribution_flags(
    event: dict[str, Any],
    first: dict[str, str] | None,
    *,
    data_evaluable: bool,
) -> tuple[list[str], str]:
    flags = []
    if not data_evaluable:
        flags.append("data_not_evaluable")
    if first is None:
        flags.append("no_alert")
    else:
        start, end = int(first["interval_start"]), int(first["interval_end"])
        action = int(first["hypothetical_action_session"])
        peak = int(event["peak_session"])
        if start > end:
            flags.append("reversed")
        if start <= action or action <= int(first["session"]):
            flags.append("non_future")
        if end > action + 63:
            flags.append("beyond_H")
        width = end - start + 1
        if width > 10:
            flags.append("too_wide")
        if end < peak:
            flags.append("early")
        elif start > peak:
            flags.append("late")
        if peak - action < 5 or start - action < 5:
            flags.append("insufficient_lead")
    groups = {
        "data_not_evaluable": "data_not_evaluable",
        "no_alert": "no_alert",
        "reversed": "reversed_non_future_beyond_H",
        "non_future": "reversed_non_future_beyond_H",
        "beyond_H": "reversed_non_future_beyond_H",
        "too_wide": "too_wide",
        "early": "early_late",
        "late": "early_late",
        "insufficient_lead": "insufficient_lead",
    }
    present = set(flags)
    primary = next(
        cause for cause in PRIMARY_CAUSE_PRIORITY
        if cause == "success" and not flags
        or cause in {groups.get(flag) for flag in present}
    )
    return flags, primary


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                if isinstance(value, (dict, list, tuple))
                else value
                for key, value in row.items()
            })


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_report(
    path: Path,
    results: list[dict[str, Any]],
    attribution_counts: dict[str, dict[str, int]],
    source_manifest: dict[str, Any],
    semantic: dict[str, Any],
    unknown_count: int,
    old_reproduction_mismatches: list[str],
) -> None:
    lines = [
        "# T02 两级评分并列比较",
        "",
        "**评分定义变化，不算模型进步。** 历史重放只使用 PR #50 保存的区间和标签资料；所有发布时刻均为假设值，不能解释为真实提前提醒。",
        "",
        f"- T02 版本：`{SCORING_CONTRACT_VERSION}`；PR #50 evaluator：`{source_manifest['source_parameters']['evaluator_version']}`。",
        f"- PR #50 保存范围：{len(results)} 个 symbol×arm×scope 评分组；stage event-arm attribution 为 {sum(sum(counts.values()) for counts in attribution_counts.values())} 行。",
        f"- 本次新标签表未成熟/未知状态：{unknown_count} 个 `(scale, session)`。",
        f"- sh000001 语义检查：{semantic['status']}（short 2024-03-18；stage 2024-05-20）。",
        f"- PR #50 evaluator 重放与保存 metrics 的关键字段不一致数：{len(old_reproduction_mismatches)}。",
        "",
        "## 指标差异",
        "",
        "| arm | scope | metric | PR #50 | T02 | 旧分母 | 新分母 |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    metric_rows = {
        "stage": (
            ("E", "E", "E"),
            ("P", "P", "resolved_claims_denominator"),
            ("TP", "TP", "strict_success_count"),
            ("FP", "FP", "resolved_false_positive_count"),
            ("FN", "FN", "missed_event_count"),
            ("no_formal_alert_rate", "no_formal_alert_rate", "no_formal_alert_rate"),
            ("first_window_coverage", "first_window_coverage", "first_window_coverage"),
            ("QualifiedStageRecall5", "QualifiedStageRecall5", "QualifiedStageRecall5"),
            ("StrictStageRecall5W10", "strict_recall", "StrictStageRecall5W10"),
            ("strict_stage_miss_rate", "strict_miss", "strict_stage_miss_rate"),
            ("resolved_claim_precision", "precision", "resolved_claim_precision"),
            ("duplicate_notices", "duplicate_notices", "duplicate_notices"),
            ("pending_claims", "pending_claims", "pending_claims"),
            ("revisions", "revisions", "revisions"),
            ("claim_notices", "claim_notices", "claim_notices"),
            ("formal_alerts", "NOT_DEFINED", "formal_alerts"),
            ("observation_notices", "NOT_DEFINED", "observation_notices"),
            ("alerts_per_asset_year", "alerts_per_asset_year", "alerts_per_asset_year"),
            ("alarm_occupied_days", "alarm_occupied_days", "alarm_occupied_days"),
            ("formal_alarm_occupied_days", "NOT_DEFINED", "formal_alarm_occupied_days"),
        ),
        "short": (
            ("E", "E", "E"),
            ("P", "P", "resolved_claims_denominator"),
            ("TP", "TP", "strict_success_count"),
            ("FP", "FP", "resolved_false_positive_count"),
            ("FN", "FN", "missed_event_count"),
            ("no_formal_alert_rate", "no_formal_alert_rate", "no_formal_alert_rate"),
            ("first_window_coverage", "first_window_coverage", "first_window_coverage"),
            ("QualifiedShortRecall5", "QualifiedShortRecall5", "QualifiedShortRecall5"),
            ("StrictShortRecall5W10", "strict_recall", "StrictShortRecall5W10"),
            ("strict_short_miss_rate", "strict_miss", "strict_short_miss_rate"),
            ("resolved_claim_precision", "precision", "resolved_claim_precision"),
            ("duplicate_notices", "duplicate_notices", "duplicate_notices"),
            ("pending_claims", "pending_claims", "pending_claims"),
            ("revisions", "revisions", "revisions"),
            ("claim_notices", "claim_notices", "claim_notices"),
            ("formal_alerts", "NOT_DEFINED", "formal_alerts"),
            ("observation_notices", "NOT_DEFINED", "observation_notices"),
            ("alerts_per_asset_year", "alerts_per_asset_year", "alerts_per_asset_year"),
            ("alarm_occupied_days", "alarm_occupied_days", "alarm_occupied_days"),
            ("formal_alarm_occupied_days", "NOT_DEFINED", "formal_alarm_occupied_days"),
        ),
    }
    for result in sorted(results, key=lambda row: (row["arm"], row["scope"])):
        old = result["old_metrics"]
        new = result["new_metrics"]
        for metric, old_key, new_key in metric_rows[result["scope"]]:
            old_value = "not_defined" if old_key == "NOT_DEFINED" else old.get(old_key)
            new_value = new.get(new_key)
            if metric == "resolved_claim_precision":
                old_denominator = old.get("P")
                new_denominator = new.get("resolved_claims_denominator")
            elif metric in {
                "E", "no_formal_alert_rate", "first_window_coverage",
                "QualifiedStageRecall5", "StrictStageRecall5W10", "strict_stage_miss_rate",
                "QualifiedShortRecall5", "StrictShortRecall5W10", "strict_short_miss_rate",
            }:
                old_denominator = old.get("E")
                new_denominator = new.get("E")
            elif metric == "alerts_per_asset_year":
                old_denominator = old.get("asset_years")
                new_denominator = new.get("asset_years")
            else:
                old_denominator = new_denominator = "—"
            lines.append(
                f"| {result['arm']} | {result['scope']} | {metric} | {old_value if old_value is not None else 'null'} "
                f"| {new_value if new_value is not None else 'null'} "
                f"| {old_denominator if old_denominator is not None else 'null'} "
                f"| {new_denominator if new_denominator is not None else 'null'} |"
            )
    lines.extend([
        "",
        "### 数据可评价子集（独立 E）",
        "",
        "| arm | scope | PR #50 E | PR #50 strict recall | T02 E | T02 strict recall |",
        "|---|---|---:|---:|---:|---:|",
    ])
    for result in sorted(results, key=lambda row: (row["arm"], row["scope"])):
        old_subset = result["old_data_evaluable_subset"]
        new_subset = result["new_metrics"]["data_evaluable_subset"]
        strict_key = (
            "StrictStageRecall5W10"
            if result["scope"] == "stage"
            else "StrictShortRecall5W10"
        )
        lines.append(
            f"| {result['arm']} | {result['scope']} | {old_subset['E']} "
            f"| {old_subset['strict_recall'] if old_subset['strict_recall'] is not None else 'null'} "
            f"| {new_subset['E']} | {new_subset.get(strict_key) if new_subset.get(strict_key) is not None else 'null'} |"
        )
    lines.extend([
        "",
        "PR #50 的“precision”是其旧 evaluator 的 `TP/P`；T02 precision 只以 resolved first formal claims 为分母。`null` 表示分母为零，不转成100%。只有相同定义且分母相同的数值才可直接比较。",
        "旧列的 no-formal-alert/first-window coverage 使用 PR #50 的首条旧 claim 作为可计算代理；PR #50 没有 T02 的 formal-claim lifecycle，故该代理不等于 T02 定义。alerts/year 两侧按相同 action-session 范围和 asset-years 计算全部回放通知；occupied days 两侧按同一评分范围裁剪所有完整区间。T02 另列 formal-only 负担；PR #50 自身的 published-notification operational 指标不是该并列 burden。",
        "",
        "### PR #50 专属诊断字段（T02无同义指标）",
        "",
        "| PR #50 字段 | T02对应 | 原因 |",
        "|---|---|---|",
        "| `event_only.{E,P,TP,FP,FN,recall,precision}` | not_defined | T02只报告 Qualified/Strict 两层首正式区间命中。 |",
        "| `issued_claims`、`pending_events`、`pending_label_regions`、`known_anchors`、`unknown_anchors`、`known_anchor_fraction`、`complete_recall_denominator_established` | not_defined | T02将未知/待定状态显式列出，不将状态汇总为旧 known-anchor 比例。 |",
        "| `failure_counts`、`missed_event_reasons`、lead/width distributions | not_defined | 保留为 PR #50 诊断，不作为 T02 核心评分。 |",
        "| `diagnostics` / `operational` 中的历史运行/首claim汇总 | not_defined | T02 claims 与行动日分母有不同生命周期。 |",
        "| `short_affiliate`、`family` 跨尺度聚合 | not_defined | T02 short/stage 独立一对一匹配，不作跨尺度归因。 |",
        "",
        "## 91阶段事件 × 10策略的互斥主因计数",
        "",
        "| arm | data_not_evaluable | no_alert | reversed/non_future/beyond_H | too_wide | early/late | insufficient_lead | success |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for arm in ARMS:
        counts = attribution_counts.get(arm, {})
        lines.append("| " + arm + " | " + " | ".join(
            str(counts.get(cause, 0)) for cause in PRIMARY_CAUSE_PRIORITY
        ) + " |")
    lines.extend([
        "",
        "每个事件/策略行同时保留重叠 flags；主因只按冻结优先级选择，不表示因果归因。未用区间挑选目标。",
        "",
        "## PR #50 与 T02 语义差异",
        "",
        "- 数值默认相同：close、short 10/10、stage 63/42、G=5、valley 21/21、rise 21–126、H=63、lead=5、inclusive width=10。",
        "- PR #50 `known` bool 映射成 `unknown/pending/no_event/mature_event`；缺数与未成熟不再共用一个负例语义。",
        "- 新增 `support_end/label_available_session/label_version`，阶段资格来自标签规则，不由拟合窗口长度推导。",
        "- T02 对所有 arm 使用相同 future/width/lead/H geometry gate；saved interval 原样保留，不缩窄。",
        "- PR #50 对每条保存 forecast 评分并把几何失败记作失败原因；T02 将不通过几何门的条目保留为完整 observation，仅合格 formal claim 参加事件首窗评分。",
        "- 新增 append-only 首次正式主张账本；历史回放 `first_visible_at=null`，保存模拟可用/行动时间及延迟假设；无PIT则 vintage 未建立。",
        "- scope 目标仅按行动日后下一个同层事件确定；未知锚点阻断；首条窗口决定成绩，revision/换episode均不能挽救。",
        "- PR #50 的 `TP/P`, event-only、family affiliate 等旧指标继续原样运行；T02 的 metrics/denominators 另列，不把定义差异描述为模型收益。",
        "- PR #50 stage-event 已采用阶段上涨标签且未使用−10%跌幅门；未修改任何旧幅度标签字段。",
        "",
        "## sh000001 数据语义",
        "",
        f"- v20261024 qfq parquet：{semantic['status']}；SHA256 `{semantic.get('data_sha256', 'NOT_ESTABLISHED')}`。",
        f"- short 2024-03-18：{semantic.get('short_event', 'NOT_ESTABLISHED')}；stage 2024-05-20：{semantic.get('stage_event', 'NOT_ESTABLISHED')}。",
        "- 结果只核对冻结快照上的事后标签，不是历史PIT标签或预测命中。",
        "",
    ])
    content = "\n".join(lines)
    if hasattr(path, "write"):
        path.write(content)
    else:
        path.write_text(content, encoding="utf-8", newline="\n")


def _read_parquet_labels(
    expected_hashes: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    event_rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    unknown_rows: list[dict[str, Any]] = []
    inputs: dict[str, Any] = {}
    semantic: dict[str, Any] = {
        "status": "NOT_ESTABLISHED",
        "reason": "v20261024 qfq parquet unavailable",
    }
    for symbol in SYMBOLS:
        path = ROOT / f"data/frozen/v20261024/{symbol}_qfq.parquet"
        if not path.is_file():
            continue
        data = pd.read_parquet(path)
        if "date" not in data or "close" not in data:
            continue
        sessions = tuple(
            value.date().isoformat() if hasattr(value, "date") else str(value)[:10]
            for value in pd.to_datetime(data["date"])
        )
        book = build_labels(
            symbol,
            sessions,
            [str(value) if pd.notna(value) else None for value in data["close"]],
            config=Protocol(),
            input_status="FROZEN_QFQ_NOT_HISTORICAL_PIT",
        )
        events = {(event.scale, event.peak_session): event for event in book.events}
        for scale in ("short", "stage"):
            for session, state in enumerate(book.states[scale]):
                event = events.get((scale, session))
                row = {
                    "symbol": symbol,
                    "scope": scale,
                    "session": session,
                    "date": book.sessions[session],
                    "label_state": state.value,
                    "event_id": event.event_id if event else "",
                    "support_end": event.support_end if event else "",
                    "label_available_session": event.label_available_session if event else "",
                    "label_version": event.label_version if event else LABEL_VERSION,
                }
                state_rows.append(row)
                if state in {LabelState.UNKNOWN, LabelState.PENDING}:
                    unknown_rows.append({
                        "symbol": symbol,
                        "scope": scale,
                        "session": session,
                        "date": book.sessions[session],
                        "label_state": state.value,
                        "source": "T02_regenerated_frozen_qfq",
                        "reason": _state_reason(book, scale, session),
                    })
        for event in book.events:
            event_rows.append({
                "symbol": symbol,
                "scope": event.scale,
                "event_id": event.event_id,
                "peak_session": event.peak_session,
                "peak_date": book.sessions[event.peak_session],
                "candidate_sessions": list(event.candidate_sessions),
                "price": event.price,
                "support_start": event.support_start,
                "support_end": event.support_end,
                "support_end_date": book.sessions[event.support_end],
                "label_available_session": event.label_available_session,
                "label_available_date": book.sessions[event.label_available_session],
                "label_version": event.label_version,
                "rise_start": event.rise_start if event.rise_start is not None else "",
                "family_id": event.family_id,
                "family_ambiguous": event.family_ambiguous,
            })
        file_hash = _sha256(path.read_bytes())
        expected_hash = expected_hashes.get(
            f"D:\\LPPL-development\\async-stock-20261106\\data\\frozen\\v20261024\\{symbol}_qfq.parquet"
        )
        inputs[symbol] = {
            "path": str(path.relative_to(ROOT)),
            "sha256": file_hash,
            "rows": len(data),
            "first_date": book.sessions[0],
            "last_date": book.sessions[-1],
            "adjustment": "qfq (filename and frozen dataset contract)",
            "input_status": "FROZEN_QFQ_NOT_HISTORICAL_PIT",
            "matches_pr50_source_hash": file_hash == expected_hash if expected_hash else None,
            "pr50_source_sha256": expected_hash,
        }
        if symbol == "sh000001":
            short = [event for event in book.events
                     if event.scale == "short" and book.sessions[event.peak_session] == "2024-03-18"]
            stage = [event for event in book.events
                     if event.scale == "stage" and book.sessions[event.peak_session] == "2024-05-20"]
            semantic = {
                "status": (
                    "VERIFIED_ON_FROZEN_QFQ_SNAPSHOT"
                    if short and stage and expected_hash and file_hash == expected_hash
                    else "NOT_ESTABLISHED"
                ),
                "data_sha256": file_hash,
                "matches_pr50_source_hash": file_hash == expected_hash if expected_hash else None,
                "short_event": "mature_event" if short else "NOT_ESTABLISHED",
                "stage_event": "mature_event" if stage else "NOT_ESTABLISHED",
                "short_peak_price": short[0].price if short else None,
                "stage_peak_price": stage[0].price if stage else None,
                "short_support_end": (
                    book.sessions[short[0].support_end] if short else None
                ),
                "stage_support_end": (
                    book.sessions[stage[0].support_end] if stage else None
                ),
            }
    return event_rows, state_rows, {
        "inputs": inputs,
        "unknown_rows": unknown_rows,
        "state_rows": state_rows,
        "semantic": semantic,
    }


def _state_reason(book: LabelBook, scope: str, session: int) -> str:
    for row in book.pending:
        if row.get("scale") != scope:
            continue
        if row.get("peak_session") == session:
            return str(row.get("reason", "pending anchor"))
        if (
            row.get("kind") == "unresolved_anchor_range"
            and row.get("start_session", len(book.sessions)) <= session
            <= row.get("end_session", -1)
        ):
            return str(row.get("reason", "unknown anchor"))
    return "no resolved supporting evidence"


def _source_manifest() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(_git_blob("manifest.json"))
    hashes = {
        name: _sha256(_git_blob(name))
        for name in (
            "manifest.json",
            "hypothetical_forecasts.csv.gz",
            "label_books.jsonl.gz",
            "daily_replay_ledger.csv.gz",
            "evaluations.jsonl.gz",
            "event_scores.csv",
            "input_map.json",
        )
    }
    source_scoring = _git_source_blob("research/eval/top_time/scoring.py")
    local_scoring = (ROOT / "research/eval/top_time/scoring.py").read_bytes()
    source_code_hash = _sha256(source_scoring)
    local_code_hash = _sha256(local_scoring)
    if local_code_hash != source_code_hash:
        raise RuntimeError("PR #50 scoring.py port is not byte-identical to the pinned source")
    return manifest, {
        "source_sha": PR50_SHA,
        "input_sha256": hashes,
        "evaluator_code": {
            "path": "research/eval/top_time/scoring.py",
            "pr50_sha256": source_code_hash,
            "working_sha256": local_code_hash,
            "byte_identical": True,
        },
    }


def _contract(
    source_manifest: dict[str, Any],
    source_hashes: dict[str, Any],
    local_inputs: dict[str, Any],
    semantic: dict[str, Any],
) -> dict[str, Any]:
    protocol = Protocol()
    not_established = [
        "Historical point-in-time vintage and original publication/first-visible timestamps.",
        "Exchange-complete session calendar and actual execution/actionability; replay uses observed indices.",
        "Historical availability of qfq adjustment factors and corporate-action vintages.",
        "Predictive skill or any model improvement; no scan, refit, or prospective run was performed.",
        "Whether PR #50 hypothetical forecasts were ever delivered to users.",
    ]
    if semantic.get("status") != "VERIFIED_ON_FROZEN_QFQ_SNAPSHOT":
        not_established.append(
            "sh000001 March/May 2024 event semantics on the PR #50 v20261024 qfq source hash."
        )
    if any(row.get("matches_pr50_source_hash") is not True for row in local_inputs.values()):
        not_established.append(
            "Exact PR #50 source-data hash equivalence for every local qfq label input."
        )
    return {
        "scoring_contract_version": SCORING_CONTRACT_VERSION,
        "label_version": LABEL_VERSION,
        "parameter_status": protocol.parameter_status,
        "implementation_sources": {
            "legacy_evaluator": "research/eval/top_time/scoring.py (byte-identical PR #50 port)",
            "label_states_and_events": "research/eval/top_time/contracts.py; research/eval/top_time/labels.py",
            "T02_ledger_and_scoring": "research/eval/top_time/t02.py",
            "guarded_artifact_generator": "scripts/research/t02_manifest.py",
        },
        "research_defaults": {
            "price_field": protocol.price_field,
            "short": {"left_sessions": protocol.short_left, "right_sessions": protocol.short_right},
            "stage": {"left_sessions": protocol.stage_left, "right_sessions": protocol.stage_right},
            "same_price_merge_gap_sessions": protocol.merge_gap,
            "trough": {
                "left_sessions": protocol.trough_left,
                "right_sessions": protocol.trough_right,
            },
            "stage_rise": {
                "minimum_sessions": protocol.rise_min,
                "maximum_sessions": protocol.rise_max,
                "required": protocol.require_stage_rise,
            },
            "horizon_sessions": protocol.horizon,
            "minimum_event_lead_sessions": protocol.minimum_lead,
            "maximum_inclusive_width_sessions": protocol.maximum_width,
        },
        "label_states": [
            LabelState.UNKNOWN.value,
            LabelState.PENDING.value,
            LabelState.NO_EVENT.value,
            LabelState.MATURE_EVENT.value,
        ],
        "event_fields": [
            "support_end", "label_available_session", "label_version",
        ],
        "stage_eligibility_source": "explicit retrospective label rule; never inferred from fit-window length",
        "formal_interval_gate": {
            "same_for_all_arms": True,
            "future": "interval_start > action_session",
            "inclusive_width": "interval_end - interval_start + 1 <= 10",
            "minimum_lead": "interval_start - action_session >= 5",
            "horizon": "interval_end <= action_session + 63",
            "observation_interval_policy": "preserve full saved interval; never narrow",
        },
        "claim_ledger": {
            "append_only": True,
            "kinds": ["observation", "formal", "revision", "new"],
            "required_identity_fields": [
                "claim_id", "parent_claim_id", "episode_id", "scope",
                "first_interval_start", "first_interval_end",
                "first_clock_session", "fixed_expiry_session",
            ],
            "modes": {
                "historical_replay": {
                    "first_visible_at": None,
                    "required": [
                        "simulated_available_at", "simulated_action_session", "delay_assumption",
                    ],
                    "default_vintage_status": "HISTORICAL_VINTAGE_NOT_ESTABLISHED",
                },
                "forward": {
                    "first_visible_at": "required from delivery evidence",
                    "full_close_data": (
                        "first_visible_at must be at or after the timezone-aware "
                        "published_session_close_at evidence"
                    ),
                    "action_session": "next session after full-close publication under fixed calendar/cutoff",
                },
            },
            "scope_upgrade": "short-to-stage starts a separate stage first-clock",
        },
        "matching": {
            "target": "next same-scope event in (action_session, action_session + H]",
            "interval_used_to_choose_target": False,
            "unknown_anchor": "pending; do not scan past",
            "one_to_one": True,
            "primary": "earliest formal claim for each event",
            "revision_can_rescue_first_claim": False,
            "tie_break": "first_clock_session, action_session, claim_id; event anchors by session then event_id",
        },
        "metrics": {
            "E": "qualified mature events of the scored scope; stage E is qualified mature stage tops",
            "no_formal_alert_rate": "events without a primary formal claim / E",
            "first_window_coverage": "primary first interval contains event / E",
            "QualifiedStageRecall5": "first interval contains stage event and event lead >= 5 / E",
            "StrictStageRecall5W10": (
                "QualifiedStageRecall5 plus inclusive width <= 10 and window start lead >= 5 / E"
            ),
            "strict_stage_miss_rate": "1 - StrictStageRecall5W10",
            "resolved_claim_precision": "strict primary successes / resolved first formal claims",
            "burden": [
                "duplicate_notices", "pending_claims", "revisions",
                "claim_notices", "observation_notices", "formal_alerts",
                "alerts_per_asset_year", "alarm_occupied_days",
                "formal_alarm_occupied_days",
            ],
            "zero_denominator": None,
            "main_denominator": "end-to-end; data/run failures remain in E",
            "conditional_subset": "separate explicitly data-evaluable event IDs and denominator",
            "unknown_labels": "listed as unknown/pending; never inserted into E",
        },
        "legacy_amplitude_labels": {
            "status": "UNCHANGED",
            "note": "T02 does not add a -10% drawdown requirement or overwrite legacy amplitude fields.",
        },
        "pr50_comparison": {
            "source_sha": PR50_SHA,
            "evaluator_version": source_manifest["source_parameters"]["evaluator_version"],
            "evaluator_code": source_hashes["evaluator_code"],
            "numerical_defaults_match": True,
            "differences": [
                "new frozen scoring version while preserving parameter_status",
                "known bool is surfaced as four explicit label states",
                "label availability and version are explicit event fields",
                "immutable append-only claim lifecycle and historical/forward evidence modes",
                (
                    "PR #50 scores every saved forecast and records geometry failures; "
                    "T02 keeps failing intervals as full-width observations and gates "
                    "formal claims before event scoring"
                ),
                "new scope metrics and explicit zero-denominator/null behavior",
            ],
            "input_sha256": source_hashes["input_sha256"],
        },
        "local_data": local_inputs,
        "sh000001_semantic_check": semantic,
        "not_established": not_established,
    }


def generate(output: Path = OUTPUT) -> dict[str, Any]:
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing T02 run directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    source_manifest, source_hashes = _source_manifest()
    saved_books = {
        row["symbol"]: _book_from_saved(row)
        for row in _json_gz("label_books.jsonl.gz")
    }
    saved_unknown_rows = []
    for book in saved_books.values():
        for row in unknown_label_rows(book):
            saved_unknown_rows.append({
                **row,
                "source": "PR50_saved_label_book",
                "reason": _state_reason(book, row["scope"], row["session"]),
            })
    saved_evaluations = _json_gz("evaluations.jsonl.gz")
    forecast_rows = _csv_gz("hypothetical_forecasts.csv.gz")
    daily_rows = _csv_gz("daily_replay_ledger.csv.gz")

    forecasts_by_key: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    daily_by_key: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in forecast_rows:
        forecasts_by_key[(row["symbol"], row["arm"], row["scope_probe"])].append(row)
    for row in daily_rows:
        daily_by_key[(row["symbol"], row["arm"], row["scope_probe"])].append(row)

    results = []
    rerun_metrics: dict[tuple[str, str, str], Any] = {}
    t02_results: dict[tuple[str, str, str], Any] = {}
    old_reproduction_mismatches = []
    archive_metrics = {
        (row["symbol"], row["arm"], row["scope_probe"]): row["metrics"]
        for row in saved_evaluations
    }
    for reference in saved_evaluations:
        key = (reference["symbol"], reference["arm"], reference["scope_probe"])
        book = saved_books[reference["symbol"]]
        source_rows = forecasts_by_key[key]
        daily_group = daily_by_key[key]
        old_result, old_forecasts, old_runs = _evaluate_saved_group(
            key, book, source_rows, daily_group, reference
        )
        old_metrics = old_result.metrics[key[2]]
        archived = archive_metrics[key][key[2]]
        for metric in ("E", "P", "TP", "FN", "recall", "precision"):
            if old_metrics.get(metric) != archived.get(metric):
                old_reproduction_mismatches.append(
                    f"{key}: {metric}: rerun={old_metrics.get(metric)!r} saved={archived.get(metric)!r}"
                )
        scoped_old_events = [
            event for event in old_result.events if event.get("scale") == key[2]
        ]

        data_evaluable = {
            event.event_id
            for event in book.events
            if event.scale == key[2]
            and int(reference["metadata"]["start_session"])
            <= event.peak_session
            <= int(reference["metadata"]["end_session"])
            and _event_data_evaluable(event, daily_group, Protocol().horizon)
        }
        expiry_by_forecast_id = {}
        for daily in daily_group:
            if daily["status"] != "HYPOTHETICAL_INTERVAL":
                continue
            prediction_id = daily["new_forecast_id"]
            expiry = daily["episode_original_expiry_session"]
            if not expiry:
                raise RuntimeError(
                    f"saved replay has no episode expiry for {prediction_id}"
                )
            expiry_by_forecast_id[prediction_id] = int(expiry) + 1
        claims = _saved_claim_rows(source_rows, key[2], expiry_by_forecast_id)
        new_result = score_t02(
            book,
            claims,
            data_evaluable_event_ids=data_evaluable,
            start_session=int(reference["metadata"]["start_session"]),
            end_session=int(reference["metadata"]["end_session"]),
        )
        new_metrics = new_result["scopes"][key[2]]["metrics"]
        asset_years = new_metrics["asset_years"]
        subset_old_events = [
            event for event in scoped_old_events
            if event["event_id"] in data_evaluable
        ]
        subset_old_E = len(subset_old_events)
        subset_old = {
            "E": subset_old_E,
            "strict_recall": (
                sum(event["strict_hit"] for event in subset_old_events) / subset_old_E
                if subset_old_E else None
            ),
        }
        rerun_metrics[key] = old_result
        t02_results[key] = new_result
        results.append({
            "symbol": key[0],
            "arm": key[1],
            "scope": key[2],
            "old_metrics": {
                **old_metrics,
                "no_formal_alert_rate": (
                    sum(event["first_prediction_id"] is None for event in scoped_old_events)
                    / old_metrics["E"] if old_metrics["E"] else None
                ),
                "first_window_coverage": (
                    sum(
                        _old_first_covers(event, old_result.claims, old_forecasts)
                        for event in scoped_old_events
                    ) / old_metrics["E"] if old_metrics["E"] else None
                ),
                "QualifiedStageRecall5": _old_recall5(old_result, old_forecasts, key[2]),
                "QualifiedShortRecall5": _old_recall5(old_result, old_forecasts, key[2]),
                "strict_recall": old_metrics["recall"],
                "strict_miss": 1 - old_metrics["recall"] if old_metrics["recall"] is not None else None,
                "duplicate_notices": old_result.metrics["diagnostics"]["duplicate_claims"],
                "pending_claims": old_result.metrics["diagnostics"]["pending_claims"],
                "revisions": sum(claim.get("is_revision", False) for claim in old_result.claims),
                "claim_notices": sum(
                    forecast.action_session is not None
                    and int(reference["metadata"]["start_session"])
                    <= forecast.action_session
                    <= int(reference["metadata"]["end_session"])
                    for forecast in old_forecasts
                ),
                "alerts_per_asset_year": _old_alerts_per_year(
                    old_forecasts,
                    asset_years,
                    int(reference["metadata"]["start_session"]),
                    int(reference["metadata"]["end_session"]),
                ),
                "asset_years": asset_years,
                "alarm_occupied_days": _occupied_days(
                    old_forecasts,
                    int(reference["metadata"]["start_session"]),
                    int(reference["metadata"]["end_session"]),
                ),
            },
            "new_metrics": new_metrics,
            "old_data_evaluable_subset": subset_old,
            "old_events": scoped_old_events,
            "new_events": new_result["scopes"][key[2]]["events"],
            "old_claims": old_result.claims,
            "forecast_inputs": source_rows,
            "t02_claims": claims,
            "data_evaluable_event_ids": data_evaluable,
            "book": book,
            "daily_rows": daily_group,
        })

    attribution, cause_counts = _make_attribution(results)
    label_events, label_states, local = _read_parquet_labels(source_manifest["before_sha256"])
    semantic = local["semantic"]
    unknown_rows = [
        *local["unknown_rows"],
        *saved_unknown_rows,
    ]

    contract = _contract(
        source_manifest, source_hashes, local["inputs"], semantic
    )
    fixture_bytes = FIXTURE.read_bytes()

    temp = Path(tempfile.mkdtemp(prefix=".t02_20261116_a1-", dir=output.parent))
    try:
        _write_json(temp / "scoring_contract_frozen.json", contract)
        _write_csv(
            temp / "label_event_table.csv",
            [
                "symbol", "scope", "event_id", "peak_session", "peak_date",
                "candidate_sessions", "price", "support_start", "support_end",
                "support_end_date", "label_available_session", "label_available_date",
                "label_version", "rise_start", "family_id", "family_ambiguous",
            ],
            label_events,
        )
        _write_csv(
            temp / "label_state_table.csv",
            [
                "symbol", "scope", "session", "date", "label_state", "event_id",
                "support_end", "label_available_session", "label_version",
            ],
            label_states,
        )
        _write_csv(
            temp / "unknown_label_list.csv",
            ["symbol", "scope", "session", "date", "label_state", "source", "reason"],
            unknown_rows,
        )
        _write_csv(
            temp / "first_alert_failure_attribution.csv",
            [
                "symbol", "arm", "event_id", "peak_date", "first_prediction_id",
                "t02_first_formal_claim_id", "data_evaluable", "flags", "primary_cause",
                "interval_start", "interval_end", "action_session", "inclusive_width",
                "event_lead",
            ],
            attribution,
        )
        ledger_rows = [
            claim
            for result in results
            for claim in result["t02_claims"]
        ]
        _write_csv(
            temp / "historical_claim_ledger.csv",
            [
                "claim_id", "parent_claim_id", "episode_id", "kind", "scope",
                "interval_start", "interval_end", "first_interval_start",
                "first_interval_end", "first_clock_session", "fixed_expiry_session",
                "action_session", "mode", "first_visible_at", "simulated_available_at",
                "simulated_action_session", "delay_assumption", "vintage_status",
            ],
            ledger_rows,
        )
        (temp / "hand_cases.json").write_bytes(fixture_bytes)
        (temp / "hand_cases.sha256").write_text(
            _sha256(fixture_bytes) + "\n", encoding="ascii", newline="\n"
        )
        (temp / "old_vs_new_scoring.md").write_text(
            _markdown_report(
                results, cause_counts, source_manifest, semantic,
                len(unknown_rows), old_reproduction_mismatches,
            ),
            encoding="utf-8",
            newline="\n",
        )
        (temp / "README.md").write_text(
            _readme(
                source_manifest, source_hashes, semantic, local["inputs"],
                len(results), len(attribution), cause_counts, len(unknown_rows),
                old_reproduction_mismatches,
            ),
            encoding="utf-8",
            newline="\n",
        )
        output_hashes = {
            path.name: {"sha256": _sha256(path.read_bytes()), "bytes": path.stat().st_size}
            for path in sorted(temp.iterdir())
        }
        _write_json(temp / "manifest.json", {
            "scoring_contract_version": SCORING_CONTRACT_VERSION,
            "source_pr50_sha": PR50_SHA,
            "source_inputs_sha256": source_hashes["input_sha256"],
            "source_evaluator_code": source_hashes["evaluator_code"],
            "local_data": local["inputs"],
            "output_sha256": output_hashes,
            "counts": {
                "old_evaluator_groups": len(results),
                "attribution_event_arm_rows": len(attribution),
                "unknown_label_rows": len(unknown_rows),
                "old_reproduction_mismatches": len(old_reproduction_mismatches),
            },
        })
        if output.exists():
            raise FileExistsError(f"refusing to overwrite existing T02 run directory: {output}")
        os.rename(temp, output)
    except Exception:
        if temp.exists():
            shutil.rmtree(temp)
        raise
    return {
        "output": str(output),
        "old_evaluator_groups": len(results),
        "attribution_event_arm_rows": len(attribution),
        "cause_counts": cause_counts,
        "unknown_label_rows": len(unknown_rows),
        "semantic": semantic,
        "old_reproduction_mismatches": old_reproduction_mismatches,
    }


def _old_first_covers(event, old_claims, forecasts) -> bool:
    prediction_id = event.get("first_prediction_id")
    if not prediction_id:
        return False
    claim = next((row for row in old_claims if row.get("prediction_id") == prediction_id), None)
    if claim is None:
        return False
    forecast = next((row for row in forecasts if row.prediction_id == prediction_id), None)
    return bool(
        forecast
        and forecast.interval_start <= event["peak_session"] <= forecast.interval_end
    )


def _old_recall5(old_result, forecasts, scope: str) -> float | None:
    if not old_result.events:
        return None
    by_id = {forecast.prediction_id: forecast for forecast in forecasts}
    successes = 0
    for event in old_result.events:
        if event.get("scale") != scope:
            continue
        prediction_id = event.get("first_prediction_id")
        forecast = by_id.get(prediction_id)
        action = forecast.action_session if forecast else None
        if (
            forecast is not None
            and action is not None
            and forecast.interval_start <= event["peak_session"] <= forecast.interval_end
            and event["peak_session"] - action >= 5
        ):
            successes += 1
    return successes / len(old_result.events)


def _old_alerts_per_year(
    forecasts: list[Forecast], asset_years: float, start_session: int, end_session: int
) -> float | None:
    notices = sum(
        forecast.action_session is not None
        and start_session <= forecast.action_session <= end_session
        for forecast in forecasts
    )
    return notices / asset_years if asset_years else None


def _occupied_days(
    forecasts: list[Forecast], start_session: int, end_session: int
) -> int:
    days: set[int] = set()
    for forecast in forecasts:
        if (
            forecast.action_session is not None
            and start_session <= forecast.action_session <= end_session
            and forecast.interval_end >= forecast.interval_start
        ):
            days.update(range(
                max(start_session, forecast.interval_start),
                min(end_session, forecast.interval_end) + 1,
            ))
    return len(days)


def _make_attribution(results):
    rows = []
    counts: dict[str, Counter] = {arm: Counter() for arm in ARMS}
    for result in results:
        if result["scope"] != "stage":
            continue
        first_by_id = {
            row["new_forecast_id"]: row
            for row in result["forecast_inputs"]
            if row["new_forecast_id"]
        }
        old_by_event = {
            row["event_id"]: row for row in result["old_events"]
            if row.get("scale") == "stage"
        }
        t02_by_event = {row["event_id"]: row for row in result["new_events"]}
        event_by_id = {
            event.event_id: event
            for event in result["book"].events
            if event.scale == "stage"
        }
        for event_id, old_event in sorted(old_by_event.items()):
            first_id = old_event.get("first_prediction_id")
            first = first_by_id.get(first_id) if first_id else None
            event = event_by_id[event_id]
            data_evaluable = event_id in result["data_evaluable_event_ids"]
            flags, primary = _attribution_flags(
                old_event, first, data_evaluable=data_evaluable
            )
            counts[result["arm"]][primary] += 1
            t02_event = t02_by_event.get(event_id, {})
            if first is None:
                start = end = action = width = lead = ""
            else:
                start = int(first["interval_start"])
                end = int(first["interval_end"])
                action = int(first["hypothetical_action_session"])
                width = end - start + 1
                lead = event.peak_session - action
            rows.append({
                "symbol": event.symbol,
                "arm": result["arm"],
                "event_id": event_id,
                "peak_date": result["book"].sessions[event.peak_session],
                "first_prediction_id": first_id or "",
                "t02_first_formal_claim_id": t02_event.get("first_formal_claim_id") or "",
                "data_evaluable": data_evaluable,
                "flags": flags,
                "primary_cause": primary,
                "interval_start": start,
                "interval_end": end,
                "action_session": action,
                "inclusive_width": width,
                "event_lead": lead,
            })
    return rows, {arm: dict(counts[arm]) for arm in ARMS}


def _markdown_report(results, cause_counts, source_manifest, semantic, unknown_count, mismatches):
    buffer = io.StringIO()
    _write_report(buffer, results, cause_counts, source_manifest, semantic, unknown_count, mismatches)
    return buffer.getvalue()


def _readme(source_manifest, source_hashes, semantic, local_inputs, groups, attribution_count,
            cause_counts, unknown_count, mismatches):
    source_matches = sum(
        data.get("matches_pr50_source_hash") is True for data in local_inputs.values()
    )
    not_established = [
        "PR #50 历史模型 vintage、用户实际可见时间与真实发布/送达证据；其输出都是 hypothetical replay。",
        "回放所用观测日期是完整交易所日历，或假设 action_session 等同实际可成交时间。",
        "v20261024 qfq 的历史逐日 PIT 复权因子和公司行动可得性；快照哈希一致不建立PIT。",
        "任何模型预测技能、独立前瞻表现或性能改善；本任务不运行扫描、重拟合或 forward study。",
        "PR #50 保存区间是否曾真实通知用户、原始 scope 的真实语义及线上stage/short分级。",
        "attribution 主因是互斥的审计分类，不证明失败机制的因果关系。",
    ]
    if semantic.get("status") != "VERIFIED_ON_FROZEN_QFQ_SNAPSHOT":
        not_established.append(
            "sh000001 2024-03-18 short / 2024-05-20 stage 标签未在精确 PR #50 v20261024 qfq 数据上建立。"
        )
    if source_matches != len(local_inputs) or not local_inputs:
        not_established.append("并非所有本地 qfq 标签输入都与 PR #50 source manifest 哈希一致。")
    if mismatches:
        not_established.append("PR #50 evaluator 重放与封存 metrics 存在关键字段差异；见 old_vs_new_scoring.md。")
    lines = [
        "# T02 两级评分与首次提醒账本",
        "",
        f"评分合同：`{SCORING_CONTRACT_VERSION}`。PR #50 原评价器按源提交 `{PR50_SHA}` 原样移植；该分支单独的移植提交已保留。",
        "",
        "本目录是研究交付，不是生产配置、模型重拟合、预测能力声明或新 holdout。报告中的数值变化属于**评分定义变化，不算模型进步**。",
        "",
        "## 冻结语义",
        "",
        "- close；short 10/10；stage 63/42；同价合并 G=5；谷点21/21；阶段上涨段21–126；H=63；lead=5；含端点宽度10。",
        "- `parameter_status` 原样保留为 `RESEARCH_DEFAULT_NOT_FROZEN`；冻结的是评分合同版本，不表示这些研究默认是最优参数。",
        "- 标签状态为 unknown/pending/no_event/mature_event；事件显式保存 support_end、label_available_session、label_version。阶段资格来自事件标签规则，不由拟合窗口长度决定。",
        "- Claims ledger 只追加；历史回放不伪造 first_visible_at，保存 simulated availability/action 与 delay assumption；forward 需 delivery evidence，完整收盘数据的 first_visible_at 不早于带时区的收盘证据且最早下个 session 可行动。",
        "- 所有 arm 共用完整区间几何门：未来、inclusive width≤10、区间起点至少提前5、终点≤action+63；不缩窄 observation interval。",
        "- PR #50 evaluator 对所有保存 forecast 计分并把几何问题列为失败原因；T02 按同一数值阈值将不合格区间留作完整 observation、不作为 formal alert 计分。",
        "- 匹配不读区间：行动日后 H=63 内下一同级事件；遇 unknown/pending 锚点停止并 pending；首条正式主张决定成绩，revision/换episode不修复；一对一并固定 tie-break。",
        "- 零分母输出 null；主表成熟事件分母保留数据/运行失败，条件子集使用显式独立分母；unknown 标签另表列示，不混进 E。",
        "- burden 中 alerts/year 与 alarm-occupied days 包含所有可见 observation/formal/revision/new 通知及未缩窄区间；另列 formal-only alerts 与 occupied days。",
        "- 旧−10%幅度标签如有，保持原字段名和含义；T02 不添加跌幅成功条件，不重命名或覆盖旧幅度标签。",
        "",
        "## PR #50 replay 输入与旧新比较",
        "",
        f"- PR #50 evaluator/replay source SHA：`{PR50_SHA}`；saved source 的 evaluator version：`{source_manifest['source_parameters']['evaluator_version']}`。",
        f"- 旧 evaluator 的 `scoring.py` 与 PR #50 源 SHA256 字节相同：`{source_hashes['evaluator_code']['byte_identical']}`（`{source_hashes['evaluator_code']['working_sha256']}`）。",
        f"- 已对 {groups} 个 symbol×arm×scope 组重跑 PR #50 evaluator；按 E/P/TP/FN/recall/precision 对比其封存 metrics，差异 {len(mismatches)} 项。",
        f"- Attribution CSV 含 {attribution_count} 行，即 91 个阶段事件 × 10 个保存策略；每行保留多标签 flags 和优先级唯一主因。",
        f"- 原始输入哈希：`{json.dumps(source_hashes['input_sha256'], ensure_ascii=False, sort_keys=True)}`。",
        "- PR #50 默认数值与 T02 研究默认相同；变化集中于版本化、多态标签状态、append-only/PIT账本、首正式区间指标和显式分母。逐项见 `old_vs_new_scoring.md`。",
        "- 旧对照中 `TP/P`、首次旧 claim 和旧 notifications 沿用 PR #50 定义；T02 用首 formal claim 与明确的已解析分母。未定义的新旧同名指标须按 `old_vs_new_scoring.md` 注释解释。",
        "",
        "## 数据与 sh000001 语义检查",
        "",
        f"- sh000001：{semantic['status']}；short 2024-03-18={semantic.get('short_event')}；stage 2024-05-20={semantic.get('stage_event')}。",
        f"- 本地 qfq 文件只读；{source_matches}/{len(local_inputs)} 个指数源 SHA 与 PR #50 manifest 一致；其调整类型为 qfq。",
        "- label state/event 表由本地 frozen v20261024 qfq 生成；unknown 清单同时标记本地重算和 PR #50 保存 label book 的来源。它们是事后快照标签，不代表当时可得因子或真实首见时刻。",
        f"- 未知/未成熟 label 状态行：{unknown_count}，详见 `unknown_label_list.csv`。",
        "",
        "## NOT_ESTABLISHED",
        "",
        *[f"{index}. {item}" for index, item in enumerate(not_established, start=1)],
        "",
        "## 交付与复现",
        "",
        "- `scoring_contract_frozen.json`：版本、默认值、状态、几何门、账本和指标分母。",
        "- `label_state_table.csv` / `label_event_table.csv` / `unknown_label_list.csv`：逐session标签、事件支持和未知清单。",
        "- `hand_cases.json` 与 `hand_cases.sha256`：人工预期 fixture 的原样副本及哈希。",
        "- `historical_claim_ledger.csv`：历史回放 claim rows，保留 observation 原宽度及模拟时序。",
        "- `first_alert_failure_attribution.csv` 与 `old_vs_new_scoring.md`：91×10事件策略归因及旧/新指标。",
        "- 用 `python scripts/research/t02_manifest.py` 在源 PR #50 commit 和本地 frozen data 可用时再生；目标目录已存在会拒绝覆盖。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = generate(args.out)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
