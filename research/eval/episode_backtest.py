"""Episode 事件级回测评估（按轮次统计严格 as-of 首次预警与事后顶对照 + 随机基线）。

LPPLS 置信度是相变序参量而非校准概率：本模块将连续出现顶部聚类/区间的周度帧归并为
预警段（Episode），计算每轮首次预警日、提前天数、事后最大回撤、区间命中率，并与同等
预警轮数随机置放的 Null Permutation 基线对照。
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _has_scale_signal(frame: dict[str, Any], scale: str) -> bool:
    w = (frame.get("w") or {}).get(scale)
    cl = (frame.get("clusters") or {}).get(scale)
    return bool((isinstance(w, list) and len(w) == 2 and w[0] and w[1]) or (isinstance(cl, list) and len(cl) > 0))


def _first_interval(frame: dict[str, Any], scale: str) -> list[str] | None:
    cl = (frame.get("clusters") or {}).get(scale)
    if isinstance(cl, list) and cl:
        main = cl[0]
        if main.get("q20_date") and main.get("q80_date"):
            return [str(main["q20_date"]), str(main["q80_date"])]
    w = (frame.get("w") or {}).get(scale)
    if isinstance(w, list) and len(w) == 2 and w[0] and w[1]:
        return [str(w[0]), str(w[1])]
    return None


def _classify_top(top_date: date | None, interval: list[str] | None, buffer_days: int = 0) -> str:
    if top_date is None or not interval:
        return "none"
    lo = _parse_date(interval[0])
    hi = _parse_date(interval[1])
    if lo is None or hi is None:
        return "none"
    if (lo.toordinal() - buffer_days) <= top_date.toordinal() <= (hi.toordinal() + buffer_days):
        return "inside"
    return "before" if top_date < lo else "after"


def extract_episodes(
    frames: list[dict[str, Any]],
    tops: list[dict[str, Any]],
    scale: str = "6-12m",
    buffer_days: int = 15,
) -> list[dict[str, Any]]:
    """从按时间排序的周度帧中提取预警段（Episode），严格以 first_asof 对照其后的事后顶。"""
    ordered = sorted(
        [f for f in frames if _parse_date(f.get("asof")) is not None],
        key=lambda f: str(f["asof"]),
    )
    parsed_tops = sorted(
        [
            (d, t)
            for t in tops
            if (d := _parse_date(t.get("date"))) is not None
        ],
        key=lambda item: item[0],
    )

    episodes: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []

    def _flush(group: list[dict[str, Any]]) -> None:
        if not group:
            return
        first = group[0]
        last = group[-1]
        first_dt = _parse_date(first["asof"])
        interval = _first_interval(first, scale)
        next_top = next(((d, t) for d, t in parsed_tops if first_dt is not None and d > first_dt), None)
        top_dt, top_obj = next_top if next_top else (None, None)
        days_to_top = (top_dt - first_dt).days if (top_dt and first_dt) else None
        relation = _classify_top(top_dt, interval, buffer_days=0)
        relation_buffered = _classify_top(top_dt, interval, buffer_days=buffer_days)
        episodes.append(
            {
                "scale": scale,
                "first_asof": str(first["asof"]),
                "last_asof": str(last["asof"]),
                "weeks": len(group),
                "split": first.get("split"),
                "first_interval": interval,
                "max_fco_intensity": round(
                    max(float(f.get("fco_intensity") or 0.0) for f in group), 3
                ),
                "next_top_date": str(top_obj["date"]) if top_obj else None,
                "next_top_max_dd": top_obj.get("max_dd") if top_obj else None,
                "days_to_top": days_to_top,
                "top_relation": relation,
                "top_relation_buffered": relation_buffered,
            }
        )

    for frame in ordered:
        if _has_scale_signal(frame, scale):
            cur.append(frame)
        else:
            _flush(cur)
            cur = []
    _flush(cur)
    return episodes


def evaluate_episodes(
    frames: list[dict[str, Any]],
    tops: list[dict[str, Any]],
    scale: str = "6-12m",
    buffer_days: int = 15,
    n_perm: int = 200,
    seed: int = 0,
) -> dict[str, Any]:
    """计算事件级命中率与同等预警轮数随机置放（Null Permutation）基线对比。"""
    episodes = extract_episodes(frames, tops, scale=scale, buffer_days=buffer_days)
    n_ep = len(episodes)
    if n_ep == 0:
        return {
            "scale": scale,
            "n_episodes": 0,
            "hit_rate_exact": None,
            "hit_rate_buffered": None,
            "null_hit_rate_buffered": None,
            "p_value_buffered": None,
            "median_days_to_top": None,
            "episodes": [],
        }

    exact_hits = sum(1 for ep in episodes if ep["top_relation"] == "inside")
    buf_hits = sum(1 for ep in episodes if ep["top_relation_buffered"] == "inside")
    hit_exact = exact_hits / n_ep
    hit_buf = buf_hits / n_ep
    lead_days = [ep["days_to_top"] for ep in episodes if ep["days_to_top"] is not None]
    median_lead = float(np.median(lead_days)) if lead_days else None

    # 同等频率随机置放基线：保持每轮预警窗口宽度不变，在全部帧日期中随机抽取同等数量的起始帧
    ordered_dates = [d for f in frames if (d := _parse_date(f.get("asof"))) is not None]
    parsed_tops = sorted(
        d for t in tops if (d := _parse_date(t.get("date"))) is not None
    )
    widths = []
    for ep in episodes:
        iv = ep["first_interval"]
        f_dt = _parse_date(ep["first_asof"])
        lo_dt = _parse_date(iv[0]) if iv else None
        hi_dt = _parse_date(iv[1]) if iv else None
        if f_dt and lo_dt and hi_dt:
            widths.append((lo_dt.toordinal() - f_dt.toordinal(), hi_dt.toordinal() - f_dt.toordinal()))
        else:
            widths.append((0, 0))

    null_rate = None
    p_value = None
    if ordered_dates and parsed_tops and n_perm > 0:
        rng = np.random.default_rng(seed)
        top_ords = np.array([d.toordinal() for d in parsed_tops], dtype=int)
        date_ords = np.array([d.toordinal() for d in ordered_dates], dtype=int)
        null_rates = np.empty(n_perm, dtype=float)
        for p in range(n_perm):
            picks = rng.choice(date_ords, size=n_ep, replace=len(date_ords) < n_ep)
            hits = 0
            for start_ord, (lo_off, hi_off) in zip(picks, widths, strict=True):
                future_tops = top_ords[top_ords > start_ord]
                if len(future_tops):
                    nxt = int(future_tops[0])
                    if (start_ord + lo_off - buffer_days) <= nxt <= (start_ord + hi_off + buffer_days):
                        hits += 1
            null_rates[p] = hits / n_ep
        null_rate = round(float(null_rates.mean()), 4)
        p_value = round(float((1 + np.sum(null_rates >= hit_buf)) / (n_perm + 1)), 4)

    return {
        "scale": scale,
        "n_episodes": n_ep,
        "hit_rate_exact": round(hit_exact, 4),
        "hit_rate_buffered": round(hit_buf, 4),
        "null_hit_rate_buffered": null_rate,
        "p_value_buffered": p_value,
        "median_days_to_top": round(median_lead, 1) if median_lead is not None else None,
        "episodes": episodes,
    }
