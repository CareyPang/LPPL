"""开发段模型阶梯（预登记 §5–§6）：叠加式、逐级增量检验。

第 k 级模型 = L2 逻辑回归，输入 = 此前所有保留级别选中配置的特征 + 本级配置的特征。
保留条件：相对前一保留级别 ΔBrier < 0 且块 bootstrap（块长 80 日）90% 区间上界 < 0。
同一级多个配置按开发段 OOF Brier 选一个；试过的配置数全部记录（多重比较）。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..features.run_daily import OUT as FEAT
from .baselines import R1_FEATURES, cpcv_oof, logit_model, paired_delta_brier, r0_predict
from .dataset import LABELS, SPLITS, _snapshot, price_series
from .metrics import score_table

OOF_DIR = Path("data/oof")
INDEXES = ("sh000001", "sh000016", "sh000300", "sh000905", "sh000688", "sz399001", "sz399006")

# 每级的候选配置：名字 -> 特征列表；C 由外层 {0.1, 1.0} 展开
LEVELS: dict[str, dict[str, list[str]]] = {
    "R1": {"vol": R1_FEATURES},
    "R2": {f"bsadf{W}_{m}": [f"bsadf{W}_{m}"] for W in (250, 500) for m in ("psy", "36")},
    "R7": {f"sp{w}": [f"var{w}", f"ar1_{w}", f"dfa{w}", f"pe{w}", f"tau{w}"] for w in (60, 120, 250)},
}
CS = (0.1, 1.0)
Z_WINDOW = 1250  # v1.2 §12.6：按标的过去 5 年滚动 z 分数（PIT）


def with_z_variants(levels: dict[str, dict[str, list[str]]]) -> dict[str, dict[str, list[str]]]:
    return {lv: {**cfgs, **{f"{c}_z": [f"{f}_z" for f in fs] for c, fs in cfgs.items()}} for lv, cfgs in levels.items()}


def rolling_z(df: pd.DataFrame, cols: list[str], window: int = Z_WINDOW, min_periods: int = 250) -> pd.DataFrame:
    r = df[cols].rolling(window, min_periods=min_periods)
    z = (df[cols] - r.mean()) / r.std()
    return z.add_suffix("_z")


def assemble(split: str, variant: str = "main") -> pd.DataFrame:
    a, b, csv, entry = SPLITS[split]
    rows = []
    for group, syms in (("index", INDEXES), ("stock", sorted(_snapshot(csv)))):
        for sym in syms:
            p = LABELS / f"{sym}.parquet"
            fp = FEAT / f"{sym}.parquet"
            if not (p.exists() and fp.exists()):
                continue
            lab = pd.read_parquet(p)
            df = pd.read_parquet(fp)
            lo = pd.Timestamp(a)
            if group == "stock":
                logp = price_series(sym)
                lo = max(lo, pd.Timestamp(entry), logp.index[0] + pd.DateOffset(years=5))
            feats = [c for lv in LEVELS.values() for cfg in lv.values() for c in cfg if c in df.columns]
            df = pd.concat([df, rolling_z(df, sorted(set(feats)))], axis=1)
            df["y"] = lab[f"{variant}__y"].reindex(df.index)
            df = df[(df.index >= lo) & (df.index <= pd.Timestamp(b))].dropna(subset=["y", "rv120"])
            df["symbol"] = sym
            df["group"] = group
            rows.append(df)
    out = pd.concat(rows).rename_axis("date").reset_index()
    return out.sort_values(["date", "symbol"]).reset_index(drop=True)


def fit_logit(features: list[str], C: float):
    def fp(tr, te):
        m = logit_model(C).fit(tr[features].to_numpy(), tr.y.to_numpy())
        return m.predict_proba(te[features].to_numpy())[:, 1]

    return fp


def run_ladder(levels=LEVELS, split: str = "dev", tag: str = "ladder_dev"):
    OOF_DIR.mkdir(parents=True, exist_ok=True)
    df = assemble(split)
    all_feats = sorted({c for lv in levels.values() for cfg in lv.values() for c in cfg})
    df = df.dropna(subset=all_feats).reset_index(drop=True)
    tdays = price_series("sh000001").index
    tdays = tdays[(tdays >= df.date.min()) & (tdays <= df.date.max())]
    print(f"{split}: n={len(df)} pos={int(df.y.sum())} symbols={df.symbol.nunique()}", flush=True)

    oof0 = cpcv_oof(df, tdays, lambda tr, te: r0_predict(tr.y.to_numpy(), len(te)))
    oof0.to_parquet(OOF_DIR / f"{tag}_R0.parquet")
    p_ref = oof0.p.to_numpy()
    kept = [("R0", [], oof0)]
    rows = [dict(level="R0", config="base", C=np.nan, kept=True, vs="-", **score_table(oof0.y, oof0.p, p_ref))]
    n_configs = 0
    for name, cfgs in levels.items():
        prev_name, prev_feats, prev_oof = kept[-1]
        best = None
        for cfg, feats in cfgs.items():
            for C in CS:
                n_configs += 1
                oof = cpcv_oof(df, tdays, fit_logit(sorted(set(prev_feats) | set(feats)), C))
                sc = score_table(oof.y, oof.p, p_ref)
                rows.append(dict(level=name, config=cfg, C=C, kept=False, vs=prev_name, **sc))
                print(f"{name} {cfg} C={C} brier={sc['brier']:.5f}", flush=True)
                if best is None or sc["brier"] < best[0]:
                    best = (sc["brier"], cfg, C, feats, oof)
        _, cfg, C, feats, oof = best
        d, lo, hi = paired_delta_brier(oof, prev_oof)
        keep = hi < 0
        oof.to_parquet(OOF_DIR / f"{tag}_{name}_{cfg}_C{C}.parquet")
        rows.append(dict(level=name, config=f"{cfg} (chosen)", C=C, kept=keep, vs=prev_name,
                         dbrier=d, ci_lo=lo, ci_hi=hi, **score_table(oof.y, oof.p, p_ref)))
        print(f"{name}: chosen {cfg} C={C} dBrier={d:.6f} 90%CI=[{lo:.6f},{hi:.6f}] keep={keep}", flush=True)
        if keep:
            kept.append((name, sorted(set(prev_feats) | set(feats)), oof))
    tab = pd.DataFrame(rows)
    Path("reports").mkdir(exist_ok=True)
    tab.to_csv(f"reports/{tag}.csv", index=False)
    with open(f"reports/{tag}.md", "w") as f:
        f.write(f"# 开发段模型阶梯（{split}，CPCV 6/2=15 路，purge/embargo 80）\n\n")
        f.write(f"样本 n={len(df)}，正标签 {int(df.y.sum())}，标的 {df.symbol.nunique()}；试过的配置总数 {n_configs}（多重比较）。\n\n")
        f.write(tab.round(5).to_markdown(index=False) + "\n\n")
        f.write("保留链：" + " → ".join(k[0] for k in kept) + "\n")
    json.dump(dict(kept=[k[0] for k in kept], n_configs=n_configs), open(f"reports/{tag}.json", "w"))
    return tab, kept


if __name__ == "__main__":
    run_ladder()
