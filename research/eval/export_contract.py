"""C1：把 v2 开发段结果导出为产品契约 JSON（docs/product_contract.md），供 web/mock/top-panel.html 回放。
含"电影"数据：连续 as-of 日期的三尺度置信度与各尺度 t_c 分位（q20/q50/q80，换算为日历日）。
用法：LPPLS_BOX=v2 python -m research.eval.export_contract sh000001 2015-06-12 [movie_from movie_to]"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ..features.lppls_rules import (
    SCALE_EVIDENCE,
    SCALES_FCO,
    _derived,
    grid_rules,
    lagrange_pick,
    rules,
)
from ..features.regime_bands import regime_bands
from ..lppls.scenarios import scale_windows, scenarios
from .dataset import price_series
from .original_standard import SCAN, load

OOF_P20 = Path("data/oof/ladder_dev_full_v2_R4_i_box_ms_C1.0.parquet")
FROZEN = Path("data/frozen/v20261024")


def _conf(d: pd.DataFrame, r: pd.DataFrame, date: pd.Timestamp) -> dict:
    out = {}
    for sc, (lo, hi) in SCALES_FCO.items():
        m = (d.date == date) & d.n.between(lo, hi)
        out[sc] = round(float(r.box[m].mean()), 3) if m.any() else None
    return out


def _to_cal(cal: pd.DatetimeIndex, date: pd.Timestamp, ahead: float) -> str:
    i = cal.get_indexer([date])[0]
    j = int(np.clip(round(i + ahead), 0, len(cal) - 1))
    return str(cal[j].date())


def record(sym: str, asof: str) -> dict:
    """开发段回放：从 v2 扫描 parquet 取 as-of 日拟合与 CPCV OOF p20。"""
    sc, _ = load(sym)
    d = _derived(sc)
    r = rules(d)
    cal = price_series(sym).index
    date = pd.Timestamp(asof)
    p20 = None
    if OOF_P20.exists():
        o = pd.read_parquet(OOF_P20)
        o = o[(o.symbol == sym) & (o.date == date)]
        p20 = round(float(o.p.iloc[0]), 3) if len(o) else None
    return build_record(sym, asof, d, r, cal, pd.read_parquet(FROZEN / f"{sym}_qfq.parquet"), p20)


FCO_SETS = {"standard": "g_fco_standard", "early": "g_fco_early", "end": "g_fco_end", "pure": "g_fco_pure"}
NEG_SCAN = Path("data/features/lppls_v2_neg_lite")


def _close(ohlc: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.Series:
    c = ohlc["close"] if isinstance(ohlc.index, pd.DatetimeIndex) else ohlc.set_index("date")["close"]
    return c.reindex(cal).ffill()


def _fit_params(row: pd.Series, gg: pd.DataFrame, cal: pd.DatetimeIndex, date: pd.Timestamp) -> dict:
    """FCO Scenario/F11 字段：t1、t2、tc、m、ω、D、振荡、loss、属于哪些过滤集。"""
    i0 = cal.get_indexer([date])[0]
    return {"t1": str(cal[max(i0 - int(row.n) + 1, 0)].date()), "t2": str(date.date()), "tc": _to_cal(cal, date, float(row.ahead)),
            "m": round(float(row.m), 3), "omega": round(float(row.w), 2), "damping": round(float(row.D), 2),
            "oscillations_half": round(float(row.osc), 2), "oscillations_cycles": round(float(row.n_osc), 2),
            "loss": round(float(row.sse / max(int(row.n) - 7, 1)), 6),
            "sets": [k for k, c in FCO_SETS.items() if bool(gg.loc[row.name, c])]}


def _indicators(dd: pd.DataFrame, rr: pd.DataFrame, gg: pd.DataFrame, cal: pd.DatetimeIndex, date: pd.Timestamp) -> dict:
    """每尺度：各过滤集置信度（合格窗口比例，E1/E4 定义）、最佳起点 t1（Lagrange 正则选窗）及其是否合格、signal_status。"""
    out = {}
    for sc, (lo, hi) in SCALES_FCO.items():
        m = dd.n.between(lo, hi)
        if not m.any():
            out[sc] = {"signal_status": "not_computed", "direction": "positive"}
            continue
        sub = dd[m]
        pick = lagrange_pick(sub)
        i = pick.iloc[0] if len(pick) else None
        conf = {"box": round(float(rr.box[m].mean()), 3), **{k: round(float(gg[c][m].mean()), 3) for k, c in FCO_SETS.items()}}
        nq = int(gg["g_fco_standard"][m].sum())
        out[sc] = {"direction": "positive", "n_windows": int(m.sum()), "confidence": conf, "n_qualified_standard": nq,
                   "best_t1": str(cal[max(cal.get_indexer([date])[0] - int(sub.loc[i].n) + 1, 0)].date()) if i is not None else None,
                   "t1_qualified": bool(gg.loc[i, "g_fco_standard"]) if i is not None else None,
                   "signal_status": "signal" if nq > 0 else "no_qualified_fit"}
    return out


def _tc_distribution(dd: pd.DataFrame, gg: pd.DataFrame, cal: pd.DatetimeIndex, date: pd.Timestamp) -> dict:
    """F09：合格（STANDARD）拟合的 t_c 数量分布，按尺度，5 交易日分箱；n 与直方图合计一致。"""
    out = {}
    for sc, (lo, hi) in SCALES_FCO.items():
        f = dd[dd.n.between(lo, hi) & gg["g_fco_standard"]]
        if not len(f):
            out[sc] = {"n": 0, "bins": []}
            continue
        a = f.ahead.to_numpy(float)
        edges = np.arange(np.floor(a.min() / 5) * 5, np.ceil(a.max() / 5) * 5 + 5.1, 5.0)
        h, e = np.histogram(a, bins=edges)
        out[sc] = {"n": int(len(a)), "bin_days": 5,
                   "bins": [[_to_cal(cal, date, float(e[k])), _to_cal(cal, date, float(e[k + 1])), int(h[k])] for k in range(len(h)) if h[k] > 0]}
    return out


def _combo(ind: dict, set_name: str = "standard") -> dict:
    """FCO Combo(p)：跨尺度置信度幂平均（p=0.1≈几何、1 算术、10 趋向最大）。展示口径，开发段无报警证据（§17.14）。"""
    c = np.array([v["confidence"][set_name] for v in ind.values() if "confidence" in v], float)
    if not len(c):
        return {"evidence": "none"}
    out = {}
    for p_ in (0.1, 1.0, 10.0):
        out[f"p{p_:g}"] = round(float(np.mean(np.maximum(c, 1e-9) ** p_) ** (1 / p_)), 3)
    return {**out, "set": set_name, "scales": [k for k, v in ind.items() if "confidence" in v], "evidence": "none",
            "note": "原版默认 p=0.1；开发段 Combo 作为报警器无稳健证据，仅展示"}


def _negative(sym: str, date: pd.Timestamp, cal: pd.DatetimeIndex, logp: pd.Series) -> dict:
    """负泡沫置信度（对 −ln P 拟合，Yan 2010）；开发段 0/424 稳健 → 只展示、标无证据。"""
    p = NEG_SCAN / f"{sym}.parquet"
    if not p.exists():
        return {"evidence": "none", "signal_status": "not_computed"}
    sc = pd.read_parquet(p)
    sc = sc[sc.date == date]
    if not len(sc):
        return {"evidence": "none", "signal_status": "not_computed"}
    pos = cal.get_indexer([date])[0]
    lp = logp.to_numpy()
    sc = sc.assign(y_std=[lp[pos + 1 - n : pos + 1].std() for n in sc.n])
    dn = _derived(sc)
    gn = pd.DataFrame(grid_rules(dn))
    gn.index = dn.index
    out = {}
    for s_, (lo, hi) in SCALES_FCO.items():
        m = dn.n.between(lo, hi)
        out[s_] = round(float(gn["g_fco_standard"][m].mean()), 3) if m.any() else None
    return {"direction": "negative", "confidence_standard": out, "n_windows": int(len(dn)), "evidence": "none",
            "note": "开发段负泡沫 0/424 组合稳健、A1≈随机（§17.12）；仅作镜像展示"}


def _bubble(dd: pd.DataFrame, gg: pd.DataFrame, date: pd.Timestamp, cal: pd.DatetimeIndex, ohlc: pd.DataFrame) -> dict:
    """FCO 口径泡沫大小/持续时间（描述性）：起点 t1 = Lagrange 正则选窗（Demos–Sornette 2019，FCO 方法附录同）；
    size_model = P̂(t_c)/P(t1) − 1 = exp(A)/P(t1) − 1（FAQ："从泡沫起点到 t_c 处模型预测价格的轨迹幅度"）；
    size_realized = P(as-of)/P(t1) − 1（补充，非原版字段）；duration = t1 → as-of 交易日数；scale = 选中窗口所属尺度。
    bubbleProgress 公式未公开，置 null。"""
    if not len(dd):
        return {"size_model": None, "size_realized": None, "duration_days": None, "start": None, "evidence": "descriptive",
                "signal_status": "not_computed"}
    close = _close(ohlc, cal)
    i0 = cal.get_indexer([date])[0]
    pick = lagrange_pick(dd)
    row = dd.loc[pick.iloc[0]]
    n = int(row.n)
    p1 = float(close.iloc[max(i0 - n + 1, 0)])
    scale = next((k for k, (lo, hi) in SCALES_FCO.items() if lo <= n <= hi), "other")
    qualified = bool(gg.loc[row.name, "g_fco_standard"])
    longest = [k for k, (lo, hi) in SCALES_FCO.items() if (dd.n.between(lo, hi) & gg["g_fco_standard"]).any()]
    return {"start": str(cal[max(i0 - n + 1, 0)].date()), "duration_days": n, "scale": scale, "t1_qualified_standard": qualified,
            "size_model": round(float(np.exp(row.A) / p1 - 1), 3), "size_realized": round(float(close.iloc[i0]) / p1 - 1, 3),
            "tc": _to_cal(cal, date, float(row.ahead)), "progress": None, "longest_qualified_scale": longest[-1] if longest else None,
            "rule": "FCO：Lagrange 起点 t1；大小=模型 t_c 价格/P(t1)−1；持续=t1→as-of；progress 公式未公开",
            "evidence": "descriptive", "signal_status": "signal" if qualified else "t1_not_qualified"}


def build_record(sym: str, asof: str, d: pd.DataFrame, r: pd.DataFrame, cal: pd.DatetimeIndex, ohlc: pd.DataFrame,
                 p20: float | None = None, data_version: str = "frozen_v20261024") -> dict:
    """由 as-of 日的（已 _derived 的）拟合表 d、规则表 r、交易日历 cal、OHLC 日线构造契约记录；日更流水线与回放共用。"""
    date = pd.Timestamp(asof)
    q = d[(d.date == date) & r.box]
    scen = scenarios(q[["n", "ahead"]]) if len(q) else pd.DataFrame()
    sw = scale_windows(q[["n", "ahead"]], SCALES_FCO) if len(q) else pd.DataFrame()
    rb = regime_bands(ohlc)
    prev_month = (date - pd.offsets.MonthBegin(1) - pd.Timedelta(days=1)).strftime("%Y-%m")
    band = rb.loc[prev_month] if prev_month in rb.index else None
    names = {"sh000001": "上证指数", "sh000016": "上证50", "sh000300": "沪深300", "sh000905": "中证500", "sz399001": "深证成指", "sz399006": "创业板指"}
    dd = d[d.date == date]
    rr = r.loc[dd.index]
    gg = grid_rules(dd)
    ind = _indicators(dd, rr, gg, cal, date)
    bubble = _bubble(dd, gg, date, cal, ohlc)
    w612 = sw[sw.scale == "6-12m"] if len(sw) else pd.DataFrame()
    window = ({"start": _to_cal(cal, date, float(w612.q20.iloc[0])), "end": _to_cal(cal, date, float(w612.q80.iloc[0])),
               "rule": "6–12 月档合格拟合 t_c 的 20–80% 分位窗（情景，非时点；开发段覆盖率低）", "evidence": "dev"}
              if len(w612) else {"start": None, "end": None, "rule": "6–12 月档无合格拟合", "evidence": "dev"})
    rec = {
        "symbol": sym, "name": names.get(sym, sym), "asof": asof, "data_version": data_version, "model_version": "prereg_v1.7_v2",
        "top": {
            "p20": {"value": None, "evidence": "dev_failed",
                    "notes": ["冻结 p20=R2（GSADF）；校准段 2019–2021 前推 ΔBrier +0.00077 [−0.0013, +0.0030]，判据(i)未通过，不显示概率",
                              f"研究层 OOF（仅开发段回放）：{p20}" if p20 is not None else "日更无 p20"]},
            "bubble": bubble,
            "indicators": {**ind, "rule_note": "置信度=该尺度窗口中通过过滤集的比例（E1/E4 定义）；box=本项目纯形态框（无阻尼/振荡条件），"
                           "standard/early/end/pure=FCO 公开四套；振荡数按 (ω/2)·ln[(t_c−t₁)/(t_c−t₂)]≥2.5（E7 写法，≈0.8 周期），"
                           "FCO 'oscillations≥2.5' 的口径未公开核验"},
            "combo": _combo(ind),
            "tc_distribution": _tc_distribution(dd, gg, cal, date),
            "negative_bubble": _negative(sym, date, cal, np.log(_close(ohlc, cal))),
            "signal_status": "signal" if any(v.get("signal_status") == "signal" for v in ind.values()) else "no_qualified_fit",
            "window": window,
            "lppls_confidence": {**_conf(d, r, date), "evidence": "cal_fragile", "scale_evidence": SCALE_EVIDENCE,
                                 "scale_note": "§17.14：FCO 六档重聚合后仅 6–12 月、12–24 月有开发段稳健信号；1–3 月 0 稳健组合，仅描述性显示；2–6 年档未扫、不显示",
                                 "notes": ["6–12 月、12–24 月档报警精度集中于 2001/2007/2015 泡沫年；非高估年份≈随机（by_year.md、scale_sens_dev/summary.md）"]},
            "scenarios": [
                {"share": round(float(x.share), 2), "dt_range": [int(x.dt_min), int(x.dt_max)],
                 "ahead_mean": round(float(x.ahead_mean), 1), "ahead_sd": round(float(x.ahead_std), 1),
                 "q20": round(float(x.q20), 1), "q80": round(float(x.q80), 1),
                 "q20_date": _to_cal(cal, date, x.q20), "q80_date": _to_cal(cal, date, x.q80),
                 "q025_date": _to_cal(cal, date, x.q025), "q975_date": _to_cal(cal, date, x.q975), "tc_mode_date": _to_cal(cal, date, x.tc_mode),
                 "representative": _fit_params(q.loc[x.rep_idx], gg, cal, date)}
                for x in scen.itertuples()
            ],
            "scenarios_note": "簇间不平均；簇占比<5% 不列；t_c 分位窗开发段覆盖率 1–4%，不作为峰值日预测",
            "scale_windows": [
                {"scale": x.scale, "q20_date": _to_cal(cal, date, x.q20), "q80_date": _to_cal(cal, date, x.q80), "n": int(x.n)}
                for x in sw.itertuples()
            ],
            "invalidation": {"rule": "6–12 月与 12–24 月档置信度均<5%（连续 2 个 as-of）", "evidence": "rule"},
            "drawdown_price": {"value": None, "descriptive": [-0.18, -0.35], "evidence": "none"},
            "drawdown_time": {"value": None, "evidence": "none"},
            "second_wave": {"value": None, "evidence": "none"},
        },
        "regime_band": ({"month": prev_month, "state": band.state, "channel": band.channel,
                         "rule": "FCO 公开定义：相对自身前 60 个月分位", "evidence": "descriptive"}
                        if band is not None and isinstance(band.state, str) else {"month": prev_month, "state": None, "evidence": "descriptive"}),
        "bottom": {"state_p": {"value": None, "evidence": "fail_i",
                               "note": "底部概率链 B1/B2/B3：校准段 ΔBrier +0.0012～+0.0014、测试段 +0.0035～+0.0047，区间含/高于 0，判据(i)三段未通过；不显示概率"},
                   "thrust_p": {"value": None, "evidence": "fail_i", "note": "同上；负泡沫/反泡沫 LPPLS 在开发段亦无预测信息"},
                   "entry_rule": {"value": None, "evidence": "none", "note": "不预测起涨时间；仅参考上月体制带（描述性）与价格自高点回撤"}},
        "validation": [
            {"split": "开发段 2000–2018（6 指数）", "events": 74, "hit": 0.50, "false_alarm": 0.70, "brier": "ΔBrier −0.0053 [−0.0116, 0.0000]", "status": "dev",
             "note": "长尺度 box 置信度≥5%：顶被提前报警比例 0.50；报警日 120 日内未见顶比例 0.70（精度 0.30，集中于 2007/2015）"},
            {"split": "校准段 2019–2021（7 指数，开发段模型前推）", "events": 12, "hit": None, "status": "fail_i",
             "brier": "p20(R2) ΔBrier +0.00077 [−0.0013, +0.0030]；底部 B1/B2/B3 +0.0012～+0.0014，区间含 0",
             "note": "判据(i)未通过：概率模型不优于历史基率；留出任一指数/年份不翻转。判据(ii)：仅 box 6–12 月 H=120 名义通过（4/7 指数 A1 显著且 A2≥0.5，"
                     "A1 中位 0.47 vs 随机 0.23），Holm 后 3/7、留出任一指数后 3/6 → 判据(iii)不满足；FCO END/STANDARD 全部不过。LPPLS 置信度证据等级 cal_fragile"},
            {"split": "最终测试 2022–2025.08", "events": None, "hit": None, "status": "pending_test"},
        ],
        "evidence_levels": {"dev": "开发段 2000–2018", "cal": "校准段未运行", "test": "最终测试未运行", "none": "无证据，仅描述",
                            "rule": "执行规则", "dev_failed": "开发段模型，校准段未通过", "fail_i": "判据(i)校准段与测试段均未通过，不显示概率", "cal_fragile": "校准段部分通过（4/7 指数），留出/多重比较后不满足，不升级", "descriptive_bubble": "原版口径描述量", "dev_pending": "开发段评估进行中", "descriptive": "描述已完成月份，非预测"},
    }
    return rec


def movie(sym: str, a: str, b: str) -> list[dict]:
    sc, _ = load(sym)
    d = _derived(sc)
    r = rules(d)
    cal = price_series(sym).index
    frames = []
    for date in sorted(x for x in d.date.unique() if pd.Timestamp(a) <= x <= pd.Timestamp(b)):
        q = d[(d.date == date) & r.box]
        sw = scale_windows(q[["n", "ahead"]], SCALES_FCO) if len(q) else pd.DataFrame()
        frames.append({"asof": str(pd.Timestamp(date).date()), "confidence": _conf(d, r, date),
                       "tc_windows": {x.scale: [_to_cal(cal, date, x.q20), _to_cal(cal, date, x.q50), _to_cal(cal, date, x.q80)] for x in sw.itertuples()}})
    return frames


if __name__ == "__main__":
    sym, asof = sys.argv[1], sys.argv[2]
    out = Path("web/mock/data")
    out.mkdir(parents=True, exist_ok=True)
    rec = record(sym, asof)
    if len(sys.argv) > 4:
        rec["movie"] = movie(sym, sys.argv[3], sys.argv[4])
    (out / f"{sym}_{asof}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({k: v for k, v in rec.items() if k != "movie"}, ensure_ascii=False, default=str)[:1500])
    print("movie frames", len(rec.get("movie", [])), "scan", SCAN)
