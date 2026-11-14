"""前瞻日志季度复盘（计划 H）：对 ledger 中某季度的封存记录出表，只做描述，不做预测。

每标的：封存天数 n、哈希核验失败数、`model_version`/`data_version` 分段、报警事件簇（指标置信度 ≥ Q 的连续封存日）、
已成熟记录数（asof 之后行情日历上已有 ≥H 个交易日，同 forward_log.review）；A1/A2 只有在成熟记录 ≥ 8 且报警 ≥ 3 时才由 forward_log.review 计算，这里不算。
缺日清单：季度内（自 ledger 首日起、截至 ledger 最后一次封存）交易日历上没有该标的封存的日期；整季无封存的标的也列出——按 §22 规则缺日只标注、不回填。
证据等级固定为 `descriptive`，直到 ledger 覆盖 ≥ 6 个季度（见 docs/plan_continuation_2026_11.md H）。
用法：python -m research.pipeline.forward_review 2026Q4 [--root forward_log] [--out reports/forward_review_2026Q4.csv]
独立于 forward_log.py 的 check/precision（PR #54），避免两支同时改同一文件。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from .forward_log import SCALES, SETS, H, Q

MIN_QUARTERS = 6
KEYS = tuple(f"{st}__{sc}" for sc in SCALES for st in SETS)


def quarter_range(q: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    p = pd.Period(q, freq="Q")
    return p.start_time.normalize(), p.end_time.normalize()


def load_ledger(root: Path) -> pd.DataFrame:
    f = root / "ledger.jsonl"
    if not f.exists():
        return pd.DataFrame(columns=["asof", "symbol", "sha256", "sealed_at", "data_version", "model_version", "path"])
    led = pd.DataFrame([json.loads(x) for x in f.read_text().splitlines() if x.strip()])
    paths = [root / Path(p).relative_to(Path(p).parts[0]) if Path(p).parts and Path(p).parts[0] == "forward_log" else Path(p) for p in led.path]
    led["file"] = [str(p) for p in paths]
    led["ok"] = [p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in zip(paths, led.sha256, strict=True)]
    return led


def _segments(g: pd.DataFrame, col: str) -> str:
    segs, cur = [], None
    for r in g.itertuples():
        v = getattr(r, col)
        if cur is None or cur[0] != v:
            cur = [v, r.asof, r.asof, 1]
            segs.append(cur)
        else:
            cur[2], cur[3] = r.asof, cur[3] + 1
    return "; ".join(f"{v}:{a}..{b}(n={n})" for v, a, b, n in segs)


def _clusters(g: pd.DataFrame) -> tuple[int, str]:
    conf = []
    for r in g.itertuples():
        ind = json.loads(Path(r.file).read_text()).get("top", {}).get("indicators", {})
        conf.append({k: float((ind.get(k.split("__")[1], {}).get("confidence") or {}).get(k.split("__")[0]) or 0.0) for k in KEYS})
    out, total = [], 0
    for k in KEYS:
        run = None
        for asof, c in zip(g["asof"], conf, strict=True):
            if c[k] >= Q:
                run = [asof, asof, 1] if run is None else [run[0], asof, run[2] + 1]
            elif run is not None:
                out.append(f"{k}:{run[0]}..{run[1]}(n={run[2]})")
                total += 1
                run = None
        if run is not None:
            out.append(f"{k}:{run[0]}..{run[1]}(n={run[2]})")
            total += 1
    return total, "; ".join(out)


def trading_days(start: pd.Timestamp, end: pd.Timestamp, symbol: str) -> pd.DatetimeIndex:
    try:
        from ..data import cache
        ohlc = cache.load(symbol, auto_refresh=False)
        d = pd.to_datetime(ohlc["date"] if "date" in ohlc.columns else ohlc.index)
        if d.max() >= end:
            return pd.DatetimeIndex(d[(d >= start) & (d <= end)])
    except Exception:  # noqa: BLE001 — 无缓存时退回工作日历（节假日会被列为缺日，表头注明）
        pass
    return pd.bdate_range(start, end)


def _mature_end(symbol: str) -> pd.Timestamp:
    """与 forward_log.review 同口径：asof 之后在可得行情日历上还有 ≥H 个交易日才算成熟；无缓存时退回工作日历。"""
    try:
        from ..data import cache
        ohlc = cache.load(symbol, auto_refresh=False)
        d = pd.DatetimeIndex(pd.to_datetime(ohlc["date"] if "date" in ohlc.columns else ohlc.index)).sort_values()
        if len(d) > H:
            return d[-1 - H]
    except Exception:  # noqa: BLE001
        pass
    return pd.Timestamp.today().normalize() - pd.tseries.offsets.BDay(H)


def review_quarter(q: str, root: Path = Path("forward_log")) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    start, end = quarter_range(q)
    led = load_ledger(root)
    n_quarters = pd.to_datetime(led["asof"]).dt.to_period("Q").nunique() if len(led) else 0
    evidence = "descriptive" if n_quarters < MIN_QUARTERS else "forward_reviewable"
    led["asof_ts"] = pd.to_datetime(led["asof"])  # DataFrame.asof 是方法名，必须下标取列
    # 缺日区间按整个 ledger 定：从 ledger 首日起（日志启动前不是缺日）、到 ledger 最后一次封存止（停更后又恢复时，
    # 季度末尾的停更段也要列出）；标的集合也取整个 ledger（整季无封存的标的记 n_sealed=0、全季缺日）
    first = led.asof_ts.min() if len(led) else start
    last = led.asof_ts.max() if len(led) else start
    all_syms = sorted(led.symbol.unique())
    led = led[(led.asof_ts >= start) & (led.asof_ts <= end)].sort_values(["symbol", "asof"])
    rows, missing = [], []
    if all_syms and last >= start and first <= end:  # 季度与 ledger 覆盖期有交集才出表
        for s in all_syms:
            g = led[led.symbol == s]
            ok = g[g.ok]
            mature_end = _mature_end(s)
            n_cl, cl = _clusters(ok)
            rows.append(dict(symbol=s, n_sealed=len(g), n_tampered=int((~g.ok).sum()), n_mature=int((ok.asof_ts <= mature_end).sum()),
                             n_alarm_clusters=n_cl, alarm_clusters=cl, model_versions=_segments(g, "model_version"),
                             data_versions=_segments(g, "data_version"), A1_A2="未算（成熟记录<8 或报警<3；成熟后用 forward_log review）",
                             evidence=evidence))
            cal = trading_days(max(start, first), min(end, last), s)
            have = set(g.asof_ts)
            missing += [dict(symbol=s, date=d.date().isoformat()) for d in cal if d not in have]
    return pd.DataFrame(rows), pd.DataFrame(missing, columns=["symbol", "date"]), evidence


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("quarter", help="如 2026Q4")
    ap.add_argument("--root", default="forward_log")
    ap.add_argument("--out", default=None, help="可选：CSV 输出路径（缺日表写到 <out>.missing.csv）")
    a = ap.parse_args()
    tab, miss, ev = review_quarter(a.quarter, Path(a.root))
    print(f"[{a.quarter}] 证据等级={ev}（<{MIN_QUARTERS} 季度一律 descriptive）；缺日只标注不回填")
    print(tab.to_string(index=False) if len(tab) else "该季度无封存记录")
    print(f"缺日 {len(miss)} 条" + (":\n" + miss.to_string(index=False) if len(miss) else ""))
    if a.out:
        tab.to_csv(a.out, index=False)
        miss.to_csv(a.out + ".missing.csv", index=False)


if __name__ == "__main__":
    main()
