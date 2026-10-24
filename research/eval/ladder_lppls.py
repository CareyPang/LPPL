"""LPPLS 类候选（R3、R4a–R4f、R5 代理）的开发段阶梯（预登记 v1.1 §11：稀疏时点上配对比较）。

前一保留级别（由 ladder_dev.json 给出的保留链末级及其选中配置/C）在同一组稀疏时点上用同一 CPCV 重新拟合作为对照；
本级模型 = 逻辑回归(前一保留级特征 + 本级 LPPLS 分数)。
R5 这里只用 LPPLS/纯幂律 SSE 比值的中位数作为代理特征（预登记要求的块 bootstrap 零分布尚未实现，记为代理）。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..features.lppls_rules import scores
from ..features.lppls_scan import OUT as SCAN
from .baselines import cpcv_oof, paired_delta_brier
from .dataset import price_series
from .ladder import CS, LEVELS, OOF_DIR, assemble, fit_logit, keep_rule, with_z_variants
from .metrics import score_table

DAILY_LEVELS = with_z_variants(LEVELS)

LPPLS_LEVELS: dict[str, dict[str, list[str]]] = {
    "R3": {"power": ["s_power"]},
    "R4": {
        "a_p_ds": ["s_p_ds"],
        "b_p_strict": ["s_p_strict"],
        "c_p_top": ["s_p_top", "top_tc_iqr_rel"],
        "d_lit1": ["s_lit1"],
        "d_lit2": ["s_lit2"],
        "f_lit_ms": ["s_lit1_s", "s_lit1_m", "s_lit1_l"],
    },
    "R5proxy": {"sse_ratio": ["s_ratio_lppls_pow"]},
}


def load_scores(sym: str) -> pd.DataFrame:
    sc = pd.read_parquet(SCAN / f"{sym}.parquet")
    logp = price_series(sym)
    pos = pd.Series(np.arange(len(logp)), index=logp.index)
    lp = logp.to_numpy()
    end = pos.reindex(sc.date).to_numpy()
    sc["y_std"] = [lp[e + 1 - n : e + 1].std() for e, n in zip(end, sc.n, strict=True)]
    s = scores(sc)
    s["symbol"] = sym
    return s


def assemble_sparse(split: str = "dev") -> pd.DataFrame:
    daily = assemble(split)
    parts = [load_scores(p.stem) for p in SCAN.glob("*.parquet")]
    sc = pd.concat(parts).rename_axis("date").reset_index()
    df = daily.merge(sc, on=["date", "symbol"], how="inner")
    df[[c for c in df.columns if c.startswith("s_")]] = df[[c for c in df.columns if c.startswith("s_")]].fillna(0.0)
    df["top_tc_iqr_rel"] = df.top_tc_iqr_rel.fillna(df.top_tc_iqr_rel.max() if df.top_tc_iqr_rel.notna().any() else 1.0)
    return df.sort_values(["date", "symbol"]).reset_index(drop=True)


def prev_features(prev_json: str = "reports/ladder_dev.json") -> tuple[str, list[str], float]:
    kept = json.load(open(prev_json))["kept"]
    tab = pd.read_csv(prev_json.replace(".json", ".csv"))
    feats: list[str] = []
    C = 1.0
    for lv in kept[1:]:
        row = tab[(tab.level == lv) & tab.config.str.endswith("(chosen)")].iloc[0]
        feats += DAILY_LEVELS[lv][row.config.replace(" (chosen)", "")]
        C = float(row.C)
    return kept[-1], sorted(set(feats)), C


def daily_loss(oof: pd.DataFrame) -> pd.Series:
    """逐日平均 Brier（跨标的与 CPCV 路径），供 PBO/SPA 使用。"""
    return ((oof.p - oof.y) ** 2).groupby(oof.date.to_numpy()).mean()


FULL_ORDER = ["R1", "R2", "R3", "R4", "R5proxy", "R7"]


def run_full(split: str = "dev", rule: str = "ci"):
    """按预登记顺序 R1→R2→R3→R4→R5→R7 在稀疏时点上从 R0 起完整重算（§12.2 后、§5 顺序；R6 待特征实现后插入 R5 与 R7 之间）。"""
    tag = "ladder_dev_full" if rule == "ci" else f"ladder_dev_full_{rule}"
    df = assemble_sparse(split)
    daily_feats = sorted({c for lv in DAILY_LEVELS.values() for cfg in lv.values() for c in cfg})
    df = df.dropna(subset=daily_feats).reset_index(drop=True)
    tdays = price_series("sh000001").index
    tdays = tdays[(tdays >= df.date.min()) & (tdays <= df.date.max())]
    from .baselines import r0_predict

    oof0 = cpcv_oof(df, tdays, lambda tr, te: r0_predict(tr.y.to_numpy(), len(te)))
    p_ref = oof0.p.to_numpy()
    print(f"{split} sparse full-order: n={len(df)} pos={int(df.y.sum())} symbols={df.symbol.nunique()}", flush=True)
    rows = [dict(level="R0", config="base", C=np.nan, kept=True, vs="-", **score_table(oof0.y, oof0.p, p_ref))]
    kept = [("R0", [], oof0)]
    kept_path = {"R0": None}
    losses = {"R0": daily_loss(oof0)}
    n_configs = 0
    all_levels = {**DAILY_LEVELS, **LPPLS_LEVELS}
    for name in FULL_ORDER:
        pn, pf, po = kept[-1]
        best = None
        for cfg, feats in all_levels[name].items():
            for C in CS:
                n_configs += 1
                oof = cpcv_oof(df, tdays, fit_logit(sorted(set(pf) | set(feats)), C))
                sc = score_table(oof.y, oof.p, p_ref)
                losses[f"{name}_{cfg}_C{C}"] = daily_loss(oof)
                rows.append(dict(level=name, config=cfg, C=C, kept=False, vs=pn, **sc))
                print(f"{name} {cfg} C={C} brier={sc['brier']:.5f}", flush=True)
                if best is None or sc["brier"] < best[0]:
                    best = (sc["brier"], cfg, C, feats, oof)
        _, cfg, C, feats, oof = best
        d, lo, hi = paired_delta_brier(oof, po)
        keep = keep_rule(rule, d, hi)
        oof.to_parquet(OOF_DIR / f"{tag}_{name}_{cfg}_C{C}.parquet")
        rows.append(dict(level=name, config=f"{cfg} (chosen)", C=C, kept=keep, vs=pn, dbrier=d, ci_lo=lo, ci_hi=hi,
                         **score_table(oof.y, oof.p, p_ref)))
        print(f"{name}: chosen {cfg} C={C} dBrier={d:.6f} 90%CI=[{lo:.6f},{hi:.6f}] keep={keep}", flush=True)
        if keep:
            kept.append((name, sorted(set(pf) | set(feats)), oof))
            kept_path[name] = str(OOF_DIR / f"{tag}_{name}_{cfg}_C{C}.parquet")
    pd.DataFrame(losses).to_parquet(OOF_DIR / f"{tag}_losses.parquet")
    tab = pd.DataFrame(rows)
    tab.to_csv(f"reports/{tag}.csv", index=False)
    with open(f"reports/{tag}.md", "w") as f:
        f.write(f"# 开发段完整顺序阶梯（{split}，稀疏时点，R1→R2→R3→R4→R5proxy→R7，CPCV 6/2=15 路，purge/embargo 80；规则 {rule}）\n\n")
        f.write(f"稀疏样本 n={len(df)}，正标签 {int(df.y.sum())}，标的 {df.symbol.nunique()}；配置总数 {n_configs}（多重比较）。"
                "R6 资金面特征尚未实现，未参与。\n\n")
        f.write(tab.round(5).to_markdown(index=False) + "\n\n保留链：" + " → ".join(k[0] for k in kept) + "\n")
    json.dump(dict(kept=[k[0] for k in kept], n_configs=n_configs, rule=rule,
                   last_oof=kept_path[kept[-1][0]]),
              open(Path(f"reports/{tag}.json"), "w"))
    return tab


def run(split: str = "dev", rule: str = "ci"):
    tag = "ladder_dev_lppls" if rule == "ci" else f"ladder_dev_lppls_{rule}"
    prev_json = "reports/ladder_dev.json" if rule == "ci" else f"reports/ladder_dev_{rule}.json"
    df = assemble_sparse(split)
    prev_name, prev_feats, prev_C = prev_features(prev_json)
    if prev_feats:
        df = df.dropna(subset=prev_feats).reset_index(drop=True)
    tdays = price_series("sh000001").index
    tdays = tdays[(tdays >= df.date.min()) & (tdays <= df.date.max())]
    print(f"{split} sparse: n={len(df)} pos={int(df.y.sum())} symbols={df.symbol.nunique()} prev={prev_name}", flush=True)
    if prev_feats:
        prev_oof = cpcv_oof(df, tdays, fit_logit(prev_feats, prev_C))
    else:
        from .baselines import r0_predict

        prev_oof = cpcv_oof(df, tdays, lambda tr, te: r0_predict(tr.y.to_numpy(), len(te)))
    from .baselines import r0_predict

    p_ref = cpcv_oof(df, tdays, lambda tr, te: r0_predict(tr.y.to_numpy(), len(te))).p.to_numpy()
    rows = [dict(level=prev_name, config="prev (refit on sparse grid)", C=prev_C, kept=True, vs="-",
                 **score_table(prev_oof.y, prev_oof.p, p_ref))]
    kept = [(prev_name, prev_feats, prev_oof)]
    n_configs = 0
    for name, cfgs in LPPLS_LEVELS.items():
        pn, pf, po = kept[-1]
        best = None
        for cfg, feats in cfgs.items():
            for C in CS:
                n_configs += 1
                oof = cpcv_oof(df, tdays, fit_logit(sorted(set(pf) | set(feats)), C))
                sc = score_table(oof.y, oof.p, p_ref)
                rows.append(dict(level=name, config=cfg, C=C, kept=False, vs=pn, **sc))
                print(f"{name} {cfg} C={C} brier={sc['brier']:.5f}", flush=True)
                if best is None or sc["brier"] < best[0]:
                    best = (sc["brier"], cfg, C, feats, oof)
        _, cfg, C, feats, oof = best
        d, lo, hi = paired_delta_brier(oof, po)
        keep = keep_rule(rule, d, hi)
        oof.to_parquet(OOF_DIR / f"{tag}_{name}_{cfg}_C{C}.parquet")
        rows.append(dict(level=name, config=f"{cfg} (chosen)", C=C, kept=keep, vs=pn, dbrier=d, ci_lo=lo, ci_hi=hi,
                         **score_table(oof.y, oof.p, p_ref)))
        print(f"{name}: chosen {cfg} C={C} dBrier={d:.6f} 90%CI=[{lo:.6f},{hi:.6f}] keep={keep}", flush=True)
        if keep:
            kept.append((name, sorted(set(pf) | set(feats)), oof))
    tab = pd.DataFrame(rows)
    tab.to_csv(f"reports/{tag}.csv", index=False)
    with open(f"reports/{tag}.md", "w") as f:
        f.write(f"# 开发段 LPPLS 类候选阶梯（{split}，稀疏时点，CPCV 6/2=15 路，purge/embargo 80）\n\n")
        f.write(f"稀疏样本 n={len(df)}，正标签 {int(df.y.sum())}，标的 {df.symbol.nunique()}；本阶段试过的配置数 {n_configs}。\n\n")
        f.write(tab.round(5).to_markdown(index=False) + "\n\n保留链：" + " → ".join(k[0] for k in kept) + "\n")
    json.dump(dict(kept=[k[0] for k in kept], n_configs=n_configs, rule=rule), open(Path(f"reports/{tag}.json"), "w"))
    return tab


if __name__ == "__main__":
    import sys

    _rule = sys.argv[1] if len(sys.argv) > 1 else "ci"
    if len(sys.argv) > 2 and sys.argv[2] == "full":
        run_full(rule=_rule)
    else:
        run(rule=_rule)
