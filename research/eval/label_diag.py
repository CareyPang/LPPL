"""开发段诊断（dev_only diagnostic，不改任何冻结阈值 / 证据等级）：
同一套 LPPLS 六档置信度报警，在三种顶部标签下的原版标准 A1/A2：
  main = Round 1 主标签（ε-共识顶 + 自适应门槛 + 60 日回撤）；
  PS   = Pagan–Sossounov ±168 日局部极值，固定最小幅度：峰后 126 日内回撤 ≥15%；
  LT   = Lunde–Timmermann 20%/15% 停时（顶 = 牛市阶段最高点）。
另给"二波子集"：PS/LT 顶中位于上一次 ≥30% 回撤的谷底之后 126–378 个交易日内者（崩盘后 6–18 个月）。
随机对照 = 报警序列循环平移 N_PERM 次。输出 reports/label_diag_dev/{grid.csv,summary.md}。
python -m research.eval.label_diag   环境变量：N_PERM（默认 300）、SYMS
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from .alt_labels import lt_turns, ps_turns
from .by_year import DEV_END, event_dates
from .dataset import price_series
from .scale_sens import BANDS, RULES, a1_a2, band_conf, load, power_mean

OUT = Path("reports/label_diag_dev")
HORIZONS = (60, 120)
THRS = (0.05, 0.2)
N_PERM = int(os.environ.get("N_PERM", "300"))
PS_MIN_DD, PS_LOOK = 0.15, 126
CRASH_DD, SW_LO, SW_HI = 0.30, 126, 378


def ps_tops(logp: pd.Series) -> np.ndarray:
    x = logp.to_numpy()
    pk, _ = ps_turns(x)
    out = [i for i in pk if np.exp(x[i : i + PS_LOOK + 1].min() - x[i]) - 1 <= -PS_MIN_DD]
    return np.array(out, int)


def lt_tops(logp: pd.Series) -> np.ndarray:
    pk, _ = lt_turns(logp.to_numpy())
    return np.array(pk, int)


def second_wave(tpos: np.ndarray, logp: pd.Series) -> np.ndarray:
    """顶 t 是二波顶 ⇔ 存在更早的顶 t0，t0→谷 回撤 ≥30%，且 t 落在谷后 126–378 日。"""
    x = logp.to_numpy()
    out = []
    for t in tpos:
        for t0 in tpos[tpos < t]:
            seg = x[t0 : t + 1]
            j = int(np.argmin(seg))
            if np.exp(seg[j] - seg[0]) - 1 <= -CRASH_DD and SW_LO <= t - (t0 + j) <= SW_HI:
                out.append(t)
                break
    return np.array(out, int)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261029)
    syms = os.environ.get("SYMS")
    syms = (
        syms.split(",")
        if syms
        else sorted(p.stem for p in Path("data/features/lppls_v2").glob("*.parquet"))
    )
    rows, tops_rows = [], []
    for sym in syms:
        sc = load(sym)
        if sc is None:
            continue
        logp = price_series(sym)
        cal = logp.index
        bc = band_conf(sc)
        dates = next(iter(bc.values())).index
        apos = cal.get_indexer(dates)
        first, last = int(apos.min()), cal.get_indexer([DEV_END], method="pad")[0]

        def clip(a: np.ndarray, lo: int = first, hi: int = last) -> np.ndarray:
            return np.sort(a[(a >= lo) & (a <= hi)])

        labels = {
            "main": clip(cal.get_indexer(event_dates(sym, "top"))),
            "PS": clip(ps_tops(logp)),
            "LT": clip(lt_tops(logp)),
        }
        labels["PS_2nd"] = second_wave(labels["PS"], logp)
        labels["LT_2nd"] = second_wave(labels["LT"], logp)
        for k, v in labels.items():
            for t in v:
                tops_rows.append(dict(sym=sym, label=k, top=cal[t].date()))
        ms = min(250, max(1, len(apos) // 4))
        for rule in RULES:
            confs = {b: bc[b][rule].to_numpy() for b in BANDS}
            confs["combo_p0.1"] = np.array(
                [power_mean([bc[b][rule].iloc[i] for b in BANDS], 0.1) for i in range(len(dates))]
            )
            for band, conf in confs.items():
                valid = ~np.isnan(conf)
                if valid.sum() < 50:
                    continue
                for thr in THRS:
                    al = np.where(valid, conf >= thr, False)
                    if al.sum() == 0:
                        continue
                    for H in HORIZONS:
                        for lab, tpos in labels.items():
                            a1, a2, n = a1_a2(al, apos, tpos, H)
                            r = np.array(
                                [
                                    a1_a2(
                                        np.roll(al, int(rng.integers(ms, len(al) - ms))),
                                        apos,
                                        tpos,
                                        H,
                                    )[:2]
                                    for _ in range(N_PERM)
                                ],
                                float,
                            )
                            rows.append(
                                dict(
                                    sym=sym,
                                    rule=rule,
                                    band=band,
                                    thr=thr,
                                    H=H,
                                    label=lab,
                                    n_alarm=n,
                                    n_top=len(tpos),
                                    A1=a1,
                                    A1_rand=np.nanmean(r[:, 0]),
                                    p_A1=float(np.nanmean(r[:, 0] >= a1)) if n else np.nan,
                                    A2=a2,
                                    A2_rand=np.nanmean(r[:, 1]),
                                    p_A2=float(np.nanmean(r[:, 1] >= a2)) if len(tpos) else np.nan,
                                )
                            )
        print("done", sym, flush=True)
    R = pd.DataFrame(rows)
    R.to_csv(OUT / "grid.csv", index=False)
    pd.DataFrame(tops_rows).to_csv(OUT / "tops.csv", index=False)
    agg = (
        R.groupby(["label", "rule", "band", "thr", "H"])
        .agg(
            n_sym=("sym", "nunique"),
            n_alarm=("n_alarm", "sum"),
            n_top=("n_top", "sum"),
            A1=("A1", "median"),
            A1_rand=("A1_rand", "median"),
            A2=("A2", "median"),
            A2_rand=("A2_rand", "median"),
            n_sig=("p_A1", lambda s: int((s <= 0.05).sum())),
            n_sig2=("p_A2", lambda s: int((s <= 0.05).sum())),
        )
        .reset_index()
    )
    agg["robust"] = (agg.n_sig >= 4) & (agg.n_sig2 >= 4)
    agg.to_csv(OUT / "grid_agg.csv", index=False)
    with open(OUT / "summary.md", "w") as f:
        f.write("# 标签诊断（开发段 2000–2018，6 指数；dev_only diagnostic，不改任何冻结结论）\n\n")
        f.write(
            f"同一报警序列，三种顶部标签 + 二波子集；随机对照循环平移 {N_PERM} 次；稳健 = ≥4 指数 p_A1≤0.05 且 p_A2≤0.05。\n\n"
        )
        f.write("## 每种标签的顶数（6 指数合计）\n\n")
        f.write(pd.DataFrame(tops_rows).groupby("label").size().to_markdown() + "\n\n")
        f.write("## 稳健组合数 / 组合总数，按标签\n\n")
        f.write(
            agg.groupby("label")
            .agg(total=("robust", "size"), robust=("robust", "sum"))
            .to_markdown()
            + "\n\n"
        )
        for lab in ["main", "PS", "LT", "PS_2nd", "LT_2nd"]:
            sub = agg[(agg.label == lab) & (agg.H == 120)].copy()
            sub["lift"] = sub.A1 - sub.A1_rand
            f.write(f"## {lab}：H=120，按 A1 提升排序前 12\n\n")
            f.write(
                sub.sort_values("lift", ascending=False)
                .head(12)[
                    [
                        "rule",
                        "band",
                        "thr",
                        "n_alarm",
                        "n_top",
                        "A1",
                        "A1_rand",
                        "A2",
                        "A2_rand",
                        "n_sig",
                        "n_sig2",
                        "robust",
                    ]
                ]
                .round(3)
                .to_markdown(index=False)
                + "\n\n"
            )
        f.write("## box 6–12 月档 thr=0.05 H=120：三种标签并排\n\n")
        f.write(
            agg[
                (agg.rule == "box") & (agg.band == "B4_6-12m") & (agg.thr == 0.05) & (agg.H == 120)
            ][
                [
                    "label",
                    "n_alarm",
                    "n_top",
                    "A1",
                    "A1_rand",
                    "A2",
                    "A2_rand",
                    "n_sig",
                    "n_sig2",
                    "robust",
                ]
            ]
            .round(3)
            .to_markdown(index=False)
            + "\n"
        )
    print(agg.groupby("label").agg(total=("robust", "size"), robust=("robust", "sum")))


if __name__ == "__main__":
    main()
