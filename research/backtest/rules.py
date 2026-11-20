from __future__ import annotations

from itertools import product

import pandas as pd

from .engine import run

VARIANTS = tuple(product((2, 3), (5, 20)))


def top_risk_target(n_on: pd.Series, threshold: int, reentry_days: int) -> pd.Series:
    invalid = ~n_on.isin([0, 1, 2, 3])
    if invalid.any():
        raise ValueError(
            f"R-TR1 risk history missing or invalid on {int(invalid.sum())} sessions; "
            f"first: {n_on.index[invalid][0]}"
        )
    target = []
    invested = True
    clear_days = 0
    for value in n_on:
        if invested and value >= threshold:
            invested = False
            clear_days = 0
        elif not invested:
            clear_days = clear_days + 1 if value == 0 else 0
            if clear_days >= reentry_days:
                invested = True
                clear_days = 0
        target.append(int(invested))
    return pd.Series(target, index=n_on.index, dtype=int)


def lppls_target(
    dates: pd.Series,
    frames: list[dict],
    scale: str = "6-12m",
    reentry_days: int = 20,
) -> pd.Series:
    ordered = sorted(frames, key=lambda frame: frame["asof"])
    active = []
    cursor = -1
    frame = None
    invested = True
    clear_days = 0
    for value in pd.to_datetime(dates).dt.strftime("%Y-%m-%d"):
        while cursor + 1 < len(ordered) and ordered[cursor + 1]["asof"] <= value:
            cursor += 1
            frame = ordered[cursor]
        clusters = [] if frame is None else (frame.get("clusters") or {}).get(scale) or []
        on = any(
            cluster.get("q80_date") is not None and cluster["q80_date"] >= value
            for cluster in clusters
        )
        if on:
            invested = False
            clear_days = 0
        elif not invested:
            clear_days += 1
            if clear_days >= reentry_days:
                invested = True
                clear_days = 0
        active.append(int(invested))
    return pd.Series(active, index=dates.index, dtype=int)


def select_top_risk_variant(
    prices: pd.DataFrame,
    n_on: pd.Series,
    dev_start: str = "2014-01-01",
    dev_end: str = "2022-12-31",
) -> tuple[dict, dict]:
    dev = prices.loc[
        prices["date"].astype(str).between(dev_start, dev_end)
    ].copy()
    dates = pd.to_datetime(dev["date"]).dt.strftime("%Y-%m-%d")
    aligned = n_on.copy()
    aligned.index = pd.to_datetime(aligned.index).strftime("%Y-%m-%d")
    selected = aligned.reindex(dates)
    variants = {}
    for threshold, reentry_days in VARIANTS:
        target = top_risk_target(selected, threshold, reentry_days)
        target.index = dates
        _, _, metrics = run(dev, target)
        drawdown = abs(metrics["max_drawdown"])
        calmar = metrics["cagr"] / drawdown if drawdown else None
        key = f"K{threshold}_M{reentry_days}"
        variants[key] = {
            "K": threshold,
            "M": reentry_days,
            **metrics,
            "calmar": calmar,
            "evidence": "dev_only",
        }
    best = max(
        variants,
        key=lambda key: (
            (
                float("inf")
                if variants[key]["calmar"] is None and variants[key]["cagr"] > 0
                else (
                    float("-inf")
                    if variants[key]["calmar"] is None
                    else variants[key]["calmar"]
                )
            ),
            -variants[key]["n_trades"],
        ),
    )
    return {"K": variants[best]["K"], "M": variants[best]["M"]}, variants
