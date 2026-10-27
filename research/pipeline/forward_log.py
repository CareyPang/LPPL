"""前瞻日志（FBE 做法）：把日更契约 JSON 原样封存并记录 sha256，事后按同一判据复盘。

seal  ：把 web/mock/data/<sym>_latest.json 复制到 forward_log/<asof>/<sym>.json，追加 forward_log/ledger.jsonl
        {asof, symbol, sha256, sealed_at, data_version, model_version}；同一 (asof, symbol) 已封存则跳过（不覆盖）。
review：读取 ledger 中 since 之后的记录，取 top.indicators[scale].confidence[set]（6–12m / 12–24m × box/standard/end），
        报警 = 置信度 ≥ 0.05；用最新行情重算 ε-回撤顶标签（research.labels.run_top.build），按 H=120 算 A1/A2 与循环平移对照
        （与开发/校准/测试段同一函数）。顶标签需要事件后 ≥80 日成熟，所以复盘只覆盖 asof ≤ 最新日 − 120 交易日的记录。
用法：python -m research.pipeline.forward_log seal | review [--since 2026-01-01]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("forward_log")
LEDGER = ROOT / "ledger.jsonl"
SRC = Path("web/mock/data")
SYMS = ("sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006")
Q, H = 0.05, 120
SETS = ("box", "standard", "end")
SCALES = ("6-12m", "12-24m")


def _ledger() -> pd.DataFrame:
    if not LEDGER.exists():
        return pd.DataFrame(columns=["asof", "symbol", "sha256", "sealed_at", "data_version", "model_version", "path"])
    return pd.DataFrame([json.loads(x) for x in LEDGER.read_text().splitlines() if x.strip()])


def seal(syms: tuple[str, ...] = SYMS) -> list[dict]:
    led = _ledger()
    done = set(zip(led.asof, led.symbol, strict=True)) if len(led) else set()
    out = []
    for s in syms:
        p = SRC / f"{s}_latest.json"
        if not p.exists():
            continue
        rec = json.loads(p.read_text())
        asof = rec["asof"]
        if (asof, s) in done:
            continue
        dst = ROOT / asof / f"{s}.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)
        row = dict(asof=asof, symbol=s, sha256=hashlib.sha256(dst.read_bytes()).hexdigest(),
                   sealed_at=datetime.now(UTC).isoformat(timespec="seconds"),
                   data_version=rec.get("data_version"), model_version=rec.get("model_version"), path=str(dst))
        with LEDGER.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        out.append(row)
    return out


def verify() -> pd.DataFrame:
    led = _ledger()
    led["ok"] = [hashlib.sha256(Path(p).read_bytes()).hexdigest() == h if Path(p).exists() else False
                 for p, h in zip(led.path, led.sha256, strict=True)]
    return led


def review(since: str = "2026-01-01") -> pd.DataFrame:
    from ..data import cache
    from ..eval.calibration_lppls import _null
    from ..eval.original_standard import _alarm_metrics
    from ..labels.run_top import build

    led = verify()
    led = led[(led.asof >= since) & led.ok]
    rows = []
    for s, g in led.groupby("symbol"):
        ohlc = cache.load(s, auto_refresh=False)
        px = ohlc.set_index(pd.to_datetime(ohlc["date"]))["close"] if "date" in ohlc.columns else ohlc["close"]
        logp = np.log(px.to_numpy(float))
        cal = px.index
        lab = build(s, cal, logp)
        tops = np.sort(np.flatnonzero(lab["main__y"].to_numpy()))
        mature_end = len(cal) - 1 - H
        recs = []
        for r in g.sort_values("asof").itertuples():
            j = json.loads(Path(r.path).read_text())
            ind = j.get("top", {}).get("indicators", {})
            pos = cal.get_indexer([pd.Timestamp(r.asof)])[0]
            if pos < 0 or pos > mature_end:
                continue
            recs.append((pos, {f"{st}__{sc}": (ind.get(sc, {}).get("confidence") or {}).get(st) for sc in SCALES for st in SETS}))
        if len(recs) < 3:
            continue
        gpos = np.array([p for p, _ in recs])
        rng = np.random.default_rng(0)
        for key in [f"{st}__{sc}" for sc in SCALES for st in SETS]:
            x = np.array([(d.get(key) or 0.0) for _, d in recs], float)
            alarm = x >= Q
            a1, a2 = _alarm_metrics(alarm, tops, gpos, H)
            nul = _null(alarm, tops, gpos, H, rng) if alarm.sum() >= 3 and len(gpos) >= 8 else np.full((1, 2), np.nan)
            rows.append(dict(symbol=s, indicator=key, n_asof=len(gpos), n_alarm=int(alarm.sum()), n_tops=int(((tops >= gpos.min()) & (tops <= gpos.max() + H)).sum()),
                             A1=a1, A1_null=float(np.nanmean(nul[:, 0])), A1_p=float(np.nanmean(nul[:, 0] >= a1)) if alarm.sum() >= 3 else np.nan,
                             A2=a2, A2_null=float(np.nanmean(nul[:, 1]))))
    tab = pd.DataFrame(rows)
    out = ROOT / f"review_{datetime.now(UTC).date()}.csv"
    tab.to_csv(out, index=False)
    print(tab.round(3).to_string(index=False) if len(tab) else "成熟记录不足，暂无可复盘样本")
    return tab


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["seal", "verify", "review"])
    ap.add_argument("--since", default="2026-01-01")
    a = ap.parse_args()
    if a.cmd == "seal":
        rows = seal()
        print(f"sealed {len(rows)}: " + ", ".join(f"{r['symbol']}@{r['asof']}" for r in rows))
    elif a.cmd == "verify":
        v = verify()
        print(v[["asof", "symbol", "ok"]].to_string(index=False) if len(v) else "ledger 为空")
    else:
        review(a.since)


if __name__ == "__main__":
    main()
