"""抄底面板样本外检验（H1 相似事件分位、H2 首次触及）。测试集：2019-01-01 起入场的事件。
每个测试事件只用 known 日期早于其入场日的事件/无条件样本（PIT）。Δ = 基线损失 − 模型损失，>0 表示模型更好。
门槛：按入场月分簇 bootstrap 90% 区间下界 > 0，且 2019–2025 至少 5 年 Δ 均值 > 0。"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def main():
    LIB = Path(sys.argv[1])
    OUT = Path(sys.argv[2])
    Q = np.array([0.10, 0.25, 0.50, 0.75, 0.90])
    TEST0 = "2019-01-01"
    MIN_REF = 30
    B = 2000
    FH = {"fh60": (0.85, 1.15, 60), "fh120": (0.80, 1.30, 120)}
    MAN = json.loads((LIB / "manifest.json").read_text())
    OUT.mkdir(exist_ok=True, parents=True)
    ev = pd.read_parquet(LIB / MAN["events_file"])
    un = pd.read_parquet(LIB / MAN["unconditional_file"])
    ex1516 = ~ev.sig_date.str[:4].isin(["2015", "2016"])

    def pinball(y, qs):  # qs: (n,5)
        d = y[:, None] - qs
        return np.mean(np.maximum(Q * d, (Q - 1) * d), axis=1)

    def rw_quant(vol, h, kind, n=4000, seed=1):
        rng = np.random.default_rng(seed)
        s = rng.normal(-(vol**2) / 2, vol, (n, h))
        p = np.exp(np.cumsum(s, 1))
        v = {"r": p[:, -1] - 1, "mdd": p.min(1) - 1, "up": p.max(1) - 1}[kind]
        return np.quantile(v, Q)

    def rw_fh(vol, L, U, H, n=4000, seed=2):
        rng = np.random.default_rng(seed)
        p = np.exp(np.cumsum(rng.normal(-(vol**2) / 2, vol, (n, H)), 1))
        iL = np.where((p <= L).any(1), (p <= L).argmax(1), H + 1)
        iU = np.where((p >= U).any(1), (p >= U).argmax(1), H + 1)
        return np.array([(iU < iL).mean(), (iL < iU).mean(), (iL == iU).mean()])

    VG = np.exp(np.linspace(np.log(0.005), np.log(0.12), 40))

    def nearest(v):
        return int(np.abs(np.log(VG) - np.log(max(v, 1e-4))).argmin())

    RWQ = {
        (k, h): np.array([rw_quant(v, h, k) for v in VG])
        for k, h in (("r", 120), ("mdd", 120), ("up", 120))
    }
    RWF = {k: np.array([rw_fh(v, *FH[k]) for v in VG]) for k in FH}

    UQ = {}

    def uq(col, month):  # 无条件分位：只用入场月第一天之前已知的样本（比逐日更严格，仍为 PIT）
        k = (col, month)
        if k not in UQ:
            UQ[k] = np.quantile(un.loc[un.known120 < month + "-01", col].dropna(), Q)[None]
        return UQ[k]

    def run(pool_mask, label):
        rows = []
        E = ev[pool_mask]
        test = ev[(ev.entry_date >= TEST0)]
        for depth in sorted(ev.depth.unique()):
            T = test[test.depth == depth]
            R = E[E.depth == depth]
            for t in T.itertuples():
                if not np.isfinite(t.vol_d):
                    continue
                vi = nearest(t.vol_d)
                base = dict(depth=depth, entry=t.entry_date, sym=t.sym)
                for col, kind in (("r120", "r"), ("mdd120", "mdd"), ("up120", "up")):
                    y = getattr(t, col, np.nan)
                    if pd.isna(y):
                        continue
                    ref = R[(R.known120 < t.entry_date)][col].dropna()
                    if len(ref) < MIN_REF:
                        continue
                    m = pinball(np.array([y]), np.quantile(ref, Q)[None])[0]
                    bu = pinball(np.array([y]), uq(col, t.entry_date[:7]))[0]
                    br = pinball(np.array([y]), RWQ[(kind, 120)][vi][None])[0]
                    rows.append(
                        base | dict(test="H1_" + col, n_ref=len(ref), d_uncond=bu - m, d_rw=br - m)
                    )
                for k in FH:
                    y = getattr(t, k, None)
                    if y is None or pd.isna(y):
                        continue
                    ref = R[R[k + "_known"] < t.entry_date][k].dropna()
                    if len(ref) < MIN_REF:
                        continue
                    p = np.array([(ref == c).mean() for c in ("U", "L", "none")])
                    o = np.array([y == c for c in ("U", "L", "none")], float)
                    rows.append(
                        base
                        | dict(
                            test="H2_" + k,
                            n_ref=len(ref),
                            d_rw=((RWF[k][vi] - o) ** 2).sum() - ((p - o) ** 2).sum(),
                        )
                    )
        d = pd.DataFrame(rows)
        d["month"] = d.entry.str[:7]
        d["year"] = d.entry.str[:4]
        res = []
        rng = np.random.default_rng(20261104)
        for (test_name, depth), g in d.groupby(["test", "depth"]):
            for base in ("d_uncond", "d_rw"):
                if base not in g or g[base].isna().all():
                    continue
                x = g.dropna(subset=[base])
                months = x.month.unique()
                by = {m: x.loc[x.month == m, base].to_numpy() for m in months}
                bs = []
                for _ in range(B):
                    pick = rng.choice(months, len(months))
                    v = np.concatenate([by[m] for m in pick])
                    bs.append(v.mean())
                yr = x[x.year <= "2025"].groupby("year")[base].mean()
                lo, hi = np.quantile(bs, [0.05, 0.95])
                res.append(
                    dict(
                        pool=label,
                        test=test_name,
                        depth=depth,
                        baseline=base[2:],
                        n=len(x),
                        n_months=len(months),
                        delta=x[base].mean(),
                        ci90=[lo, hi],
                        years_pos=int((yr > 0).sum()),
                        years=len(yr),
                        passed=bool(lo > 0 and (yr > 0).sum() >= 5),
                    )
                )
        return d, res

    out = {
        "definition": __doc__,
        "lib": json.loads((LIB / "manifest.json").read_text()),
        "min_ref": MIN_REF,
        "B": B,
        "results": [],
    }
    for mask, label in ((pd.Series(True, index=ev.index), "全市场"), (ex1516, "剔除2015-16")):
        d, res = run(mask, label)
        out["results"] += res
        d.to_parquet(OUT / f"oos_rows_{label}.parquet")
    OUT.mkdir(exist_ok=True, parents=True)
    (OUT / "oos.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float))
    r = pd.DataFrame(out["results"])
    r["ci90"] = r.ci90.map(lambda c: f"[{c[0]:+.4f},{c[1]:+.4f}]")
    print(r.to_string(index=False))


if __name__ == "__main__":
    main()
