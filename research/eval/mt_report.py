"""多重比较报告（§14.3 工具接入）：对阶梯逐日损失矩阵算 PBO（CSCV）与 SPA p 值（相对 R0）。开发段用于诊断配置选择的过拟合程度。"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from .multiple_testing import pbo, spa_pvalue


def run(losses_path: str, tag: str) -> dict:
    L = pd.read_parquet(losses_path).dropna()
    base = L["R0"].to_numpy()
    cands = [c for c in L.columns if c != "R0"]
    M = -L[cands].to_numpy()  # 得分 = −损失，越大越好
    res = pbo(M, S=16, metric=lambda x: x.mean(0))  # CSCV 以 IS 平均损失最小（得分最大）选配置
    d = base[:, None] - L[cands].to_numpy()  # 正为候选优于 R0
    p, best = spa_pvalue(d, block=80, B=2000)
    out = dict(n_days=len(L), n_configs=len(cands), pbo=res["pbo"], spa_p_vs_R0=p, spa_best=cands[best], logit_mean=res["logit_mean"])
    with open(f"reports/{tag}_mt.md", "w") as f:
        f.write(f"# 多重比较诊断（{tag}；开发段，不是样本外）\n\n")
        f.write(f"- 逐日损失矩阵：{len(L)} 日 × {len(cands)} 配置（来源 `{losses_path}`）\n")
        f.write(f"- PBO（CSCV，S=16）：**{res['pbo']:.3f}**（样本内最优配置在样本外落到中位数以下的概率；> 0.5 说明选择基本是运气）\n")
        f.write(f"- SPA p 值（所有配置相对 R0，80 日块 bootstrap，B=2000）：**{p:.4f}**；SPA 最优候选 {cands[best]}\n")
        for k, v in res.items():
            if k != "pbo" and np.isscalar(v):
                f.write(f"- {k}: {v:.4f}\n")
    print(out, flush=True)
    return out


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
