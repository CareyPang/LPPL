"""开发段基线：R0 基率、R1 波动率逻辑回归（C∈{0.1,1}），CPCV 15 条路径，输出 reports/ladder_dev.md 的前两级。
python -m research.eval.run_baselines"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .baselines import R1_FEATURES, cpcv_oof, evaluate, logit_model, paired_delta_brier, r0_predict
from .dataset import assemble, price_series

ROOT = Path(__file__).resolve().parents[2]
OOF = ROOT / "data" / "oof"


def trading_days(df: pd.DataFrame) -> pd.DatetimeIndex:
    idx = price_series("sh000001").index
    return idx[(idx >= df.date.min()) & (idx <= df.date.max())]


def run_r0(df, td):
    return cpcv_oof(df, td, lambda tr, te: r0_predict(tr.y.to_numpy(), len(te)))


def run_logit(df, td, feats, C):
    def fp(tr, te):
        m = logit_model(C).fit(tr[feats], tr.y)
        return m.predict_proba(te[feats])[:, 1]
    return cpcv_oof(df, td, fp)


def main():
    OOF.mkdir(parents=True, exist_ok=True)
    df = assemble("dev")
    td = trading_days(df)
    print("dev samples", len(df), "pos", int(df.y.sum()), "symbols", df.symbol.nunique(), flush=True)
    oof = {"R0": run_r0(df, td)}
    for C in (0.1, 1.0):
        oof[f"R1_C{C}"] = run_logit(df, td, R1_FEATURES, C)
    for k, v in oof.items():
        v.to_parquet(OOF / f"dev_{k}.parquet")
    rows = []
    for k, v in oof.items():
        s = evaluate(v, oof["R0"])
        d, lo, hi = paired_delta_brier(v, oof["R0"])
        rows.append(dict(model=k, **s, dbrier_vs_R0=d, ci_lo=lo, ci_hi=hi))
    tab = pd.DataFrame(rows).set_index("model")
    # 同级变体按开发段 Brier 选一个
    r1 = tab.loc[[i for i in tab.index if i.startswith("R1")]]
    chosen = r1.brier.idxmin()
    keep = bool(tab.loc[chosen, "ci_hi"] < 0)
    (ROOT / "reports" / "ladder_dev_baselines.md").write_text(
        "# 模型阶梯（开发段 CPCV）：R0 基率与 R1 波动率\n\n"
        f"样本 {len(df)}，正标签 {int(df.y.sum())}，标的 {df.symbol.nunique()}，"
        f"as-of {df.date.min().date()} 至 {df.date.max().date()}；CPCV N=6,k=2，purge/embargo 80 日。\n\n"
        + tab.round(5).to_markdown()
        + f"\n\nR1 同级选择（开发段 Brier 最低）：**{chosen}**；ΔBrier 95% 区间上界 < 0 → "
        + ("**保留 R1**" if keep else "**R1 不优于 R0，按规则淘汰**") + "\n")
    json.dump(dict(chosen_R1=chosen, keep_R1=keep, n=len(df), pos=int(df.y.sum())),
              open(ROOT / "reports" / "ladder_dev_baselines.json", "w"))
    print(tab.round(5))
    print("chosen", chosen, "keep", keep)


if __name__ == "__main__":
    main()
