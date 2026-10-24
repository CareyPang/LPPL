"""校准段工具（预登记 §6、§12.3、§13.1）：固定 Platt 校准与区间保形缩放。

- Platt（Platt 1999；小样本优于 isotonic：Niculescu-Mizil & Caruana 2005）：在校准段 OOF/前推概率的 logit 上拟合 p' = σ(a·logit(p) + b)，一次拟合、之后固定。
- 区间保形缩放（§12.3）：对校准段的 (区间中点, 半宽, 目标) 选择单一缩放系数 s，使 |目标 − 中点| ≤ s·半宽 的覆盖率达到目标水平（分裂保形的分位数形式）。
本文件只在合成数据上测试；校准段数据在模型锁定后一次性使用。
"""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression

EPS = 1e-6


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


class Platt:
    def __init__(self):
        self.a = 1.0
        self.b = 0.0

    def fit(self, p: np.ndarray, y: np.ndarray) -> Platt:
        m = LogisticRegression(C=1e6, solver="lbfgs").fit(logit(p)[:, None], y)
        self.a, self.b = float(m.coef_[0, 0]), float(m.intercept_[0])
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        z = self.a * logit(p) + self.b
        return 1 / (1 + np.exp(-z))


def conformal_scale(center: np.ndarray, half_width: np.ndarray, target: np.ndarray, level: float = 0.8) -> float:
    """返回缩放系数 s，使校准段覆盖率 ≥ level（含有限样本修正 ⌈(n+1)·level⌉/n）。half_width 必须 > 0。"""
    score = np.abs(target - center) / half_width
    n = len(score)
    q = min(1.0, np.ceil((n + 1) * level) / n)
    return float(np.quantile(score, q, method="higher"))
