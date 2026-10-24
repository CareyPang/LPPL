"""v1.6 辅助检验：§16.8 指数/个股分层（顶部阶梯，全部配置）与 §16.2 留出单一崩盘年（保留链已选配置）。
python -m research.eval.robustness strata | loco"""
from __future__ import annotations

import sys

import pandas as pd

from .ladder import LEVELS, assemble, run_ladder, with_z_variants
from .ladder_bottom import LEVELS_B, assemble_bottom

CHOSEN = {"R1": {"vol_z": [f"{c}_z" for c in LEVELS["R1"]["vol"]]},
          "R2": {"bsadf500_psy_z": ["bsadf500_psy_z"]},
          "R7": {"sp120_z": [f"{c}_z" for c in LEVELS["R7"]["sp120"]]}}
CHOSEN_B = {"B1": {"dd_nodur_z": [f"{c}_z" for c in LEVELS_B["B1"]["dd_nodur"]]},
            "B2": {"amt_only_z": [f"{c}_z" for c in LEVELS_B["B2"]["amt_only"]]},
            "B3": {"omori25": LEVELS_B["B3"]["omori25"]}}
LOCO = {"ex2007_08": (2007, 2008), "ex2015": (2015,), "ex2018": (2018,)}


def _data(side: str):
    if side == "top":
        return assemble("dev"), with_z_variants(LEVELS), CHOSEN, "ladder_dev"
    levels = with_z_variants(LEVELS_B)
    return assemble_bottom("dev", levels), levels, CHOSEN_B, "ladder_bottom_dev"


def strata(rule: str = "ci", side: str = "top"):
    df, levels, _, base = _data(side)
    for grp in ("index", "stock"):
        sub = df[df.group == grp].reset_index(drop=True)
        run_ladder(levels, tag=f"{base}_{grp}" + ("" if rule == "ci" else f"_{rule}"), rule=rule, df=sub,
                   title=f"开发段模型阶梯（§16.8 分层：{side} / {grp}）")


def loco(rule: str = "ci", side: str = "top"):
    df, _, chosen, base = _data(side)
    rows = []
    for name, years in LOCO.items():
        sub = df[~df.date.dt.year.isin(years)].reset_index(drop=True)
        tab, kept = run_ladder(chosen, tag=f"{base}_{name}", rule=rule, df=sub, title=f"开发段保留链（§16.2 {side} 剔除 {years}）")
        ch = tab[tab.config.str.contains("chosen")]
        for _, r in ch.iterrows():
            rows.append(dict(holdout=name, level=r.level, dbrier=r.dbrier, ci_lo=r.ci_lo, ci_hi=r.ci_hi, kept=r.kept))
    out = pd.DataFrame(rows)
    out.to_csv(f"reports/{base}_loco.csv", index=False)
    with open(f"reports/{base}_loco.md", "w") as f:
        f.write(f"# 留出单一崩盘年（prereg §16.2；{side} 保留链已选配置 {[list(v)[0] for v in chosen.values()]}，逐级相对前一级）\n\n")
        f.write(out.round(5).to_markdown(index=False) + "\n\n某级在剔除某年后区间含 0 → 记“依赖该年”。开发段结果，不是样本外。\n")
    print(out.round(5).to_string(index=False))


if __name__ == "__main__":
    {"strata": strata, "loco": loco}[sys.argv[1]](sys.argv[2] if len(sys.argv) > 2 else "ci", sys.argv[3] if len(sys.argv) > 3 else "top")
