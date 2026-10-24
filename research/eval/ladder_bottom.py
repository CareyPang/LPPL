"""底部阶梯（阶段 5 开发段，prereg v1.5 §15，名单 B0–B8）：B0 基率 → B1 回撤/久期 → B2 流动性 → B3 Omori 余震 → B4 熊市高波动状态
→ [B5 杠杆去化：2010 起子样本，单独脚本] → [B6 负泡沫 LPPLS、B7 反泡沫部分：待 −ln P 扫描] → B7 支撑井 → B8 统计物理。
标签：data/labels/bottom_v1（三重障碍，main 变体）。特征：daily_v1（R1/R7 同款）+ bottom_v1 + wells_v1。"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from ..features.run_bottom_feats import OUT as BFEAT
from ..features.run_daily import OUT as FEAT
from ..features.run_wells import OUT as WELLS
from ..labels.run_bottom import OUT as LABELS
from .dataset import INDEXES, SPLITS, _snapshot, price_series
from .ladder import rolling_z, run_ladder, with_z_variants

LEVELS_B: dict[str, dict[str, list[str]]] = {
    "B1": {
        "dd": ["dd_from_max250", "days_since_max250", "ret20", "ret60", "rv20", "rv60", "rv120"],
        "dd_nodur": ["dd_from_max250", "ret20", "ret60", "rv20", "rv60", "rv120"],
    },
    "B2": {"liq": ["amihud_rel", "amt_ratio20", "damt5"], "amt_only": ["amt_ratio20", "damt5"]},
    "B3": {"omori2": ["after_ratio_20", "days_since_shock_20", "omori_p_20"],
           "omori25": ["after_ratio_25", "days_since_shock_25", "omori_p_25"]},
    "B4": {"state": ["bear500", "rv20_pct", "bear_x_rv"]},
    "B7well": {"well": ["well_F", "well_depth", "well_dist_below"]},
    "B8": {f"sp{w}": [f"var{w}", f"ar1_{w}", f"dfa{w}", f"pe{w}", f"tau{w}"] for w in (60, 120, 250)},
}


def days_since_max(logp: pd.Series, w: int = 250) -> pd.Series:
    return logp.rolling(w).apply(lambda a: w - 1 - int(np.argmax(a)), raw=True)


def assemble_bottom(split: str, levels: dict, variant: str = "main") -> pd.DataFrame:
    a, b, csv, entry = SPLITS[split]
    feats = sorted({c for lv in levels.values() for cfg in lv.values() for c in cfg if not c.endswith("_z")})
    rows = []
    for group, syms in (("index", INDEXES), ("stock", sorted(_snapshot(csv)))):
        for sym in syms:
            p, fp, wp, bp = LABELS / f"{sym}.parquet", FEAT / f"{sym}.parquet", WELLS / f"{sym}.parquet", BFEAT / f"{sym}.parquet"
            if not (p.exists() and fp.exists() and wp.exists() and bp.exists()):
                continue
            logp = price_series(sym)
            df = pd.read_parquet(fp).join(pd.read_parquet(wp)).join(pd.read_parquet(bp))
            df["days_since_max250"] = days_since_max(logp).reindex(df.index)
            df = pd.concat([df, rolling_z(df, feats)], axis=1)
            df["y"] = pd.read_parquet(p)[f"{variant}__y"].reindex(df.index)
            lo = pd.Timestamp(a)
            if group == "stock":
                lo = max(lo, pd.Timestamp(entry), logp.index[0] + pd.DateOffset(years=5))
            df = df[(df.index >= lo) & (df.index <= pd.Timestamp(b))].dropna(subset=["y", "rv120"])
            df["symbol"] = sym
            df["group"] = group
            rows.append(df)
    out = pd.concat(rows).rename_axis("date").reset_index()
    return out.sort_values(["date", "symbol"]).reset_index(drop=True)


def run(rule: str = "ci", split: str = "dev"):
    levels = with_z_variants(LEVELS_B)
    df = assemble_bottom(split, levels)
    tag = "ladder_bottom_dev" if rule == "ci" else f"ladder_bottom_dev_{rule}"
    tab, kept = run_ladder(levels, split=split, tag=tag, rule=rule, df=df,
                           title="阶段 5 底部阶梯（B0→B1→B2→B3→B4→B7well→B8；B5 子样本另报，B6/B7 反泡沫待 −ln P 扫描）")
    with open(f"reports/{tag}.md", "a") as f:
        f.write("\nB5 杠杆去化只能在 2010 起子样本上单独比较（另报）；B6 负泡沫 LPPLS 与 B7 原型反泡沫部分未参与（需对 −ln P 做 LPPLS 扫描，排在顶部扫描与 §12.2 算力门之后）。"
                "标签 = 三重障碍 main 变体；事件级指标为底部事件段。开发段结果，不是样本外。\n")
    return tab, kept


if __name__ == "__main__":
    run(rule=sys.argv[1] if len(sys.argv) > 1 else "ci")
