# ruff: noqa: E402, E702
"""Phase 3a：按底部类型分层诊断 LPPLS −lnP 抄底（开发段 6 指数 + 100 成分股；描述性，dev_only）。
底部 = 有效底标签事件段末 +1 日。类型按"从前 250 日最高收盘到底的交易日数" d_fall：panic ≤60、mid 61–120、slow >120（文献：负泡沫 LPPLS 适用阴跌减速，不适用恐慌 V 底）。
指标：召回 A2 = 底前 120 日内有 −lnP 首报（FCO 尺度 box/STANDARD 置信度 ≥0.10）的比例，按类型；零对照 = 报警序列循环平移 300 次的召回；
      精度 = 首报后 120 日内的底按类型分布。
用法：LPPLS_BOX=v2 PYTHONPATH=. python scripts/audit_stock_math/exp16_bottom_type_diag.py"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("LPPLS_BOX", "v2")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.eval.dataset import price_series
from research.eval.precision_baseline import (
    DEV,
    INDEXES,
    OUT,
    SCALES,
    confidence,
    event_dates,
    first_alarms,
)

H, N_PERM = 120, 300


def btype(d_fall: int) -> str:
    return "panic" if d_fall <= 60 else ("mid" if d_fall <= 120 else "slow")


def run(sym: str, feat_dir: str, lo: pd.Timestamp, grp: str, rng) -> tuple[pd.DataFrame, pd.DataFrame]:
    logp = price_series(sym); cal = logp.index; lp = logp.to_numpy()
    sc = pd.read_parquet(f"data/features/{feat_dir}/{sym}.parquet"); sc = sc[(sc.date >= lo) & (sc.date <= DEV[1])]
    if sc.empty:
        return pd.DataFrame(), pd.DataFrame()
    conf = confidence(sc, logp); gpos = cal.get_indexer(conf.index)
    bpos = np.sort(cal.get_indexer(event_dates(sym, "bottom"))); bpos = bpos[(bpos >= gpos.min()) & (bpos <= gpos.max() + H)]
    bots = []
    for b in bpos:
        w = lp[max(0, b - 250) : b + 1]; hi_i = int(np.argmax(w)); d_fall = len(w) - 1 - hi_i
        bots.append(dict(symbol=sym, group=grp, date=cal[b], pos=b, d_fall=d_fall, dd=float(np.exp(lp[b] - w[hi_i]) - 1), btype=btype(d_fall)))
    B = pd.DataFrame(bots)
    rows = []
    for scn in SCALES:
        for rule in ("box", "standard"):
            alarm = conf[(scn, rule)].fillna(0).to_numpy() >= 0.10
            if alarm.sum() < 3 or B.empty:
                continue
            fa = gpos[first_alarms(alarm, gpos)]

            def recall(fa_pos):
                return np.array([((fa_pos >= b - H) & (fa_pos < b)).any() for b in B.pos])

            rec = recall(fa)
            nul = np.zeros((N_PERM, len(B)), bool)
            step = max(1, int(np.median(np.diff(gpos))))
            for k in range(N_PERM):
                sh = int(rng.integers(250 // step, len(alarm) - 250 // step))
                nul[k] = recall(gpos[first_alarms(np.roll(alarm, sh), gpos)])
            for i, b in B.iterrows():
                rows.append(dict(symbol=sym, group=grp, scale=scn, rule=rule, date=b.date, btype=b.btype, d_fall=b.d_fall, dd=b.dd, recalled=bool(rec[i]), null_recall=float(nul[:, i].mean())))
            # 精度：首报后 120 日内的第一个底的类型
            for a in fa:
                nb = bpos[bpos > a]
                hit = len(nb) and nb[0] - a <= H
                t = B.loc[B.pos == nb[0], "btype"].iloc[0] if hit else "none"
                rows.append(dict(symbol=sym, group=grp, scale=scn, rule=rule, date=cal[a], kind="alarm", hit=bool(hit), hit_type=t))
    return B, pd.DataFrame(rows)


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    Bs, Rs = [], []
    for s in INDEXES:
        b, r = run(s, "lppls_v2_neg_lite", DEV[0], "index", rng); Bs.append(b); Rs.append(r)
    for p in sorted(Path("data/features/lppls_v2_neg_lite_stk100").glob("*.parquet")):
        b, r = run(p.stem, "lppls_v2_neg_lite_stk100", pd.Timestamp("2010-01-01"), "stock", rng); Bs.append(b); Rs.append(r)
    B = pd.concat(Bs); R = pd.concat(Rs)
    OUT.mkdir(parents=True, exist_ok=True); B.to_csv(OUT / "bottom_types.csv", index=False); R.to_csv(OUT / "bottom_type_diag.csv", index=False)
    pd.set_option("display.width", 220)
    print("== 底部类型分布（d_fall 中位，回撤中位）")
    print(B.groupby(["group", "btype"]).agg(n=("pos", "size"), d_fall_med=("d_fall", "median"), dd_med=("dd", "median")).round(3).to_string())
    rec = R[R.get("kind").isna()] if "kind" in R else R
    print("\n== 召回 A2（底前 120 日有 −lnP 首报）按类型 vs 循环平移零对照")
    print(rec.groupby(["group", "scale", "rule", "btype"]).agg(n=("recalled", "size"), recall=("recalled", "mean"), null=("null_recall", "mean")).round(3).to_string())
    al = R[R.get("kind") == "alarm"]
    print("\n== 首报命中（120 日内有底）与命中底类型分布")
    print(al.groupby(["group", "scale", "rule"]).agg(n_alarm=("hit", "size"), hit=("hit", "mean"),
          panic=("hit_type", lambda x: (x == "panic").mean()), mid=("hit_type", lambda x: (x == "mid").mean()), slow=("hit_type", lambda x: (x == "slow").mean())).round(3).to_string())
