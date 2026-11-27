"""One-off archive of broad-ETF shares and prices before the daily series starts.

`collect` downloads raw exchange data (slow: the SSE endpoint is queried once per trading day);
`build` turns it into the compact file the market page reads next to the daily snapshot.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import requests

from research.data import nt_etf

SPLIT_LOG = 0.15
SPLIT_TOLERANCE = 0.15
WIDE_LIMIT_PRICE_LOG = 0.25  # ChiNext and STAR ETFs can move 20% in a day


def collect(start: str, end: str, out: Path) -> None:
    universe = json.loads(nt_etf.UNIVERSE_PATH.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    prices, errors = nt_etf._prices(universe, start, end)
    if errors:
        raise RuntimeError(f"price errors: {errors}")
    (out / "prices.json").write_text(json.dumps(prices))
    session = requests.Session()
    nt_etf._request(session, "https://www.sse.com.cn/", headers=nt_etf.HEADERS)
    sse_codes = {u["code"] for u in universe if u["exchange"] == "SH"}
    sse = {}
    for day in sorted({d for v in prices.values() for d in v}):
        rows = nt_etf._shanghai_etf(session, day)
        sse[day] = {c: rows[c]["shares_10k"] for c in sse_codes if c in rows}
    (out / "sse.json").write_text(json.dumps(sse))
    szse = {u["code"]: nt_etf._szse_history(session, u["code"], start, end) for u in universe if u["exchange"] == "SZ"}
    (out / "szse.json").write_text(json.dumps(szse))


def _is_split(share_ratio: float, price_ratio: float, price_log: float = SPLIT_LOG) -> bool:
    """A conversion moves shares and price by inverse ratios, and the price by more than the daily limit allows."""
    return (
        abs(math.log(share_ratio)) > SPLIT_LOG
        and abs(math.log(price_ratio)) > price_log
        and abs(math.log(share_ratio * price_ratio)) < SPLIT_TOLERANCE
    )


def adjust_splits(days: list[str], shares: list, close: list, price_log: float = SPLIT_LOG) -> tuple[list, list[dict]]:
    """Blank the share count on a day when shares were already converted but the price was not.

    Exchanges may report the converted share count one day before the price adjusts; shares x close would then be
    off by the conversion ratio for that day. Returns (shares, events); events list the days whose flow is undefined.
    """
    shares = list(shares)
    events = []
    last = None
    settled = set()
    for i, value in enumerate(shares):
        if value is None or close[i] is None:
            continue
        if i in settled:
            last = i
            continue
        if last is not None and shares[last] is not None:
            share_ratio = value / shares[last]
            price_same = close[i] / close[last]
            nxt = next((j for j in range(i + 1, len(days)) if close[j] is not None), None)
            if _is_split(share_ratio, price_same, price_log):
                events.append({"date": days[i], "ratio": round(share_ratio, 4), "no_flow": [days[i]]})
            elif nxt is not None and _is_split(share_ratio, close[nxt] / close[i], price_log):
                events.append({"date": days[nxt], "ratio": round(share_ratio, 4), "no_flow": [days[i], days[nxt]]})
                shares[i] = None
                settled.add(nxt)
                continue
        last = i
    return shares, events


def build(raw: Path, end_exclusive: str | None = None) -> dict:
    universe = json.loads(nt_etf.UNIVERSE_PATH.read_text(encoding="utf-8"))
    prices = json.loads((raw / "prices.json").read_text())
    sse = json.loads((raw / "sse.json").read_text())
    szse = json.loads((raw / "szse.json").read_text())
    days = sorted(d for d in {d for v in prices.values() for d in v} if not end_exclusive or d < end_exclusive)
    etfs, splits = {}, []
    for item in universe:
        code = item["code"]
        own = prices.get(code, {})
        listed = [i for i, d in enumerate(days) if d in own]
        if not listed:
            continue
        first = listed[0]
        span = days[first:]
        close = [own.get(d) for d in span]
        raw_shares = [
            (szse.get(code, {}).get(d) if item["exchange"] == "SZ" else sse.get(d, {}).get(code)) for d in span
        ]
        # a day without a close (suspended for a share conversion) has no row in the daily series either
        observed = [v / 10000 if v is not None and close[i] is not None else None for i, v in enumerate(raw_shares)]
        wide = any(k in item["category"] for k in ("创业板", "科创"))
        shares, events = adjust_splits(span, observed, close, WIDE_LIMIT_PRICE_LOG if wide else SPLIT_LOG)
        no_flow = {d for e in events for d in e["no_flow"]}
        flow, prior = [], None
        for i, day in enumerate(span):
            value = nt_etf.flow_yuan(shares[i], prior, close[i])
            flow.append(None if day in no_flow or value is None else round(value, 4))
            prior = shares[i]  # a day without shares or price breaks the chain: no multi-day change is booked as one day
        etfs[code] = {
            "from": first,
            "shares": [round(v, 6) if v is not None else None for v in shares],
            "close": close,
            "flow": flow,
        }
        splits += [{"code": code, "date": e["date"], "ratio": e["ratio"]} for e in events]
    return {
        "schema": "nt_etf_history_v1",
        "start": days[0],
        "end": days[-1],
        "units": {"shares": "亿份", "close": "元", "flow": "亿元"},
        "sources": "上交所 ETF 规模日报、深交所基金规模历史、腾讯日线收盘价（不复权）",
        "dates": days,
        "etfs": etfs,
        "splits": splits,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--end-exclusive")
    parser.add_argument("--out", type=Path, default=nt_etf.ROOT / "web/mock/data/nt_etf/nt_etf_history.json")
    args = parser.parse_args()
    if args.start and args.end:
        collect(args.start, args.end, args.raw)
    args.out.write_text(json.dumps(build(args.raw, args.end_exclusive), ensure_ascii=False, separators=(",", ":")))
