"""C1：把 v2 开发段结果导出为产品契约 JSON（docs/product_contract.md），供 web/mock/top-panel.html 回放。
含"电影"数据：连续 as-of 日期的三尺度置信度与各尺度 t_c 分位（q20/q50/q80，换算为日历日）。
用法：LPPLS_BOX=v2 python -m research.eval.export_contract sh000001 2015-06-12 [movie_from movie_to]"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ..features.lppls_rules import SCALE_EVIDENCE, SCALES_FCO, _derived, rules
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


def _bubble(q: pd.DataFrame, date: pd.Timestamp, cal: pd.DatetimeIndex, ohlc: pd.DataFrame) -> dict:
    """原版口径的泡沫大小/持续时间（描述性，不预测）：取 as-of 日通过 box 过滤的最长窗口 n_max，
    大小 = P(as-of)/P(窗口起点) − 1，持续时间 = n_max 个交易日；另给合格窗口数与各合格窗口大小的中位数。"""
    if not len(q):
        return {"size": None, "duration_days": None, "start": None, "n_qualified": 0, "evidence": "descriptive"}
    close = ohlc["close"] if isinstance(ohlc.index, pd.DatetimeIndex) else ohlc.set_index("date")["close"]
    close = close.reindex(cal).ffill()
    i0 = cal.get_indexer([date])[0]
    p0 = float(close.iloc[i0])

    def size(n: int) -> float:
        return p0 / float(close.iloc[max(i0 - int(n) + 1, 0)]) - 1

    nmax = int(q.n.max())
    return {"size": round(size(nmax), 3), "duration_days": nmax, "start": str(cal[max(i0 - nmax + 1, 0)].date()),
            "size_median": round(float(np.median([size(n) for n in q.n])), 3), "n_qualified": int(len(q)),
            "rule": "FCO 口径：最长合格窗口起点至 as-of 的涨幅与交易日数", "evidence": "descriptive"}


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
    bubble = _bubble(q, date, cal, ohlc)
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
            "window": window,
            "lppls_confidence": {**_conf(d, r, date), "evidence": "dev", "scale_evidence": SCALE_EVIDENCE,
                                 "scale_note": "§17.14：FCO 六档重聚合后仅 6–12 月、12–24 月有开发段稳健信号；1–3 月 0 稳健组合，仅描述性显示；2–6 年档未扫、不显示",
                                 "notes": ["6–12 月、12–24 月档报警精度集中于 2001/2007/2015 泡沫年；非高估年份≈随机（by_year.md、scale_sens_dev/summary.md）"]},
            "scenarios": [
                {"share": round(float(x.share), 2), "dt_range": [int(x.dt_min), int(x.dt_max)],
                 "ahead_mean": round(float(x.ahead_mean), 1), "ahead_sd": round(float(x.ahead_std), 1),
                 "q20": round(float(x.q20), 1), "q80": round(float(x.q80), 1),
                 "q20_date": _to_cal(cal, date, x.q20), "q80_date": _to_cal(cal, date, x.q80)}
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
        "bottom": {"state_p": {"value": None, "evidence": "dev_pending"}, "thrust_p": {"value": None, "evidence": "dev_pending"},
                   "entry_rule": {"value": None, "evidence": "none"}},
        "validation": [
            {"split": "开发段 2000–2018（6 指数）", "events": 74, "hit": 0.50, "false_alarm": 0.70, "brier": "ΔBrier −0.0053 [−0.0116, 0.0000]", "status": "dev",
             "note": "长尺度 box 置信度≥5%：顶被提前报警比例 0.50；报警日 120 日内未见顶比例 0.70（精度 0.30，集中于 2007/2015）"},
            {"split": "校准段 2019–2021（7 指数，开发段模型前推）", "events": 12, "hit": None, "status": "fail_i",
             "brier": "p20(R2) ΔBrier +0.00077 [−0.0013, +0.0030]；底部 B1/B2/B3 +0.0012～+0.0014，区间含 0",
             "note": "判据(i)未通过：概率模型不优于历史基率；留出任一指数/年份不翻转。判据(ii) LPPLS 置信度 A1/A2 待校准段扫描完成"},
            {"split": "最终测试 2022–2025.08", "events": None, "hit": None, "status": "pending_test"},
        ],
        "evidence_levels": {"dev": "开发段 2000–2018", "cal": "校准段未运行", "test": "最终测试未运行", "none": "无证据，仅描述",
                            "rule": "执行规则", "dev_failed": "开发段模型，校准段未通过", "descriptive_bubble": "原版口径描述量", "dev_pending": "开发段评估进行中", "descriptive": "描述已完成月份，非预测"},
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
