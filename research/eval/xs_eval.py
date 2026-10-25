"""§17.6 XS 探索尺度（15–30 日窗口）单独评价：box 规则置信度报警 → H 日内见顶的 A1/A2，对照循环平移零分布。
样本点少（15–30 点拟合 7 参数），结果只作参考，不进保留链。用法：LPPLS_BOX=v2 python -m research.eval.xs_eval"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..features.lppls_rules import SCALES_XS, _derived, rules
from .dataset import price_series
from .original_standard import HORIZONS, THRESHOLDS, top_dates

SCAN = Path("data/features/lppls_v2_xs")
OUT = Path("reports/original_standard_dev_v2_xs")
DEV_END = pd.Timestamp("2018-12-31")
N_PERM = 500


def _a1a2(alarm: np.ndarray, apos: np.ndarray, tpos: np.ndarray, H: int) -> tuple[float, float]:
    if alarm.sum() == 0 or len(tpos) == 0:
        return np.nan, np.nan
    a = apos[alarm]
    a1 = np.mean([((tpos > x) & (tpos <= x + H)).any() for x in a])
    a2 = np.mean([((a < t) & (a >= t - H)).any() for t in tpos])
    return float(a1), float(a2)


def main() -> None:
    rng = np.random.default_rng(0)
    rows = []
    lo, hi = SCALES_XS["XS"]
    for p in sorted(SCAN.glob("*.parquet")):
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
        r = rules(d)
        m = d.n.between(lo, hi)
        conf = r.box[m].groupby(d.date[m]).mean()
        tops = top_dates(sym)
        tpos = np.sort(cal.get_indexer(tops))
        tpos = tpos[tpos >= 0]
        apos = cal.get_indexer(conf.index)
        for q in THRESHOLDS:
            al = conf.to_numpy() >= q
            ms = min(250, max(1, len(al) // 4))
            for H in HORIZONS:
                a1, a2 = _a1a2(al, apos, tpos, H)
                null = np.array([_a1a2(np.roll(al, rng.integers(ms, len(al) - ms)), apos, tpos, H) for _ in range(N_PERM)])
                rows.append(
                    dict(sym=sym, thr=q, H=H, n_alarm=int(al.sum()), alarm_rate=round(al.mean(), 3), A1=a1, A2=a2,
                         A1_null=np.nanmedian(null[:, 0]), A2_null=np.nanmedian(null[:, 1]),
                         p_A1=np.mean(null[:, 0] >= a1), p_A2=np.mean(null[:, 1] >= a2))
                )
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "alarm_xs.csv", index=False)
    agg = df.groupby(["thr", "H"]).agg(n_sym=("sym", "size"), A1_med=("A1", "median"), A1_null=("A1_null", "median"),
                                      A2_med=("A2", "median"), A2_null=("A2_null", "median"),
                                      p_A1_med=("p_A1", "median"), p_A2_med=("p_A2", "median")).round(3)
    with open(OUT / "summary.md", "w") as f:
        f.write("# XS 探索尺度（15–30 日）box 规则 A1/A2（开发段，只作参考）\n\n")
        f.write(agg.to_markdown() + "\n\n按指数：\n\n" + df.round(3).to_markdown(index=False) + "\n")
    print(agg.to_string())


if __name__ == "__main__":
    main()
