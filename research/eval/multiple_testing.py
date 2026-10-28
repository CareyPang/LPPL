"""多重比较与"运气"校正工具（预登记 §6、§12.4；最终测试段前必须就绪，本文件只在合成数据上测试）。

- SPA（Hansen 2005, JBES "A Test for Superior Predictive Ability"）：块 bootstrap 下"所有候选都不优于基准"的 p 值。
- PBO（Bailey, Borwein, López de Prado, Zhu 2017, J. Comput. Finance "The Probability of Backtest Overfitting"）：CSCV。
- Deflated Sharpe（Bailey & López de Prado 2014, J. Portfolio Mgmt）：对候选数、偏度、峰度校正后的夏普显著性。
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
from scipy.stats import norm


def circular_block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    starts = rng.integers(0, n, int(np.ceil(n / block)))
    idx = (starts[:, None] + np.arange(block)[None, :]).ravel() % n
    return idx[:n]


def spa_pvalue(d: np.ndarray, block: int = 80, B: int = 2000, seed: int = 0) -> tuple[float, int]:
    """d：(T, K) 损失差，d[t,k] = L_base[t] − L_k[t]，正为候选 k 优于基准。返回 (p 值, 最优候选列号)。

    统计量 T_SPA = max_k sqrt(n) d̄_k / ω̂_k；零分布按 Hansen 的一致性再中心化 μ̂_k = d̄_k·1{ sqrt(n) d̄_k/ω̂_k ≤ −sqrt(2 log log n) }。
    """
    d = np.atleast_2d(d.T).T if d.ndim == 1 else d
    n, K = d.shape
    rng = np.random.default_rng(seed)
    dbar = d.mean(0)
    boots = np.empty((B, K))
    for b in range(B):
        boots[b] = d[circular_block_indices(n, block, rng)].mean(0)
    omega = np.sqrt(n) * boots.std(0, ddof=1)
    omega = np.where(omega > 0, omega, np.inf)
    t_stat = np.sqrt(n) * dbar / omega
    mu = np.where(t_stat <= -np.sqrt(2 * np.log(np.log(max(n, 3)))), dbar, 0.0)
    T_obs = max(t_stat.max(), 0.0)
    T_boot = np.maximum((np.sqrt(n) * (boots - dbar + mu) / omega).max(1), 0.0)
    return float((T_boot >= T_obs).mean()), int(np.argmax(t_stat))


def pbo(M: np.ndarray, S: int = 16, metric=None) -> dict:
    """M：(T, N) 各候选的逐期收益/得分；CSCV：S 个等长块，所有 S/2 组合做 IS/OOS，IS 最优在 OOS 的相对排名。"""
    metric = metric or (lambda x: x.mean(0) / (x.std(0, ddof=1) + 1e-12))
    T, N = M.shape
    blocks = np.array_split(np.arange(T - T % S), S)
    logits = []
    for c in combinations(range(S), S // 2):
        is_idx = np.concatenate([blocks[i] for i in c])
        oos_idx = np.concatenate([blocks[i] for i in range(S) if i not in c])
        best = int(np.argmax(metric(M[is_idx])))
        oos = metric(M[oos_idx])
        r = (np.sum(oos < oos[best]) + 0.5) / (N + 1)
        logits.append(np.log(r / (1 - r)))
    logits = np.asarray(logits)
    return dict(pbo=float((logits < 0).mean()), n_combos=len(logits), logit_mean=float(logits.mean()))


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    g = 0.5772156649
    return float(np.sqrt(var_sr) * ((1 - g) * norm.ppf(1 - 1 / n_trials) + g * norm.ppf(1 - 1 / (n_trials * np.e))))


def deflated_sharpe(sr: float, T: int, skew: float, kurt: float, n_trials: int, var_sr: float) -> float:
    """sr 为每期（非年化）夏普；kurt 为非超额峰度；var_sr 为候选夏普的方差；返回 DSR = P(真夏普 > 0)。"""
    sr0 = expected_max_sharpe(n_trials, var_sr) if n_trials > 1 else 0.0
    denom = np.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr**2, 1e-12))
    return float(norm.cdf((sr - sr0) * np.sqrt(T - 1) / denom))
