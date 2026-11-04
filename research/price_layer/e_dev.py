"""§21.5 (e) 价格层开发段评价（A 股 6 指数，as-of 2000–2018；research-only，不进产品，不读校准/测试段价格）。

1. Q-DD2 条件分位：y = 未来 250 日对数最大回撤（≤0）；特征 ret500、accel；τ∈{0.2,0.5,0.8}；逐年扩展窗（训练 ≤ Y−2 且标签终点早于测试年起点）；
   评分 pinball 比值 vs 同训练集无条件分位。通过：τ=0.2 比值 90% 块 bootstrap 上界 < 1。
2. 尾部概率：P(−y ≥ d)，d∈{0.2,0.3,0.4}，逻辑回归同特征；Brier vs 训练集无条件频率，ΔBrier 90% 上界 < 0。
3. PPE 首次触及（V2588 §6.4–6.6）：U/L = P_t·exp(±kσ√H)，σ = EWMA(0.94) 日波动，k∈{1,2}，H∈{20,60}；结果 {U 先, L 先, 期限内不触及}，
   以日 high/low 判触及，同 bar 双触 INTERVAL_ORDER_AMBIGUOUS 剔除，期限未满 DATASET_END_RIGHT_CENSORED 剔除。
   基线 B0：零漂移 BM 对称双边界解析首达概率（反射级数）；挑战者 PPE：wells_v1 支撑井特征的多项逻辑回归（逐年扩展窗）。
   评分：三类 Brier、log loss、Activity（是否触及）与 Direction（触及时方向）分解；通过：ΔBrier < 0 且 90% 上界 < 0。
块 bootstrap：按日历切 250 交易日块、各指数共用同一块划分（事件跨指数相关），B=1000，重抽块后重算比值 / ΔBrier。
as-of 只取标签视野完整落在 2018-12-31 之前的日期（不读 2019 年价格）。
用法：PYTHONPATH=. python -m research.price_layer.e_dev"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression, QuantileRegressor

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / "data/frozen/v20261024"
WELLS = ROOT / "data/features/wells_v1"
OUT = ROOT / ("reports/price_layer_e_dev" + ("" if os.environ.get("E_BLOCK", "250") == "250" else f"_b{os.environ['E_BLOCK']}"))
SYMS = ("sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006")
START, END = pd.Timestamp("2000-01-01"), pd.Timestamp("2018-12-31")
STEP, H_DD, TAUS, DS = 5, 250, (0.2, 0.5, 0.8), (0.2, 0.3, 0.4)
KS, HS, LAM = (1, 2), (20, 60), 0.94
BLOCK, B_BOOT, SEED = int(os.environ.get("E_BLOCK", "250")), 1000, 0  # E_BLOCK=80 为块长敏感性（诊断，不作判定）


def bars(sym: str) -> pd.DataFrame:
    d = pd.read_parquet(FROZEN / f"{sym}_qfq.parquet").set_index("date")[["open", "high", "low", "close"]].astype(float)
    return d[d.close > 0]


# ---------- Q-DD2 / 尾部 ----------
def dd_panel(sym: str) -> pd.DataFrame:
    b = bars(sym)
    lp = np.log(b.close)
    p = b.close
    f = pd.DataFrame(index=b.index)
    f["ret500"] = lp - lp.shift(500)
    f["accel"] = p / p.shift(500) - p.shift(250) / p.shift(500)
    x = lp.to_numpy()
    fut = np.full(len(x), np.nan)
    for i in range(len(x) - H_DD):
        fut[i] = min(0.0, x[i + 1 : i + H_DD + 1].min() - x[i])
    f["y"] = fut
    f["yend"] = pd.Series(list(b.index[H_DD:]) + [pd.NaT] * H_DD, index=b.index)
    f["sym"] = sym
    f = f[(f.index >= START) & (f.yend <= END)].dropna()
    return f.iloc[::STEP]


def pinball(y, q, tau):
    d = y - q
    return np.maximum(tau * d, (tau - 1) * d)


def yearly_oos(panel: pd.DataFrame, fit_predict, baseline, cols: list[str]):
    """逐年扩展窗；返回 OOS 行（含模型与基线的逐样本损失）。"""
    d = panel.assign(yr=panel.index.year)
    rows = []
    for Y in sorted(d.yr.unique()):
        te = d[d.yr == Y]
        tr = d[(d.yr <= Y - 2) & (d.yend < te.index.min())]
        if len(tr) < 150 or tr.yr.nunique() < 3 or not len(te):
            continue
        lm, lb = fit_predict(tr, te, cols), baseline(tr, te)
        rows.append(pd.DataFrame(dict(loss_m=lm, loss_b=lb, sym=te.sym.to_numpy()), index=te.index))
    return pd.concat(rows) if rows else None


def block_ci(df: pd.DataFrame, stat, level=0.9, block=BLOCK, B=B_BOOT, seed=SEED):
    """df 含 loss_m/loss_b；stat(df)->float；按日历 250 日块重抽（各指数共用块）。"""
    days = np.sort(df.index.unique())
    blk = pd.Series(np.arange(len(days)) // block, index=days).reindex(df.index).to_numpy()
    groups = [df[blk == g] for g in np.unique(blk)]
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(B):
        pick = rng.integers(0, len(groups), len(groups))
        vals.append(stat(pd.concat([groups[i] for i in pick])))
    a = (1 - level) / 2
    return float(stat(df)), float(np.quantile(vals, a)), float(np.quantile(vals, 1 - a))


def qdd2(panel: pd.DataFrame) -> list[dict]:
    res = []
    for tau in TAUS:
        def fp(tr, te, cols, tau=tau):
            m = QuantileRegressor(quantile=tau, alpha=0.0, solver="highs").fit(tr[cols].to_numpy(), tr.y.to_numpy())
            return pinball(te.y.to_numpy(), m.predict(te[cols].to_numpy()), tau)

        def base(tr, te, tau=tau):
            return pinball(te.y.to_numpy(), np.full(len(te), np.quantile(tr.y, tau)), tau)

        oos = yearly_oos(panel, fp, base, ["ret500", "accel"])
        if oos is None:
            continue
        pt, lo, hi = block_ci(oos, lambda d: d.loss_m.sum() / d.loss_b.sum())
        res.append(dict(test="Q-DD2", tau=tau, n_oos=len(oos), years=f"{oos.index.year.min()}–{oos.index.year.max()}",
                        ratio=pt, ci_lo=lo, ci_hi=hi, passed=bool(hi < 1) if tau == 0.2 else None))
    return res


def tail(panel: pd.DataFrame) -> list[dict]:
    res = []
    for dthr in DS:
        def fp(tr, te, cols, dthr=dthr):
            ytr = (-tr.y >= dthr).astype(int)
            if ytr.nunique() < 2:
                return np.full(len(te), np.nan)
            m = LogisticRegression(C=1.0, max_iter=1000).fit(tr[cols].to_numpy(), ytr)
            p = m.predict_proba(te[cols].to_numpy())[:, 1]
            return (p - (-te.y >= dthr).astype(float)) ** 2

        def base(tr, te, dthr=dthr):
            p = (-tr.y >= dthr).mean()
            return (p - (-te.y >= dthr).astype(float)) ** 2

        oos = yearly_oos(panel, fp, base, ["ret500", "accel"])
        if oos is None:
            continue
        oos = oos.dropna()
        pt, lo, hi = block_ci(oos, lambda d: (d.loss_m - d.loss_b).mean())
        res.append(dict(test="tail", d=dthr, n_oos=len(oos), event_rate=float(np.nan), years=f"{oos.index.year.min()}–{oos.index.year.max()}",
                        dbrier=pt, ci_lo=lo, ci_hi=hi, brier_b=float(oos.loss_b.mean()), passed=bool(pt < 0 and hi < 0)))
    return res


# ---------- PPE 首次触及 ----------
def q_none_bm(k: float, terms: int = 20) -> float:
    """零漂移 BM、对称边界 ±k（以 σ√H 为单位）、T=1 内不触及任一边界的概率（反射级数）。"""
    j = np.arange(-terms, terms + 1)
    return float(np.sum((-1.0) ** j * (norm.cdf((2 * j + 1) * k) - norm.cdf((2 * j - 1) * k))))


def ft_panel(sym: str, k: float, H: int) -> pd.DataFrame:
    b = bars(sym)
    r = np.log(b.close).diff()
    var = r.pow(2).ewm(alpha=1 - LAM, adjust=False).mean()
    sig = np.sqrt(var)
    hi, lo, c = b.high.to_numpy(), b.low.to_numpy(), b.close.to_numpy()
    n = len(b)
    out = np.full(n, -9, dtype=int)  # 0=U 先, 1=L 先, 2=不触及, -1=歧义, -2=删失
    for i in range(n):
        if np.isnan(sig.iloc[i]) or i < 60:
            continue
        U, L = c[i] * np.exp(k * sig.iloc[i] * np.sqrt(H)), c[i] * np.exp(-k * sig.iloc[i] * np.sqrt(H))
        if i + H >= n:
            out[i] = -2
            continue
        res = 2
        for j in range(i + 1, i + H + 1):
            up, dn = hi[j] >= U, lo[j] <= L
            if up and dn:
                res = -1
                break
            if up:
                res = 0
                break
            if dn:
                res = 1
                break
        out[i] = res
    f = pd.DataFrame(dict(outcome=out, sig=sig.to_numpy()), index=b.index)
    f["yend"] = pd.Series(list(b.index[H:]) + [pd.NaT] * H, index=b.index)
    w = pd.read_parquet(WELLS / f"{sym}.parquet").reindex(b.index).ffill(limit=4)
    f = f.join(w)
    f["sym"] = sym
    f = f[(f.index >= START) & (f.yend <= END) & (f.outcome >= -1)]
    return f.iloc[::STEP]


def brier3(P: np.ndarray, y: np.ndarray) -> np.ndarray:
    Y = np.eye(3)[y]
    return ((P - Y) ** 2).sum(axis=1)


def ppe(k: float, H: int) -> dict:
    panel = pd.concat([ft_panel(s, k, H) for s in SYMS])
    n_amb = int((panel.outcome == -1).sum())
    d = panel[panel.outcome >= 0].dropna(subset=["well_F", "well_depth", "well_dist_below"])
    qn = q_none_bm(k)
    P0 = np.array([(1 - qn) / 2, (1 - qn) / 2, qn])
    cols = ["well_F", "well_depth", "well_dist_below"]
    d = d.assign(yr=d.index.year)
    rows = []
    for Y in sorted(d.yr.unique()):
        te = d[d.yr == Y]
        tr = d[(d.yr <= Y - 2) & (d.yend < te.index.min())]
        if len(tr) < 300 or tr.yr.nunique() < 3 or not len(te) or tr.outcome.nunique() < 3:
            continue
        m = LogisticRegression(C=1.0, max_iter=2000).fit(tr[cols].to_numpy(), tr.outcome.to_numpy())
        P = m.predict_proba(te[cols].to_numpy())
        P = P[:, np.argsort(m.classes_)]
        y = te.outcome.to_numpy()
        hit = (y < 2).astype(float)
        rows.append(pd.DataFrame(dict(
            loss_m=brier3(P, y), loss_b=brier3(np.tile(P0, (len(te), 1)), y),
            ll_m=-np.log(np.clip(P[np.arange(len(y)), y], 1e-6, 1)), ll_b=-np.log(P0[y]),
            act_m=((1 - P[:, 2]) - hit) ** 2, act_b=((1 - qn) - hit) ** 2,
            dir_m=np.where(y < 2, (P[:, 0] / np.maximum(1 - P[:, 2], 1e-9) - (y == 0)) ** 2, np.nan),
            dir_b=np.where(y < 2, (0.5 - (y == 0)) ** 2, np.nan),
            sym=te.sym.to_numpy()), index=te.index))
    oos = pd.concat(rows)
    pt, lo, hi = block_ci(oos, lambda d: (d.loss_m - d.loss_b).mean())
    emp = np.bincount(d.outcome, minlength=3) / len(d)
    return dict(test="PPE", k=k, H=H, n=len(d), n_ambiguous=n_amb, n_oos=len(oos), years=f"{oos.index.year.min()}–{oos.index.year.max()}",
                b0_qU=P0[0], b0_qnone=qn, emp_qU=emp[0], emp_qL=emp[1], emp_qnone=emp[2],
                brier_b0=float(oos.loss_b.mean()), brier_ppe=float(oos.loss_m.mean()), dbrier=pt, ci_lo=lo, ci_hi=hi,
                logloss_b0=float(oos.ll_b.mean()), logloss_ppe=float(oos.ll_m.mean()),
                d_activity=float((oos.act_m - oos.act_b).mean()), d_direction=float((oos.dir_m - oos.dir_b).mean()),
                passed=bool(pt < 0 and hi < 0))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    panel = pd.concat([dd_panel(s) for s in SYMS])
    print("Q-DD panel", len(panel), panel.index.min().date(), panel.index.max().date(), flush=True)
    r_q = qdd2(panel)
    for r in r_q:
        print(r, flush=True)
    r_t = tail(panel)
    for r in r_t:
        r["event_rate"] = float((-panel.y >= r["d"]).mean())
        print(r, flush=True)
    r_p = [ppe(k, H) for k in KS for H in HS]
    for r in r_p:
        print(r, flush=True)
    pd.DataFrame(r_q).to_csv(OUT / "qdd2.csv", index=False)
    pd.DataFrame(r_t).to_csv(OUT / "tail.csv", index=False)
    pd.DataFrame(r_p).to_csv(OUT / "ppe.csv", index=False)
    json.dump(dict(qdd2=r_q, tail=r_t, ppe=r_p, n_panel=len(panel), syms=SYMS), open(OUT / "summary.json", "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
