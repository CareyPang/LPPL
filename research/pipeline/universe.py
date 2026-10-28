"""原站工作台层（F01 排行 / F02 汇总 / F04 高级列表）的多资产日更：行业指数 + 宽基指数 + 沪深300 成分股。

每个资产：腾讯不复权日线（近 6 年，个股叠加新浪复权因子）→ 最新日 16 个窗口（127–502 日，步长 25，只覆盖 6–12 月 / 12–24 月两主档）
LPPLS 拟合 → `build_record` → 摘要一行。**全部描述性**：开发段已证明个股 LPPLS 横截面排名无预测信息（§17.11），
排行键只用原版量（Combo p=0.1、最长合格尺度及其 STANDARD 置信度、代表 t_c），不造 bubbleScore。成分为中证最近公布名单（非 PIT）。
输出 web/mock/data/universe_latest.json。
"""
from __future__ import annotations

import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.tencent_sina import apply_factors, sina_factors, tencent_raw
from ..eval.export_contract import build_record
from ..features.lppls_rules import _derived, rules
from ..features.lppls_scan import BOX, BOXES
from ..lppls import core as _core
from .daily import fit_asof

OUT = Path("web/mock/data/universe_latest.json")
WINDOWS = tuple(range(127, 505, 25))
YEARS = 6
INDUSTRY = {"sh000928": "中证能源", "sh000929": "中证材料", "sh000930": "中证工业", "sh000931": "中证可选", "sh000932": "中证消费",
            "sh000933": "中证医药", "sh000934": "中证金融", "sh000935": "中证信息", "sh000936": "中证电信", "sh000937": "中证公用"}
BROAD = {"sh000001": "上证指数", "sh000016": "上证50", "sh000300": "沪深300", "sh000905": "中证500", "sz399001": "深证成指", "sz399006": "创业板指"}


def _sym(code6: str) -> str:
    return ("sh" if code6.startswith("6") else "sz") + code6


def _ret(c: pd.Series, k: int) -> float | None:
    return round(float(c.iloc[-1] / c.iloc[-1 - k] - 1), 4) if len(c) > k else None


def one(args) -> dict:
    sym, name, typ = args
    t0 = time.time()
    try:
        start = str((pd.Timestamp.today() - pd.DateOffset(years=YEARS)).date())
        raw = tencent_raw(sym, start=start)
        if typ == "stock":
            raw = apply_factors(raw, sina_factors(sym, "qfq"), "qfq")
        ohlc = raw.assign(date=pd.to_datetime(raw.date)).sort_values("date").reset_index(drop=True)
        ohlc = ohlc[ohlc.close > 0]
        logp = pd.Series(np.log(ohlc.close.to_numpy(float)), index=pd.DatetimeIndex(ohlc.date))
        date = logp.index[-1]
        _core.ALLOW_INSIDE = bool(BOXES[BOX]["inside"])
        d = _derived(fit_asof(logp, date, WINDOWS))
        rec = build_record(sym, str(date.date()), d, rules(d), logp.index, ohlc, None, data_version=f"vintage_{date:%Y%m%d}_tencent_sina_lite")
        T = rec["top"]
        ind = {k: v for k, v in T["indicators"].items() if k in ("6-12m", "12-24m")}
        sc612 = next((s for s in T["scenarios"]), None)
        row = {"symbol": sym, "name": name, "type": typ, "latest": str(date.date()), "close": round(float(ohlc.close.iloc[-1]), 3),
               "ret_5d": _ret(ohlc.close, 5), "ret_21d": _ret(ohlc.close, 21), "ret_252d": _ret(ohlc.close, 252),
               "conf": {k: (v.get("confidence") or {}) for k, v in ind.items()},
               "n_qualified": {k: v.get("n_qualified_standard", 0) for k, v in ind.items()},
               "combo_p01": T["combo"].get("p0.1"), "longest_qualified_scale": T["bubble"].get("longest_qualified_scale"),
               "bubble_size_model": T["bubble"].get("size_model"), "bubble_duration_days": T["bubble"].get("duration_days"),
               "tc_representative": sc612["representative"]["tc"] if sc612 else None, "tc_q20_q80": [sc612["q20_date"], sc612["q80_date"]] if sc612 else None,
               "signal_status": T["signal_status"], "n_windows": int(len(d)), "secs": round(time.time() - t0, 1), "error": None}
    except Exception as e:  # noqa: BLE001 —— 单资产失败不拖垮全表，显式记录为失败状态（不填 0）
        row = {"symbol": sym, "name": name, "type": typ, "signal_status": "error", "error": f"{type(e).__name__}: {str(e)[:120]}",
               "secs": round(time.time() - t0, 1)}
    return row


def assets(universe: Path = Path("web/mock/data/universe_current.json"), names: dict[str, str] | None = None) -> list[tuple]:
    u = json.loads(universe.read_text())
    names = names or {}
    out = [(s, n, "index") for s, n in BROAD.items()] + [(s, n, "industry") for s, n in INDUSTRY.items()]
    out += [(_sym(c), names.get(c, c), "stock") for c in u["indices"]["sh000300"]]
    return out


def _write(rows: list[dict]) -> Path:
    ok = [r for r in rows if r["signal_status"] != "error"]
    asof = max((r["latest"] for r in ok), default=None)
    summary = {}
    for typ in ("index", "industry", "stock"):
        g = [r for r in ok if r["type"] == typ]
        summary[typ] = {"analysed": len(g), "failed": sum(1 for r in rows if r["type"] == typ and r["signal_status"] == "error"),
                        "positive_signal": sum(1 for r in g if r["signal_status"] == "signal"),
                        "positive_share": round(sum(1 for r in g if r["signal_status"] == "signal") / len(g), 3) if g else None,
                        "negative": "not_computed"}
    out = {"asof": asof, "generated": str(pd.Timestamp.now())[:19], "windows": list(WINDOWS), "n_assets": len(rows),
           "note": "描述性多资产扫描：16 窗（127–502 日）仅覆盖 6–12 月/12–24 月；成分=中证最近公布（非 PIT）；个股 LPPLS 横截面排名在开发段无预测信息（§17.11），"
                   "排行只用原版量（Combo p=0.1 / 最长合格尺度 / 代表 t_c），不构造 bubbleScore；负泡沫未计算；收益期按交易日（5/21/252）",
           "evidence": "descriptive", "summary": summary, "rows": rows}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return OUT


def run(procs: int = 6, limit: int | None = None, names_path: Path = Path("web/mock/data/stock_names.json"), retry_procs: int = 2) -> Path:
    """第一遍并行；腾讯接口对并发敏感（501/空返回），失败的资产第二遍低并发重试，仍失败的保留 error 状态（不填 0）。"""
    names = json.loads(names_path.read_text()) if names_path.exists() else {}
    todo = assets(names=names)[:limit]
    with Pool(procs) as pool:
        rows = pool.map(one, todo, chunksize=1)
    return retry(rows, todo, retry_procs)


def retry(rows: list[dict], todo: list[tuple] | None = None, procs: int = 2) -> Path:
    by = {r["symbol"]: r for r in rows}
    todo = todo or assets(names={r["symbol"][2:]: r["name"] for r in rows})
    bad = [a for a in todo if by.get(a[0], {}).get("signal_status") == "error"]
    if bad:
        time.sleep(3)
        with Pool(procs) as pool:
            for r in pool.map(one, bad, chunksize=1):
                by[r["symbol"]] = r
    return _write([by[a[0]] for a in todo if a[0] in by])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "retry":
        p = retry(json.loads(OUT.read_text())["rows"])
    else:
        lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
        p = run(limit=lim)
    d = json.loads(p.read_text())
    print(p, d["asof"], d["summary"], "secs/asset", round(float(np.mean([r["secs"] for r in d["rows"]])), 1))
