"""预登记检验 breadth_signal_v1：2014–2021 宽度重建 + 买卖候选评估（只跑一次）。

用法：python -m research.eval.breadth_signal_test --stocks <baostock 逐股 csv 目录> --out reports/breadth_signal
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.data import breadth
from research.eval import breadth_signal_candidates as C

ROOT = Path(__file__).resolve().parents[2]
REBUILT = ROOT / "data" / "market" / "breadth_state_2013_2021_baostock.csv"
TEST_START, TEST_END = "2014-01-02", "2021-05-14"
CHINEXT_20 = "2020-08-24"


def _limit(prev: np.ndarray, rate: np.ndarray, up: bool) -> np.ndarray:
    return np.floor(prev * (1 + rate if up else 1 - rate) * 100 + 0.5 + 1e-9) / 100


def rebuild(stock_dir: Path) -> pd.DataFrame:
    parts = []
    for path in sorted(stock_dir.glob("*.csv")):
        part = pd.read_csv(path, dtype={"code": str})
        if not part.empty:
            parts.append(part)
    rows = pd.concat(parts, ignore_index=True)
    for field in ("low", "close", "preclose", "volume", "amount"):
        rows[field] = pd.to_numeric(rows[field], errors="coerce")
    rows = rows.loc[
        rows["tradestatus"].astype(str).eq("1")
        & rows["volume"].gt(0)
        & rows["preclose"].gt(0)
        & rows["close"].gt(0)
        & rows["code"].str[3:5].isin(("60", "68", "00", "30"))
    ].copy()
    prefix = rows["code"].str[3:5]
    rate = np.where(
        prefix.eq("68") | (prefix.eq("30") & rows["date"].ge(CHINEXT_20)), 0.2, 0.1
    )
    prev, close, low = (rows[name].to_numpy(float) for name in ("preclose", "close", "low"))
    rows["up"] = close > prev
    rows["down"] = close < prev
    rows["lu"] = close >= _limit(prev, rate, True) - 0.001
    rows["ld"] = (close <= _limit(prev, rate, False) + 0.001) | (
        (close <= _limit(prev, np.full_like(rate, 0.05), False) + 0.001)
        & (close <= low + 0.001)
        & (rate == 0.1)
        & ((close / prev - 1) < -0.045)
    )
    daily = rows.groupby("date").agg(
        n=("code", "size"), adv=("up", "sum"), dec=("down", "sum"),
        lu=("lu", "sum"), ld=("ld", "sum"), amount=("amount", "sum"),
    )
    daily["red"] = daily["adv"] / daily["n"]
    daily["amount_yi"] = daily["amount"] / 1e8
    closes = rows.pivot(index="date", columns="code", values="close")
    daily["P20"] = breadth.compute_price_breadth(closes, windows=(20,))["P20"]
    bars = json.loads((ROOT / "web/mock/data/sh000001_bars.json").read_text(encoding="utf-8"))
    daily["sh"] = pd.Series(bars["close"], index=bars["dates"]).reindex(daily.index)
    daily = daily.reset_index()
    return daily.loc[:, ["date", "sh", "n", "red", "lu", "ld", "amount_yi", "P20"]]


def consistency(rebuilt: pd.DataFrame) -> dict[str, float]:
    seed = pd.read_csv(breadth.STATE_SEED).set_index("date")
    mine = rebuilt.set_index("date")
    days = [day for day in mine.index if day in seed.index]
    out: dict[str, float] = {"days": len(days)}
    for field in ("red", "ld", "amount_yi", "P20"):
        a, b = mine.loc[days, field], seed.loc[days, field]
        keep = a.notna() & b.notna()
        diff = (a[keep] - b[keep]).abs()
        out[field] = float(diff.max() if field in ("red", "P20", "ld") else (diff / b[keep]).max())
    return out


def evaluate(rebuilt: pd.DataFrame) -> dict:
    frame = rebuilt.dropna(subset=["sh"]).reset_index(drop=True)
    states, buy, sell = C.candidates(frame)
    close = states["sh"].to_numpy(float)
    dates = states["date"]
    valid = (dates.ge(TEST_START) & dates.le(TEST_END) & states["state"].notna()).to_numpy().copy()
    valid[len(valid) - C.HORIZON :] = False
    result: dict = {
        "test": [str(dates[valid].iloc[0]), str(dates[valid].iloc[-1])],
        "n_days": int(valid.sum()),
        "state_counts": {k: int(v) for k, v in states.loc[valid, "state"].value_counts().items()},
        "flag_counts": {f: int(states.loc[valid, f].sum()) for f in breadth.FLAG_LABELS},
        "candidates": {},
    }
    everyday = list(np.flatnonzero(valid))
    for side, group in (("buy", buy), ("sell", sell)):
        base = C.summary(C.outcomes(close, everyday, side), side)
        result[f"baseline_{side}"] = base
        for name, mask in group.items():
            idx = C.episodes(mask, valid)
            table = C.outcomes(close, idx, side)
            stats = C.summary(table, side)
            stats["signal_days"] = int((mask & valid).sum())
            stats["p_shift"] = C.shift_p(close, mask, valid, side) if idx else None
            if not table.empty:
                table.insert(0, "date", [str(dates[i]) for i in table["i"]])
                table.insert(1, "close", [float(close[i]) for i in table["i"]])
                stats["events"] = table.drop(columns="i").round(4).to_dict("records")
            limit = 0.10 if side == "buy" else 0.02
            sign = 1 if side == "buy" else -1
            if stats["n"] < 8:
                stats["verdict"] = "样本不足"
            else:
                checks = [
                    round(stats["near"] - base["near"], 4) >= 0.15,
                    sign * (stats["ret60_median"] - base["ret60_median"]) > 0,
                    stats["ret60_right"] > base["ret60_right"],
                    stats["p_shift"] <= limit,
                ]
                stats["checks"] = [bool(x) for x in checks]
                stats["verdict"] = "通过" if all(checks) else "未通过"
            result["candidates"][name] = stats
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stocks", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "reports" / "breadth_signal")
    parser.add_argument("--rebuild-only", action="store_true")
    args = parser.parse_args()
    if REBUILT.is_file() and not args.rebuild_only:
        rebuilt = pd.read_csv(REBUILT)
    else:
        rebuilt = rebuild(args.stocks)
        rebuilt.round(6).to_csv(REBUILT, index=False)
    args.out.mkdir(parents=True, exist_ok=True)
    check = consistency(rebuilt)
    (args.out / "consistency.json").write_text(json.dumps(check, ensure_ascii=False, indent=2), encoding="utf-8")
    print("consistency", check)
    if args.rebuild_only:
        return
    result = evaluate(rebuilt)
    result["consistency"] = check
    (args.out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, stats in result["candidates"].items():
        print(name, {k: v for k, v in stats.items() if k != "events"})


if __name__ == "__main__":
    main()
