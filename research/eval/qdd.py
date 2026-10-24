"""连续次要目标 Q-DD（预登记 v1.2 §12.5）：未来 60 日最大回撤 dd_ahead 的 τ=0.9 分位数回归。

特征：主链保留级的特征集（由 reports/ladder_dev.json 读取）；配置 C ∈ {0.1, 1}，映射为 L1 惩罚 alpha = 1 / (C · n_train)。
主评分：pinball loss（τ=0.9）；基线：训练段无条件 90% 分位。差值用 80 日块 bootstrap 90% 区间。
不参与 R0–R7 的淘汰决策。训练样本每 5 个交易日抽一行以减轻重叠并加速 LP 求解；评分用全部 OOF 样本。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import QuantileRegressor

from .baselines import cpcv_oof
from .dataset import LABELS, price_series
from .ladder import CS, OOF_DIR, assemble
from .ladder_lppls import prev_features

TAU = 0.9
SUB = 5


def pinball(y: np.ndarray, q: np.ndarray, tau: float = TAU) -> np.ndarray:
    d = y - q
    return np.where(d >= 0, tau * d, (tau - 1) * d)


def assemble_dd(split: str = "dev") -> pd.DataFrame:
    df = assemble(split)
    dd = pd.concat(
        [pd.read_parquet(LABELS / f"{s}.parquet")["main__dd_ahead"].rename_axis("date").reset_index().assign(symbol=s)
         for s in df.symbol.unique()])
    df = df.merge(dd.rename(columns={"main__dd_ahead": "dd"}), on=["date", "symbol"], how="left").dropna(subset=["dd"])
    df["dd"] = df.dd.clip(lower=0.0)
    return df


def fit_quantile(features: list[str], C: float):
    def fp(tr, te):
        tr = tr.iloc[::SUB]
        m = QuantileRegressor(quantile=TAU, alpha=1 / (C * len(tr)), solver="highs")
        m.fit(tr[features].to_numpy(), tr.y.to_numpy())
        return m.predict(te[features].to_numpy())

    return fp


def fit_unconditional(tr, te):
    return np.full(len(te), np.quantile(tr.y, TAU))


def block_ci(d: pd.Series, dates: pd.Series, block_days: int = 80, B: int = 1000, seed: int = 0, level: float = 0.9):
    days = np.sort(dates.unique())
    blk = pd.Series(np.arange(len(days)) // block_days, index=days)
    g = d.groupby(blk.reindex(dates).to_numpy()).agg(["sum", "size"])
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(B):
        pick = rng.integers(0, len(g), len(g))
        vals.append(g["sum"].to_numpy()[pick].sum() / g["size"].to_numpy()[pick].sum())
    a = (1 - level) / 2
    return float(d.mean()), float(np.quantile(vals, a)), float(np.quantile(vals, 1 - a))


def run(split: str = "dev", tag: str = "qdd_dev") -> pd.DataFrame:
    prev, feats, _ = prev_features("reports/ladder_dev.json")
    df = assemble_dd(split).drop(columns=["y"]).rename(columns={"dd": "y"})
    df = df.dropna(subset=feats).reset_index(drop=True)
    cal = price_series("sh000001").index
    base = cpcv_oof(df, cal, fit_unconditional)
    base.to_parquet(OOF_DIR / f"{tag}_base.parquet")
    rows = []
    for C in CS:
        oof = cpcv_oof(df, cal, fit_quantile(feats, C))
        oof.to_parquet(OOF_DIR / f"{tag}_C{C}.parquet")
        m = oof.merge(base[["date", "symbol", "path", "p"]], on=["date", "symbol", "path"], suffixes=("", "_b"))
        d = pd.Series(pinball(m.y.to_numpy(), m.p.to_numpy()) - pinball(m.y.to_numpy(), m.p_b.to_numpy()))
        delta, lo, hi = block_ci(d, m.date)
        rows.append(dict(config=f"{prev}_feats_C{C}", n_feats=len(feats), pinball=float(pinball(m.y, m.p).mean()),
                         pinball_base=float(pinball(m.y, m.p_b).mean()), delta=delta, lo=lo, hi=hi,
                         cover=float((m.y <= m.p).mean()), q_mean=float(m.p.mean()), n=len(m)))
        print(rows[-1], flush=True)
    tab = pd.DataFrame(rows)
    tab.to_csv(f"reports/{tag}.csv", index=False)
    with open(f"reports/{tag}.md", "w") as f:
        f.write(f"# Q-DD 开发段（§12.5）：未来 60 日最大回撤的 τ=0.9 分位数回归，特征 = 主链保留级 {prev} 的特征集（{len(feats)} 个）\n\n")
        f.write(tab.round(5).to_markdown(index=False) + "\n\n")
        f.write("delta = pinball(模型) − pinball(无条件 90% 分位)，负为改善；lo/hi 为 80 日块 bootstrap 90% 区间。cover = 实际回撤 ≤ 预测分位的比例（目标 0.90）。开发段 CPCV 结果，不是样本外。\n")
    return tab


if __name__ == "__main__":
    run()
