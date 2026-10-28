"""§16.1 标签稳健性：用两套替代转折点标签重跑保留链（顶部 R1/R2/R7 已选配置；底部 B1/B2/B3 已选配置），只报结论是否翻转。
(a) ps：Pagan–Sossounov 2003 / Harding–Pagan 2002（窗口 ±168 日、最短阶段 84 日、最短周期 336 日、峰谷交替）；
(b) lt：Lunde–Timmermann 2004 停时法（λ1=20% 牛转熊，λ2=15% 熊转牛；顶 = 牛市阶段最高点，底 = 熊市阶段最低点）。
事件进入标签仍需满足主标签的幅度门槛（顶：随后回撤 ≥ main__d_t；底：随后上涨 ≥ main__d_up），y = 未来 20 日内出现合格转折点。
python -m research.eval.alt_labels top|bottom"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from .dataset import price_series
from .ladder import assemble, run_ladder
from .ladder_bottom import LEVELS_B, assemble_bottom, with_z_variants
from .robustness import CHOSEN, CHOSEN_B

H = 20
LAB_TOP, LAB_BOT = "data/labels/top_v1", "data/labels/bottom_v1"


def ps_turns(x: np.ndarray, win: int = 168, phase: int = 84, cycle: int = 336) -> tuple[np.ndarray, np.ndarray]:
    n = len(x)
    peaks = [i for i in range(win, n - win) if x[i] == x[i - win:i + win + 1].max()]
    troughs = [i for i in range(win, n - win) if x[i] == x[i - win:i + win + 1].min()]
    turns = sorted([(i, 1) for i in peaks] + [(i, -1) for i in troughs])
    out: list[tuple[int, int]] = []
    for i, s in turns:  # 峰谷交替：同类相邻取更极端者
        if out and out[-1][1] == s:
            j = out[-1][0]
            if (s == 1 and x[i] > x[j]) or (s == -1 and x[i] < x[j]):
                out[-1] = (i, s)
            continue
        out.append((i, s))
    ok = []
    for i, s in out:
        if ok and i - ok[-1][0] < phase:
            continue
        if len(ok) >= 2 and i - ok[-2][0] < cycle:
            continue
        ok.append((i, s))
    return np.array([i for i, s in ok if s == 1], int), np.array([i for i, s in ok if s == -1], int)


def lt_turns(x: np.ndarray, l1: float = 0.20, l2: float = 0.15) -> tuple[np.ndarray, np.ndarray]:
    bull, ref, peaks, troughs = True, 0, [], []
    for i in range(1, len(x)):
        if bull:
            if x[i] > x[ref]:
                ref = i
            elif x[ref] - x[i] >= np.log(1 / (1 - l1)):
                peaks.append(ref)
                bull, ref = False, i
        else:
            if x[i] < x[ref]:
                ref = i
            elif x[i] - x[ref] >= np.log(1 + l2):
                troughs.append(ref)
                bull, ref = True, i
    return np.array(peaks, int), np.array(troughs, int)


def alt_y(sym: str, side: str, method: str) -> pd.Series:
    lp = price_series(sym)
    x = lp.to_numpy()
    peaks, troughs = (ps_turns if method == "ps" else lt_turns)(x)
    if side == "top":
        thr = pd.read_parquet(f"{LAB_TOP}/{sym}.parquet")["main__d_t"].reindex(lp.index).to_numpy()
        pts = [i for i in peaks if i + 1 < len(x) and (x[i] - x[i + 1:i + 1 + 250].min()) >= (thr[i] if np.isfinite(thr[i]) else 0.1)]
    else:
        thr = pd.read_parquet(f"{LAB_BOT}/{sym}.parquet")["main__d_up"].reindex(lp.index).to_numpy()
        pts = [i for i in troughs if i + 1 < len(x) and (x[i + 1:i + 1 + 60].max() - x[i]) >= (thr[i] if np.isfinite(thr[i]) else 0.1)]
    y = np.zeros(len(x))
    for i in pts:
        y[max(0, i - H):i] = 1
    return pd.Series(y, lp.index)


def run(side: str = "top", rule: str = "ci"):
    if side == "top":
        df, chosen, base = assemble("dev"), CHOSEN, "ladder_dev"
    else:
        df, chosen, base = assemble_bottom("dev", with_z_variants(LEVELS_B)), CHOSEN_B, "ladder_bottom_dev"
    rows = []
    for method in ("ps", "lt"):
        ys = pd.concat([alt_y(s, side, method).rename("y_alt").to_frame().assign(symbol=s).reset_index().rename(columns={"index": "date"})
                        for s in df.symbol.unique()])
        d = df.drop(columns=["y"]).merge(ys, on=["symbol", "date"], how="inner").rename(columns={"y_alt": "y"})
        tab, kept = run_ladder(chosen, tag=f"{base}_alt_{method}", rule=rule, df=d, title=f"§16.1 替代标签 {method}（{side} 保留链已选配置）")
        for _, r in tab[tab.config.str.contains("chosen")].iterrows():
            rows.append(dict(label=method, level=r.level, pos_rate=float(d.y.mean()), dbrier=r.dbrier, ci_lo=r.ci_lo, ci_hi=r.ci_hi, kept=r.kept))
    out = pd.DataFrame(rows)
    out.to_csv(f"reports/{base}_alt_labels.csv", index=False)
    with open(f"reports/{base}_alt_labels.md", "w") as f:
        f.write(f"# §16.1 标签稳健性（{side}；ps = Pagan–Sossounov 转折点，lt = Lunde–Timmermann 停时；保留链已选配置逐级相对前一级）\n\n")
        f.write(out.round(5).to_markdown(index=False) + "\n\n与主标签结论比较：kept 翻转即记“标签敏感”。开发段结果，不是样本外。\n")
    print(out.round(5).to_string(index=False))


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "top", sys.argv[2] if len(sys.argv) > 2 else "ci")
