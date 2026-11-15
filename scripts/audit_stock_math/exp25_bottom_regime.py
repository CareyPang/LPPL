# ruff: noqa: E702
"""预登记 §23：底部体制 as-of 代理 bottom_regime 的开发段一次性核对（指数 6 + 成分股 100；用 Phase 3a 的事后分型与召回表）。
代理在底前 1 日（pos−1）计算：dd60 = 1 − P/max(P[t−60..t])，dd250 同理；dd250 < 0.10 → not_in_drawdown；dd250 ∈ [0.10, 0.15) → mixed；否则 fall_speed=dd60/dd250 ≥ θ → panic，< θ → slow。
一致率分母 = 3a 有效底中 panic ∪ slow（mid 剔除）；代理给 mixed / not_in_drawdown 记为不一致。θ ∈ {0.5,0.6,0.7,0.8} 取指数与成分股一致率之和最大者，只定一个。
门：两组一致率都 ≥ 0.70，且 slow 代理子集上 −lnP STANDARD 12–24m 召回 > 循环平移零对照（3a 的 300 次零对照均值）。
用法：PYTHONPATH=. python scripts/audit_stock_math/exp25_bottom_regime.py（读 reports/precision_baseline/bottom_types.csv 与 bottom_type_diag.csv，写 reports/bottom_regime_s23/）"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.eval.dataset import price_series  # noqa: E402

THETAS = (0.5, 0.6, 0.7, 0.8)
SRC = Path("reports/precision_baseline")
OUT = Path("reports/bottom_regime_s23")


def proxy_at(lp: np.ndarray, t: int) -> tuple[float, float]:
    p = np.exp(lp[: t + 1])
    return 1 - p[-1] / p[max(0, t - 60) :].max(), 1 - p[-1] / p[max(0, t - 250) :].max()


def regime(dd60: float, dd250: float, theta: float) -> str:
    if dd250 < 0.10:
        return "not_in_drawdown"
    if dd250 < 0.15:
        return "mixed"
    return "panic" if dd60 / dd250 >= theta else "slow"


def main() -> None:
    B = pd.read_csv(SRC / "bottom_types.csv", parse_dates=["date"])
    B = B[B.btype.isin(["panic", "slow"])].copy()
    cache: dict[str, np.ndarray] = {}
    d60, d250 = [], []
    for r in B.itertuples():
        if r.symbol not in cache:
            cache[r.symbol] = price_series(r.symbol).to_numpy()
        a, b = proxy_at(cache[r.symbol], int(r.pos) - 1)
        d60.append(a); d250.append(b)
    B["dd60"], B["dd250"] = d60, d250
    B["fall_speed"] = np.where(B.dd250 > 0, B.dd60 / B.dd250.where(B.dd250 > 0), np.nan)
    rows = []
    for th in THETAS:
        B[f"reg_{th}"] = [regime(a, b, th) for a, b in zip(B.dd60, B.dd250, strict=True)]
        for g, q in B.groupby("group"):
            rows.append(dict(theta=th, group=g, n=len(q), agree=float((q[f"reg_{th}"] == q.btype).mean()),
                             agree_panic=float((q[q.btype == "panic"][f"reg_{th}"] == "panic").mean()),
                             agree_slow=float((q[q.btype == "slow"][f"reg_{th}"] == "slow").mean()),
                             share_mixed_or_nid=float(q[f"reg_{th}"].isin(["mixed", "not_in_drawdown"]).mean())))
    A = pd.DataFrame(rows)
    tot = A.groupby("theta").agree.sum()
    th = float(tot.idxmax())
    sel = A[A.theta == th].set_index("group")
    R = pd.read_csv(SRC / "bottom_type_diag.csv", parse_dates=["date"])
    R = R[R.kind.isna() & (R.scale == "12-24m") & (R.rule == "standard")]
    R = R.merge(B[["symbol", "date", f"reg_{th}"]], on=["symbol", "date"], how="inner")
    rec = []
    for g, q in R.groupby("group"):
        for lab, s in (("proxy_slow", q[q[f"reg_{th}"] == "slow"]), ("proxy_panic", q[q[f"reg_{th}"] == "panic"]),
                       ("posthoc_slow", q[q.btype == "slow"])):
            rec.append(dict(group=g, subset=lab, n=len(s), recall=float(s.recalled.mean()) if len(s) else np.nan,
                            null=float(s.null_recall.mean()) if len(s) else np.nan))
    C = pd.DataFrame(rec)
    ok_agree = bool((sel.agree >= 0.70).all())
    cs = C[C.subset == "proxy_slow"].set_index("group")
    ok_rec = bool((cs.recall > cs.null).all()) and set(cs.index) == {"index", "stock"}
    OUT.mkdir(parents=True, exist_ok=True)
    B.to_csv(OUT / "bottoms_proxy.csv", index=False); A.to_csv(OUT / "agreement.csv", index=False); C.to_csv(OUT / "recall_recheck.csv", index=False)
    pd.set_option("display.width", 220)
    print("== 一致率（分母 panic ∪ slow；mixed/not_in_drawdown 记不一致）"); print(A.round(3).to_string(index=False))
    print(f"\n选定 θ = {th}（两组一致率之和 {tot.max():.3f}）"); print(sel.round(3).to_string())
    print("\n== −lnP STANDARD 12–24m 召回复核（θ 选定后）"); print(C.round(3).to_string(index=False))
    print(f"\n门：一致率 {'通过' if ok_agree else '未通过'}；slow 子集召回 > 零对照 {'通过' if ok_rec else '未通过'} → §23.2 {'通过' if ok_agree and ok_rec else '未通过'}")


if __name__ == "__main__":
    main()
