"""C1：把 v2 开发段结果导出为产品契约 JSON（docs/product_contract.md），供 web/mock/top-panel.html 回放。
含"电影"数据：连续 as-of 日期的三尺度置信度与各尺度 t_c 分位（q20/q50/q80，换算为日历日）。
用法：LPPLS_BOX=v2 python -m research.eval.export_contract sh000001 2015-06-12 [movie_from movie_to]"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ..features.lppls_rules import SCALES, _derived, rules
from ..features.regime_bands import regime_bands
from ..lppls.scenarios import scale_windows, scenarios
from .dataset import price_series
from .original_standard import SCAN, load

OOF_P20 = Path("data/oof/ladder_dev_full_v2_R4_i_box_ms_C1.0.parquet")
FROZEN = Path("data/frozen/v20261024")


def _conf(d: pd.DataFrame, r: pd.DataFrame, date: pd.Timestamp) -> dict:
    out = {}
    for sc, (lo, hi) in SCALES.items():
        m = (d.date == date) & d.n.between(lo, hi)
        out[sc] = round(float(r.box[m].mean()), 3) if m.any() else None
    return out


def _to_cal(cal: pd.DatetimeIndex, date: pd.Timestamp, ahead: float) -> str:
    i = cal.get_indexer([date])[0]
    j = int(np.clip(round(i + ahead), 0, len(cal) - 1))
    return str(cal[j].date())


def record(sym: str, asof: str) -> dict:
    sc, _ = load(sym)
    d = _derived(sc)
    r = rules(d)
    cal = price_series(sym).index
    date = pd.Timestamp(asof)
    q = d[(d.date == date) & r.box]
    scen = scenarios(q[["n", "ahead"]]) if len(q) else pd.DataFrame()
    sw = scale_windows(q[["n", "ahead"]], SCALES) if len(q) else pd.DataFrame()
    p20 = None
    if OOF_P20.exists():
        o = pd.read_parquet(OOF_P20)
        o = o[(o.symbol == sym) & (o.date == date)]
        p20 = round(float(o.p.iloc[0]), 3) if len(o) else None
    rb = regime_bands(pd.read_parquet(FROZEN / f"{sym}_qfq.parquet"))
    prev_month = (date - pd.offsets.MonthBegin(1) - pd.Timedelta(days=1)).strftime("%Y-%m")
    band = rb.loc[prev_month] if prev_month in rb.index else None
    rec = {
        "symbol": sym, "asof": asof, "data_version": "frozen_v20261024", "model_version": "prereg_v1.7_v2",
        "top": {
            "p20": {"value": p20, "evidence": "dev", "notes": ["R4 三尺度形态框 CPCV OOF；开发段，非样本外"]},
            "window": {"rule": "p20 首次≥阈值起 20 个交易日", "evidence": "dev"},
            "lppls_confidence": {**_conf(d, r, date), "evidence": "dev",
                                 "notes": ["长尺度报警精度集中于 2001/2007/2015 泡沫年；非高估年份≈随机（by_year.md）"]},
            "scenarios": [
                {"share": round(float(x.share), 2), "dt_range": [int(x.dt_min), int(x.dt_max)],
                 "ahead_mean": round(float(x.ahead_mean), 1), "ahead_sd": round(float(x.ahead_std), 1),
                 "q20": round(float(x.q20), 1), "q80": round(float(x.q80), 1),
                 "tc_q20_date": _to_cal(cal, date, x.q20), "tc_q80_date": _to_cal(cal, date, x.q80)}
                for x in scen.itertuples()
            ],
            "scenarios_note": "簇间不平均；簇占比<5% 不列；t_c 分位窗开发段覆盖率 1–4%，不作为峰值日预测",
            "scale_windows": [
                {"scale": x.scale, "q20_date": _to_cal(cal, date, x.q20), "q80_date": _to_cal(cal, date, x.q80), "n": int(x.n)}
                for x in sw.itertuples()
            ],
            "invalidation": {"rule": "p20 连续 10 日<阈值 或 三尺度置信度均<5%", "evidence": "rule"},
            "drawdown_price": {"value": None, "evidence": "none"},
            "drawdown_time": {"value": None, "evidence": "none"},
            "second_wave": {"value": None, "evidence": "none"},
        },
        "regime_band": ({"month": prev_month, "state": band.state, "channel": band.channel,
                         "rule": "FCO 公开定义：相对自身前 60 个月分位", "evidence": "descriptive"}
                        if band is not None and isinstance(band.state, str) else {"month": prev_month, "state": None, "evidence": "descriptive"}),
        "bottom": {"state_p": {"value": None, "evidence": "dev_pending"}, "thrust_p": {"value": None, "evidence": "dev_pending"},
                   "entry_rule": {"value": None, "evidence": "none"}},
        "evidence_levels": {"dev": "开发段 2000–2018", "cal": "校准段未运行", "test": "最终测试未运行", "none": "无证据，仅描述",
                            "rule": "执行规则", "dev_pending": "开发段评估进行中", "descriptive": "描述已完成月份，非预测"},
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
        sw = scale_windows(q[["n", "ahead"]], SCALES) if len(q) else pd.DataFrame()
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
