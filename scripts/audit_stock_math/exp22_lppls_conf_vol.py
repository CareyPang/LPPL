# ruff: noqa: E402, E702
"""§24.2 W7：LPPLS 置信度（lppls_v2_g2，FCO 尺度 box 通过率）→ 未来 log RV_h / MDD_60；HAR-RV + 涨幅/回撤基线；CPCV（6 块、k=2、gap 80）；
250 日块 bootstrap 90% 区间。开发段 6 指数，描述性，dev_only。用法：LPPLS_BOX=v2 PYTHONPATH=. python scripts/audit_stock_math/exp22_lppls_conf_vol.py [outdir]"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("LPPLS_BOX", "v2")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.eval.dataset import price_series
from research.eval.splits import cpcv_paths
from research.features.lppls_rules import SCALES_FCO, _derived, rules
from research.price_layer.e_dev import block_ci

INDEXES = ("sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006")
START, END = pd.Timestamp("2000-01-01"), pd.Timestamp("2018-12-31")
EX = {2007, 2008, 2014, 2015}
STEP, HS, EPS = 5, (20, 60), 1e-5
CONF = [f"conf_{s}" for s in ("1-3m", "6-12m", "12-24m")]
HAR, R1B1 = ["lrv1", "lrv5", "lrv22"], ["runup250", "dd250"]
SETS = {"har": HAR, "har_conf": HAR + CONF, "har_r1b1": HAR + R1B1, "base": HAR + R1B1, "cand": HAR + R1B1 + CONF}
TARGETS = ["lrv20", "lrv60", "mdd60"]
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/w7_conf_vol")


def lrv(r: np.ndarray, a: int, b: int) -> float:
    return float(np.log(np.sqrt(np.sum(r[a:b] ** 2)) + EPS))


def panel(sym: str) -> pd.DataFrame:
    logp = price_series(sym); cal = logp.index; lp = logp.to_numpy(); close = np.exp(lp); r = np.diff(lp, prepend=np.nan)
    sc = pd.read_parquet(f"data/features/lppls_v2_g2/{sym}.parquet"); sc = sc[sc.date <= END]
    pos = pd.Series(np.arange(len(lp)), index=cal); end = pos.reindex(sc.date).to_numpy()
    sc = sc.assign(y_std=[lp[e + 1 - n : e + 1].std() for e, n in zip(end, sc.n, strict=True)])
    d = _derived(sc); d["box"] = rules(d).box.to_numpy()
    conf = {}
    for name, (lo, hi) in SCALES_FCO.items():
        conf[f"conf_{name}"] = d[d.n.between(lo, hi)].groupby("date").box.mean()
    conf = pd.DataFrame(conf)
    rows, last = [], -10**9
    for date, c in conf.sort_index().iterrows():
        t = int(pos[date])
        if date < START or t < 260 or t + 60 >= len(lp) or cal[t + 60] > END or t - last < STEP:
            continue
        last = t
        hi250 = lp[t - 250 : t + 1].max()
        seg = close[t : t + 61]; mdd = float(1 - np.min(seg / np.maximum.accumulate(seg)))
        rows.append(dict(symbol=sym, date=date, lrv1=np.log(abs(r[t]) + EPS), lrv5=lrv(r, t - 4, t + 1), lrv22=lrv(r, t - 21, t + 1),
                         runup250=lp[t] - lp[t - 250], dd250=1 - np.exp(lp[t] - hi250), **c.to_dict(),
                         lrv20=lrv(r, t + 1, t + 21), lrv60=lrv(r, t + 1, t + 61), mdd60=mdd))
    return pd.DataFrame(rows)


def ols_fit_predict(Xtr, ytr, Xte):
    A = np.column_stack([np.ones(len(Xtr)), Xtr]); beta, *_ = np.linalg.lstsq(A, ytr, rcond=None)
    return np.column_stack([np.ones(len(Xte)), Xte]) @ beta


def cpcv_losses(P: pd.DataFrame, target: str, paths) -> pd.DataFrame:
    """返回逐 (path, 样本) 的各模型平方误差与 QLIKE，index=date。"""
    y = P[target].to_numpy(); out = []
    for tr, te, _ in paths:
        rec = dict(date=P.date.to_numpy()[te], symbol=P.symbol.to_numpy()[te], y=y[te])
        for name, cols in SETS.items():
            yh = ols_fit_predict(P[cols].to_numpy()[tr], y[tr], P[cols].to_numpy()[te])
            rec[f"se_{name}"] = (y[te] - yh) ** 2
            if target.startswith("lrv"):
                ratio = np.exp(2 * (y[te] - yh)); rec[f"ql_{name}"] = ratio - np.log(ratio) - 1
        out.append(pd.DataFrame(rec))
    return pd.concat(out).set_index("date")


def delta(df: pd.DataFrame, m: str, b: str, kind: str = "se") -> float:
    return float(1 - df[f"{kind}_{m}"].sum() / df[f"{kind}_{b}"].sum())


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    P = pd.concat([panel(s) for s in INDEXES], ignore_index=True).dropna()
    P.to_csv(OUT / "panel.csv", index=False); print("panel", len(P), P.groupby("symbol").size().to_dict(), flush=True)
    tdays = price_series("sh000001").index; tdays = tdays[(tdays >= START) & (tdays <= END)]
    paths = cpcv_paths(P.date, tdays, n_blocks=6, k=2, gap=80)
    res = []
    for tg in TARGETS:
        L = cpcv_losses(P, tg, paths)
        ex = L[~L.index.year.isin(EX)]
        row = dict(target=tg, n=len(P), n_paths=len(paths))
        for kind in (("se", "ql") if tg.startswith("lrv") else ("se",)):
            d, lo, hi = block_ci(L.rename(columns={f"{kind}_cand": "loss_m", f"{kind}_base": "loss_b"}), lambda df: 1 - df.loss_m.sum() / df.loss_b.sum())
            row.update({f"{kind}_delta": d, f"{kind}_lo": lo, f"{kind}_hi": hi, f"{kind}_delta_ex": delta(ex, "cand", "base", kind),
                        f"{kind}_d_harconf": delta(L, "har_conf", "har", kind), f"{kind}_d_harr1b1": delta(L, "har_r1b1", "har", kind)})
        row["pass"] = bool(row["se_lo"] > 0 and row["se_delta_ex"] > 0 and row["se_d_harconf"] > row["se_d_harr1b1"])
        res.append(row); print(tg, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()}, flush=True)
    R = pd.DataFrame(res); R.to_csv(OUT / "gate.csv", index=False)
    rv_pass = bool(R[R.target.isin(["lrv20", "lrv60"])]["pass"].any()); mdd_pass = bool(R[R.target == "mdd60"]["pass"].any())
    print("GATE rv:", rv_pass, "mdd:", mdd_pass)
