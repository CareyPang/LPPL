"""P1 顶后价格带（描述性；战略规划 §2.7 / §4.1）：回撤情景表 + 估值地板带。

事件：Pagan–Sossounov 转折点（±168 日局部极值、相位 ≥84 日、周期 ≥336 日、峰谷交替，`alt_labels.ps_turns`），
顶须满足顶后 126 日内回撤 ≥15%（与 `label_diag.ps_tops` 同口径）；底对称（底后 126 日内上涨 ≥15%）。
每个顶：起点 = 与上一合格顶之间的最低点，后一谷 = 与下一合格顶之间的最低点；run_up = P(顶)/P(起点) − 1；时长 = 起点 → 顶；max_dd = P(后一谷)/P(顶) − 1；
days_to_trough = 顶 → 后一谷 交易日；dd60/120/250 = 顶后固定窗内最低价回撤。
分桶（按涨幅、按时长、汇总）给 max_dd 与 days_to_trough 的 20/50/80 分位与 n；
样本 = A 股 6 指数（frozen v20261024）+ 外部 4 指数（ext_v20261029，只读价格，不做任何模型评价）。
估值地板：A 股指数每个 PS 底所在月的 PE（乐咕月频，`research.data.valuation` 缓存），给底部 PE 的 20/50/80 分位与 n，
并按最新 PE 折算为点位带。PE 序列为数据商事后整理，非严格 PIT，仅作描述。

全部字段 evidence = descriptive。不输出任何预测日期 / 目标价；不打开 Round 2；不改 Round 1 结论。
用法：python -m research.price_layer.drawdown_table
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.valuation import INDEX_MAP
from ..data.valuation import load as load_pe
from ..eval.alt_labels import ps_turns
from ..eval.dataset import price_series

ROOT = Path(__file__).resolve().parents[2]
EXT_DIR = ROOT / "data/frozen/ext_v20261029"
EXT = {"HSI": "恒生", "SPX": "标普500", "NDX": "纳指100", "N225": "日经225"}
A_SHARE = list(INDEX_MAP)
OUT_JSON = ROOT / "web/mock/data/price_layer/drawdown_table.json"
OUT_DIR = ROOT / "reports/price_layer"

MIN_DD, LOOK = 0.15, 126
HORIZONS = (60, 120, 250)
RUNUP_BINS = [(-np.inf, 0.5, "<50%"), (0.5, 1.0, "50–100%"), (1.0, 2.0, "100–200%"), (2.0, np.inf, ">200%")]
DUR_BINS = [(0, 250, "<1 年"), (250, 500, "1–2 年"), (500, np.inf, ">2 年")]
QS = (0.2, 0.5, 0.8)
MIN_N_A = 5  # 契约显示规则：A 股单独 n<5 不显示


def load_logp(sym: str) -> pd.Series:
    if sym in EXT:
        d = pd.read_parquet(EXT_DIR / f"{sym}.parquet")
        return pd.Series(np.log(d.close.to_numpy(float)), index=pd.DatetimeIndex(d.date))
    return price_series(sym)


def qualified_turns(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pk, tr = ps_turns(x)
    pk = np.array([i for i in pk if i + 1 < len(x) and np.exp(x[i + 1 : i + LOOK + 1].min() - x[i]) - 1 <= -MIN_DD], int)
    tr = np.array([i for i in tr if i + 1 < len(x) and np.exp(x[i + 1 : i + LOOK + 1].max() - x[i]) - 1 >= MIN_DD], int)
    return pk, tr


def top_events(sym: str, logp: pd.Series) -> list[dict]:
    """相邻两个合格顶之间的最低点 = 本顶的后一谷；本顶与上一合格顶之间的最低点 = 本顶的起点。
    最后一个顶没有后续合格顶（下跌可能仍在进行）不计。"""
    x = logp.to_numpy()
    pk, _ = qualified_turns(x)
    out = []
    for k, i in enumerate(pk[:-1]):
        lo = int(pk[k - 1]) if k else 0
        a = lo + int(np.argmin(x[lo : i + 1]))
        if a == 0 and not k:
            continue  # 起点落在数据首日，涨幅不可知
        nxt = int(pk[k + 1])
        b = i + 1 + int(np.argmin(x[i + 1 : nxt + 1]))
        row = {
            "sym": sym, "market": "A" if sym in A_SHARE else "ext",
            "top": str(logp.index[i].date()), "start": str(logp.index[a].date()), "trough": str(logp.index[b].date()),
            "run_up": round(float(np.exp(x[i] - x[a]) - 1), 3), "dur_days": int(i - a),
            "max_dd": round(float(np.exp(x[b] - x[i]) - 1), 3), "days_to_trough": int(b - i),
        }
        for h in HORIZONS:
            seg = x[i + 1 : i + h + 1]
            row[f"dd{h}"] = round(float(np.exp(seg.min() - x[i]) - 1), 3) if len(seg) == h else None
        out.append(row)
    return out


def _bucket(v: float, bins) -> str:
    return next(name for lo, hi, name in bins if lo <= v < hi)


def _q(vals: list[float]) -> dict:
    a = np.asarray(vals, float)
    return {f"q{int(q * 100)}": round(float(np.quantile(a, q)), 3) for q in QS}


def summarize(ev: pd.DataFrame) -> dict:
    """每桶：n（全部 / A 股）、max_dd 与 days_to_trough 分位（全部；A 股单独 n≥MIN_N_A 才给）。"""
    def cell(df: pd.DataFrame) -> dict:
        d = {"n": int(len(df)), "n_a": int((df.market == "A").sum())}
        if len(df):
            d["max_dd"] = _q(df.max_dd.tolist())
            d["days_to_trough"] = {k: int(v) for k, v in _q(df.days_to_trough.tolist()).items()}
            d["dd120"] = _q(df.dd120.dropna().tolist()) if df.dd120.notna().any() else None
        a = df[df.market == "A"]
        d["a_share"] = {"max_dd": _q(a.max_dd.tolist()), "days_to_trough": {k: int(v) for k, v in _q(a.days_to_trough.tolist()).items()}} if len(a) >= MIN_N_A else None
        return d

    ev = ev.assign(runup_bucket=ev.run_up.map(lambda v: _bucket(v, RUNUP_BINS)), dur_bucket=ev.dur_days.map(lambda v: _bucket(v, DUR_BINS)))
    return {
        "all": cell(ev),
        "by_run_up": {name: cell(ev[ev.runup_bucket == name]) for _, _, name in RUNUP_BINS},
        "by_duration": {name: cell(ev[ev.dur_bucket == name]) for _, _, name in DUR_BINS},
        "by_run_up_x_duration": {f"{r}|{d}": cell(ev[(ev.runup_bucket == r) & (ev.dur_bucket == d)])
                                 for _, _, r in RUNUP_BINS for _, _, d in DUR_BINS},
    }


def valuation_floor(sym: str, logp: pd.Series) -> dict | None:
    """A 股指数：PS 底所在月的 PE 分位 → 用最新 PE 折算点位带。"""
    try:
        pe = load_pe(sym)
    except Exception:  # noqa: BLE001 缓存缺失且无网
        return None
    x = logp.to_numpy()
    _, tr = qualified_turns(x)
    rows = []
    for i in tr:
        t = logp.index[i]
        m = pe[(pe.index.to_period("M") == t.to_period("M"))]
        if len(m) and np.isfinite(m.iloc[-1]):
            rows.append({"trough": str(t.date()), "pe": round(float(m.iloc[-1]), 2)})
    if len(rows) < 3:
        return {"n": len(rows), "troughs": rows, "evidence": "descriptive", "note": "PS 底部样本不足 3 个，不给地板带"}
    pes = [r["pe"] for r in rows]
    q = _q(pes)
    pe_latest, pe_date = float(pe.iloc[-1]), str(pe.index[-1].date())
    close = float(np.exp(x[-1]))
    return {
        "n": len(rows), "troughs": rows, "trough_pe": q, "pe_latest": round(pe_latest, 2), "pe_date": pe_date,
        "close_ref": round(close, 2), "close_date": str(logp.index[-1].date()),
        "band_points": {k: round(close * v / pe_latest, 0) for k, v in q.items()},
        "floor_band_points": [round(close * q["q20"] / pe_latest, 0), round(close * q["q50"] / pe_latest, 0)],
        "rule": "地板带 = 历次 PS 底部所在月 PE 的 20–50% 分位 × 最新收盘 / 最新 PE（q80 仅作上参考）；PE 月频、事后整理、非严格 PIT",
        "evidence": "descriptive",
    }


def build() -> dict:
    events, floors = [], {}
    for sym in A_SHARE + list(EXT):
        lp = load_logp(sym)
        events += top_events(sym, lp)
        if sym in A_SHARE:
            floors[sym] = valuation_floor(sym, lp)
    ev = pd.DataFrame(events).sort_values(["market", "sym", "top"]).reset_index(drop=True)
    return {
        "version": "p1_v20261031", "evidence": "descriptive",
        "sources": {"a_share": "data/frozen/v20261024", "external": "data/frozen/ext_v20261029", "pe": "research.data.valuation（乐咕月频缓存）"},
        "definition": {"turns": "Pagan–Sossounov ±168/84/336 日，顶后 126 日内回撤 ≥15%", "run_up": "P(顶)/P(起点)−1，起点=与上一合格顶之间最低点",
                       "max_dd": "P(后一谷)/P(顶)−1，后一谷=与下一合格顶之间最低点", "quantiles": [int(q * 100) for q in QS], "min_n_a_share": MIN_N_A},
        "n_events": int(len(ev)), "n_events_a": int((ev.market == "A").sum()),
        "n_distinct_top_months": int(ev.assign(m=ev.top.str[:7]).groupby(["market", "m"]).ngroups),
        "n_distinct_top_months_a": int(ev[ev.market == "A"].top.str[:7].nunique()),
        "symbols": {**{s: INDEX_MAP[s][1] for s in A_SHARE}, **EXT},
        "buckets": {"run_up": [n for _, _, n in RUNUP_BINS], "duration": [n for _, _, n in DUR_BINS]},
        "table": summarize(ev),
        "events": ev.to_dict("records"),
        "valuation_floor": floors,
        "note": "描述性历史分位，不是预测；最后一个顶（其后尚无新合格顶，下跌可能仍在进行）不计入；分桶按起点→顶的实际涨幅与时长；同一市场多指数在同月见顶计多个事件（非独立），n_distinct_top_months 为去重后的独立顶月数",
    }


def write_md(rec: dict) -> str:
    t = rec["table"]

    def line(name: str, c: dict) -> str:
        if not c["n"]:
            return f"| {name} | 0 | 0 | — | — | — |"
        dd, dt = c["max_dd"], c["days_to_trough"]
        a = c["a_share"]
        a_s = f"{a['max_dd']['q20']:+.0%} / {a['max_dd']['q50']:+.0%} / {a['max_dd']['q80']:+.0%}" if a else "n<5 不显示"
        return f"| {name} | {c['n']} | {c['n_a']} | {dd['q20']:+.0%} / {dd['q50']:+.0%} / {dd['q80']:+.0%} | {dt['q20']} / {dt['q50']} / {dt['q80']} | {a_s} |"

    hdr = "| 桶 | n | 其中 A 股 | 顶→谷回撤 20/50/80% | 顶→谷交易日 20/50/80% | A 股单独回撤 20/50/80% |\n|---|---:|---:|---|---|---|"
    out = [f"# P1 回撤情景表（描述性，{rec['version']}）", "",
           f"事件 {rec['n_events']} 个（A 股 {rec['n_events_a']}，外部 {rec['n_events'] - rec['n_events_a']}；去重后独立顶月 {rec['n_distinct_top_months']}，A 股 {rec['n_distinct_top_months_a']}）；{rec['definition']['turns']}。{rec['note']}。", "",
           "## 汇总", hdr, line("全部", t["all"]), "",
           "## 按泡沫涨幅（起点→顶）", hdr, *[line(k, v) for k, v in t["by_run_up"].items()], "",
           "## 按泡沫时长（起点→顶）", hdr, *[line(k, v) for k, v in t["by_duration"].items()], "",
           "## 涨幅 × 时长", hdr, *[line(k.replace("|", " × "), v) for k, v in t["by_run_up_x_duration"].items() if v["n"]], "",
           "## 估值地板带（A 股，PS 底部所在月 PE）", "| 指数 | 底部 n | 底部 PE 20/50/80% | 最新 PE（月） | 折算点位 20/50/80% |", "|---|---:|---|---|---|"]
    for s, f in rec["valuation_floor"].items():
        name = rec["symbols"][s]
        if not f or "trough_pe" not in f:
            out.append(f"| {name} | {f['n'] if f else 0} | 样本不足 | — | — |")
        else:
            q, b = f["trough_pe"], f["band_points"]
            out.append(f"| {name} | {f['n']} | {q['q20']} / {q['q50']} / {q['q80']} | {f['pe_latest']}（{f['pe_date']}） | {b['q20']:.0f} / {b['q50']:.0f} / {b['q80']:.0f}（收盘 {f['close_ref']:.0f} @ {f['close_date']}） |")
    out += ["", "## 事件表", "| 市场 | 指数 | 起点 | 顶 | 后一谷 | 涨幅 | 时长(日) | 顶→谷回撤 | 顶→谷(日) | dd120 |", "|---|---|---|---|---|---:|---:|---:|---:|---:|"]
    for e in rec["events"]:
        dd120 = "—" if e["dd120"] is None else f"{e['dd120']:+.0%}"
        out.append(f"| {e['market']} | {rec['symbols'][e['sym']]} | {e['start']} | {e['top']} | {e['trough']} | {e['run_up']:+.0%} | {e['dur_days']} | {e['max_dd']:+.0%} | {e['days_to_trough']} | {dd120} |")
    out += ["", "所有数字为历史描述性分位（evidence = descriptive），不是预测；A 股单独 n<5 的桶不显示 A 股分位。"]
    return "\n".join(out) + "\n"


def main() -> None:
    rec = build()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rec["events"]).to_csv(OUT_DIR / "drawdown_events.csv", index=False)
    (OUT_DIR / "drawdown_table.md").write_text(write_md(rec), encoding="utf-8")
    print(OUT_JSON, OUT_DIR / "drawdown_table.md", "events", rec["n_events"], "A", rec["n_events_a"])


if __name__ == "__main__":
    main()
