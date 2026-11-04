"""§21.4 (d) Ising 序参量 R8 变体阶梯（开发段 2010–2018；research-only）。

在保留链 R0→R1→R2→R7（已选配置）之后加 R8 候选：ising_phi（φ 与 Δφ，6–12m / 12–24m）、ising_chi（χ）、ising_phi_chi。
§16.6 规则不变：R8 内按 Brier 选最优配置，与 R7 配对 ΔBrier（80 日块 bootstrap 90% 区间）；主链 ci（上界 < 0）、次要链 point（点估计 < −0.001）。
样本只用 2010-01-04—2018-12-28（2010 前无 PIT 成分股），指数与成分股同样截断；对照同样本上的既有 R8 breadth_alarm（tag *_ref）。
python -m research.eval.ladder_ising [ci|point] [ref] [chain]"""
from __future__ import annotations

import sys

import pandas as pd

from ..features import ising
from .dataset import SPLITS, _snapshot, price_series
from .ladder import assemble, run_ladder
from .ladder_r8 import R8 as R8_REF
from .ladder_r8 import market_features as ref_features
from .robustness import CHOSEN

START = "2010-01-04"
PHI = ["phi_6_12", "phi_12_24", "dphi_6_12", "dphi_12_24"]
R8 = {"ising_phi": PHI, "ising_chi": ["chi"], "ising_phi_chi": PHI + ["chi"]}


def data() -> pd.DataFrame:
    df = assemble("dev")
    df = df[df.date >= pd.Timestamp(START)].reset_index(drop=True)
    tdays = price_series("sh000001").index
    tdays = tdays[(tdays >= pd.Timestamp(START) - pd.Timedelta(days=200)) & (tdays <= df.date.max())]
    m = ising.market_features(sorted(_snapshot(SPLITS["dev"][2])), tdays)
    return df.merge(m, on="date", how="left")


def run(rule: str = "ci", ref: bool = False, chain: bool = False):
    """chain=True：固定已登记保留链 R1/R2/R7（在 2010–2018 子样本上不重新裁决），R8 与 R7 配对比较。"""
    df = data()
    levels = dict(CHOSEN)
    if ref:
        df = df.merge(ref_features(df), on="date", how="left").dropna(subset=["br_hi20", "share_alarm"])
        levels["R8"] = {"breadth_alarm": R8_REF["breadth_alarm"]}
        tag = "ladder_dev_ising_ref"
    else:
        levels["R8"] = R8
        tag = "ladder_dev_ising"
    df = df.dropna(subset=PHI + ["chi"]).reset_index(drop=True)
    tag += ("_chain" if chain else "") + ("" if rule == "ci" else f"_{rule}")
    return run_ladder(levels, tag=tag, rule=rule, df=df, force_keep=frozenset(CHOSEN) if chain else frozenset(),
                      title="开发段 2010–2018 阶梯 R0→R1→R2→R7（已选配置）→ R8 Ising 序参量 φ/Δφ/χ（§21.4）")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "ci", ref="ref" in sys.argv[2:], chain="chain" in sys.argv[2:])
