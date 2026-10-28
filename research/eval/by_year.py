"""按报警年份 / 事件年份拆分 A1、A2（长尺度 box 规则，阈值 0.05，H=120），用于判断结果是否只靠一两次大顶/大底。
用法：python -m research.eval.by_year <scan_dir> <top|bottom> [rule=box] [scale=L]
输出：reports/by_year_<scan_dir_name>_<side>.md"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ..features.lppls_rules import SCALES, _derived, grid_rules, rules
from ..labels.top import event_segments
from .dataset import price_series

DEV_END = pd.Timestamp("2018-12-31")


def event_dates(sym: str, side: str) -> pd.DatetimeIndex:
    f = Path("data/labels") / ("top_v1" if side == "top" else "bottom_v1") / f"{sym}.parquet"
    if not f.exists():
        return pd.DatetimeIndex([])
    lab = pd.read_parquet(f)["main__y"]
    cal = price_series(sym).index
    out = []
    for _, end in event_segments(lab):
        i = cal.get_indexer([end])[0]
        if 0 <= i + 1 < len(cal):
            out.append(cal[i + 1])
    return pd.DatetimeIndex(out)


def main(scan_dir: str, side: str, rule: str = "box", scale: str = "L", thr: float = 0.05, H: int = 120) -> None:
    sd = Path(scan_dir)
    rows, ev = [], []
    for p in sorted(sd.glob("*.parquet")):
        sym = p.stem
        sc = pd.read_parquet(p)
        sc = sc[sc.date <= DEV_END]
        if sc.empty:
            continue
        logp = price_series(sym)
        cal = logp.index
        lp = logp.to_numpy()
        end = pd.Series(np.arange(len(cal)), index=cal).reindex(sc.date).to_numpy()
        sc["y_std"] = [lp[e + 1 - n : e + 1].std() for e, n in zip(end, sc.n, strict=True)]
        d = _derived(sc)
        r = pd.concat([rules(d), grid_rules(d)], axis=1)
        m = d.n.between(*SCALES[scale])
        conf = r[rule][m].groupby(d.date[m]).mean()
        apos = cal.get_indexer(conf.index)
        al = conf.to_numpy() >= thr
        tpos = np.sort(cal.get_indexer(event_dates(sym, side)))
        tpos = tpos[tpos >= 0]
        for a, dt in zip(apos[al], conf.index[al], strict=True):
            rows.append(dict(sym=sym, year=dt.year, hit=bool(((tpos > a) & (tpos <= a + H)).any())))
        for t in tpos:
            td = cal[t]
            if 2000 <= td.year <= 2018:
                ev.append(dict(sym=sym, year=td.year, alarmed=bool(al[(apos < t) & (apos >= t - H)].any())))
    R, E = pd.DataFrame(rows), pd.DataFrame(ev)
    out = Path("reports") / f"by_year_{sd.name}_{side}.md"
    with open(out, "w") as f:
        f.write(f"# 按年拆分 {sd.name} / {side}（{rule}，尺度 {scale}，阈值 {thr}，H={H}；开发段）\n\n")
        if len(R):
            a1 = R.groupby("year").hit.agg(["size", "mean"]).round(2)
            f.write("## A1 精度按报警年份\n\n" + a1.T.to_markdown() + "\n\n")
            for yrs in ([2007, 2015], [2005, 2008], [2008], [2015]):
                x = R[~R.year.isin(yrs)]
                f.write(f"- 剔除 {yrs}：A1 {x.hit.mean():.2f} (n={len(x)})；全部 {R.hit.mean():.2f} (n={len(R)})\n")
        if len(E):
            a2 = E.groupby("year").alarmed.agg(["size", "mean"]).round(2)
            f.write("\n## A2 召回按事件年份\n\n" + a2.T.to_markdown() + "\n")
            f.write(f"\n全部召回 {E.alarmed.mean():.2f} (n={len(E)})\n")
    print(out.read_text())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], *(sys.argv[3:5]))
