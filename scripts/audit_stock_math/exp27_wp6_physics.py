"""WP6 物理方法背景层（描述性，不报警，无门；docs/drafts_forward_expansion_wp456.md §J.3）。
样本：开发段 2010–2018，成分股 = csi300_20100104 快照（2010-01-04 时点 PIT，之后不换成分；已知限制），沪深300 交易日历，每 5 个交易日一个 as-of，滚动 250 日。
指标：eig1 = 相关矩阵最大特征值 / N；ar5 = 前 5 个特征值之和 / N（吸收比）；var60 = 等权组合近 60 日收益方差；
      lowfreq = 等权组合 250 日收益周期图里周期 ≥20 日的功率占比；mst = 距离 √(2(1−ρ)) 的最小生成树平均边长。
零模型：每只股票的收益序列独立循环平移（[250, T−250] 均匀），整条时间线重算全部指标，300 次 → 每个 as-of 的零分布分位 null_pct。
另给 own_pct：指标相对自身过去（≥52 个 as-of）的扩展分位，只用当时可知数据（登记外的描述性补充，因为按股平移会抹掉一切横截面相关，零分位对相关类指标没有区分度）。
顶部描述：sh000300 top_v1 顶标签（事件段末 +1 日）；对每个指标统计 own_pct≥0.95 / null_pct≥0.95 的 as-of 中 120 个交易日内出现顶的比例，与全体 as-of 的基准比例并列。不是 A1 判据，不构成门。
用法：OMP_NUM_THREADS=1 PYTHONPATH=. python scripts/audit_stock_math/exp27_wp6_physics.py"""
import os
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import minimum_spanning_tree

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("LPPLS_BOX", "v2")
from research.eval.dataset import price_series  # noqa: E402
from research.eval.precision_baseline import event_dates  # noqa: E402

LO, HI, W, STEP, N_PERM, MIN_SHIFT, H = pd.Timestamp("2010-01-01"), pd.Timestamp("2018-12-31"), 250, 5, 300, 250, 120
OUT = Path("reports/wp6_physics")
IND = ("eig1", "ar5", "var60", "lowfreq", "mst")


def load() -> tuple[np.ndarray, pd.DatetimeIndex, np.ndarray]:
    u = pd.read_csv("data/universe/csi300_20100104.csv", dtype=str)
    cal = price_series("sh000300").index
    cal = cal[(cal >= LO - pd.Timedelta(days=420)) & (cal <= HI)]
    R = {}
    for c, m in zip(u.code, u.market, strict=True):
        s = f"{m.lower()}{int(c):06d}"
        try:
            lp = price_series(s)
        except Exception:  # noqa: BLE001
            continue
        R[s] = lp.reindex(cal).diff()
    X = pd.DataFrame(R).to_numpy()
    ends = np.array([i for i in range(W, len(cal)) if cal[i] >= LO])[::STEP]
    return X, cal, ends


def indicators(X: np.ndarray, ends: np.ndarray) -> np.ndarray:
    out = np.full((len(ends), len(IND)), np.nan)
    for k, e in enumerate(ends):
        w = X[e - W + 1 : e + 1]
        ok = np.isfinite(w).sum(0) >= 200
        w = np.nan_to_num(w[:, ok])
        w = w[:, w.std(0) > 0]
        n = w.shape[1]
        if n < 30:
            continue
        C = np.corrcoef(w.T)
        ev = np.linalg.eigvalsh(C)[::-1]
        mkt = w.mean(1)
        f = np.abs(np.fft.rfft(mkt - mkt.mean())) ** 2
        fr = np.fft.rfftfreq(W)
        D = np.sqrt(np.clip(2 * (1 - C), 0, None)) + 1e-12
        np.fill_diagonal(D, 0)
        t = minimum_spanning_tree(D)
        out[k] = (ev[0] / n, ev[:5].sum() / n, mkt[-60:].var(), f[(fr > 0) & (fr <= 1 / 20)].sum() / f[fr > 0].sum(), t.sum() / (n - 1))
    return out


def _perm(args):
    seed, X, ends = args
    rng = np.random.default_rng(seed)
    T = X.shape[0]
    Z = np.column_stack([np.roll(X[:, j], int(rng.integers(MIN_SHIFT, T - MIN_SHIFT))) for j in range(X.shape[1])])
    return indicators(Z, ends)


def main() -> None:
    X, cal, ends = load()
    obs = indicators(X, ends)
    with Pool(int(os.environ.get("NPROC", "8"))) as p:
        null = np.stack(p.map(_perm, [(s, X, ends) for s in range(N_PERM)]))
    dates = cal[ends]
    df = pd.DataFrame(obs, columns=IND, index=dates)
    tops = event_dates("sh000300", "top")
    tops = tops[(tops >= LO) & (tops <= HI + pd.Timedelta(days=200))]
    tpos = cal.get_indexer(tops[tops <= cal[-1]])
    has_top = np.array([((tpos > e) & (tpos <= e + H)).any() for e in ends])
    rows, ts = [], {"date": dates, "top_within_120": has_top}
    for j, name in enumerate(IND):
        np_ = (null[:, :, j] < obs[None, :, j]).mean(0)
        own = df[name].expanding(52).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True).to_numpy()
        ts[name], ts[f"{name}_null_pct"], ts[f"{name}_own_pct"] = obs[:, j], np_, own
        for lab, pct in (("null_pct", np_), ("own_pct", own)):
            fin = np.isfinite(pct)
            hi = fin & (pct >= 0.95)
            rows.append(dict(indicator=name, ref=lab, n_asof=int(fin.sum()), share_ge95=float(hi[fin].mean()),
                             top_rate_ge95=float(has_top[hi].mean()) if hi.any() else np.nan, top_rate_all=float(has_top[np.isfinite(pct)].mean())))
    S = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(ts).to_csv(OUT / "weekly.csv", index=False)
    S.to_csv(OUT / "summary.csv", index=False)
    pd.set_option("display.width", 220)
    print(f"股票 {X.shape[1]} 只，as-of {len(ends)} 个，顶 {len(tpos)} 个（{', '.join(str(d.date()) for d in tops)}）")
    print(S.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
