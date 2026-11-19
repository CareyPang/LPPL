"""Experimental close-of-day market breadth warnings. All inputs use trading-session order."""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Iterable, Mapping
from statistics import fmean
from typing import Any

RULE_VERSION = "stage-breadth-1"
PHASE_LABELS = {
    "unavailable": "阶段资料不足",
    "short_rebound": "下跌后的短线回升",
    "medium_up": "中期上涨",
    "early_decline": "刚开始转弱",
    "sustained_decline": "下跌已持续一段时间",
    "mixed": "方向尚不清楚",
}
WATCH_SESSIONS = {"rebound_end": 10, "stage_top": 20, "rebound": 5, "reversal": 20}
OPPOSITE = {
    "rebound_end": "rebound",
    "rebound": "rebound_end",
    "stage_top": "reversal",
    "reversal": "stage_top",
}
WARMUP = "需要前一交易日及更早的61个上证收盘，以及近期站上均线的股票占比。"


def _number(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def classify_phase(prior: list[dict]) -> dict:
    """Classify the setup using only observations preceding the alert date."""
    result = {
        "id": "unavailable",
        "label": PHASE_LABELS["unavailable"],
        "asof": prior[-1]["date"] if prior else None,
        "features": {},
        "maturity": "unclear",
        "maturity_label": "波段进度尚不清楚",
        "leg_sessions": 0,
    }
    if len(prior) < 61:
        return result
    closes = [_number(row.get("sh")) for row in prior[-61:]]
    references = [_number(row.get(k)) for row in prior[-6:] for k in ("P20", "P60")]
    if any(v is None or v <= 0 for v in closes) or any(
        v is None or not 0 <= v <= 1 for v in references
    ):
        return result
    p20_then, p60_then = references[:2]
    p20_now, p60_now = references[-2:]
    p20_slope, p60_slope = p20_now - p20_then, p60_now - p60_then
    close = closes[-1]
    ret5, ret20, ret60 = (close / closes[-i - 1] - 1 for i in (5, 20, 60))
    recent = closes[-20:]
    high, low = max(recent), min(recent)
    high_age, low_age = recent[::-1].index(high), recent[::-1].index(low)
    result["features"] = {
        "ret5": ret5,
        "ret20": ret20,
        "ret60": ret60,
        "from_high20": close / high - 1,
        "from_low20": close / low - 1,
        "from_high60": close / max(closes[-60:]) - 1,
        "from_low60": close / min(closes[-60:]) - 1,
        "days_since_high20": high_age,
        "days_since_low20": low_age,
        "p20_change5": p20_slope,
        "p60_change5": p60_slope,
    }
    phase = "mixed"
    if ret5 > 0 and ret60 <= 0 and close > low and max(p20_slope, p60_slope) > 0:
        phase = "short_rebound"
    elif ret20 < 0 and high_age >= 5 and (ret60 < 0 or p60_slope < 0) and close < (low + high) / 2:
        phase = "sustained_decline"
    elif ret5 < 0 and high_age > 0 and p20_slope < 0:
        phase = "early_decline"
    elif ret20 > 0 and ret60 > 0 and low_age >= 5 and (close >= (high + low) / 2 or p60_slope >= 0):
        phase = "medium_up"
    result.update(id=phase, label=PHASE_LABELS[phase])
    if phase != "mixed":
        up = phase in ("short_rebound", "medium_up")
        sign = 1 if up else -1
        sessions = 0
        for i in range(len(closes) - 1, 4, -1):
            if (closes[i] - closes[i - 5]) * sign <= 0:
                break
            sessions += 1
        if sessions:
            direction = "上涨" if up else "下跌"
            result["leg_sessions"] = sessions
            result["maturity"] = "middle_late" if sessions >= 5 else "early"
            result["maturity_label"] = (
                f"这段{direction}已持续多日" if sessions >= 5 else f"这段{direction}刚开始"
            )
    return result


def _recent_extreme(row: dict, prior: list[dict], key: str, *, high: bool) -> bool:
    """Upper/lower historical quartile. A flat series cannot qualify."""
    value = _number(row.get(key))
    history = [_number(d.get(key)) for d in prior[-20:]]
    if value is None or len(history) < 20 or any(v is None for v in history):
        return False
    return sum(v < value if high else v > value for v in history) >= 15


def _contracts(row: dict) -> Mapping:
    raw = row.get("basis")
    if raw is None:
        raw = row.get("basis_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, Mapping) else {}


def _extra_reasons(row: dict, prior: list[dict]) -> list[str]:
    amount = _number(row.get("amount_ratio20"))
    messages = []
    if amount is not None:
        messages.append(f"全市场成交额是此前20日平均值的{amount:.2f}倍。")
    p250 = _number(row.get("P250"))
    if p250 is not None:
        messages.append(f"收盘高于过去250日平均价的股票占{p250:.1%}。")
    group_ratios = []
    for key in ("up_mean_amount", "down_mean_amount"):
        daily = [_number(r.get(key)) for r in prior[-20:]]
        current = _number(row.get(key))
        if current is not None and len(daily) == 20 and all(v is not None and v > 0 for v in daily):
            group_ratios.append(current / fmean(daily))
    if len(group_ratios) == 2:
        messages.append(
            f"与各组此前20日均值相比，上涨股平均成交额为{group_ratios[0]:.2f}倍、下跌股为{group_ratios[1]:.2f}倍。"
        )
    previous_contracts = _contracts(prior[-1])
    changes = []
    for product, contract in _contracts(row).items():
        reference = previous_contracts.get(product)
        if not isinstance(contract, Mapping) or not isinstance(reference, Mapping):
            continue
        if not contract.get("symbol") or contract["symbol"] != reference.get("symbol"):
            continue
        now, before = _number(contract.get("pct")), _number(reference.get("pct"))
        if now is not None and before is not None:
            changes.append(now - before)
    if changes:
        rising = sum(v > 0 for v in changes)
        falling = sum(v < 0 for v in changes)
        messages.append(
            f"可同合约对比的{len(changes)}种股指期货中，相对现货走强{rising}种、走弱{falling}种。"
        )
    return messages


def _warning(
    episode: dict,
    level: str,
    row: dict,
    title: str,
    message: str,
    reasons: list[str],
    next_check: str,
) -> None:
    alert = episode["alert"]
    alert.update(
        level=level,
        title=title,
        message=message,
        reasons=reasons,
        next_check=next_check,
        update_date=row["date"],
        active=level != "invalidated",
    )


def _open(kind: str, phase: dict, row: dict, prior: list[dict], index: int, evidence: str) -> dict:
    day = row["date"]
    return {
        "start": index,
        "close": row["sh"],
        "p20": row["P20"],
        "p60": row["P60"],
        "floor": min([p["sh"] for p in prior[-5:]] + [row["sh"]]),
        "higher_retest": False,
        "alert": {
            "id": f"{RULE_VERSION}:{kind}:{day}",
            "kind": kind,
            "trigger_date": day,
            "phase_at_trigger": phase["id"],
            "evidence": evidence,
        },
    }


def _advance(
    episode: dict,
    row: dict,
    prior: list[dict],
    index: int,
    narrowing: bool,
    broad_recovery: bool,
    reasons: list[str],
) -> None:
    alert, prev = episode["alert"], prior[-1]
    kind = alert["kind"]
    upper = kind in ("stage_top", "rebound_end")
    if upper:
        broken = row["sh"] > episode["close"] and row["P20"] > episode["p20"] and broad_recovery
    elif kind == "rebound" and alert["level"] == "watch":
        # A watch anticipates a bounce within its five-session horizon. A new
        # low before any bounce keeps it a watch; a new low after a bounce
        # ends that episode and permits a distinct warning at the new low.
        episode["floor"] = min(episode["floor"], row["sh"])
        broken = False
    else:
        broken = row["sh"] < episode["floor"]
    if broken:
        title = "上涨重新扩散，转弱提醒解除" if upper else "收盘跌破观察时的低位，回升提醒解除"
        alert["closure_reason"] = "breadth_recovered" if upper else "lower_close"
        _warning(
            episode,
            "invalidated",
            row,
            title,
            "前一次提醒的依据已经改变。",
            reasons,
            "等待新一轮价格和上涨家数变化。",
        )
        return
    if index - episode["start"] >= WATCH_SESSIONS[kind]:
        alert["closure_reason"] = "expired"
        _warning(
            episode,
            "invalidated",
            row,
            "这次观察期已结束",
            "本轮提醒到期。",
            reasons,
            "再次出现相应变化时，会重新标记日期。",
        )
        return
    if alert["level"] != "watch":
        return
    if upper and narrowing:
        title = "这波反弹正在失去支撑" if kind == "rebound_end" else "这轮中期上涨的转弱迹象加深"
        _warning(
            episode,
            "strengthening",
            row,
            title,
            "过半股票未收涨，近期市场参与度继续转弱。",
            reasons,
            "看指数是否也走低，以及站上中期均线的股票是否继续减少。",
        )
    elif kind == "rebound" and broad_recovery:
        _warning(
            episode,
            "strengthening",
            row,
            "短线反弹已经出现",
            "指数回升，超过一半股票收涨，站上短期均线的股票增多。",
            reasons,
            "接下来观察回踩能否守住，以及上涨能否持续。",
        )
    elif kind == "reversal":
        if row["sh"] < prev["sh"]:
            episode["higher_retest"] = row["sh"] > episode["floor"]
        medium_breadth = [_number(d.get("P60")) for d in [*prior[-2:], row]]
        held = all(value is not None and value >= episode["p60"] for value in medium_breadth)
        distribution = (
            _recent_extreme(row, prior, "trin_amt", high=True)
            and (_number(row.get("trin_amt")) or 0) > 1
        )
        if (
            episode["higher_retest"]
            and broad_recovery
            and held
            and not distribution
            and index - episode["start"] >= 3
        ):
            _warning(
                episode,
                "strengthening",
                row,
                "下跌趋势可能正在扭转",
                "回踩守住了观察低点，随后上涨面再度扩大。",
                reasons,
                "观察后续收盘能否继续守住回踩低点，以及中期上涨面能否保持。",
            )


def build_trend_ledger(rows: Iterable[dict], *, evidence: str = "research_replay") -> list[dict]:
    """Replay once in date order, preserving the original alert ID across updates.

    The input is one completed end-of-day record per trading session. No dates
    are filled in, and missing observations cannot initiate a warning.
    """
    if evidence not in {"experimental", "research_replay"}:
        raise ValueError("unsupported breadth alert evidence")
    prior, ledger, active = [], [], {}
    for index, source in enumerate(rows):
        row = dict(source)
        day = dt.date.fromisoformat(str(row["date"])).isoformat()
        if prior and day <= prior[-1]["date"]:
            raise ValueError("breadth alert rows must have unique increasing trading dates")
        row["date"] = day
        for k in ("sh", "red", "MCL", "P20", "P60"):
            row[k] = _number(row.get(k))
        for key in ("red", "P20", "P60"):
            if row[key] is not None and not 0 <= row[key] <= 1:
                row[key] = None
        phase = classify_phase(prior)
        snapshot = {
            "schema": "breadth-alerts.v1",
            "rule_version": RULE_VERSION,
            "asof": day,
            "phase": phase,
            "state": "unavailable",
            "alerts": [],
            "evidence": evidence,
            "reason": WARMUP,
        }
        previous = prior[-1] if prior else {}
        available = all(
            d.get(k) is not None
            for d in (row, previous)
            for k in ("sh", "red", "P20", "P60", "MCL")
        )
        if phase["id"] != "unavailable" and available and row["sh"] > 0:
            _evaluate_day(snapshot, row, prior, active, index, evidence)
        elif phase["id"] != "unavailable":
            snapshot["reason"] = "最近两日的行情或上涨家数资料不齐，今天的转折提醒暂时无法判断。"
        ledger.append(snapshot)
        prior.append(row)
    return ledger


def _evaluate_day(
    snapshot: dict, row: dict, prior: list[dict], active: dict, index: int, evidence: str
) -> None:
    prev, phase = prior[-1], snapshot["phase"]
    momentum_down = row["MCL"] < prev["MCL"]
    narrowing = (
        row["red"] < 0.5
        and momentum_down
        and (
            prev["red"] - row["red"] >= 0.20
            or (row["P20"] < prev["P20"] and row["sh"] < prev["sh"])
        )
    )
    recovery = (
        row["sh"] > prev["sh"]
        and row["red"] > 0.5
        and row["P20"] > prev["P20"]
        and not momentum_down
    )
    change = row["sh"] / prev["sh"] - 1
    index_move = f"比上一交易日{'涨' if change > 0 else '跌'}{abs(change):.2%}" if change else "与上一交易日持平"
    reasons = [
        f"上证收盘{index_move}，上涨股票占比由{prev['red']:.1%}变为{row['red']:.1%}。",
        f"收盘高于过去20日、60日平均价的股票分别占{row['P20']:.1%}和{row['P60']:.1%}。",
        *_extra_reasons(row, prior),
    ]
    closed = []
    for episode in active.values():
        _advance(episode, row, prior, index, narrowing, recovery, reasons)
    for kind in list(active):
        if not active[kind]["alert"]["active"]:
            closed.append(active.pop(kind)["alert"])

    def start(kind: str, title: str, message: str, extra: list[str], next_check: str) -> None:
        if kind not in active:
            entry = _open(kind, phase, row, prior, index, evidence)
            _warning(entry, "watch", row, title, message, extra + reasons, next_check)
            replaced = active.pop(OPPOSITE[kind], None)
            if replaced is not None:
                old = replaced["alert"]
                old["closure_reason"] = "new_opposite_observation"
                old["replaced_by"] = entry["alert"]["id"]
                scope = "短线" if kind in ("rebound_end", "rebound") else "中期"
                _warning(
                    replaced,
                    "invalidated",
                    row,
                    f"上一轮{scope}观察已结束",
                    f"市场出现反方向变化，今天起改为关注“{title}”。",
                    reasons,
                    "可按起始日期对照这两次观察。",
                )
                closed.append(old)
            active[kind] = entry

    amount = _number(row.get("trin_amt"))
    if phase["id"] in ("short_rebound", "medium_up"):
        concentrated = (
            row["red"] > 0.5
            and amount is not None
            and amount > 1
            and _recent_extreme(row, prior, "trin_amt", high=True)
        )
        if concentrated or narrowing:
            kind = "stage_top" if phase["id"] == "medium_up" else "rebound_end"
            title = "中期上涨可能接近转折" if kind == "stage_top" else "这波反弹可能接近尾声"
            detail = (
                [f"平均每只下跌股成交额是上涨股的{amount:.2f}倍，处在近期较高位置。"]
                if concentrated
                else []
            )
            message = (
                "多数股票上涨，但下跌股的平均成交更活跃。"
                if concentrated
                else "过半股票未收涨，涨跌家数的近期走势转弱。"
            )
            start(kind, title, message, detail, "看接下来上涨家数能否恢复，以及指数是否开始回落。")
    if phase["id"] == "sustained_decline":
        if (
            row["red"] <= 0.25
            and amount is not None
            and amount < 1
            and _recent_extreme(row, prior, "trin_amt", high=False)
        ):
            start(
                "rebound",
                "短线可能反弹",
                "下跌已持续一段时间，少数上涨股的平均成交更活跃。",
                [f"平均每只下跌股成交额是上涨股的{amount:.2f}倍，处在近期较低位置。"],
                "看接下来指数能否回升、上涨家数能否扩大。",
            )
        if recovery and row["P60"] > prev["P60"]:
            start(
                "reversal",
                "跌势可能出现转折",
                "指数回升，站上短期和中期均线的股票都在增加。",
                [],
                "看回踩能否守住近期收盘低点，以及随后的上涨能否扩散。",
            )
    snapshot["alerts"] = [
        {**entry["alert"], "is_new": entry["alert"]["trigger_date"] == row["date"]}
        for entry in active.values()
    ]
    snapshot["alerts"].extend({**alert, "is_new": False} for alert in closed)
    snapshot["state"] = "watch" if snapshot["alerts"] else "quiet"
    snapshot["reason"] = "" if snapshot["alerts"] else "今天的收盘数据没有形成新的转折提醒。"
