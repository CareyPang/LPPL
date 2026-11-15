"""Phase 3b：底部保留链 R0→B1→B2→B3（已选配置，force_keep）后加 B9 候选（开发段；research-only）。
候选：regime（as-of 可知的阴跌/恐慌代理：fall_speed = dd60/dd250、days_since_max250）、newlow（成分股 60 日新低比例及 20 日均值，市场级）、
omori_stab（omori_p_25 的 20 日滚动标准差）、regime_newlow（合并）；子集 106 标的（6 指数 + 100 成分股）另加 neglppls（−lnP STANDARD 12–24m 置信度，
按 as-of 前向填充）与 neg_x_slow（置信度 × 阴跌代理）。§16.6 规则不变：CPCV ΔBrier 80 日块 90% 区间，主链 ci / 次要链 point。
python -m research.eval.ladder_bottom_b9 [ci|point] [sub]"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("LPPLS_BOX", "v2")

from ..features.lppls_rules import _derived, grid_rules  # noqa: E402
from .dataset import SPLITS, _snapshot, price_series  # noqa: E402
from .ladder import run_ladder, with_z_variants  # noqa: E402
from .ladder_bottom import LEVELS_B, assemble_bottom  # noqa: E402
from .robustness import CHOSEN_B  # noqa: E402

FEAT = Path("data/features")
B9 = {"regime": ["fall_speed", "days_since_max250"], "newlow": ["nl60", "nl60_m20"], "omori_stab": ["omori_p_sd20"],
      "regime_newlow": ["fall_speed", "days_since_max250", "nl60", "nl60_m20"]}
B9_SUB = {"neglppls": ["neg_conf"], "neg_x_slow": ["neg_conf", "fall_speed", "neg_x_slow"]}


def sym_feats(sym: str) -> pd.DataFrame:
    lp = price_series(sym)
    dd60 = lp - lp.rolling(60).max()
    dd250 = lp - lp.rolling(250).max()
    fs = (dd60 / dd250.where(dd250 < -1e-6)).clip(0, 1)
    return pd.DataFrame(dict(fall_speed=fs), index=lp.index)


def newlow_breadth(symbols: list[str], tdays: pd.DatetimeIndex) -> pd.DataFrame:
    px = pd.concat({s: price_series(s) for s in symbols}, axis=1).reindex(tdays)
    nl = (px <= px.rolling(60).min()).astype(float).where(px.notna()).mean(axis=1)
    return pd.DataFrame(dict(nl60=nl, nl60_m20=nl.rolling(20).mean()))


def neg_conf(sym: str, feat_dir: str, tdays: pd.DatetimeIndex) -> pd.Series:
    p = FEAT / feat_dir / f"{sym}.parquet"
    if not p.exists():
        return pd.Series(np.nan, index=tdays)
    sc = pd.read_parquet(p)
    lp = price_series(sym)
    pos = pd.Series(np.arange(len(lp)), index=lp.index)
    arr = lp.to_numpy()
    end = pos.reindex(sc.date).to_numpy()
    sc = sc.assign(y_std=[arr[e + 1 - n : e + 1].std() for e, n in zip(end, sc.n, strict=True)])
    d = _derived(sc)
    ok = grid_rules(d).g_fco_standard.to_numpy()
    m = d.n.between(253, 504)
    c = pd.Series(ok[m]).groupby(d.date[m].to_numpy()).mean()
    return c.reindex(tdays, method="ffill")


def run(rule: str = "ci", sub: bool = False):
    levels = dict(CHOSEN_B)
    df = assemble_bottom("dev", with_z_variants(LEVELS_B))
    df = df.merge(pd.concat([sym_feats(s).assign(symbol=s) for s in df.symbol.unique()]).rename_axis("date").reset_index(), on=["date", "symbol"], how="left")
    tdays = price_series("sh000001").index
    tdays = tdays[(tdays >= df.date.min() - pd.Timedelta(days=200)) & (tdays <= df.date.max())]
    df = df.merge(newlow_breadth(sorted(_snapshot(SPLITS["dev"][2])), tdays).rename_axis("date").reset_index(), on="date", how="left")
    df["omori_p_sd20"] = df.groupby("symbol").omori_p_25.transform(lambda x: x.rolling(20, min_periods=10).std())
    if sub:
        subs = [s for s in df.symbol.unique() if (FEAT / ("lppls_v2_neg_lite" if s.startswith(("sh0", "sz39")) else "lppls_v2_neg_lite_stk100") / f"{s}.parquet").exists()]
        df = df[df.symbol.isin(subs)].reset_index(drop=True)
        nc = pd.concat([neg_conf(s, "lppls_v2_neg_lite" if s.startswith(("sh0", "sz39")) else "lppls_v2_neg_lite_stk100", tdays).rename("neg_conf").rename_axis("date").reset_index().assign(symbol=s) for s in subs])
        df = df.merge(nc, on=["date", "symbol"], how="left")
        df["neg_x_slow"] = df.neg_conf * df.fall_speed
        levels["B9"] = {**B9, **B9_SUB}
        tag = "ladder_bottom_b9_sub"
    else:
        levels["B9"] = B9
        tag = "ladder_bottom_b9"
    need = sorted({c for cfg in levels["B9"].values() for c in cfg})
    df = df.dropna(subset=need).reset_index(drop=True)
    tag += "" if rule == "ci" else f"_{rule}"
    return run_ladder(levels, tag=tag, rule=rule, df=df, force_keep=frozenset(CHOSEN_B),
                      title="底部阶梯 R0→B1→B2→B3（已选配置，固定）→ B9 阴跌/恐慌代理、新低广度、Omori 稳定性" + ("、−lnP LPPLS（106 标的子集）" if sub else ""))


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "ci", sub="sub" in sys.argv[2:])
