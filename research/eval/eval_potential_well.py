"""价格势阱原型：冻结参数开发段检验。口径见 docs/prereg_potential_well.md（跑前提交，跑后不改）。

python -m research.eval.eval_potential_well  → reports/potential_well_dev/{summary.md, a_events.csv, b_trades.csv}
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..features.potential_well import build_potential_series
from ..labels.top import consensus_tops, epsilon_tops

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / "data" / "frozen" / "v20261024"
OUT = ROOT / "reports" / "potential_well_dev"
INDEXES = ("sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006")
DEV = (pd.Timestamp("2000-01-01"), pd.Timestamp("2018-12-31"))
H, MIN_DD, HIT_BAND, MIN_PRIOR = 120, 0.08, 0.02, 20
SEARCH, HOLD, FIXED_STOP = 120, 60, 0.08
N_PERM, SEED = 2000, 0
EX_A, EX_B = (2007, 2008, 2015), (2008, 2015)
ARMS = {  # arm: (entry condition column, stop rule)
    "R0": ("event", "none"),
    "S1": ("c_well", "none"),
    "S1f": ("c_well", "fixed"),
    "S2": ("c_well", "barrier"),
    "S3": ("c_well_mass", "none"),
    "S4": ("c_well_damp", "none"),
    "S5": ("c_full", "barrier"),
    "S6": ("c_full_mass", "barrier"),
}
INCREMENTS = (("S2", "S1f"), ("S3", "S1"), ("S4", "S1"), ("S5", "S1"), ("S5", "S4"), ("S6", "S5"))


def _pval_le(null: np.ndarray, obs: float) -> float:
    v = null[np.isfinite(null)]
    return float(np.mean(v <= obs)) if len(v) and np.isfinite(obs) else float("nan")


def load(sym: str) -> pd.DataFrame:
    d = pd.read_parquet(FROZEN / f"{sym}_qfq.parquet")
    d["date"] = pd.to_datetime(d["date"])
    d = d[d.date <= DEV[1]].sort_values("date").reset_index(drop=True)  # 2019 年以后的数据不读入
    return d


# ---------- 检验 A ----------
def events_a(sym: str, d: pd.DataFrame, snaps: dict) -> pd.DataFrame:
    lp = np.log(d.close.to_numpy(float))
    n = len(lp)
    ret = np.diff(lp, prepend=lp[0])
    sig = pd.Series(ret).rolling(60, min_periods=60).std().to_numpy() * np.sqrt(60)
    tops = np.asarray(consensus_tops(lp, epsilon_tops(lp), share=0.5), int)
    cand = []
    for i in tops:
        if i + H >= n or not np.isfinite(sig[i]):
            continue
        dd = float(lp[i] - lp[i + 1 : i + H + 1].min())
        if 1 - np.exp(-dd) >= MIN_DD:
            cand.append((i, dd, dd / sig[i]))
    rows = []
    for i, dd, _ in cand:
        date = d.date.iloc[i]
        if date < DEV[0] or date not in snaps:
            continue
        prior = np.array([z for j, _, z in cand if j + H < i])
        offs = np.array([lp[i] - w.center_log for w in snaps[date].wells_below(lp[i])])
        rows.append(dict(symbol=sym, date=date, year=date.year, dd=dd, sigma=sig[i], n_prior=len(prior), k=len(offs),
                         offs=offs, prior=prior))
    return pd.DataFrame(rows)


def test_a(ev: pd.DataFrame, rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    zero_share = float((ev.k == 0).mean())
    use = ev[(ev.k > 0) & (ev.n_prior >= MIN_PRIOR)].reset_index(drop=True).copy()
    d_well, d_b1 = [], []
    for r in use.itertuples():
        d_well.append(np.abs(r.offs - r.dd).min() / r.sigma)
        lv = np.quantile(r.prior, np.arange(1, r.k + 1) / (r.k + 1)) * r.sigma
        d_b1.append(np.abs(lv - r.dd).min() / r.sigma)
    use["d_well"], use["d_b1"] = d_well, d_b1
    use["hit_well"] = use.d_well * use.sigma <= HIT_BAND
    use["hit_b1"] = use.d_b1 * use.sigma <= HIT_BAND
    groups = {s: g.index.to_numpy() for s, g in use.groupby("symbol")}
    zoffs = [r.offs / r.sigma for r in use.itertuples()]
    ddz = (use.dd / use.sigma).to_numpy()
    ex = ~use.year.isin(EX_A).to_numpy()
    null, null_ex = np.full(N_PERM, np.nan), np.full(N_PERM, np.nan)
    for b in range(N_PERM):
        dist = np.full(len(use), np.nan)
        for idx in groups.values():
            if len(idx) < 2:
                continue
            pick = rng.integers(0, len(idx) - 1, len(idx))
            pick = idx[np.where(pick >= np.arange(len(idx)), pick + 1, pick)]  # 另一个顶部
            for a, o in zip(idx, pick, strict=True):
                dist[a] = np.abs(zoffs[o] - ddz[a]).min()
        null[b], null_ex[b] = np.nanmean(dist), np.nanmean(dist[ex])
    per = use.groupby("symbol").agg(n=("d_well", "size"), d_well=("d_well", "mean"), d_b1=("d_b1", "mean"),
                                    hit_well=("hit_well", "mean"), hit_b1=("hit_b1", "mean"))
    obs, obs_ex = float(use.d_well.mean()), float(use.d_well[ex].mean())
    res = dict(n_all=len(ev), zero_well_share=zero_share, n_used=len(use), d_well=obs, d_b1=float(use.d_b1.mean()),
               null_mean=float(np.nanmean(null)), p=_pval_le(null, obs),
               idx_beat_b1=int((per.d_well < per.d_b1).sum()), n_ex=int(ex.sum()), d_well_ex=obs_ex,
               d_b1_ex=float(use.d_b1[ex].mean()), null_mean_ex=float(np.nanmean(null_ex)),
               hit_well=float(use.hit_well.mean()), hit_b1=float(use.hit_b1.mean()))
    c1 = res["p"] <= 0.05
    c2 = res["idx_beat_b1"] >= 4
    c3 = obs_ex < res["null_mean_ex"] and obs_ex < res["d_b1_ex"]
    res.update(c1=bool(c1), c2=bool(c2), c3=bool(c3), sufficient=zero_share <= 0.5,
               passed=bool(c1 and c2 and c3 and zero_share <= 0.5))
    res["per_index"] = per
    return use.drop(columns=["offs", "prior"]), res


# ---------- 检验 B ----------
def day_returns(d: pd.DataFrame, f: pd.DataFrame) -> dict[str, np.ndarray]:
    """每个信号日 j 在三种止损规则下的收益（次日开盘买入；卖出日超出开发段则 NaN）。"""
    o, c = d.open.to_numpy(float), d.close.to_numpy(float)
    bar = f.nearest_barrier_below.to_numpy(float)
    n = len(c)
    out = {k: np.full(n, np.nan) for k in ("none", "fixed", "barrier")}
    for j in range(n - HOLD):
        entry = o[j + 1]
        if not np.isfinite(entry) or entry <= 0:
            continue
        final = c[j + HOLD] / entry - 1
        out["none"][j] = final
        for rule, px in (("fixed", entry * (1 - FIXED_STOP)), ("barrier", bar[j])):
            r = final
            if np.isfinite(px) and px < entry:
                hit = np.where(c[j + 1 : j + HOLD] < px)[0]  # 收盘破位 → 次日开盘卖出
                if len(hit):
                    r = o[j + 1 + hit[0] + 1] / entry - 1
            out[rule][j] = r
    return out


def events_b(d: pd.DataFrame) -> list[int]:
    c = d.close.to_numpy(float)
    ev, used = [], set()
    for t in range(119, len(c)):
        w = c[t - 119 : t + 1]
        pk = t - 119 + int(np.argmax(w))
        if 1 - c[t] / c[pk] >= MIN_DD and pk not in used:
            used.add(pk)
            ev.append(t)
    return ev


def trades_b(sym: str, d: pd.DataFrame, f: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    f = f.reset_index(drop=True)
    assert (f.date.to_numpy() == d.date.to_numpy()).all()
    n = len(d)
    mass = f.overhead_mass
    low_mass = (mass <= mass.expanding(min_periods=20).median()).fillna(False).to_numpy()
    well = f.in_well_capture.to_numpy(bool)
    cond = dict(c_well=well, c_well_mass=well & low_mass, c_well_damp=well & f.damping_ok.to_numpy(bool),
                c_full=f.reentry_signal.to_numpy(bool), c_full_mass=f.reentry_signal.to_numpy(bool) & low_mass)
    rets = day_returns(d, f)
    first_ok = int(np.argmax(mass.notna().to_numpy())) + 250
    rows, pools = [], {}
    for e in events_b(d):
        if d.date.iloc[e] < DEV[0] or e < first_ok:
            continue
        days = np.arange(e + 1, min(e + SEARCH, n - 1) + 1)
        days = days[np.isfinite(rets["none"][days])] if len(days) else days
        pools[(sym, e)] = days
        row = dict(symbol=sym, e=e, date=d.date.iloc[e], year=d.date.iloc[e].year)
        for arm, (col, rule) in ARMS.items():
            if col == "event":
                j = e if np.isfinite(rets[rule][e]) else -1
            else:
                ok = days[cond[col][days]] if len(days) else days
                j = int(ok[0]) if len(ok) else -1
            row[f"{arm}_j"] = j
            row[f"{arm}_ret"] = rets[rule][j] if j >= 0 else np.nan
            row[f"{arm}_wait"] = j - e if j >= 0 else np.nan
            row[f"{arm}_stopped"] = (rets[rule][j] != rets["none"][j]) if j >= 0 else np.nan
        rows.append(row)
    return pd.DataFrame(rows), dict(rets=rets, pools=pools)


def _p5(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    return float(np.quantile(x, 0.05)) if len(x) else float("nan")


def test_b(tr: pd.DataFrame, aux: dict, rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    syms = tr.symbol.to_numpy()
    ex = ~tr.year.isin(EX_B).to_numpy()
    arm_rows = []
    for arm, (_, rule) in ARMS.items():
        r = tr[f"{arm}_ret"].to_numpy(float)
        ent = np.isfinite(r)
        idx = np.where(ent)[0]
        rnd = np.full((N_PERM, len(idx)), np.nan)
        for q, i in enumerate(idx):
            s, e = syms[i], int(tr.e.iloc[i])
            if arm == "R0":
                pool = np.append(aux[s]["pools"][(s, e)], e)
            else:
                pool = aux[s]["pools"][(s, e)]
            rnd[:, q] = aux[s]["rets"][rule][rng.choice(pool, N_PERM)]
        rm = rnd.mean(axis=1)
        rp5 = np.quantile(rnd, 0.05, axis=1)
        mean, p5 = float(r[ent].mean()) if ent.any() else np.nan, _p5(r)
        n_idx = 0
        for s in INDEXES:
            m = syms[idx] == s
            if m.any() and r[idx][m].mean() > np.median(rnd[:, m].mean(axis=1)):
                n_idx += 1
        mex = ex[idx]
        mean_ex = float(r[idx][mex].mean()) if mex.any() else np.nan
        rnd_ex_med = float(np.median(rnd[:, mex].mean(axis=1))) if mex.any() else np.nan
        c = [mean > np.quantile(rm, 0.95), p5 >= np.median(rp5), ent.mean() >= 0.30, n_idx >= 4, mean_ex > rnd_ex_med]
        arm_rows.append(dict(arm=arm, n_events=len(tr), n_trades=int(ent.sum()), coverage=float(ent.mean()), mean=mean,
                             rnd_mean_med=float(np.median(rm)), rnd_mean_p95=float(np.quantile(rm, 0.95)), p5=p5,
                             rnd_p5_med=float(np.median(rp5)), idx_beat=n_idx, mean_ex=mean_ex, rnd_ex_med=rnd_ex_med,
                             mean_fill0=float(np.where(ent, r, 0.0).mean()),
                             stop_rate=float(np.nanmean(tr[f"{arm}_stopped"].astype(float))),
                             wait_med=float(np.nanmedian(tr[f"{arm}_wait"])) if ent.any() else np.nan,
                             c1=bool(c[0]), c2=bool(c[1]), c3=bool(c[2]), c4=bool(c[3]), c5=bool(c[4]), passed=bool(all(c))))
    arms = pd.DataFrame(arm_rows)
    blocks = pd.factorize(tr.symbol + "_" + tr.year.astype(str))[0]
    nb = blocks.max() + 1
    members = [np.where(blocks == b)[0] for b in range(nb)]
    inc_rows = []
    for a, base in INCREMENTS:
        ra, rb = tr[f"{a}_ret"].to_numpy(float), tr[f"{base}_ret"].to_numpy(float)
        diff, diff0 = np.full(N_PERM, np.nan), np.full(N_PERM, np.nan)
        for q in range(N_PERM):
            ii = np.concatenate([members[b] for b in rng.integers(0, nb, nb)])
            xa, xb = ra[ii], rb[ii]
            if np.isfinite(xa).any() and np.isfinite(xb).any():
                diff[q] = np.nanmean(xa) - np.nanmean(xb)
            diff0[q] = np.nan_to_num(xa).mean() - np.nan_to_num(xb).mean()
        lo, hi = np.nanquantile(diff, [0.025, 0.975])
        lo0, hi0 = np.nanquantile(diff0, [0.025, 0.975])
        inc_rows.append(dict(arm=a, base=base, diff=float(np.nanmean(ra) - np.nanmean(rb)), ci_lo=float(lo), ci_hi=float(hi),
                             passed=bool(lo > 0), diff_fill0=float(np.nan_to_num(ra).mean() - np.nan_to_num(rb).mean()),
                             ci_lo_fill0=float(lo0), ci_hi_fill0=float(hi0)))
    inc = pd.DataFrame(inc_rows)
    s5 = bool(arms.set_index("arm").loc["S5", "passed"])
    s5_inc = bool(inc[(inc.arm == "S5") & (inc.base == "S1")].passed.iloc[0])
    return arms, inc, dict(s5=s5, s5_inc=s5_inc, passed=s5 and s5_inc)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    ev_a, tr_b, aux = [], [], {}
    for sym in INDEXES:
        d = load(sym)
        f, snaps = build_potential_series(d, half_life=100)
        ev_a.append(events_a(sym, d, snaps))
        t, aux[sym] = trades_b(sym, d, f)
        tr_b.append(t)
        print(sym, len(d), "A events", len(ev_a[-1]), "B events", len(t), flush=True)
    use, ra = test_a(pd.concat(ev_a, ignore_index=True), rng)
    tr = pd.concat(tr_b, ignore_index=True)
    arms, inc, rb = test_b(tr, aux, rng)
    use.to_csv(OUT / "a_events.csv", index=False)
    tr.to_csv(OUT / "b_trades.csv", index=False)
    yn = lambda b: "通过" if b else "不通过"  # noqa: E731
    per = ra.pop("per_index")
    md = ["# 价格势阱原型：开发段检验结果（2000–2018，参数冻结）", "", "口径：`docs/prereg_potential_well.md`。", "",
          "## 检验 A：势阱价位对回撤低点的定位", "",
          f"- 事件 {ra['n_all']}，下方势阱数为 0 的占 {ra['zero_well_share']:.1%}，参加统计 {ra['n_used']}。",
          f"- 距离均值（σ 单位）：势阱 {ra['d_well']:.3f}，跨顶部调换零对照 {ra['null_mean']:.3f}（p={ra['p']:.3f}），同数量档位 {ra['d_b1']:.3f}。",
          f"- ±2% 命中率：势阱 {ra['hit_well']:.1%}，同数量档位 {ra['hit_b1']:.1%}。",
          f"- 条件 1（p ≤ 0.05）：{yn(ra['c1'])}；条件 2（≥4/6 指数优于档位，实际 {ra['idx_beat_b1']}/6）：{yn(ra['c2'])}；"
          f"条件 3（剔除 2007/2008/2015，n={ra['n_ex']}：势阱 {ra['d_well_ex']:.3f}，零对照 {ra['null_mean_ex']:.3f}，档位 {ra['d_b1_ex']:.3f}）：{yn(ra['c3'])}。",
          f"- 检验 A：**{yn(ra['passed'])}**", "", per.round(3).to_markdown(), "",
          "## 检验 B：反手做多增量消融", "", "主口径只统计已入场交易；`mean_fill0` 为“未入场记 0”副口径。多重比较未校正，S5 为主判据。", "",
          arms.round(4).to_markdown(index=False), "", "### 增量（指数×年份整块自助抽样 95% 区间）", "",
          inc.round(4).to_markdown(index=False), "",
          f"- S5 单组：{yn(rb['s5'])}；S5 对 S1 增量：{yn(rb['s5_inc'])}。", f"- 检验 B：**{yn(rb['passed'])}**", ""]
    (OUT / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
