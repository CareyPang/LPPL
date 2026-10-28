"""沪深 300 历史成分股（PIT 快照）个股日线：不复权价 + 新浪后复权因子 → 自算后复权价。

python -m research.data.stocks  →  data/cache/stocks/<sym>.parquet + data/frozen/stocks_v<date>/manifest.json
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
UNIVERSE = ROOT / "data" / "universe"
CACHE = ROOT / "data" / "cache" / "stocks"
GAP = 1.7
UTC = timezone.utc  # noqa: UP017


def universe() -> list[str]:
    syms: set[str] = set()
    for f in sorted(UNIVERSE.glob("csi300_*.csv")):
        u = pd.read_csv(f, dtype=str)
        syms |= {m.lower() + c for c, m in zip(u.code, u.market, strict=True)}
    return sorted(syms)


def _raw(sym: str) -> tuple[pd.DataFrame, str]:
    import akshare as ak

    try:
        df = ak.stock_zh_a_daily(symbol=sym, adjust="")
        if len(df):
            return df, "sina"
    except Exception:  # noqa: BLE001
        pass
    from .sources import fetch_tencent

    return fetch_tencent(sym[:2], sym[2:], False, adjust=""), "tencent"


def _factor(sym: str) -> pd.DataFrame:
    import akshare as ak

    f = ak.stock_zh_a_daily(symbol=sym, adjust="hfq-factor")
    f = f.rename(columns={f.columns[1]: "hfq_factor"})
    f["date"] = pd.to_datetime(f["date"])
    f["hfq_factor"] = pd.to_numeric(f["hfq_factor"])
    return f[f["date"] > "1900-01-02"].sort_values("date")[["date", "hfq_factor"]]


def build(sym: str) -> dict:
    raw, src = _raw(sym)
    time.sleep(GAP)
    raw = raw.copy()
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.sort_values("date")[["date", "open", "high", "low", "close", "volume"]]
    fac = _factor(sym)
    time.sleep(GAP)
    df = pd.merge_asof(raw, fac, on="date", direction="backward")
    df["hfq_factor"] = df["hfq_factor"].fillna(1.0)
    df["close_hfq"] = df["close"].astype(float) * df["hfq_factor"]
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{sym}.parquet"
    df.to_parquet(path, index=False)
    return dict(
        symbol=sym, source=src, factor_source="sina_hfq_factor", rows=len(df),
        first=str(df["date"].iloc[0].date()), last=str(df["date"].iloc[-1].date()),
        factor_rows=len(fac), nonpositive=int((df["close_hfq"] <= 0).sum()),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def main() -> None:
    tag = datetime.now(UTC).strftime("%Y%m%d")
    out = ROOT / "data" / "frozen" / f"stocks_v{tag}"
    out.mkdir(parents=True, exist_ok=True)
    mf = out / "manifest.json"
    done = {e["symbol"]: e for e in json.loads(mf.read_text())["symbols"]} if mf.exists() else {}
    for i, sym in enumerate(universe()):
        if sym in done and "error" not in done[sym]:
            continue
        try:
            done[sym] = build(sym)
        except Exception as e:  # noqa: BLE001
            done[sym] = dict(symbol=sym, error=f"{type(e).__name__}: {str(e)[:150]}")
            time.sleep(GAP)
        mf.write_text(json.dumps(dict(
            downloaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
            universe_files=sorted(p.name for p in UNIVERSE.glob("csi300_*.csv")),
            symbols=sorted(done.values(), key=lambda e: e["symbol"]),
        ), ensure_ascii=False, indent=1))
        if i % 25 == 0:
            print(i, sym, done[sym].get("rows", done[sym].get("error")), flush=True)


if __name__ == "__main__":
    main()
