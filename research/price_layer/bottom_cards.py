"""Descriptive LT bottom-state, cheapness, and rebound cards."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.valuation import CACHE as PE_CACHE
from ..data.valuation import LAG_MONTHS
from ..data.valuation import load as load_pe
from ..eval.alt_labels import lt_turns
from . import drawdown_table as dt

ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = ROOT / "web/mock/data/price_layer/rebound_table.json"
OUT_MD = ROOT / "reports/price_layer/rebound_table.md"

LT_L1, LT_L2 = 0.20, 0.15
REBOUND_DAYS = 250
PE_MONTHS, MIN_PE_MONTHS = 120, 36
QS = (0.2, 0.5, 0.8)
SYMBOL_NAMES = {
    "sh000001": "上证指数",
    "sh000016": "上证50",
    "sh000300": "沪深300",
    "sh000905": "中证500",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    **dt.EXT,
}
CONFIRM_RULE = (
    "Lunde–Timmermann 2004：自牛市高点跌 20% 确认熊市；自熊市低点涨 15% 确认熊市结束"
    "（滞后确认，不是预测）"
)


def _close(logp: pd.Series) -> np.ndarray:
    return np.exp(logp.to_numpy(dtype=float))


def _date_at(dates: pd.DatetimeIndex, i: int) -> str:
    return str(pd.Timestamp(dates[i]).date())


def lt_state(x: np.ndarray, dates: pd.DatetimeIndex) -> dict:
    """Return the LT state at the last bar; private turn indices support parity tests."""
    x = np.asarray(x, dtype=float)
    dates = pd.DatetimeIndex(dates)
    if len(x) != len(dates):
        raise ValueError("x and dates must have the same length")
    if not len(x):
        return {
            "state": "bull", "ref_date": None, "ref_close": None,
            "threshold": LT_L2, "confirmed": False, "_peaks": [], "_troughs": [],
        }

    bull, ref = True, 0
    peaks: list[int] = []
    troughs: list[int] = []
    confirmed_peak: int | None = None
    last_trough: int | None = None
    confirmed_date: str | None = None
    for i in range(1, len(x)):
        if bull:
            if x[i] > x[ref]:
                ref = i
            elif x[ref] - x[i] >= np.log(1 / (1 - LT_L1)):
                peaks.append(ref)
                confirmed_peak = ref
                bull, ref = False, i
        elif x[i] < x[ref]:
            ref = i
        elif x[i] - x[ref] >= np.log(1 + LT_L2):
            troughs.append(ref)
            last_trough = ref
            confirmed_date = _date_at(dates, i)
            bull, ref = True, i

    turns_peaks, turns_troughs = lt_turns(x, l1=LT_L1, l2=LT_L2)
    state = {
        "state": "bull" if bull else "bear",
        "ref_date": _date_at(dates, ref),
        "ref_close": round(float(np.exp(x[ref])), 2),
        "threshold": LT_L2,
        "confirmed": bool(bull and last_trough is not None),
        "_peaks": [int(i) for i in peaks],
        "_troughs": [int(i) for i in troughs],
    }
    if not bull:
        state.update({
            "peak_date": _date_at(dates, int(confirmed_peak)),
            "peak_close": round(float(np.exp(x[int(confirmed_peak)])), 2),
            "rebound_from_low": round(float(np.exp(x[-1] - x[ref]) - 1), 4),
            "confirmed": False,
        })
    elif last_trough is not None:
        state.update({
            "last_trough_date": _date_at(dates, last_trough),
            "last_trough_close": round(float(np.exp(x[last_trough])), 2),
            "confirmed_date": confirmed_date,
        })
    if not np.array_equal(np.asarray(state["_peaks"]), turns_peaks):
        raise AssertionError("LT state peaks differ from lt_turns")
    if not np.array_equal(np.asarray(state["_troughs"]), turns_troughs):
        raise AssertionError("LT state troughs differ from lt_turns")
    return state


def _public_state(state: dict) -> dict:
    return {k: v for k, v in state.items() if not k.startswith("_")}


def _quantiles(values: list[float]) -> dict | None:
    if not values:
        return None
    a = np.asarray(values, dtype=float)
    return {f"q{int(q * 100)}": round(float(np.quantile(a, q)), 3) for q in QS}


def _share(values: list[dict], current: float) -> dict:
    if not values:
        return {"pct": None, "n": 0}
    return {
        "pct": round(sum(row["max_dd"] > current for row in values) / len(values), 3),
        "n": len(values),
    }


def _pe_percentile(sym: str, asof: pd.Timestamp) -> dict:
    if sym in dt.FLOOR_MISMATCH:
        floor = dt.valuation_floor(sym, pd.Series(dtype=float), asof)
        return {
            "value": None, "n_months": 0, "pe_date": None,
            "note": floor["note"] if floor else "PE 序列与价格指数口径不一致，不计算分位",
        }
    if not (PE_CACHE / f"{sym}.parquet").exists():
        return {"value": None, "n_months": 0, "pe_date": None, "note": "无可用 PE 缓存"}
    try:
        pe = load_pe(sym)
    except Exception:  # noqa: BLE001 离线环境中的 PE 缓存不可读
        return {"value": None, "n_months": 0, "pe_date": None, "note": "无可用 PE 缓存"}

    asof = pd.Timestamp(asof)
    usable = pe.loc[pe.index + pd.DateOffset(months=LAG_MONTHS) <= asof]
    usable = usable[np.isfinite(usable.to_numpy(dtype=float))]
    usable = usable[~usable.index.to_period("M").duplicated(keep="last")].tail(PE_MONTHS)
    if not len(usable):
        return {"value": None, "n_months": 0, "pe_date": None, "note": "截至 as-of 无满足发布滞后的 PE"}
    latest = float(usable.iloc[-1])
    n_months = len(usable)
    if n_months < MIN_PE_MONTHS:
        return {
            "value": None, "n_months": n_months,
            "pe_date": str(usable.index[-1].date()), "note": "前 120 个月可用 PE 少于 36 个月",
        }
    return {
        "value": round(float((usable.to_numpy(dtype=float) <= latest).mean()), 3),
        "n_months": n_months,
        "pe_date": str(usable.index[-1].date()),
    }


def _cheap(sym: str, logp: pd.Series, asof: pd.Timestamp, p1: dict) -> dict:
    closes = _close(logp)
    tail = pd.Series(closes, index=logp.index).tail(500)
    peak_i = int(np.argmax(tail.to_numpy()))
    peak_date = str(tail.index[peak_i].date())
    peak_close = float(tail.iloc[peak_i])
    close = float(closes[-1])
    dd_now = close / peak_close - 1

    events = p1["events"]
    all_rank = _share(events, dd_now)
    a_events = [event for event in events if event["market"] == "A"]
    a_rank = _share(a_events, dd_now) if len(a_events) >= dt.MIN_N_A else None
    if all_rank["n"]:
        shallow_pct = round(all_rank["pct"] * 100)
        note = (
            f"历史 {all_rank['n']} 次顶→谷回撤中，{shallow_pct}% 比当前回撤浅"
            "（历史分位，不是预测）"
        )
    else:
        note = "历史样本为 0，无法计算当前回撤分位（历史分位，不是预测）"
    return {
        "evidence": "descriptive",
        "dd_now": round(float(dd_now), 4),
        "peak_date": peak_date,
        "peak_close": round(peak_close, 2),
        "dd_rank": {"all": all_rank, "a_share": a_rank, "note": note},
        "pe_pct": _pe_percentile(sym, asof),
        "floor_ref": "top.drawdown_price.valuation_floor",
        "note": "价格与估值均为 as-of 描述；历史分位，不是预测",
    }


def _pair_indices(peaks: np.ndarray, troughs: np.ndarray) -> list[tuple[int, int]]:
    pairs = []
    for trough in troughs:
        prior = peaks[peaks < trough]
        if len(prior):
            pairs.append((int(prior[-1]), int(trough)))
    return pairs


def _rebound_event(sym: str, logp: pd.Series, peak_i: int, trough_i: int) -> dict:
    closes = _close(logp)
    end_i = trough_i + REBOUND_DAYS
    window = closes[trough_i + 1 : end_i + 1]
    high_i = trough_i + 1 + int(np.argmax(window))
    peak_close, trough_close = float(closes[peak_i]), float(closes[trough_i])
    high_close = float(closes[high_i])
    peak_crossings = np.flatnonzero(window >= peak_close)
    days_to_peak = int(peak_crossings[0] + 1) if len(peak_crossings) else None
    return {
        "symbol": sym,
        "market": "A" if sym in dt.A_SHARE else "external",
        "peak_date": _date_at(logp.index, peak_i),
        "trough_date": _date_at(logp.index, trough_i),
        "dd": trough_close / peak_close - 1,
        "high_date": _date_at(logp.index, high_i),
        "recovery": (high_close - trough_close) / (peak_close - trough_close),
        "recovery_log": np.log(high_close / trough_close) / np.log(peak_close / trough_close),
        "rebound_ret": high_close / trough_close - 1,
        "back_to_peak": bool(high_close >= peak_close),
        "days_to_peak": days_to_peak,
        "days_to_high": high_i - trough_i,
    }


@lru_cache(maxsize=16)
def _rebound_history(asof: str) -> tuple[list[dict], dict, dict]:
    events: list[dict] = []
    for sym in dt.A_SHARE + list(dt.EXT):
        logp = dt.load_logp(sym)
        logp = logp.loc[logp.index <= pd.Timestamp(asof)]
        if not len(logp):
            continue
        peaks, troughs = lt_turns(logp.to_numpy(dtype=float), l1=LT_L1, l2=LT_L2)
        for peak_i, trough_i in _pair_indices(peaks, troughs):
            if trough_i + REBOUND_DAYS <= len(logp) - 1:
                events.append(_rebound_event(sym, logp, peak_i, trough_i))
    events.sort(key=lambda row: (row["symbol"], row["peak_date"], row["trough_date"]))

    def distribution(rows: list[dict]) -> dict:
        return {
            "n": len(rows),
            "recovery": _quantiles([row["recovery"] for row in rows]),
            "recovery_log": _quantiles([row["recovery_log"] for row in rows]),
            "rebound_ret": _quantiles([row["rebound_ret"] for row in rows]),
            "back_to_peak_share": (
                round(sum(row["back_to_peak"] for row in rows) / len(rows), 3) if rows else None
            ),
            "days_to_high": _quantiles([row["days_to_high"] for row in rows]),
        }

    all_dist = distribution(events)
    a_events = [row for row in events if row["market"] == "A"]
    a_dist = distribution(a_events) if len(a_events) >= dt.MIN_N_A else None
    return events, all_dist, a_dist


def _current_rebound(sym: str, logp: pd.Series, state: dict, history: list[dict]) -> dict | None:
    if state["state"] != "bull" or not state["_troughs"]:
        return None
    trough_i = int(state["_troughs"][-1])
    days_since = len(logp) - 1 - trough_i
    if days_since >= REBOUND_DAYS:
        return None
    peaks, _ = lt_turns(logp.to_numpy(dtype=float), l1=LT_L1, l2=LT_L2)
    prior_peaks = peaks[peaks < trough_i]
    if not len(prior_peaks):
        return None
    peak_i = int(prior_peaks[-1])
    closes = _close(logp)
    recovery_now = (float(closes[-1]) - float(closes[trough_i])) / (float(closes[peak_i]) - float(closes[trough_i]))
    recovery_log_now = np.log(float(closes[-1]) / float(closes[trough_i])) / np.log(
        float(closes[peak_i]) / float(closes[trough_i])
    )
    rebound_ret_now = float(closes[-1]) / float(closes[trough_i]) - 1
    if not history:
        rank_pct = None
    else:
        rank_pct = round(sum(row["recovery"] < recovery_now for row in history) / len(history), 3)
    return {
        "trough_date": _date_at(logp.index, trough_i),
        "peak_date": _date_at(logp.index, peak_i),
        "recovery_now": round(float(recovery_now), 3),
        "recovery_log_now": round(float(recovery_log_now), 3),
        "rebound_ret_now": round(float(rebound_ret_now), 3),
        "days_since_trough": days_since,
        "rank_pct": rank_pct,
    }


def _latest_common_asof() -> str:
    return str(min(dt.load_logp(sym).index[-1] for sym in dt.A_SHARE + list(dt.EXT)).date())


def build(sym: str, asof: str) -> dict:
    """Build the three descriptive bottom-card objects using only observations through asof."""
    if sym not in dt.A_SHARE:
        raise ValueError(f"bottom card records are only defined for A-share indices: {sym}")
    asof_ts = pd.Timestamp(asof)
    asof_key = str(asof_ts.date())
    logp = dt.load_logp(sym)
    logp = logp.loc[logp.index <= asof_ts]
    p1 = dt.build(asof_key)
    state = lt_state(logp.to_numpy(dtype=float), logp.index)
    public_state = _public_state(state)
    confirm = {
        "evidence": "rule",
        "rule": CONFIRM_RULE,
        **public_state,
    }
    events, all_dist, a_dist = _rebound_history(asof_key)
    rebound = {
        "evidence": "descriptive" if all_dist["n"] else "none",
        **all_dist,
        "a_share": a_dist,
        "current": _current_rebound(sym, logp, state, events),
        "note": "历史分位，不是预测",
    }
    return {
        "cheap": _cheap(sym, logp, asof_ts, p1),
        "confirm": confirm,
        "rebound": rebound,
    }


def _export_events(events: list[dict]) -> list[dict]:
    return [
        {
            **row,
            "dd": round(float(row["dd"]), 3),
            "recovery": round(float(row["recovery"]), 3),
            "recovery_log": round(float(row["recovery_log"]), 3),
            "rebound_ret": round(float(row["rebound_ret"]), 3),
            "days_to_high": int(row["days_to_high"]),
        }
        for row in events
    ]


def write_rebound_table(asof: str | None = None) -> dict:
    asof = str(pd.Timestamp(asof).date()) if asof is not None else _latest_common_asof()
    events, all_dist, a_dist = _rebound_history(asof)
    table = {
        "asof": asof,
        "evidence": "descriptive" if all_dist["n"] else "none",
        "n": all_dist["n"],
        "recovery": all_dist["recovery"],
        "recovery_log": all_dist["recovery_log"],
        "rebound_ret": all_dist["rebound_ret"],
        "back_to_peak_share": all_dist["back_to_peak_share"],
        "days_to_high": all_dist["days_to_high"],
        "a_share": a_dist,
        "events": _export_events(events),
        "note": "历史分位，不是预测",
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")
    rows = [
        "# 历史反弹分位",
        "",
        f"as-of {asof}；n={all_dist['n']}；价格恢复比例分位 {all_dist['recovery']}；对数恢复比例分位 {all_dist['recovery_log']}；"
        f"反弹收益分位 {all_dist['rebound_ret']}；回前高比例 {all_dist['back_to_peak_share']}；"
        f"顶至高点交易日分位 {all_dist['days_to_high']}；历史分位，不是预测。",
        "",
        "| 指数 | 市场 | 顶日期 | 谷日期 | 回撤 | 250 日内高点日期 | 价格恢复比例 | 对数恢复比例 | 反弹收益 | 回前高 | 回前高交易日 | 谷至高点交易日 |",
        "|---|---|---|---|---:|---|---:|---:|---:|---|---:|---:|",
    ]
    for row in table["events"]:
        rows.append(
            f"| {SYMBOL_NAMES[row['symbol']]} | {row['market']} | {row['peak_date']} | {row['trough_date']} "
            f"| {row['dd']:.3f} | {row['high_date']} | {row['recovery']:.3f} | {row['recovery_log']:.3f} "
            f"| {row['rebound_ret']:.3f} | {'是' if row['back_to_peak'] else '否'} "
            f"| {row['days_to_peak'] if row['days_to_peak'] is not None else '—'} | {row['days_to_high']} |"
        )
    rows.extend(["", "历史分位，不是预测。"])
    OUT_MD.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return table


if __name__ == "__main__":
    result = write_rebound_table()
    print(OUT_JSON, "events", result["n"], "asof", result["asof"])
