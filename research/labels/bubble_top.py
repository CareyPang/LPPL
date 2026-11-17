"""确认顶部事件标签：固定回撤、观察期与可知日。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BubbleTopParams:
    look: int = 250
    rise: float = 0.50
    dd: float = 0.20
    horizon: int = 60
    dedup: int = 120
    preset: str = "index"

    @classmethod
    def stock(cls) -> BubbleTopParams:
        return cls(rise=1.00, dd=0.30, preset="stock")


TOP_COLUMNS = (
    "top_date",
    "dd_hit_date",
    "confirm_date",
    "status",
    "top_close",
    "rise_pct",
    "dd_pct_60",
    "look",
    "preset",
)


def _deduplicate(rows: list[dict], dedup: int) -> list[dict]:
    kept: list[dict] = []
    for row in rows:
        conflicts = [item for item in kept if abs(item["_idx"] - row["_idx"]) <= dedup]
        if not conflicts:
            kept.append(row)
            continue
        winner = max([*conflicts, row], key=lambda item: (item["top_close"], -item["_idx"]))
        if winner["_idx"] == row["_idx"]:
            conflict_indices = {item["_idx"] for item in conflicts}
            kept = [item for item in kept if item["_idx"] not in conflict_indices]
            kept.append(row)
    return sorted(kept, key=lambda item: item["_idx"])


def bubble_tops(
    dates: pd.DatetimeIndex,
    close: np.ndarray,
    params: BubbleTopParams,
) -> pd.DataFrame:
    dates = pd.DatetimeIndex(dates)
    prices = np.asarray(close, dtype=float)
    if len(dates) != len(prices):
        raise ValueError("dates and close must have the same length")

    rows = []
    n = len(prices)
    for i in range(params.look, n):
        price = prices[i]
        window = prices[i - params.look : i + 1]
        low = np.min(window)
        if not np.isfinite(price) or not np.isfinite(low) or low <= 0 or price != np.max(window):
            continue
        rise_pct = float(price / low - 1)
        if rise_pct < params.rise:
            continue

        dedup_end = min(n, i + params.dedup + 1)
        later_dedup = prices[i + 1 : dedup_end]
        if np.any(later_dedup > price):
            continue
        dedup_complete = i + params.dedup < n

        horizon_end = min(n, i + params.horizon + 1)
        later_horizon = prices[i + 1 : horizon_end]
        hits = np.flatnonzero(later_horizon <= price * (1 - params.dd))
        hit_idx = i + 1 + int(hits[0]) if len(hits) else None
        horizon_complete = i + params.horizon < n
        if hit_idx is None and horizon_complete:
            continue

        dd_pct = float(1 - np.min(later_horizon) / price) if len(later_horizon) else np.nan
        confirmed = hit_idx is not None and dedup_complete
        confirm_idx = max(hit_idx, i + params.dedup) if confirmed else None
        rows.append({
            "_idx": i,
            "top_date": dates[i],
            "dd_hit_date": dates[hit_idx] if hit_idx is not None else pd.NaT,
            "confirm_date": dates[confirm_idx] if confirm_idx is not None else pd.NaT,
            "status": "confirmed" if confirmed else "pending",
            "top_close": float(price),
            "rise_pct": rise_pct,
            "dd_pct_60": dd_pct,
            "look": params.look,
            "preset": params.preset,
        })

    selected = _deduplicate(rows, params.dedup)
    return pd.DataFrame([{key: row[key] for key in TOP_COLUMNS} for row in selected], columns=TOP_COLUMNS)


def known_tops(df: pd.DataFrame, asof: str | pd.Timestamp) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    confirm_date = pd.to_datetime(df["confirm_date"])
    mask = (df["status"] == "confirmed") & (confirm_date <= pd.Timestamp(asof))
    return df.loc[mask].copy()
