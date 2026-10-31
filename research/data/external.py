"""外部市场数据冻结（Round 2 §2.0；只冻结不评价）。

源：Yahoo Finance v8 chart（日线，period1=1980）；备用 AkShare 东财全球指数（VM 上不稳）。
已有版本目录只校验哈希、不覆写；抓取当日的 bar 一律剔除（可能未收盘）。
输出：data/frozen/ext_<版本>/<sym>.parquet（date, open, high, low, close, adj_close, volume）+ MANIFEST.json（行数、起止、sha256）。
python -m research.data.external [version]   默认版本 = 今天 vYYYYMMDD
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = {"HSI": "^HSI", "SPX": "^GSPC", "NDX": "^NDX", "N225": "^N225"}
P1 = int(dt.datetime(1980, 1, 1, tzinfo=dt.timezone.utc).timestamp())  # noqa: UP017


def fetch_yahoo(ticker: str) -> pd.DataFrame:
    q = urllib.parse.quote(ticker)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?period1={P1}&period2={int(time.time())}&interval=1d&events=div%2Csplit"
    raw = json.load(
        urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=120
        )
    )
    r = raw["chart"]["result"][0]
    qt = r["indicators"]["quote"][0]
    adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose", qt["close"])
    df = pd.DataFrame(
        dict(
            date=pd.to_datetime(r["timestamp"], unit="s", utc=True).tz_convert(None).normalize(),
            open=qt["open"],
            high=qt["high"],
            low=qt["low"],
            close=qt["close"],
            adj_close=adj,
            volume=qt["volume"],
        )
    )
    df = (
        df.dropna(subset=["close"])
        .drop_duplicates("date")
        .sort_values("date")
        .reset_index(drop=True)
    )
    # 只保留已完成的交易日：抓取当日（UTC）的 bar 可能仍在盘中，一律剔除
    today = pd.Timestamp(dt.datetime.now(dt.timezone.utc).date())  # noqa: UP017
    return df[df.date < today].reset_index(drop=True)


def verify(out: Path) -> bool:
    """已有版本目录：逐文件比对 MANIFEST 哈希，只报告一致 / 冲突，不改写。"""
    man = json.loads((out / "MANIFEST.json").read_text())
    ok = True
    for sym, m in man["symbols"].items():
        f = out / f"{sym}.parquet"
        h = hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else None
        same = h == m["sha256"]
        ok &= same
        print(sym, "OK" if same else f"MISMATCH/MISSING (have {h}, manifest {m['sha256']})")
    return ok


def main(version: str | None = None) -> None:
    version = version or dt.date.today().strftime("v%Y%m%d")
    out = ROOT / "data/frozen" / f"ext_{version}"
    if (out / "MANIFEST.json").exists():
        print(f"{out.name} 已存在：只校验不覆写（新数据请用新版本号）")
        sys.exit(0 if verify(out) else 1)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": version,
        "source": "yahoo_v8_chart",
        "fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017
        "symbols": {},
    }
    for sym, tk in SYMBOLS.items():
        df = fetch_yahoo(tk)
        f = out / f"{sym}.parquet"
        df.to_parquet(f, index=False)
        manifest["symbols"][sym] = dict(
            ticker=tk,
            rows=int(len(df)),
            start=str(df.date.iloc[0].date()),
            end=str(df.date.iloc[-1].date()),
            sha256=hashlib.sha256(f.read_bytes()).hexdigest(),
        )
        print(sym, len(df), df.date.iloc[0].date(), df.date.iloc[-1].date(), flush=True)
        time.sleep(2)
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps(manifest["symbols"], indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
