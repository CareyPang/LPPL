"""R8 横截面聚合顶部候选（prereg §16.6）：市场级特征接在保留链 R0→R1→R2→R7（已选配置）之后。
特征（T 日收盘可得，对所有标的相同）：成分股中 R2 报警比例 share_alarm（bsadf500_psy_z ≥ 1.645，约对应正标签率 ~5%）、
20 日新高比例 br_hi20 及其 20 日变化、上涨家数比例 20 日均值。2010 快照成分股自算，2010 前名单非严格 PIT（已知限制）。
python -m research.eval.ladder_r8 [ci|point]"""
from __future__ import annotations

import sys

import pandas as pd

from ..features.thrust import breadth
from .dataset import price_series
from .ladder import assemble, run_ladder
from .robustness import CHOSEN

R8 = {"breadth": ["br_hi20", "br_hi20_d20", "br_up20"], "breadth_alarm": ["br_hi20", "br_hi20_d20", "br_up20", "share_alarm"]}


def market_features(df: pd.DataFrame) -> pd.DataFrame:
    st = df[df.group == "stock"]
    share = (st.bsadf500_psy_z >= 1.645).groupby(st.date).mean().rename("share_alarm")
    syms = sorted(st.symbol.unique())
    px = pd.concat({s: price_series(s) for s in syms}, axis=1)
    b = breadth(px)
    b["br_hi20_d20"] = b.br_hi20 - b.br_hi20.shift(20)
    b["br_up20"] = b.br_up.rolling(20).mean()
    return b[["br_hi20", "br_hi20_d20", "br_up20"]].join(share, how="left").reset_index().rename(columns={"index": "date"})


def run(rule: str = "ci"):
    df = assemble("dev")
    m = market_features(df)
    df = df.merge(m, on="date", how="left").dropna(subset=["br_hi20", "share_alarm"]).reset_index(drop=True)
    levels = dict(CHOSEN)
    levels["R8"] = R8
    tag = "ladder_dev_r8" + ("" if rule == "ci" else f"_{rule}")
    return run_ladder(levels, tag=tag, rule=rule, df=df, title="开发段阶梯 R0→R1→R2→R7（已选配置）→ R8 横截面聚合（§16.6）")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "ci")
