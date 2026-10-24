"""D-BOT 决策层回测（prereg §15.1）：底部状态概率 p1（阶段一 OOF）+ 起涨确认概率 p2（阶段二 OOF，宽度）。
规则（阈值固定为各自开发段正标签率，不调参）：
  state_full   p1 ≥ τ1 → 满仓；confirm_full  p2 ≥ τ2 → 满仓；
  two_stage    p1 ≥ τ1 → 1/3 仓，p2 ≥ τ2 → 满仓，20 日内未确认 → 退出。
退出：目标/止损 = 标签的 PIT 障碍（d_up = max(10%, 5 年 Q90)，止损 = −0.5·d_up，按最近一个候选底的值前向填充）、时间 60 日。基线：随机进场（频率匹配 two_stage）、波动率目标（在 state 窗口内）。
主评分：单位资金·天的费后收益（年化）与 20 日内触及目标比例；并报横盘率、假底率。T+1、佣金/印花税/滑点同 D-TOP。
python -m research.eval.decision_bottom"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..labels.run_bottom import OUT as LABELS
from .dataset import price_series
from .decision import COMM, SLIP, STAMP
from .ladder import OOF_DIR

P1 = OOF_DIR / "ladder_bottom_dev_B3_omori25_C0.1.parquet"
P2 = OOF_DIR / "thrust_stage2_breadth_C1.0.parquet"
TARGET, STOP, MAXD, CONFIRM_D, VOL_TARGET, N_PLACEBO = 0.10, -0.05, 60, 20, 0.20, 50


def episodes(lp: np.ndarray, dates: pd.DatetimeIndex, entry: np.ndarray, size: np.ndarray, upgrade: np.ndarray | None,
             confirm_exit: bool, d_up: np.ndarray | None = None, model_exit: np.ndarray | None = None) -> list[dict]:
    """entry: 入场信号(bool, 在 t 收盘判定, t+1 成交)；size: 初始仓位；upgrade: 加仓到满仓的信号；返回逐笔记录。"""
    n, out, t = len(lp), [], 0
    while t < n - 2:
        if not entry[t]:
            t += 1
            continue
        e = t + 1  # T+1 成交
        target = float(d_up[t]) if d_up is not None and np.isfinite(d_up[t]) else TARGET
        stop = -0.5 * target
        pos, cost = float(size[t]), (COMM + SLIP) * float(size[t])
        confirmed = upgrade is None
        capdays, k, outcome = 0.0, e, "time"
        while k < min(e + MAXD, n - 1):
            capdays += pos
            if upgrade is not None and not confirmed and upgrade[k] and pos < 1:
                cost += (COMM + SLIP) * (1 - pos)
                pos, confirmed = 1.0, True
            if upgrade is not None and not confirmed and confirm_exit and k - e >= CONFIRM_D:
                outcome = "no_confirm"
                break
            if model_exit is not None and k - e >= 10 and model_exit[k]:
                outcome = "model_exit"
                break
            ret = np.exp(lp[k + 1] - lp[e]) - 1
            if ret >= target:
                outcome, k = "target", k + 1
                break
            if ret <= stop:
                outcome, k = "stop", k + 1
                break
            k += 1
        k = min(k, n - 1)
        gross = pos * (np.exp(lp[k] - lp[e]) - 1)
        cost += (COMM + STAMP + SLIP) * pos
        out.append(dict(entry_date=dates[e], days=k - e, capdays=max(capdays, 1e-9), ret=gross - cost, outcome=outcome,
                        hit20=float(outcome == "target" and k - e <= 20), pos_init=float(size[t])))
        t = k + 1
    return out


def run(tag: str = "dbot_dev"):
    o1 = pd.read_parquet(P1)
    p1 = o1.groupby(["date", "symbol"]).p.mean().rename("p1").reset_index()
    tau1 = float(o1.y.mean())
    o2 = pd.read_parquet(P2)
    p2 = o2.groupby(["date", "symbol"]).p.mean().rename("p2").reset_index()
    tau2 = float(o2.y.mean())
    df = p1.merge(p2, on=["date", "symbol"], how="left")
    df["p2"] = df.p2.fillna(0.0)
    cal = price_series("sh000001").index
    rng = np.random.default_rng(0)
    recs: dict[str, list] = {k: [] for k in ("state_full", "confirm_full", "two_stage", "two_stage_exit", "vol_target", "placebo")}
    for sym, g in df.groupby("symbol"):
        logp = price_series(sym)
        g = g.set_index("date").reindex(logp.index)
        lp, dates = logp.to_numpy(), logp.index
        d_up = pd.read_parquet(LABELS / f"{sym}.parquet")["main__d_up"].reindex(logp.index).ffill().to_numpy()
        s1 = (g.p1 >= tau1).fillna(False).to_numpy()
        s2 = (g.p2 >= tau2).fillna(False).to_numpy()
        ones = np.ones(len(lp))
        recs["state_full"] += [dict(symbol=sym, **r) for r in episodes(lp, dates, s1, ones, None, False, d_up)]
        recs["confirm_full"] += [dict(symbol=sym, **r) for r in episodes(lp, dates, s2, ones, None, False, d_up)]
        two = episodes(lp, dates, s1, np.full(len(lp), 1 / 3), s2, True, d_up)
        recs["two_stage"] += [dict(symbol=sym, **r) for r in two]
        low10 = pd.Series(~s2).rolling(10).sum().fillna(0).to_numpy() >= 10  # p2 连续 10 日 < τ2（§15.2 模型退出）
        recs["two_stage_exit"] += [dict(symbol=sym, **r) for r in episodes(lp, dates, s1, np.full(len(lp), 1 / 3), s2, True, d_up, low10)]
        rv20 = pd.Series(np.diff(lp, prepend=lp[0])).rolling(20).std().to_numpy() * np.sqrt(250)
        vt = np.clip(VOL_TARGET / np.where(np.isnan(rv20) | (rv20 == 0), VOL_TARGET, rv20), 0, 1)
        recs["vol_target"] += [dict(symbol=sym, **r) for r in episodes(lp, dates, s1, vt, None, False, d_up)]
        n_ep = len(two)
        if n_ep:
            for _ in range(max(1, N_PLACEBO // 10)):
                idx = rng.choice(np.arange(250, len(lp) - 2), n_ep, replace=False)
                ent = np.zeros(len(lp), bool)
                ent[idx] = True
                recs["placebo"] += [dict(symbol=sym, **r) for r in episodes(lp, dates, ent, np.full(len(lp), 1 / 3), None, False, d_up)]
    rows = []
    ep = {k: pd.DataFrame(v) for k, v in recs.items()}
    for name, e in ep.items():
        if e.empty:
            continue
        rows.append(dict(strategy=name, episodes=len(e), ret_per_capday_ann=float(e.ret.sum() / e.capdays.sum() * 250),
                         hit20=float(e.hit20.mean()), target=float((e.outcome == "target").mean()), stop=float((e.outcome == "stop").mean()),
                         flat=float(e.outcome.isin(["time", "no_confirm", "model_exit"]).mean()), mean_days=float(e.days.mean()),
                         mean_ret=float(e.ret.mean())))
    tab = pd.DataFrame(rows).set_index("strategy")
    # 区间：各策略按入场日做 80 日块 bootstrap（独立重抽样），差值区间由两组抽样差得到
    def boot(e: pd.DataFrame, B: int = 500):
        yrs = pd.Series(np.searchsorted(cal, e.entry_date.to_numpy()) // 80)
        blocks = yrs.unique()
        r = e.ret.to_numpy() / e.capdays.to_numpy() * 250
        h = e.hit20.to_numpy()
        g = {b: np.where(yrs.to_numpy() == b)[0] for b in blocks}
        out_r, out_h = [], []
        for _ in range(B):
            idx = np.concatenate([g[b] for b in rng.choice(blocks, len(blocks))])
            out_r.append(r[idx].mean())
            out_h.append(h[idx].mean())
        return np.array(out_r), np.array(out_h)

    draws = {k: boot(e) for k, e in ep.items() if len(e) >= 30}
    ci_rows = []
    for name in ("state_full", "confirm_full", "two_stage", "two_stage_exit"):
        for base in ("vol_target", "placebo"):
            if name not in draws or base not in draws:
                continue
            dr = draws[name][0] - draws[base][0]
            dh = draws[name][1] - draws[base][1]
            ci_rows.append(dict(strategy=name, vs=base, d_ret_per_capday=float(dr.mean()), lo=float(np.quantile(dr, 0.05)), hi=float(np.quantile(dr, 0.95)),
                                d_hit20=float(dh.mean()), hit_lo=float(np.quantile(dh, 0.05)), hit_hi=float(np.quantile(dh, 0.95))))
            ci_rows[-1]["kept"] = (ci_rows[-1]["lo"] > 0) & (ci_rows[-1]["hit_lo"] > 0)
    ci = pd.DataFrame(ci_rows)
    tab.to_csv(f"reports/{tag}.csv")
    ci.to_csv(f"reports/{tag}_ci.csv", index=False)
    pd.concat(ep, names=["strategy"]).reset_index(level=0).to_csv(f"reports/{tag}_episodes.csv", index=False)
    with open(f"reports/{tag}.md", "w") as f:
        f.write("# D-BOT 底部决策层回测（prereg §15.1；开发段 OOF 概率，不是样本外）\n\n")
        f.write(f"τ1（底部状态）= {tau1:.4f}，τ2（起涨确认，宽度）= {tau2:.4f}，均为开发段正标签率，不调参。目标 = PIT 障碍 d_up（≥10%）/ 止损 = −0.5·d_up / 60 日；two_stage 20 日未确认退出；two_stage_exit 另加 §15.2 模型退出（p2 连续 10 日 < τ2）。"
                "成本：佣金 0.025%、印花税 0.1%（卖出）、滑点 0.1%，T+1。\n\n## 主表\n\n")
        f.write(tab.round(4).to_markdown() + "\n\nret_per_capday_ann = 费后收益 / 资金·天 × 250；hit20 = 20 日内触及目标比例；flat = 到期/未确认退出（横盘）比例；stop = 假底比例。\n\n")
        f.write("## 相对基线（80 日块独立 bootstrap 90% 区间；kept 需收益与 hit20 两项下界均 > 0）\n\n" + ci.round(4).to_markdown(index=False) + "\n")
    print(tab.round(4).to_string())
    print(ci.round(4).to_string())
    return tab, ci


if __name__ == "__main__":
    run()
