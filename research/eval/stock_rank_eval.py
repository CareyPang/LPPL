"""§17.11 R8 LPPLS 版横截面排名评价（开发段，个股样本）。

每个 as-of 日：对样本内每只个股算 box 规则三尺度置信度与 Lagrange 选窗泡沫大小（lag_size）；
排名分数 = sqrt(|lag_size| × conf)，conf 取三尺度最大（不跨尺度平均；原版用最长合格尺度/Combo，这里登记为 max）。
正泡沫表（lag_size>0, 对 ln P 扫描）与负泡沫表（对 −ln P 扫描）分开。取每日 Top-K，检验：
  (a) Top-K 后续 H 日收益均值 vs 随机抽 K 只；(b) Top-K 中 H 日内出现个股顶（正）/底（负）标签事件的比例 vs 随机。
零分布：每个 as-of 日从当日可排名个股中随机抽 K 只，重复 N_PERM 次。
用法：python -m research.eval.stock_rank_eval <scan_dir> <pos|neg> [report_tag]"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ..features.lppls_rules import SCALES, _derived, lagrange_pick, rules
from .dataset import price_series

K, HORIZONS, N_PERM = int(os.environ.get("RANK_K", "12")), (60, 120), 300
LABEL_DIR = {"pos": Path("data/labels/top_v1"), "neg": Path("data/labels/bottom_v1")}


def stock_scores(sym: str, scan: pd.DataFrame) -> pd.DataFrame:
    logp = price_series(sym)
    cal = logp.index
    lp = logp.to_numpy()
    end = pd.Series(np.arange(len(cal)), index=cal).reindex(scan.date).to_numpy()
    scan = scan.copy()
    scan["y_std"] = [lp[e + 1 - n : e + 1].std() for e, n in zip(end, scan.n, strict=True)]
    scan["y_first"] = [lp[e + 1 - n] for e, n in zip(end, scan.n, strict=True)]
    scan["y_last"] = lp[end]
    d = _derived(scan)
    r = rules(d)
    out = {}
    for sc, (lo, hi) in SCALES.items():
        m = d.n.between(lo, hi)
        out[f"conf_{sc}"] = r.box[m].groupby(d.date[m]).mean()
    df = pd.DataFrame(out).reindex(sorted(d.date.unique())).fillna(0.0)
    pick = lagrange_pick(d.reset_index(drop=True))
    lagf = d.reset_index(drop=True).loc[pick.to_numpy()].set_index(pick.index)
    df["lag_size"] = (np.exp(lagf.y_last - lagf.y_first) - 1).reindex(df.index)
    df["lag_dt"] = lagf.n.reindex(df.index)
    df["conf_max"] = df[[f"conf_{s}" for s in SCALES]].max(axis=1)
    df["score"] = np.sqrt(df.lag_size.abs() * df.conf_max)
    df["symbol"] = sym
    return df.reset_index().rename(columns={"index": "date"})


def forward_returns(sym: str, dates: pd.DatetimeIndex) -> pd.DataFrame:
    logp = price_series(sym)
    pos = logp.index.get_indexer(dates)
    out = {}
    for H in HORIZONS:
        j = np.minimum(pos + H, len(logp) - 1)
        out[f"fwd{H}"] = np.where(pos >= 0, logp.to_numpy()[j] - logp.to_numpy()[np.maximum(pos, 0)], np.nan)
    return pd.DataFrame(out, index=dates)


def event_positions(sym: str, side: str) -> np.ndarray:
    f = LABEL_DIR[side] / f"{sym}.parquet"
    if not f.exists():
        return np.array([], int)
    lab = pd.read_parquet(f)["main__y"]
    cal = price_series(sym).index
    y = lab.reindex(cal).fillna(0).to_numpy() > 0
    # 事件起点 = 标签由 0 变 1 的位置
    starts = np.flatnonzero(np.diff(np.concatenate([[0], y.astype(int)])) == 1)
    return starts


def main(scan_dir: str, side: str, tag: str | None = None) -> None:
    sd = Path(scan_dir)
    tag = tag or f"{sd.name}_{side}"
    frames = []
    for p in sorted(sd.glob("*.parquet")):
        sc = pd.read_parquet(p)
        sc = sc[sc.date <= pd.Timestamp("2018-12-31")]
        if len(sc) == 0:
            continue
        s = stock_scores(p.stem, sc)
        fr = forward_returns(p.stem, pd.DatetimeIndex(s.date))
        s = pd.concat([s.set_index("date"), fr], axis=1).reset_index().rename(columns={"index": "date"})
        ev = event_positions(p.stem, side)
        cal = price_series(p.stem).index
        pos = cal.get_indexer(pd.DatetimeIndex(s.date))
        for H in HORIZONS:
            s[f"event{H}"] = [((ev > a) & (ev <= a + H)).any() if a >= 0 else np.nan for a in pos]
        frames.append(s)
    allp = pd.concat(frames, ignore_index=True)
    sign = 1 if side == "pos" else -1
    allp = allp[(sign * allp.lag_size > 0) & (allp.conf_max > 0)]
    rng = np.random.default_rng(0)
    rows = []
    for date, g in allp.groupby("date"):
        if len(g) < 2 * K:
            continue
        top = g.nlargest(K, "score")
        row = dict(date=date, n_universe=len(g), n_top=len(top))
        for H in HORIZONS:
            row[f"fwd{H}_top"] = top[f"fwd{H}"].mean()
            row[f"event{H}_top"] = top[f"event{H}"].astype(float).mean()
            idx = rng.integers(0, len(g), size=(N_PERM, K))
            fw = g[f"fwd{H}"].to_numpy()[idx].mean(1)
            evn = g[f"event{H}"].astype(float).to_numpy()[idx].mean(1)
            row[f"fwd{H}_null"] = np.nanmedian(fw)
            row[f"event{H}_null"] = np.nanmedian(evn)
            row[f"fwd{H}_p"] = np.mean(fw <= row[f"fwd{H}_top"]) if side == "pos" else np.mean(fw >= row[f"fwd{H}_top"])
            row[f"event{H}_p"] = np.mean(evn >= row[f"event{H}_top"])
        rows.append(row)
    res = pd.DataFrame(rows)
    out = Path("reports") / f"stock_rank_{tag}"
    out.mkdir(parents=True, exist_ok=True)
    allp.to_parquet(out / "scores.parquet")
    res.to_csv(out / "daily_topk.csv", index=False)
    summ = []
    for H in HORIZONS:
        summ.append(dict(H=H, n_days=len(res), fwd_top=res[f"fwd{H}_top"].mean(), fwd_null=res[f"fwd{H}_null"].mean(),
                         event_top=res[f"event{H}_top"].mean(), event_null=res[f"event{H}_null"].mean(),
                         share_days_p05_fwd=(res[f"fwd{H}_p"] <= 0.05).mean(), share_days_p05_event=(res[f"event{H}_p"] <= 0.05).mean()))
    S = pd.DataFrame(summ).round(4)
    res["year"] = pd.DatetimeIndex(res.date).year
    by_year = res.groupby("year")[[f"fwd{H}_top" for H in HORIZONS] + [f"fwd{H}_null" for H in HORIZONS] + [f"event{H}_top" for H in HORIZONS] + [f"event{H}_null" for H in HORIZONS]].mean().round(3)
    with open(out / "summary.md", "w") as f:
        f.write(f"# 横截面排名评价 {tag}（开发段；Top-{K}；零分布随机抽 {K} 只 ×{N_PERM}）\n\n")
        f.write("fwd = Top-K 后续 H 日对数收益均值（正泡沫期望为负/偏低，负泡沫期望为正/偏高）；event = Top-K 中 H 日内出现顶/底事件的比例。\n\n")
        f.write(S.to_markdown(index=False) + "\n\n## 按年\n\n" + by_year.to_markdown() + "\n")
    print(S.to_string())
    print(by_year.to_string())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
