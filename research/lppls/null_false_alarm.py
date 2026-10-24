"""零假设序列上的误报率（预登记方案 §8）：python -m research.lppls.null_false_alarm → reports/null_false_alarm.{json,md}

对每条零假设序列，在末端取多个窗口（60–250 日，步长 10）拟合 LPPLS，统计四套规则的合格窗口比例：
  P-DS / P-STRICT : 原型 engine.js 的 ds / strict（js_compat）
  P-TOP           : 原型 critical.js 的 TOP_RULE（core.qualifies）
  LIT-DS          : E7 表 3 条件 1。t_c 允许落在窗口末端之前，搜索域 m∈[0.01,2]、ω∈[1,50]、t_c∈[t₂−0.2dt, t₂+0.2dt]
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..optim.optimizers import METHODS
from ..synth.nulls import NULLS, sample_null
from .core import TOP_RULE, default_bounds, design, lin_fit, qualifies, unpack
from .js_compat import JS_FILTERS

OUT = Path(__file__).resolve().parents[2] / "reports"
WINDOWS = tuple(range(60, 251, 10))


def lit_ds_ok(theta, beta, t, y) -> bool:
    tc, m, w = theta
    t1, t2 = t[0], t[-1]
    dt = t2 - t1
    if not (0.1 <= m <= 0.9 and 6 <= w <= 13 and t2 - 0.15 * dt <= tc <= t2 + 0.13 * dt):
        return False
    A, B, C1, C2 = beta
    C = np.hypot(C1, C2)
    if B >= 0 or C == 0:
        return False
    damping = m * abs(B) / (w * C)
    # E7 表 3：(ω/2)·ln|(t_c−t₁)/(t_c−t₂)|；t_c 可早于 t₂，故取绝对值
    n_osc = (w / 2) * np.log(abs((tc - t1) / (tc - t2))) if tc != t2 else np.inf
    yhat = design(t, tc, m, w) @ beta
    rel_err = float(np.max(np.abs((np.exp(y) - np.exp(yhat)) / np.exp(y))))
    return bool(damping >= 1.2 and n_osc >= 2.5 and rel_err <= 0.035)


def scan(y: np.ndarray, method="tcgrid_lm", seed=0) -> dict[str, float]:
    hits = {k: 0 for k in ("P-DS", "P-STRICT", "P-TOP", "LIT-DS")}
    for n in WINDOWS:
        yw = y[-n:]
        t = np.arange(n, dtype=float)
        lo, hi = default_bounds(n, horizon=(1, 115))
        r = METHODS[method](t, yw, lo, hi, seed=seed)
        f = unpack(r.theta, t, yw)
        if f is not None:
            hits["P-DS"] += JS_FILTERS["ds"](f)
            hits["P-STRICT"] += JS_FILTERS["strict"](f)
            hits["P-TOP"] += qualifies(f, TOP_RULE)[0]
        dt = n - 1
        lo2 = np.array([dt - 0.2 * dt, 0.01, 1.0])
        hi2 = np.array([dt + 0.2 * dt, 2.0, 50.0])
        r2 = METHODS[method](t, yw, lo2, hi2, seed=seed)
        s2, beta2 = lin_fit(t, yw, *r2.theta)
        if beta2 is not None:
            hits["LIT-DS"] += lit_ds_ok(r2.theta, beta2, t, yw)
    return {k: v / len(WINDOWS) for k, v in hits.items()}


def main(n_series=20, n=250):
    rows = []
    for kind in NULLS:
        for s in range(n_series):
            t, y = sample_null(kind, n=n, seed=700 + s)
            rows.append(dict(kind=kind, series=s, **scan(y, seed=s)))
        print(kind, "done", flush=True)
    df = pd.DataFrame(rows)
    df.to_json(OUT / "null_false_alarm.json", orient="records")
    tab = df.groupby("kind")[["P-DS", "P-STRICT", "P-TOP", "LIT-DS"]].mean()
    any_tab = df.groupby("kind")[["P-DS", "P-STRICT", "P-TOP", "LIT-DS"]].agg(lambda c: (c > 0).mean())
    (OUT / "null_false_alarm.md").write_text(
        "# 零假设序列误报率（阶段 3b）\n\n每类零假设 20 条序列，每条在末端取 20 个窗口（60–250 日）。\n\n"
        "## 合格窗口的平均比例（相当于置信度指标在无泡沫数据上的均值）\n" + tab.round(3).to_markdown()
        + "\n\n## 至少一个窗口合格的序列比例（任一报警）\n" + any_tab.round(3).to_markdown() + "\n")
    print(tab.round(3))


if __name__ == "__main__":
    main()
