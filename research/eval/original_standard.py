"""§17.4-6 原版标准评分（开发段 2000–2018，指数）。

对象：多尺度置信度（E4）与 Lagrange 选窗合格标志；评价不用 Brier，而用原版的"预警 → 泡沫终结"口径：
  A1 = 报警（置信度 ≥ q）后 H 个交易日内出现合格顶的比例（精度）；
  A2 = 合格顶之前 H 个交易日内有过报警的比例（召回）；
  lead = 顶 − 窗口内首次报警（交易日）；
  对照 = 报警序列整体循环平移（偏移 ≥ 250 日）N_PERM 次的零分布（保留报警的自相关与频率）。
分位窗（Jiang 2010）：报警日合格拟合 t_c−t₂ 的 20/80 分位 → 窗口 [t+q20, t+q80]，统计对其后首个顶的覆盖率与宽度；
  基线 = 同宽度、从 t+1 起的窗口。
阈值网格不挑单一最优：输出全部组合，并标出 A1、A2 同时超过零分布 95 分位的"稳健区域"。
用法：LPPLS_BOX=v2 python -m research.eval.original_standard [symbols...]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ..eval.dataset import price_series
from ..features.lppls_rules import SCALES, _derived, grid_rules, multiscale_scores, rules
from ..features.lppls_scan import OUT as SCAN
from ..labels.run_top import INDEXES
from ..labels.top import event_segments
from ..lppls.scenarios import scenarios

DEV_END = pd.Timestamp("2018-12-31")
THRESHOLDS = (0.05, 0.10, 0.20)
HORIZONS = (60, 120)
N_PERM, MIN_SHIFT = 1000, 250
REPORT = Path("reports/original_standard_dev")


def top_dates(sym: str) -> pd.DatetimeIndex:
    lab = pd.read_parquet(f"data/labels/top_v1/{sym}.parquet")["main__y"]
    cal = price_series(sym).index
    out = []
    for _, end in event_segments(lab):
        i = cal.get_indexer([end])[0]
        if 0 <= i + 1 < len(cal):
            out.append(cal[i + 1])
    return pd.DatetimeIndex(out)


def load(sym: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    sc = pd.read_parquet(SCAN / f"{sym}.parquet")
    sc = sc[sc.date <= DEV_END]
    logp = price_series(sym)
    pos = pd.Series(np.arange(len(logp)), index=logp.index)
    lp = logp.to_numpy()
    end = pos.reindex(sc.date).to_numpy()
    sc["y_std"] = [lp[e + 1 - n : e + 1].std() for e, n in zip(end, sc.n, strict=True)]
    return sc, multiscale_scores(sc)


def _alarm_metrics(alarm: np.ndarray, top_pos: np.ndarray, grid_pos: np.ndarray, H: int) -> tuple[float, float]:
    """alarm：as-of 网格上的布尔；top_pos/grid_pos：交易日序号。"""
    if alarm.sum() == 0 or len(top_pos) == 0:
        return np.nan, np.nan
    ap = grid_pos[alarm]
    nxt = np.searchsorted(top_pos, ap, side="right")
    hit = (nxt < len(top_pos)) & (top_pos[np.minimum(nxt, len(top_pos) - 1)] - ap <= H)
    a1 = float(hit.mean())
    prev = np.searchsorted(ap, top_pos, side="left") - 1
    ok = (prev >= 0) & (top_pos - ap[np.maximum(prev, 0)] <= H)
    return a1, float(ok.mean())


def _null(alarm: np.ndarray, top_pos: np.ndarray, grid_pos: np.ndarray, H: int, rng: np.random.Generator) -> np.ndarray:
    n = len(alarm)
    step = max(1, int(np.median(np.diff(grid_pos))))
    out = np.empty((N_PERM, 2))
    for b in range(N_PERM):
        k = int(rng.integers(MIN_SHIFT // step, n - MIN_SHIFT // step))
        out[b] = _alarm_metrics(np.roll(alarm, k), top_pos, grid_pos, H)
    return out


def evaluate_symbol(sym: str, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    sc, ms = load(sym)
    cal = price_series(sym).index
    gpos = cal.get_indexer(ms.index)
    tpos = np.sort(cal.get_indexer(top_dates(sym)))
    tpos = tpos[(tpos >= gpos.min()) & (tpos <= gpos.max() + max(HORIZONS))]
    rng = np.random.default_rng(seed)
    rows = []
    conf_cols = [c for c in ms.columns if "__" in c and not c.startswith("n_")]
    for c in conf_cols:
        x = ms[c].fillna(0).to_numpy()
        for q in THRESHOLDS:
            alarm = x >= q
            if alarm.sum() < 3:
                continue
            for H in HORIZONS:
                a1, a2 = _alarm_metrics(alarm, tpos, gpos, H)
                nul = _null(alarm, tpos, gpos, H, rng)
                rows.append(dict(symbol=sym, indicator=c, q=q, H=H, n_alarm=int(alarm.sum()), alarm_rate=alarm.mean(),
                                 A1=a1, A1_null=np.nanmean(nul[:, 0]), A1_p=float(np.nanmean(nul[:, 0] >= a1)),
                                 A2=a2, A2_null=np.nanmean(nul[:, 1]), A2_p=float(np.nanmean(nul[:, 1] >= a2))))
    tab = pd.DataFrame(rows)
    # 分位窗（Jiang 2010）：用 box 规则与 E7 条件 1 的网格中位配置，按尺度与按最大簇
    d = _derived(sc)
    r = pd.concat([rules(d), grid_rules(d)], axis=1)
    win_rows = []
    for rule in ("box", "g_D0.8_w4_25_m0_1_e014", "g_D1.0_w6_13_m01_09_e014"):
        for date, idx in d.groupby("date").indices.items():
            f = d.iloc[idx][r[rule].to_numpy()[idx]]
            if len(f) < 3:
                continue
            tp = cal.get_indexer([date])[0]
            nxt = tpos[tpos > tp]
            if len(nxt) == 0:
                continue
            gap = nxt[0] - tp
            per = {sc_: f[f.n.between(lo, hi)] for sc_, (lo, hi) in SCALES.items()}
            cands = [(f"scale_{k}", v) for k, v in per.items() if len(v) >= 3]
            scn = scenarios(f)
            if len(scn):
                cands.append(("cluster_top", f.iloc[: 0]))
            for name, ff in cands:
                if name == "cluster_top":
                    q20, q80 = scn.q20.iloc[0], scn.q80.iloc[0]
                else:
                    q20, q80 = np.quantile(ff.ahead, [0.2, 0.8])
                width = max(1.0, q80 - q20)
                win_rows.append(dict(symbol=sym, rule=rule, date=date, kind=name, q20=q20, q80=q80, width=width,
                                     gap=gap, cover=bool(q20 <= gap <= q80), cover_naive=bool(1 <= gap <= 1 + width)))
    return tab, pd.DataFrame(win_rows)


def main(symbols: list[str]) -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    tabs, wins = [], []
    for sym in symbols:
        if not (SCAN / f"{sym}.parquet").exists():
            print("skip", sym, flush=True)
            continue
        t, w = evaluate_symbol(sym)
        tabs.append(t)
        wins.append(w)
        print("done", sym, len(t), len(w), flush=True)
    tab = pd.concat(tabs, ignore_index=True)
    win = pd.concat(wins, ignore_index=True)
    tab.to_csv(REPORT / "alarm_grid.csv", index=False)
    win.to_csv(REPORT / "quantile_windows.csv", index=False)
    agg = (tab.groupby(["indicator", "q", "H"])
           .agg(n_sym=("symbol", "nunique"), n_alarm=("n_alarm", "sum"), A1=("A1", "mean"), A1_null=("A1_null", "mean"),
                A1_p_med=("A1_p", "median"), A2=("A2", "mean"), A2_null=("A2_null", "mean"), A2_p_med=("A2_p", "median"))
           .reset_index())
    agg["robust"] = (agg.A1_p_med <= 0.05) & (agg.A2_p_med <= 0.05) & (agg.n_sym >= 4)
    agg.to_csv(REPORT / "alarm_grid_agg.csv", index=False)
    win["near"] = win.gap <= max(HORIZONS)
    wagg = (win.groupby(["rule", "kind"]).agg(n=("cover", "size"), cover=("cover", "mean"), cover_naive=("cover_naive", "mean"),
                                              width_med=("width", "median"), gap_med=("gap", "median"),
                                              n_near=("near", "sum")).reset_index())
    near = win[win.near].groupby(["rule", "kind"]).agg(cover_near=("cover", "mean"), cover_naive_near=("cover_naive", "mean")).reset_index()
    wagg = wagg.merge(near, on=["rule", "kind"], how="left")
    with open(REPORT / "summary.md", "w") as f:
        f.write(f"# 原版标准评分（开发段 2000–2018，{len(symbols)} 指数；扫描 {SCAN.name}）\n\n")
        f.write(f"组合总数 {len(agg)}；稳健区域（A1、A2 的中位 p ≤ 0.05 且 ≥4 指数）{int(agg.robust.sum())} 个。\n\n")
        f.write("## 稳健区域前 30（按 A1−A1_null 排序）\n\n")
        top = agg[agg.robust].assign(lift=lambda x: x.A1 - x.A1_null).sort_values("lift", ascending=False).head(30)
        f.write(top.round(3).to_markdown(index=False) + "\n\n")
        f.write("## 按尺度汇总（全部阈值/规则的中位数）\n\n")
        agg["scale"] = agg.indicator.str.split("__").str[-1]
        f.write(agg.groupby(["scale", "H"]).agg(A1=("A1", "median"), A1_null=("A1_null", "median"), A2=("A2", "median"),
                                                A2_null=("A2_null", "median"), robust=("robust", "sum")).round(3).to_markdown() + "\n\n")
        f.write("## 分位窗覆盖（Jiang 2010 口径）\n\n" + wagg.round(3).to_markdown(index=False) + "\n")
    print(open(REPORT / "summary.md").read())


if __name__ == "__main__":
    main(sys.argv[1:] or list(INDEXES))
