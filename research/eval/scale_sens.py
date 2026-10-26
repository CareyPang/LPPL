"""§17.14 尺度敏感性（开发段）：把 v2（30–750 日）与 XS（15–30 日）拟合按 FCO 公开六档尺度标签重聚合，
每档单独算置信度（合格比例），报警→H∈{20,60,120} 日内见顶的 A1、顶前 H 日有报警的 A2，按年拆分，
对照循环平移随机报警；另算六档幂平均 Combo（FCO 公开定义 p=0.1≈几何均值）与按前置牛市时长分层的召回矩阵。
六档窗口长度（交易日）是本项目的工作假设，FCO 未公开其实际窗口集合（交接包 F06）。
用法：python -m research.eval.scale_sens   环境变量：N_PERM（默认 300）、SYMS（逗号分隔，调试用）
输出：reports/scale_sens_dev/{bands.csv,by_year.csv,combo.csv,bull_strata.csv,summary.md}"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from ..features.lppls_rules import _derived, grid_rules, rules
from .by_year import DEV_END, event_dates
from .dataset import price_series

BANDS = {
    "B1_2-4w": (10, 20),
    "B2_1-3m": (21, 63),
    "B3_3-6m": (64, 126),
    "B4_6-12m": (127, 252),
    "B5_12-24m": (253, 504),
    "B6_2-6y": (505, 750),
}
RULES = ("box", "g_fco_standard", "g_fco_end")
HORIZONS = (20, 60, 120)
THRS = (0.05, 0.2)
COMBO_P = (0.1, 1.0, 10.0)
N_PERM = int(os.environ.get("N_PERM", "300"))
OUT = Path("reports/scale_sens_dev")
SCANS = ("data/features/lppls_v2", "data/features/lppls_v2_xs")


def load(sym: str) -> pd.DataFrame | None:
    parts = []
    for sd in SCANS:
        p = Path(sd) / f"{sym}.parquet"
        if p.exists():
            parts.append(pd.read_parquet(p))
    if not parts:
        return None
    sc = pd.concat(parts, ignore_index=True)
    sc = sc[sc.date <= DEV_END]
    if sc.empty:
        return None
    logp = price_series(sym)
    lp = logp.to_numpy()
    end = pd.Series(np.arange(len(logp)), index=logp.index).reindex(sc.date).to_numpy()
    sc["y_std"] = [lp[e + 1 - n : e + 1].std() for e, n in zip(end, sc.n, strict=True)]
    return sc.reset_index(drop=True)


def band_conf(sc: pd.DataFrame) -> dict[str, pd.DataFrame]:
    d = _derived(sc)
    r = pd.concat([rules(d), grid_rules(d)], axis=1)[list(RULES)]
    dates = pd.Index(sorted(d.date.unique()))
    out = {}
    for b, (lo, hi) in BANDS.items():
        m = d.n.between(lo, hi)
        c = r[m].groupby(d.date[m]).mean().reindex(dates)
        out[b] = c
    return out


def power_mean(x: np.ndarray, p: float) -> np.ndarray:
    """FCO 公开说明：跨尺度置信度幂平均，p→0 几何均值、p=1 算术均值。NaN 档忽略。"""
    x = np.asarray(x, float)
    ok = ~np.isnan(x)
    if ok.sum() == 0:
        return np.nan
    v = x[ok]
    if abs(p) < 1e-9:
        return float(np.exp(np.mean(np.log(v + 1e-6))) - 1e-6)
    return float(np.mean(v**p) ** (1 / p))


def a1_a2(al: np.ndarray, apos: np.ndarray, tpos: np.ndarray, H: int) -> tuple[float, float, int]:
    """A1：报警后 (a, a+H] 内有顶；A2：顶前 [t-H, t) 内有报警。向量化（searchsorted）。"""
    ap = np.sort(apos[al])
    n = len(ap)
    if n == 0:
        return np.nan, (0.0 if len(tpos) else np.nan), 0
    if len(tpos) == 0:
        return np.nan, np.nan, n
    nxt = np.searchsorted(tpos, ap, side="right")
    a1 = float(np.mean((nxt < len(tpos)) & (tpos[np.minimum(nxt, len(tpos) - 1)] <= ap + H)))
    lo = np.searchsorted(ap, tpos - H, side="left")
    hi = np.searchsorted(ap, tpos, side="left")
    a2 = float(np.mean(hi > lo))
    return a1, a2, n


def bull_runup(logp: pd.Series, t: int) -> tuple[int, float]:
    """前置上涨阶段（工作定义）：顶 t 之前 500 个交易日内的最低点 → t 的交易日数，以及该最低点到 t 的涨幅（倍数−1）。"""
    lo = max(0, t - 500)
    seg = logp.to_numpy()[lo : t + 1]
    j = int(np.argmin(seg))
    return int(t - (lo + j)), float(np.exp(seg[-1] - seg[j]) - 1)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261026)
    syms = os.environ.get("SYMS")
    files = sorted(Path(SCANS[0]).glob("*.parquet"))
    syms = syms.split(",") if syms else [p.stem for p in files]
    rows, yrows = [], []
    for sym in syms:
        sc = load(sym)
        if sc is None:
            continue
        logp = price_series(sym)
        cal = logp.index
        bc = band_conf(sc)
        dates = next(iter(bc.values())).index
        apos = cal.get_indexer(dates)
        tpos = np.sort(cal.get_indexer(event_dates(sym, "top")))
        first = int(apos.min())
        tpos = tpos[(tpos >= first) & (tpos <= cal.get_indexer([DEV_END], method="pad")[0])]
        dur = {t: bull_runup(logp, t) for t in tpos}
        ms = min(250, max(1, len(apos) // 4))
        for rule in RULES:
            confs = {b: bc[b][rule].to_numpy() for b in BANDS}
            for p in COMBO_P:
                confs[f"combo_p{p}"] = np.array([power_mean([bc[b][rule].iloc[i] for b in BANDS], p) for i in range(len(dates))])
            for name, conf in confs.items():
                valid = ~np.isnan(conf)
                if valid.sum() < 50:
                    continue
                for thr in THRS:
                    al = np.where(valid, conf >= thr, False)
                    for H in HORIZONS:
                        a1, a2, n = a1_a2(al, apos, tpos, H)
                        r1, r2 = [], []
                        for _ in range(N_PERM):
                            k = int(rng.integers(ms, len(al) - ms))
                            x1, x2, _ = a1_a2(np.roll(al, k), apos, tpos, H)
                            r1.append(x1)
                            r2.append(x2)
                        r1, r2 = np.array(r1, float), np.array(r2, float)
                        rows.append(dict(sym=sym, rule=rule, band=name, thr=thr, H=H, n_alarm=n, n_top=len(tpos),
                                         A1=a1, A1_rand=np.nanmean(r1), p_A1=float(np.nanmean(r1 >= a1)) if n else np.nan,
                                         A2=a2, A2_rand=np.nanmean(r2), p_A2=float(np.nanmean(r2 >= a2)) if len(tpos) else np.nan))
                        if thr == 0.05 and rule == "box":
                            for a, dt in zip(apos[al], dates[al], strict=True):
                                yrows.append(dict(sym=sym, band=name, H=H, year=dt.year, kind="A1",
                                                  hit=bool(((tpos > a) & (tpos <= a + H)).any())))
                            for t in tpos:
                                yrows.append(dict(sym=sym, band=name, H=H, year=cal[t].year, kind="A2",
                                                  hit=bool(al[(apos < t) & (apos >= t - H)].any()), dur=dur[t][0], gain=dur[t][1]))
    R = pd.DataFrame(rows)
    R.to_csv(OUT / "bands.csv", index=False)
    Y = pd.DataFrame(yrows)
    Y.to_csv(OUT / "by_year.csv", index=False)
    with open(OUT / "summary.md", "w") as f:
        f.write("# §17.14 尺度敏感性（开发段 2000–2018，6 指数；FCO 六档为工作假设窗口）\n\n")
        f.write(f"随机对照：循环平移 {N_PERM} 次。稳健 = ≥4 指数 p_A1≤0.05 且 p_A2≤0.05。\n\n")
        g = R.groupby(["rule", "band", "thr", "H"]).agg(
            n_sym=("sym", "size"), alarms=("n_alarm", "sum"),
            A1=("A1", "median"), A1_rand=("A1_rand", "median"),
            A2=("A2", "median"), A2_rand=("A2_rand", "median"),
            n_sig=("p_A1", lambda s: int(((s <= 0.05)).sum())),
        )
        both = R.assign(sig=(R.p_A1 <= 0.05) & (R.p_A2 <= 0.05)).groupby(["rule", "band", "thr", "H"]).sig.sum()
        g["n_both_sig"] = both
        g["robust"] = g.n_both_sig >= 4
        f.write("## 每档 × 阈值 × H（跨指数中位数）\n\n" + g.round(3).reset_index().to_markdown(index=False) + "\n\n")
        f.write(f"稳健组合数：{int(g.robust.sum())} / {len(g)}；按档：\n\n")
        f.write(g.reset_index().groupby("band").robust.sum().to_markdown() + "\n\n")
        if len(Y):
            f.write("## box q=0.05：A1 按报警年份（各档，H=120）\n\n")
            a1 = Y[(Y.kind == "A1") & (Y.H == 120)].pivot_table(index="band", columns="year", values="hit", aggfunc="mean").round(2)
            f.write(a1.to_markdown() + "\n\n")
            cnt = Y[(Y.kind == "A1") & (Y.H == 120)].pivot_table(index="band", columns="year", values="hit", aggfunc="size")
            f.write("报警日数：\n\n" + cnt.to_markdown() + "\n\n")
            f.write("## box q=0.05：剔除泡沫年后的 A1（各档 × H）\n\n")
            ex = []
            for (b, H), x in Y[Y.kind == "A1"].groupby(["band", "H"]):
                ex.append(dict(band=b, H=H, all=x.hit.mean(), n=len(x), ex_2007_2015=x[~x.year.isin([2007, 2015])].hit.mean(),
                               n_ex=int((~x.year.isin([2007, 2015])).sum())))
            f.write(pd.DataFrame(ex).round(3).to_markdown(index=False) + "\n\n")
            f.write("## box q=0.05：A2 召回按事件年份（各档，H=120）\n\n")
            a2 = Y[(Y.kind == "A2") & (Y.H == 120)].pivot_table(index="band", columns="year", values="hit", aggfunc="mean").round(2)
            f.write(a2.to_markdown() + "\n\n")
            A2 = Y[Y.kind == "A2"].copy()
            A2["dur_s"] = pd.cut(A2.dur, [-1, 125, 378, 10_000], labels=["<6m", "6-18m", ">18m"])
            A2["gain_s"] = pd.cut(A2.gain, [-1, 0.3, 0.8, 100], labels=["<30%", "30-80%", ">80%"])
            for col, title in (("dur_s", "前置上涨时长（500 日内最低点→顶的交易日数；<126 / 126–378 / >378）"),
                               ("gain_s", "前置涨幅（500 日内最低点→顶；<30% / 30–80% / >80%）")):
                f.write(f"## 顶部按{title}分层 × 档 × H 的召回\n\n")
                st = A2.pivot_table(index=["band", "H"], columns=col, values="hit", aggfunc="mean", observed=False).round(2)
                f.write(st.to_markdown() + "\n\n")
                st.to_csv(OUT / f"strata_{col}.csv")
                u = A2.drop_duplicates(["sym", "year", "dur"]).groupby(col, observed=False).size()
                f.write("顶部事件数（每顶一行）：\n\n" + u.to_markdown() + "\n\n")
    print((OUT / "summary.md").read_text())


if __name__ == "__main__":
    main()
