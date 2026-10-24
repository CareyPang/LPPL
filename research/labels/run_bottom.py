"""生成底部三重障碍标签并统计各切分段事件段数（预登记 v1.3 §13 / v1.5 §15）：python -m research.labels.run_bottom
输出 data/labels/bottom_v1/<symbol>.parquet（不入 git）和 reports/bottom_label_events.md。只统计事件数，不看任何特征。"""
from __future__ import annotations

from multiprocessing import Pool

import numpy as np
import pandas as pd

from ..data.stocks import CACHE
from .bottom import candidate_bottoms, label_bottom
from .run_top import FROZEN, INDEXES, ROOT, SPLITS, _snapshot
from .top import event_segments

OUT = ROOT / "data" / "labels" / "bottom_v1"
VARIANTS = {
    "main": dict(),
    "dn33": dict(dn_ratio=1 / 3),
    "dn67": dict(dn_ratio=2 / 3),
    "fixed15": dict(floor=0.15, quant=None),
}


def build(sym: str, dates: pd.DatetimeIndex, logp: np.ndarray) -> pd.DataFrame:
    bottoms = candidate_bottoms(logp)
    frames = []
    for name, kw in VARIANTS.items():
        lab = label_bottom(dates, logp, bottoms, **kw)
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


def main(procs: int = 3):
    OUT.mkdir(parents=True, exist_ok=True)
    labels: dict[str, pd.DataFrame] = {}
    for sym in INDEXES:
        d = pd.read_parquet(FROZEN / f"{sym}_qfq.parquet")
        labels[sym] = build(sym, pd.DatetimeIndex(d.date), np.log(d.close.to_numpy(float)))
        labels[sym].to_parquet(OUT / f"{sym}.parquet")
    print("indexes done", flush=True)
    stocks = sorted(p.stem for p in CACHE.glob("*.parquet"))
    first_date = {}
    with Pool(procs) as pool:
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
                n_ev = n_pos = n_obs = n_sym = n_valid = n_half = n_exp = 0
                for sym in syms:
                    if sym not in labels:
                        continue
                    lab = labels[sym]
                    lo = pd.Timestamp(a)
                    if group == "stock":
                        lo = max(lo, pd.Timestamp(entry), first_date[sym] + pd.DateOffset(years=5))
                    win = lab[(lab.index >= lo) & (lab.index <= pd.Timestamp(b))]
                    y = win[f"{var}__y"].dropna()
                    if len(y) == 0:
                        continue
                    n_sym += 1
                    n_obs += len(y)
                    n_pos += int(y.sum())
                    n_ev += len(event_segments(y))
                    oc = win[f"{var}__outcome"].dropna()
                    n_valid += int((oc == 1).sum())
                    n_half += int((oc == -1).sum())
                    n_exp += int((oc == 0).sum())
                rows.append(dict(split=split, variant=var, group=group, symbols=n_sym, obs=n_obs,
                                 pos_rate=n_pos / n_obs if n_obs else np.nan, events=n_ev,
                                 cand_valid=n_valid, cand_halfway=n_half, cand_expired=n_exp,
                                 halfway_share=n_half / (n_valid + n_half + n_exp) if (n_valid + n_half + n_exp) else np.nan))
    tab = pd.DataFrame(rows)
    tab.to_csv(ROOT / "reports" / "bottom_label_events.csv", index=False)
    cols = ["symbols", "obs", "pos_rate", "events", "cand_valid", "cand_halfway", "cand_expired", "halfway_share"]
    main_tab = tab[tab.variant == "main"].set_index(["split", "group"])[cols]
    sens = tab.pivot_table(index=["split", "group"], columns="variant", values=["events", "halfway_share"])
    (ROOT / "reports" / "bottom_label_events.md").write_text(
        "# 底部三重障碍标签事件统计（预登记 v1.3 §13 / v1.5 §15；只统计事件数，未看特征）\n\n"
        "候选底 = 对 −ln P 的 ε-回撤共识扫描；上障碍 = PIT 5 年 Q90（≥10%），下障碍 = 上障碍 × 50%，时间障碍 60 日；"
        "标签 y_t = 未来 20 日内出现有效底（先触上障碍），成熟期 80 日。cand_* 为候选底按结局分类：valid 有效底、halfway 先触下障碍（半山腰）、expired 到期未触。"
        "事件按**事件段**计。个股只计入所属快照、上市满 5 年之后的 as-of 时点。**校准段/测试段只报事件数，不做任何建模。**\n\n"
        "## 主标签\n" + main_tab.round(4).to_markdown()
        + "\n\n## 敏感性：各变体的事件段数与半山腰比例\n" + sens.round(3).to_markdown() + "\n")
    print(main_tab.round(4))


if __name__ == "__main__":
    main()
