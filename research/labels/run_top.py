"""生成顶部标签并统计各切分段事件段数：python -m research.labels.run_top
输出 data/labels/top_v1/<symbol>.parquet（不入 git）和 reports/top_label_events.md。"""
from __future__ import annotations

from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.stocks import CACHE, UNIVERSE
from .top import consensus_tops, epsilon_tops, event_segments, label_top

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / "data" / "frozen" / "v20261024"
OUT = ROOT / "data" / "labels" / "top_v1"
INDEXES = ("sh000001", "sh000016", "sh000300", "sh000905", "sh000688", "sz399001", "sz399006")
SPLITS = {
    "dev": ("2000-01-01", "2018-12-31", "csi300_20100104.csv", "2010-01-04"),
    "cal": ("2019-01-01", "2021-12-31", "csi300_20181228.csv", "2019-01-01"),
    "test": ("2022-01-01", "2025-08-31", "csi300_20211231.csv", "2022-01-01"),
}
VARIANTS = {
    "main": dict(share=0.5, kw=dict()),
    "share30": dict(share=0.3, kw=dict()),
    "share70": dict(share=0.7, kw=dict()),
    "fixed15": dict(share=0.5, kw=dict(floor=0.15, quant=None)),
    "sigma1.5": dict(share=0.5, kw=dict(quant=None, fixed_sigma_k=1.5)),
    # §17.4-6 次要检验：60 日视窗（LPPLS 提前量 1–3 个月，20 日视窗把提前报警记为误报）
    "h60": dict(share=0.5, kw=dict(horizon=60)),
}


def _snapshot(csv: str) -> set[str]:
    u = pd.read_csv(UNIVERSE / csv, dtype=str)
    return {m.lower() + c for c, m in zip(u.code, u.market, strict=True)}


def build(sym: str, dates: pd.DatetimeIndex, logp: np.ndarray) -> pd.DataFrame:
    hits = epsilon_tops(logp)
    frames = []
    for name, v in VARIANTS.items():
        tops = consensus_tops(logp, hits, share=v["share"])
        lab = label_top(dates, logp, tops, **v["kw"])
        lab.columns = [f"{name}__{c}" for c in lab.columns]
        frames.append(lab)
    df = pd.concat(frames, axis=1)
    df.insert(0, "symbol", sym)
    return df


def _stock(sym: str):
    d = pd.read_parquet(CACHE / f"{sym}.parquet")
    d = d[d.close_hfq > 0]
    first = pd.Timestamp(d.date.iloc[0])
    path = OUT / f"{sym}.parquet"
    if path.exists():
        return sym, first, pd.read_parquet(path)
    lab = build(sym, pd.DatetimeIndex(d.date), np.log(d.close_hfq.to_numpy(float)))
    lab.to_parquet(path)
    return sym, first, lab


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    labels: dict[str, pd.DataFrame] = {}
    for sym in INDEXES:
        d = pd.read_parquet(FROZEN / f"{sym}_qfq.parquet")
        labels[sym] = build(sym, pd.DatetimeIndex(d.date), np.log(d.close.to_numpy(float)))
        labels[sym].to_parquet(OUT / f"{sym}.parquet")
    print("indexes done", flush=True)
    stocks = sorted(p.stem for p in CACHE.glob("*.parquet"))
    first_date = {}
    with Pool(6) as pool:
        for i, (sym, fd, lab) in enumerate(pool.imap_unordered(_stock, stocks)):
            first_date[sym] = fd
            labels[sym] = lab
            if (i + 1) % 50 == 0:
                print(f"stocks {i + 1}/{len(stocks)}", flush=True)
    rows = []
    for split, (a, b, csv, entry) in SPLITS.items():
        snap = _snapshot(csv)
        for var in VARIANTS:
            for group, syms in (("index", INDEXES), ("stock", sorted(snap))):
                n_ev = n_pos = n_obs = n_sym = 0
                for sym in syms:
                    if sym not in labels:
                        continue
                    lab = labels[sym]
                    lo = pd.Timestamp(a)
                    if group == "stock":
                        lo = max(lo, pd.Timestamp(entry), first_date[sym] + pd.DateOffset(years=5))
                    y = lab.loc[(lab.index >= lo) & (lab.index <= pd.Timestamp(b)), f"{var}__y"].dropna()
                    if len(y) == 0:
                        continue
                    n_sym += 1
                    n_obs += len(y)
                    n_pos += int(y.sum())
                    n_ev += len(event_segments(y))
                rows.append(dict(split=split, variant=var, group=group, symbols=n_sym, obs=n_obs,
                                 pos_rate=n_pos / n_obs if n_obs else np.nan, events=n_ev))
    tab = pd.DataFrame(rows)
    tab.to_csv(ROOT / "reports" / "top_label_events.csv", index=False)
    main_tab = tab[tab.variant == "main"].set_index(["split", "group"])[["symbols", "obs", "pos_rate", "events"]]
    sens = tab.pivot_table(index=["split", "group"], columns="variant", values="events")
    (ROOT / "reports" / "top_label_events.md").write_text(
        "# 顶部标签事件统计（预登记 v1.0 §3，C 定位 + B 过滤）\n\n"
        "事件按**事件段**计（连续 Y=1 合并为一段）。个股只计入所属快照、上市满 5 年之后、成熟期已满的 as-of 时点。\n\n"
        "## 主标签（共识 50%，d_t = max(10%, Q90)）\n" + main_tab.round(4).to_markdown()
        + "\n\n## 敏感性：各变体的事件段数\n" + sens.to_markdown() + "\n")
    print(main_tab.round(4))
    print(sens)


if __name__ == "__main__":
    main()
