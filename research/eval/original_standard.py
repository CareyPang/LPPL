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

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ..eval.dataset import price_series
from ..features.lppls_rules import (
    SCALES,
    _derived,
    grid_rules,
    lagrange_pick,
    multiscale_scores,
    rules,
)
from ..features.lppls_scan import BOX, BOXES
from ..features.lppls_scan import OUT as SCAN
from ..labels.run_top import INDEXES
from ..labels.top import event_segments
from ..lppls import core as _core
from ..lppls.scenarios import scenarios
from ..lppls.tc_bootstrap import tc_interval

# OS_TARGET=top（默认，顶部标签）或 bottom（底部标签；用于反泡沫扫描 lppls_v2_neg / lppls_v2_ab 的评价，§17.4-7）
TARGET = os.environ.get("OS_TARGET", "top")
LABEL_DIR = Path("data/labels/top_v1" if TARGET == "top" else "data/labels/bottom_v1")
DEV_END = pd.Timestamp("2018-12-31")
THRESHOLDS = (0.05, 0.10, 0.20)
HORIZONS = (60, 120)
N_PERM, MIN_SHIFT = 1000, 250
BOOT_RULE, BOOT_THR, BOOT_MAX, BOOT_B = "box", 0.10, int(os.environ.get("OS_BOOT_MAX", "100")), 30
REPORT = Path(f"reports/original_standard_dev_{SCAN.name.removeprefix('lppls_')}" + ("" if TARGET == "top" else "_bottom"))


def top_dates(sym: str) -> pd.DatetimeIndex:
    lab = pd.read_parquet(LABEL_DIR / f"{sym}.parquet")["main__y"]
    cal = price_series(sym).index
    out = []
    for _, end in event_segments(lab):
        i = cal.get_indexer([end])[0]
        if 0 <= i + 1 < len(cal):
            out.append(cal[i + 1])
    return pd.DatetimeIndex(out)


def regime_changes(sym: str) -> dict[str, np.ndarray]:
    """§17.6-1 FBE 式体制改变日期（交易日序号）：
    top = 合格顶（现有标签）；updays = 60 日上涨天数占比由 >0.5 跌到 <0.5 的首日；
    sg = Savitzky–Golay（三阶、窗 21）对数价一阶导由正转负的首日。"""
    from scipy.signal import savgol_filter

    logp = price_series(sym)
    cal = logp.index
    lp = logp.to_numpy()
    out = {"top": np.sort(cal.get_indexer(top_dates(sym)))}
    up = pd.Series((np.diff(lp, prepend=lp[0]) > 0).astype(float)).rolling(60).mean().to_numpy()
    cross = np.where((up[1:] < 0.5) & (up[:-1] >= 0.5))[0] + 1
    out["updays"] = cross
    der = savgol_filter(lp, 21, 3, deriv=1)
    out["sg"] = np.where((der[1:] < 0) & (der[:-1] >= 0))[0] + 1
    return out


def stability(windows: pd.DataFrame, k: int = 3) -> pd.Series:
    """§17.6-2 t_c 分布稳定性：连续 k 个 as-of 日期的 20/80 分位窗（折算到交易日序号）两两重叠度的最小值。
    windows：index=date，列 lo/hi 为交易日序号。"""
    lo, hi = windows.lo.to_numpy(float), windows.hi.to_numpy(float)
    vals = np.full(len(windows), np.nan)
    for i in range(k - 1, len(windows)):
        ov = []
        for a in range(i - k + 1, i + 1):
            for b in range(a + 1, i + 1):
                inter = max(0.0, min(hi[a], hi[b]) - max(lo[a], lo[b]))
                union = max(hi[a], hi[b]) - min(lo[a], lo[b])
                ov.append(inter / union if union > 0 else 0.0)
        vals[i] = min(ov) if ov else np.nan
    return pd.Series(vals, index=windows.index)


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


def bootstrap_windows(sym: str, d: pd.DataFrame, r: pd.DataFrame, tpos: np.ndarray, cal: pd.DatetimeIndex) -> list[dict]:
    """§17.6-1 FBE 要求的 bootstrap 拟合：报警日（BOOT_RULE 置信度 ≥ BOOT_THR）的 Lagrange 选中窗口，
    残差区块 bootstrap B=30 次重拟合，取 t_c−t₂ 的 20/80 分位作为分位窗；最多 BOOT_MAX 个日期（等距抽样）。"""
    conf = r[BOOT_RULE].groupby(d.date).mean()
    days = conf.index[conf >= BOOT_THR]
    if len(days) > BOOT_MAX:
        days = days[np.linspace(0, len(days) - 1, BOOT_MAX).astype(int)]
    if len(days) == 0:
        return []
    picks = lagrange_pick(d[d.date.isin(days)])
    logp = price_series(sym).to_numpy()
    bx = BOXES[BOX]
    _core.ALLOW_INSIDE = bool(bx["inside"])
    rows = []
    for date, ridx in picks.items():
        f = d.loc[ridx]
        tp = cal.get_indexer([date])[0]
        n = int(f.n)
        y = logp[tp + 1 - n : tp + 1]
        dt = n - 1
        tc_lo, _ = bx["tc"]
        lo = np.array([dt + (tc_lo if tc_lo >= 0.5 else tc_lo * dt), bx["m"][0], bx["w"][0]])
        hi = np.array([dt + 0.2 * dt, bx["m"][1], bx["w"][1]])
        try:
            bi = tc_interval(y, np.array([f.tc, f.m, f.w]), lo, hi, B=BOOT_B, seed=tp)
        except Exception:  # noqa: BLE001
            continue
        nxt = tpos[tpos > tp]
        if len(nxt) == 0:
            continue
        gap = nxt[0] - tp
        width = max(1.0, bi["q80"] - bi["q20"])
        rows.append(dict(symbol=sym, rule=BOOT_RULE, date=date, kind="lagrange_boot", q20=bi["q20"], q80=bi["q80"], width=width,
                         gap=gap, cover=bool(bi["q20"] <= gap <= bi["q80"]), cover_naive=bool(1 <= gap <= 1 + width),
                         cover_random=np.nan, dt=n, ahead_hat=bi["ahead_hat"], boot_sd=bi["sd"]))
    return rows


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
    # §17.6-5 价值分数分层：泡沫信号在"高估"（PE PIT 分位 ≥0.8）与非高估时的 A1 分别报告（两维度分开，不合并）
    try:
        from ..data.valuation import load as load_pe
        from ..data.valuation import value_score

        vp = value_score(load_pe(sym), cal).reindex(ms.index).to_numpy()
        for c in [c for c in conf_cols if c.startswith("box__")]:
            x = ms[c].fillna(0).to_numpy()
            for H in HORIZONS:
                for tag_, msk in (("value_hi", vp >= 0.8), ("value_lo", vp < 0.8)):
                    alarm = (x >= 0.10) & msk
                    if alarm.sum() < 3:
                        continue
                    a1, a2 = _alarm_metrics(alarm, tpos, gpos, H)
                    rows.append(dict(symbol=sym, indicator=f"{c}|{tag_}", q=0.10, H=H, n_alarm=int(alarm.sum()),
                                     alarm_rate=alarm.mean(), A1=a1, A1_null=np.nan, A1_p=np.nan, A2=a2, A2_null=np.nan, A2_p=np.nan))
    except Exception as e:  # noqa: BLE001
        print("value score skipped:", sym, type(e).__name__, flush=True)
    tab = pd.DataFrame(rows)
    # 分位窗（Jiang 2010）：用 box 规则与 E7 条件 1 的网格中位配置，按尺度与按最大簇
    d = _derived(sc)
    r = pd.concat([rules(d), grid_rules(d)], axis=1)
    win_rows = []
    rc = regime_changes(sym)
    rng_w = np.random.default_rng(seed + 1)
    for rule in ("box", "g_D0.8_w4_25_m0_1_e014", "g_D1.0_w6_13_m01_09_e014"):
        stab_rows = {}
        for date, idx in d.groupby("date").indices.items():
            f = d.iloc[idx][r[rule].to_numpy()[idx]]
            if len(f) < 3:
                continue
            tp = cal.get_indexer([date])[0]
            q20a, q80a = np.quantile(f.ahead, [0.2, 0.8])
            stab_rows[date] = (tp + q20a, tp + q80a)
            nxt = tpos[tpos > tp]
            if len(nxt) == 0:
                continue
            gap = nxt[0] - tp
            gaps = {k: (v[v > tp][0] - tp if (v > tp).any() else np.nan) for k, v in rc.items()}
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
                rnd_lo = rng_w.integers(1, max(2, int(max(HORIZONS) - width)))
                row = dict(symbol=sym, rule=rule, date=date, kind=name, q20=q20, q80=q80, width=width,
                           gap=gap, cover=bool(q20 <= gap <= q80), cover_naive=bool(1 <= gap <= 1 + width),
                           cover_random=bool(rnd_lo <= gap <= rnd_lo + width))
                for k, g in gaps.items():
                    row[f"cover_{k}"] = bool(np.isfinite(g) and q20 <= g <= q80)
                    row[f"random_{k}"] = bool(np.isfinite(g) and rnd_lo <= g <= rnd_lo + width)
                win_rows.append(row)
        if stab_rows:
            sw = pd.DataFrame(stab_rows, index=["lo", "hi"]).T
            st = stability(sw, 3)
            for row in win_rows:
                if row["rule"] == rule and row["date"] in st.index:
                    row["stab3"] = st[row["date"]]
    win_rows += bootstrap_windows(sym, d, r, tpos, cal)
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
    val = agg[agg.indicator.str.contains(r"\|value_")]
    agg = agg[~agg.indicator.str.contains(r"\|value_")]
    agg.to_csv(REPORT / "alarm_grid_agg.csv", index=False)
    win["near"] = win.gap <= max(HORIZONS)
    wagg = (win.groupby(["rule", "kind"]).agg(n=("cover", "size"), cover=("cover", "mean"), cover_naive=("cover_naive", "mean"),
                                              width_med=("width", "median"), gap_med=("gap", "median"),
                                              n_near=("near", "sum")).reset_index())
    near = win[win.near].groupby(["rule", "kind"]).agg(cover_near=("cover", "mean"), cover_naive_near=("cover_naive", "mean")).reset_index()
    wagg = wagg.merge(near, on=["rule", "kind"], how="left")
    fbe_cols = [c for c in win.columns if c.startswith("cover_") or c.startswith("random_")]
    fbe = win.groupby(["rule", "kind"])[fbe_cols].mean().reset_index()
    if "stab3" in win:
        win["stab_hi"] = win.stab3 >= 0.5
        fbe_stab = (win.dropna(subset=["stab3"]).groupby(["rule", "kind", "stab_hi"])
                    .agg(n=("cover", "size"), cover=("cover", "mean"), cover_updays=("cover_updays", "mean"),
                         cover_sg=("cover_sg", "mean")).reset_index())
    else:
        fbe_stab = pd.DataFrame()
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
        if len(val):
            f.write("## 价值分数分层（§17.6-5：PE PIT 分位 ≥0.8 为高估；泡沫与高估两维度分开报告）\n\n" + val[["indicator", "H", "n_sym", "n_alarm", "A1", "A2"]].round(3).to_markdown(index=False) + "\n\n")
        f.write("## 分位窗覆盖（Jiang 2010 口径）\n\n" + wagg.round(3).to_markdown(index=False) + "\n\n")
        f.write("## FBE 式成功判据（§17.6-1）：分位窗覆盖三种体制改变 vs 同宽随机窗\n\n" + fbe.round(3).to_markdown(index=False) + "\n\n")
        if len(fbe_stab):
            f.write("## t_c 分布稳定性分层（§17.6-2，连续 3 期分位窗最小重叠 ≥0.5）\n\n" + fbe_stab.round(3).to_markdown(index=False) + "\n")
    print(open(REPORT / "summary.md").read())


if __name__ == "__main__":
    main(sys.argv[1:] or list(INDEXES))
