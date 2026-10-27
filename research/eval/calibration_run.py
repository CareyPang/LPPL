"""校准段（2019–2021）一次性运行（docs/dev_freeze.md §3；预登记 §18）。

前推（不是 CPCV）：模型在开发段（2000–2018）一次拟合，参数与配置取冻结清单，在校准段预测；
  T-A 顶部链 R0 → R2（bsadf500_psy，C=1.0，稀疏 as-of 时点，与 ladder_dev_full_v2 同样本构造）；
  B-A 底部链 R0 → B1(dd_nodur_z) → B2(amt_only_z) → B3(omori25)，C=0.1，日频，指数 + 沪深300（2018-12-28 快照）。
每级给 ΔBrier（相对 R0 = 开发段基率）80 日块 bootstrap 90% 区间（判据 i）、留出单一指数/单一年的区间（判据 iii）、
Platt (a,b) 一次拟合并固定（写 data/oof/calibration_platt.json）。LPPLS 置信度 A1/A2（判据 ii）在 calibration_lppls.py。
校准段结果只报告、不参与去留。用法：LPPLS_BOX=v2 python -m research.eval.calibration_run [top|bottom|all]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ..features.lppls_scan import asof_dates, calendar
from .baselines import logit_model, paired_delta_brier
from .calibration import Platt
from .dataset import INDEXES
from .ladder import assemble, with_z_variants
from .ladder_bottom import LEVELS_B, assemble_bottom
from .metrics import ece, event_metrics, score_table

SPLIT = os.environ.get("CP_EVAL_SPLIT", "cal")  # cal=校准段 2019–2021；test=最终测试段 2022-01–2025-08（只跑一次）
OUT = Path("reports/calibration_2019_2021" if SPLIT == "cal" else "reports/final_test_2022_2025")
OOF = Path("data/oof")
TOP_CHAIN = [("R2", ["bsadf500_psy"], 1.0)]
BOT_CHAIN = [("B1", [f"{c}_z" for c in LEVELS_B["B1"]["dd_nodur"]], 0.1),
             ("B2", [f"{c}_z" for c in LEVELS_B["B2"]["amt_only"]], 0.1),
             ("B3", list(LEVELS_B["B3"]["omori25"]), 0.1)]


def _oof(df: pd.DataFrame, p: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame(dict(date=df.date.to_numpy(), symbol=df.symbol.to_numpy(), y=df.y.to_numpy(), p=p, path=0))


def forward_chain(dev: pd.DataFrame, cal: pd.DataFrame, chain: list[tuple[str, list[str], float]], tag: str) -> tuple[pd.DataFrame, dict]:
    """逐级累加特征，开发段拟合、校准段预测；返回评分表与各级 OOF。"""
    base = float(dev.y.mean())
    oofs = {"R0": _oof(cal, np.full(len(cal), base))}
    rows = [dict(level="R0", features="dev base rate", C=np.nan, vs="-", dbrier=np.nan, ci_lo=np.nan, ci_hi=np.nan,
                 **score_table(oofs["R0"].y, oofs["R0"].p, oofs["R0"].p))]
    feats: list[str] = []
    prev = "R0"
    for name, fs, C in chain:
        feats = sorted(set(feats) | set(fs))
        m = logit_model(C).fit(dev[feats].to_numpy(), dev.y.to_numpy())
        oof = _oof(cal, m.predict_proba(cal[feats].to_numpy())[:, 1])
        oofs[name] = oof
        d0, lo0, hi0 = paired_delta_brier(oof, oofs["R0"])
        d, lo, hi = paired_delta_brier(oof, oofs[prev])
        rows.append(dict(level=name, features="+".join(fs), C=C, vs=prev, dbrier=d, ci_lo=lo, ci_hi=hi,
                         dbrier_vs_R0=d0, ci_lo_R0=lo0, ci_hi_R0=hi0, pass_i_vs_R0=bool(hi0 < 0 and d0 < -1e-6),
                         **score_table(oof.y, oof.p, oofs["R0"].p), **event_metrics(oof)))
        oof.to_parquet(OOF / f"cal_{tag}_{name}.parquet")
        print(f"[{tag}] {name}: ΔBrier vs R0 {d0:.5f} [{lo0:.5f},{hi0:.5f}] vs {prev} {d:.5f} [{lo:.5f},{hi:.5f}]", flush=True)
        prev = name
    return pd.DataFrame(rows), oofs


def holdouts(oofs: dict, chain_names: list[str], tag: str) -> pd.DataFrame:
    """判据 iii：留出任一指数 / 任一年后，各级相对 R0 的 ΔBrier 区间。"""
    rows = []
    ref = oofs["R0"]
    ho = [("symbol", s) for s in sorted(ref.symbol.unique()) if s in INDEXES] + [("year", y) for y in sorted(ref.date.dt.year.unique())]
    for kind, val in ho:
        keep = (ref.symbol != val) if kind == "symbol" else (ref.date.dt.year != val)
        for name in chain_names:
            d, lo, hi = paired_delta_brier(oofs[name][keep.to_numpy()], ref[keep.to_numpy()])
            rows.append(dict(holdout=f"ex_{val}", level=name, dbrier_vs_R0=d, ci_lo=lo, ci_hi=hi, pass_i=bool(hi < 0 and d < -1e-6), n=int(keep.sum())))
    out = pd.DataFrame(rows)
    out.to_csv(OUT / f"{tag}_holdouts.csv", index=False)
    return out


def platt_fit(oof: pd.DataFrame, name: str, store: dict) -> dict:
    """cal：一次拟合并写入 store；test：只套用 store 中校准段固定的 (a,b)，不重拟合。"""
    if SPLIT != "cal":
        pl = Platt()
        pl.a, pl.b = float(store[name]["a"]), float(store[name]["b"])
    else:
        pl = Platt().fit(oof.p.to_numpy(), oof.y.to_numpy())
    q = pl.transform(oof.p.to_numpy())
    res = dict(level=name, a=pl.a, b=pl.b, brier_raw=float(np.mean((oof.p - oof.y) ** 2)), brier_platt=float(np.mean((q - oof.y) ** 2)),
               ece_raw=float(ece(oof.y, oof.p)), ece_platt=float(ece(oof.y, q)), n=len(oof), pos=int(oof.y.sum()))
    if SPLIT == "cal":
        store[name] = dict(a=pl.a, b=pl.b, fitted_on="cal_2019_2021", n=len(oof), pos=int(oof.y.sum()))
    return res


def top_sparse(split: str, variant: str = "main") -> pd.DataFrame:
    df = assemble(split, variant)
    cal = calendar()
    grid = {s: set(asof_dates(s, "index", cal, (split,))) for s in INDEXES}
    keep = [d in grid.get(s, ()) for d, s in zip(df.date, df.symbol, strict=True)]
    df = df[np.asarray(keep) & (df.group == "index")].dropna(subset=["bsadf500_psy"]).reset_index(drop=True)
    return df


def run_top(store: dict, variant: str = "main") -> None:
    """variant≠main：§3 步骤 5 标签稳健性（share30/share70/fixed15/sigma1.5 替代顶部标签），只写 top_chain_<variant>.csv。"""
    dev, cal = top_sparse("dev", variant), top_sparse(SPLIT, variant)
    if variant != "main":
        tab, _ = forward_chain(dev, cal, TOP_CHAIN, f"top_{variant}")
        tab.to_csv(OUT / f"top_chain_{variant}.csv", index=False)
        return
    print(f"[top] dev n={len(dev)} pos={int(dev.y.sum())}; cal n={len(cal)} pos={int(cal.y.sum())} symbols={cal.symbol.nunique()}", flush=True)
    tab, oofs = forward_chain(dev, cal, TOP_CHAIN, "top")
    tab.to_csv(OUT / "top_chain.csv", index=False)
    holdouts(oofs, ["R2"], "top")
    pd.DataFrame([platt_fit(oofs["R2"], "top_R2", store)]).to_csv(OUT / "top_platt.csv", index=False)


def run_bottom(store: dict) -> None:
    levels = with_z_variants(LEVELS_B)
    dev, cal = assemble_bottom("dev", levels), assemble_bottom(SPLIT, levels)
    feats = sorted({c for _, fs, _ in BOT_CHAIN for c in fs})
    dev, cal = dev.dropna(subset=feats).reset_index(drop=True), cal.dropna(subset=feats).reset_index(drop=True)
    print(f"[bottom] dev n={len(dev)} pos={int(dev.y.sum())}; cal n={len(cal)} pos={int(cal.y.sum())} symbols={cal.symbol.nunique()}", flush=True)
    tab, oofs = forward_chain(dev, cal, BOT_CHAIN, "bottom")
    tab.to_csv(OUT / "bottom_chain.csv", index=False)
    holdouts(oofs, ["B1", "B2", "B3"], "bottom")
    idx = cal.group.to_numpy() == "index"
    sub = {k: v[idx].reset_index(drop=True) for k, v in oofs.items()}
    rows = []
    for name in ("B1", "B2", "B3"):
        d, lo, hi = paired_delta_brier(sub[name], sub["R0"])
        rows.append(dict(level=name, dbrier_vs_R0=d, ci_lo=lo, ci_hi=hi, pass_i=bool(hi < 0 and d < -1e-6), n=int(idx.sum())))
    pd.DataFrame(rows).to_csv(OUT / "bottom_chain_index_only.csv", index=False)
    pd.DataFrame([platt_fit(oofs["B2"], "bottom_B2", store), platt_fit(oofs["B3"], "bottom_B3", store)]).to_csv(OUT / "bottom_platt.csv", index=False)


def main(which: str = "all") -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    OOF.mkdir(parents=True, exist_ok=True)
    pj = OOF / "calibration_platt.json"
    store = json.load(open(pj)) if pj.exists() else {}
    if which in ("top", "all"):
        run_top(store)
    if which == "variants":
        for v in ("share30", "share70", "fixed15", "sigma1.5"):
            run_top(store, v)
    if which in ("bottom", "all"):
        run_bottom(store)
    if SPLIT == "cal":
        json.dump(store, open(pj, "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "all")
