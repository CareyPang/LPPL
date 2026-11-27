"""宽度买卖候选的定义与评估（docs/preregistration_breadth_signal.md）。只做研究检验，不进线上。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.data import breadth

HORIZON = 60
COOLDOWN = 20
NEAR = 0.03
SHIFTS = 2000
SEED = 20261127


def _first(mask) -> np.ndarray:
    mask = np.asarray(mask, bool)
    return mask & ~np.r_[False, mask[:-1]]


def _ended(mask) -> np.ndarray:
    mask = np.asarray(mask, bool)
    return ~mask & np.r_[False, mask[:-1]]


def _recent(mask, days: int) -> np.ndarray:
    series = pd.Series(np.asarray(mask, float)).shift(1).rolling(days, min_periods=1).max()
    return series.fillna(0).to_numpy() > 0


def candidates(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, np.ndarray], dict[str, np.ndarray]]:
    """frame: date, sh, red, lu, ld, amount_yi, P20。返回 (有状态的日序列, 买入候选, 卖出候选)。"""
    states = breadth.classify_states(frame)
    states = states.loc[states["state"].notna()].reset_index(drop=True)
    state = states["state"]
    close = states["sh"]
    panic = state.str.startswith("panic").to_numpy()
    panic_low = state.eq("panic_low").to_numpy()
    high60 = (close >= close.rolling(60, min_periods=60).max()).to_numpy()
    overheat = states["overheat"].to_numpy()
    up = (states["red"] >= breadth.STATE_RED_HIGH).to_numpy()
    heavy_down = state.eq("down_heavy").to_numpy() | panic
    p20 = states["P20"].to_numpy()
    below_half = np.zeros(len(states), bool)
    armed = False
    for i in range(len(states)):
        if overheat[i]:
            armed = True
        elif armed and p20[i] < 0.5:
            below_half[i] = True
            armed = False
    buy = {
        "B1": panic_low,
        "B0": panic,
        "B2": state.eq("panic_first").to_numpy(),
        "B7": _first(up & _recent(panic_low, 5)),
    }
    sell = {
        "S1": _first(overheat),
        "S3": overheat & high60,
        "S4": states["top_div"].to_numpy(),
        "S5": _first(heavy_down & _recent(overheat, 20)),
        "S6": below_half,
    }
    return states, buy, sell


def episodes(mask: np.ndarray, valid: np.ndarray) -> list[int]:
    """冷却去重：取到一次后，之后 COOLDOWN 个交易日内的信号不再取。"""
    out, last = [], -10**9
    for i in np.flatnonzero(mask & valid):
        if i - last > COOLDOWN:
            out.append(int(i))
            last = int(i)
    return out


def outcomes(close: np.ndarray, idx: list[int], side: str) -> pd.DataFrame:
    rows = []
    for i in idx:
        fwd = close[i : i + HORIZON + 1]
        around = close[max(0, i - HORIZON) : i + HORIZON + 1]
        extreme = fwd.min() if side == "buy" else fwd.max()
        rows.append(
            {
                "i": i,
                "extreme": extreme / close[i] - 1,
                "days": int(fwd.argmin() if side == "buy" else fwd.argmax()),
                "position": (close[i] - around.min()) / (around.max() - around.min()),
                "ret20": close[i + 20] / close[i] - 1,
                "ret60": close[i + HORIZON] / close[i] - 1,
                "best": (fwd.max() if side == "buy" else fwd.min()) / close[i] - 1,
            }
        )
    return pd.DataFrame(rows)


def summary(frame: pd.DataFrame, side: str) -> dict[str, float]:
    if frame.empty:
        return {"n": 0}
    sign = 1 if side == "buy" else -1
    return {
        "n": int(len(frame)),
        "near": float((frame["extreme"].abs() <= NEAR).mean()),
        "extreme_median": float(frame["extreme"].median()),
        "days_median": float(frame["days"].median()),
        "position_median": float(frame["position"].median()),
        "ret60_median": float(frame["ret60"].median()),
        "ret60_right": float((sign * frame["ret60"] > 0).mean()),
        "ret20_right": float((sign * frame["ret20"] > 0).mean()),
    }


def shift_p(close: np.ndarray, mask: np.ndarray, valid: np.ndarray, side: str) -> float:
    """把信号序列在检验段内整体循环平移，比较“离极值不超过 NEAR”的比例。"""
    span = np.flatnonzero(valid)
    lo, hi = span[0], span[-1] + 1
    inner = (mask & valid)[lo:hi]
    observed = summary(outcomes(close, episodes(mask, valid), side), side).get("near", np.nan)
    rng = np.random.default_rng(SEED)
    hits = 0
    for shift in rng.integers(1, hi - lo, SHIFTS):
        rolled = np.zeros(len(close), bool)
        rolled[lo:hi] = np.roll(inner, int(shift))
        value = summary(outcomes(close, episodes(rolled, valid), side), side).get("near", 0.0)
        hits += value >= observed
    return (hits + 1) / (SHIFTS + 1)
