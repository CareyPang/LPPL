"""§16.7 风险率目标（辅助比较，顶部）：离散时间 hazard，目标 = 下一 5 日内发生合格顶（y=1 且 t* ≤ 5）；
20 日累计概率 P20 = 1 − (1 − h)^4，与现二分类 OOF（保留链 R7 sp120_z C=0.1）在同一 Brier 上配对比较。
python -m research.eval.hazard"""
from __future__ import annotations

import pandas as pd

from .baselines import cpcv_oof, paired_delta_brier
from .dataset import price_series
from .ladder import OOF_DIR, assemble, fit_logit
from .robustness import CHOSEN
from .run_interval import events_with_tstar

REF = OOF_DIR / "ladder_dev_R7_sp120_z_C0.1.parquet"
STEP = 5


def run(tag: str = "hazard_dev"):
    df = assemble("dev")
    feats = sorted({c for lv in CHOSEN.values() for cfg in lv.values() for c in cfg})
    df = df.dropna(subset=feats).reset_index(drop=True)
    ts = pd.concat([events_with_tstar(s, "dev", pd.DatetimeIndex(g.date)).assign(symbol=s) for s, g in df.groupby("symbol")])
    df = df.merge(ts, on=["symbol", "date"], how="left")
    df["y20"] = df.y
    df["y"] = ((df.y20 == 1) & (df.t_star <= STEP)).astype(int)
    tdays = price_series("sh000001").index
    tdays = tdays[(tdays >= df.date.min()) & (tdays <= df.date.max())]
    oof = cpcv_oof(df, tdays, fit_logit(feats, 0.1))
    oof["h"] = oof.p
    oof["p"] = 1 - (1 - oof.h) ** (20 // STEP)
    oof["y"] = df.set_index(["symbol", "date"]).y20.reindex(pd.MultiIndex.from_frame(oof[["symbol", "date"]])).to_numpy()
    ref = pd.read_parquet(REF)
    key = ["symbol", "date", "path"] if "path" in oof.columns and "path" in ref.columns else ["symbol", "date"]
    m = oof.merge(ref[key + ["p", "y"]], on=key, suffixes=("", "_ref"))
    a, b = m[["symbol", "date", "y", "p"]], m[["symbol", "date", "y", "p"]].assign(p=m.p_ref)
    d, lo, hi = paired_delta_brier(a, b)
    b_h, b_ref = float(((a.p - a.y) ** 2).mean()), float(((b.p - b.y) ** 2).mean())
    tab = pd.DataFrame([dict(n=len(m), brier_hazard=b_h, brier_binary=b_ref, dbrier=d, ci_lo=lo, ci_hi=hi, not_worse=lo <= 0)])
    tab.to_csv(f"reports/{tag}.csv", index=False)
    with open(f"reports/{tag}.md", "w") as f:
        f.write("# §16.7 风险率目标 vs 二分类（顶部，开发段，保留链特征 R1 vol_z + R2 bsadf500_psy_z + R7 sp120_z，C=0.1）\n\n")
        f.write(tab.round(5).to_markdown(index=False) + "\n\nhazard 目标 = 下一 5 日内合格顶；P20 = 1 − (1 − h)^4（假设 20 日内风险率恒定）。")
        f.write("dBrier = hazard − 二分类，负为 hazard 更好；判定“不劣于”= 区间下界 ≤ 0（§16.7）。开发段结果，不是样本外。\n")
    print(tab.round(5).to_string(index=False))
    oof.to_parquet(OOF_DIR / f"{tag}_top.parquet")
    return tab


if __name__ == "__main__":
    run()
