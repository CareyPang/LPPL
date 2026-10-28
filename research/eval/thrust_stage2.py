"""阶段二：起涨风险率（prereg §15.1）。样本 = 阶段一（底部状态）OOF 概率 ≥ 开发段正标签率的时点；目标 = fast20 标签（20 日内出现先触上障碍的有效底）。
基线 = 仅用 logit(p1)；候选 = logit(p1) + 确认型特征组。CPCV 配对 ΔBrier，主链/次要链规则同 §6/§13.2。python -m research.eval.thrust_stage2 [ci|point]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ..features.run_thrust import OUT as THR
from ..labels.run_bottom import OUT as LABELS
from .baselines import cpcv_oof, paired_delta_brier
from .dataset import price_series
from .ladder import CS, OOF_DIR, fit_logit, keep_rule
from .metrics import score_table

STAGE1 = OOF_DIR / "ladder_bottom_dev_B3_omori25_C0.1.parquet"
GROUPS = {"amt": ["amt_jump", "amt_jump5"], "shock": ["first_up_shock", "ret5"], "breadth": ["br_hi20", "br_up", "br_hi20_d5"],
          "all": ["amt_jump", "amt_jump5", "first_up_shock", "ret5", "br_hi20", "br_up", "br_hi20_d5"]}


def assemble(stage1: Path = STAGE1, label_variant: str = "fast20") -> tuple[pd.DataFrame, float]:
    o = pd.read_parquet(stage1)
    p1 = o.groupby(["date", "symbol"]).p.mean().rename("p1").reset_index()
    base_rate = float(o.y.mean())
    sub = p1[p1.p1 >= base_rate].copy()
    br = pd.read_parquet(THR / "_breadth.parquet")
    rows = []
    for sym, g in sub.groupby("symbol"):
        lab = pd.read_parquet(LABELS / f"{sym}.parquet")[f"{label_variant}__y"]
        th = pd.read_parquet(THR / f"{sym}.parquet")
        g = g.set_index("date")
        g["y"] = lab.reindex(g.index)
        g = g.join(th).join(br)
        rows.append(g.reset_index())
    df = pd.concat(rows).dropna(subset=["y"] + GROUPS["all"]).reset_index(drop=True)
    df["logit_p1"] = np.log(np.clip(df.p1, 1e-4, 1 - 1e-4) / (1 - np.clip(df.p1, 1e-4, 1 - 1e-4)))
    return df.sort_values(["date", "symbol"]).reset_index(drop=True), base_rate


def run(rule: str = "ci"):
    df, base_rate = assemble()
    tdays = price_series("sh000001").index
    tdays = tdays[(tdays >= df.date.min()) & (tdays <= df.date.max())]
    print(f"stage2: n={len(df)} pos={int(df.y.sum())} symbols={df.symbol.nunique()} stage1_base_rate={base_rate:.4f}", flush=True)
    base = cpcv_oof(df, tdays, fit_logit(["logit_p1"], 1.0))
    p_ref = np.full(len(base), base.y.mean())
    rows = [dict(config="baseline logit(p1)", C=1.0, kept=True, **score_table(base.y, base.p, p_ref))]
    best, n_cfg = None, 0
    for name, feats in GROUPS.items():
        for C in CS:
            n_cfg += 1
            oof = cpcv_oof(df, tdays, fit_logit(["logit_p1"] + feats, C))
            sc = score_table(oof.y, oof.p, p_ref)
            d, lo, hi = paired_delta_brier(oof, base)
            rows.append(dict(config=name, C=C, kept=keep_rule(rule, d, hi), dbrier=d, ci_lo=lo, ci_hi=hi, **sc))
            print(f"{name} C={C} brier={sc['brier']:.5f} dBrier={d:.6f} [{lo:.6f},{hi:.6f}]", flush=True)
            if best is None or sc["brier"] < best[0]:
                best = (sc["brier"], name, C, oof)
    best[3].to_parquet(OOF_DIR / f"thrust_stage2_{best[1]}_C{best[2]}.parquet")
    tab = pd.DataFrame(rows)
    tag = "thrust_stage2_dev" if rule == "ci" else f"thrust_stage2_dev_{rule}"
    tab.to_csv(f"reports/{tag}.csv", index=False)
    with open(f"reports/{tag}.md", "w") as f:
        f.write(f"# 阶段二：起涨风险率（prereg §15.1；开发段，规则 {rule}）\n\n")
        f.write(f"样本 = 阶段一 OOF 概率 ≥ 正标签率 {base_rate:.4f} 的时点，n={len(df)}，正标签（fast20）{int(df.y.sum())}，标的 {df.symbol.nunique()}；配置 {n_cfg}。\n\n")
        f.write(tab.round(5).to_markdown(index=False) + "\n\n基线 = 仅 logit(阶段一概率)；ΔBrier 相对基线，负为改善，80 日块 bootstrap 90% 区间。开发段结果，不是样本外。\n")
    json.dump(dict(best=best[1], C=best[2], n_configs=n_cfg), open(f"reports/{tag}.json", "w"))
    return tab


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "ci")
