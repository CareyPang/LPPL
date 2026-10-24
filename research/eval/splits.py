"""CPCV（预登记 §4）：开发段按时间切成 N=6 个块，每条路径取 k=2 个块做测试，共 C(6,2)=15 条路径。
所有标的共用同一组时间块；训练集中剔除测试块前后各 purge/embargo 个交易日（默认 80）。"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd


def time_blocks(trading_days: pd.DatetimeIndex, n_blocks: int = 6) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    edges = np.linspace(0, len(trading_days), n_blocks + 1).astype(int)
    return [(trading_days[a], trading_days[b - 1]) for a, b in zip(edges[:-1], edges[1:], strict=True)]


def cpcv_paths(
    dates: pd.Series, trading_days: pd.DatetimeIndex, n_blocks: int = 6, k: int = 2, gap: int = 80
) -> list[tuple[np.ndarray, np.ndarray, tuple[int, ...]]]:
    """dates：每个样本的 as-of 日期（可含多个标的）。返回 [(train_mask, test_mask, test_block_ids)]。
    purge+embargo：训练样本的日期必须与任一测试块首尾相距 > gap 个交易日。"""
    blocks = time_blocks(trading_days, n_blocks)
    pos = pd.Series(np.arange(len(trading_days)), index=trading_days)
    d_pos = pos.reindex(pd.DatetimeIndex(dates)).to_numpy()
    out = []
    for test_ids in combinations(range(n_blocks), k):
        test = np.zeros(len(dates), bool)
        banned = np.zeros(len(dates), bool)
        for b in test_ids:
            lo, hi = pos[blocks[b][0]], pos[blocks[b][1]]
            test |= (d_pos >= lo) & (d_pos <= hi)
            banned |= (d_pos >= lo - gap) & (d_pos <= hi + gap)
        train = ~banned & np.isfinite(d_pos)
        out.append((train, test, test_ids))
    return out
