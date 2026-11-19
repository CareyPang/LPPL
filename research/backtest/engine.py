from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EngineConfig:
    limit_pct: float | None = None
    commission_bps: float = 2.5
    stamp_bps: float = 5.0
    slippage_bps: float = 5.0


def _config(cfg: EngineConfig | dict | None) -> EngineConfig:
    if cfg is None:
        return EngineConfig()
    if isinstance(cfg, EngineConfig):
        return cfg
    return EngineConfig(**cfg)


def max_drawdown(values: np.ndarray) -> float:
    if not len(values):
        return 0.0
    peaks = np.maximum.accumulate(values)
    return float(np.min(values / peaks - 1))


def execution_metrics(
    equity: pd.DataFrame,
    trades: list[dict],
    positions: list[bool],
) -> dict:
    nav = equity["nav"].to_numpy(dtype=float)
    bh = equity["bh_nav"].to_numpy(dtype=float)
    closed = [trade for trade in trades if trade["exit"] is not None]
    returns = np.asarray([trade["ret"] for trade in closed], dtype=float)
    years = max((len(nav) - 1) / 252, 1 / 252)
    gains = returns[returns > 0]
    losses = returns[returns < 0]
    return {
        "n_trades": len(closed),
        "win_rate": float(np.mean(returns > 0)) if len(returns) else 0.0,
        "total_return": float(nav[-1] / nav[0] - 1) if len(nav) else 0.0,
        "bh_return": float(bh[-1] / bh[0] - 1) if len(bh) else 0.0,
        "cagr": float((nav[-1] / nav[0]) ** (1 / years) - 1)
        if len(nav) and nav[-1] > 0
        else -1.0,
        "max_drawdown": max_drawdown(nav),
        "bh_max_drawdown": max_drawdown(bh),
        "profit_factor": float(gains.sum() / abs(losses.sum()))
        if len(losses) and losses.sum()
        else (None if len(gains) else 0.0),
        "avg_trade_return": float(np.mean(returns)) if len(returns) else 0.0,
        "avg_bars": float(np.mean([trade["bars"] for trade in closed]))
        if closed
        else 0.0,
        "exposure": float(np.mean(positions)) if positions else 0.0,
        "turnover": float(len(closed) / years),
    }


def run(
    prices: pd.DataFrame,
    target: pd.Series,
    cfg: EngineConfig | dict | None = None,
) -> tuple[pd.DataFrame, list[dict], dict]:
    """Simulate full/flat positions; close-t signals execute at the next open."""
    settings = _config(cfg)
    required = {"date", "open", "high", "low", "close", "prev_close"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"prices missing columns: {sorted(missing)}")
    frame = prices.loc[:, ["date", "open", "high", "low", "close", "prev_close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    frame = frame.sort_values("date").reset_index(drop=True)
    if frame["date"].duplicated().any():
        raise ValueError("prices contain duplicate dates")
    open_values = pd.to_numeric(frame["open"], errors="coerce")
    high_values = pd.to_numeric(frame["high"], errors="coerce")
    low_values = pd.to_numeric(frame["low"], errors="coerce")
    close_values = pd.to_numeric(frame["close"], errors="coerce")
    prev_values = pd.to_numeric(frame["prev_close"], errors="coerce")
    invalid_ohl = open_values.notna() & (
        ~np.isfinite(open_values) | ~np.isfinite(high_values) | ~np.isfinite(low_values)
    )
    if (
        invalid_ohl.any()
        or (high_values.notna() & ~np.isfinite(high_values)).any()
        or (low_values.notna() & ~np.isfinite(low_values)).any()
        or np.isinf(open_values).any()
        or not np.isfinite(close_values).all()
        or not np.isfinite(prev_values).all()
    ):
        raise ValueError("prices contain non-finite OHLC values")
    frame["open"] = open_values
    signals = target.copy()
    if isinstance(signals.index, pd.DatetimeIndex):
        signals.index = signals.index.strftime("%Y-%m-%d")
    signals.index = signals.index.astype(str)
    signal_values = signals.reindex(frame["date"]).fillna(0)
    if not np.isin(signal_values, [0, 1]).all():
        raise ValueError("target values must be 0 or 1")
    signal_values = signal_values.astype(int).to_numpy()

    commission = settings.commission_bps / 10_000
    stamp = settings.stamp_bps / 10_000
    slippage = settings.slippage_bps / 10_000
    nav = 1.0
    shares = 0.0
    holding = False
    entry_index: int | None = None
    entry_cost_per_share = 0.0
    trades: list[dict] = []
    rows: list[dict] = []
    positions: list[bool] = []
    bh_nav = 1.0
    pending_target: bool | None = None

    for i, row in frame.iterrows():
        desired = bool(signal_values[i - 1]) if i else False
        if pending_target is None and desired != holding:
            pending_target = desired
        opened = float(row["open"]) if pd.notna(row["open"]) else float("nan")
        open_valid = np.isfinite(opened)
        prev_close = float(row["prev_close"])
        day = row["date"]
        locked_buy = (
            open_valid
            and settings.limit_pct is not None
            and opened >= prev_close * (1 + settings.limit_pct) - 0.001
        )
        locked_sell = (
            open_valid
            and settings.limit_pct is not None
            and opened <= prev_close * (1 - settings.limit_pct) + 0.001
        )

        if pending_target is True and not holding and open_valid and not locked_buy:
            entry_price = opened * (1 + slippage)
            entry_cost_per_share = entry_price * (1 + commission)
            shares = nav / entry_cost_per_share
            holding = True
            entry_index = i
            nav = shares * float(row["close"])
            pending_target = None
        elif (
            pending_target is False
            and holding
            and open_valid
            and not locked_sell
            and entry_index is not None
            and i > entry_index
        ):
            exit_price = opened * (1 - slippage)
            proceeds_per_share = exit_price * (1 - commission - stamp)
            nav = shares * exit_price * (1 - commission - stamp)
            trades.append(
                {
                    "entry": frame.iloc[entry_index]["date"],
                    "exit": day,
                    "bars": i - entry_index,
                    "ret": proceeds_per_share / entry_cost_per_share - 1,
                    "reason_in": "target=1",
                    "reason_out": "target=0",
                }
            )
            shares = 0.0
            holding = False
            entry_index = None
            pending_target = None
        elif holding:
            nav = shares * float(row["close"])

        if i:
            bh_nav *= float(row["close"]) / float(frame.iloc[i - 1]["close"])
        rows.append({"date": day, "nav": nav, "bh_nav": bh_nav})
        positions.append(holding)

    if holding and entry_index is not None:
        trades.append(
            {
                "entry": frame.iloc[entry_index]["date"],
                "exit": None,
                "bars": len(frame) - 1 - entry_index,
                "ret": None,
                "reason_in": "target=1",
                "reason_out": None,
            }
        )
    equity = pd.DataFrame(rows)
    metrics = execution_metrics(equity, trades, positions)
    return equity, trades, metrics
