"""1990 年代 A 股指数日线冻结（§21.3 (c)；只冻结不评价）。

源：新浪（AkShare `stock_zh_index_daily`，`sources.fetch_ak_sina_index`），不复权（指数无复权）。
为何不用现行冻结版 v20261024（腾讯）的 1990s 段：腾讯 sh000001 1990-12-19—1992-08 只有 346 行且数值与公开历史不符
（1990-12-19 收 113.1，1992 年 5 月仍 ~139；实际 99.98 / 1266），1992 年缺 165 个交易日；sz399001 腾讯自 1993-01-03 起
（首行是周日），1995-02—04 有 56 日日期错位。新浪两指数的高/低点与公开历史（1992-05-26 高 1429.01、1992-11-17 低 386.85、
1993-02-16 高 1558.95、1994-07-29 低 325.89、1999-06-30 高 1756.18）逐点一致；1993–2000 段与腾讯收盘仅 4 日差异。
sz399001 以 1994-07-20=1000 为基日，1991-04-03—1994-07-19 为回算值（源依赖），报告中单列。
已有版本目录只校验哈希、不覆写；截止日 END 之后的 bar 不写入（评价 as-of 限 1990 年代，2000 年只为 250 日标签视野留出）。
python -m research.data.a90s [version]   默认版本 = 今天 vYYYYMMDD
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

import pandas as pd

from research.data import sources as S

ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = {"sh000001": ("sh", "000001", "1990-12-19"), "sz399001": ("sz", "399001", "1991-04-03")}
END = "2000-12-31"


def fetch(market: str, six: str, start: str) -> pd.DataFrame:
    df = S.fetch_ak_sina_index(market, six, True)
    df = df.dropna(subset=["close"]).drop_duplicates("date").sort_values("date")
    df = df[(df.date >= pd.Timestamp(start)) & (df.date <= pd.Timestamp(END))]
    today = pd.Timestamp(dt.datetime.now(dt.timezone.utc).date())  # noqa: UP017
    return df[df.date < today].reset_index(drop=True)


def verify(out: Path) -> bool:
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
    out = ROOT / "data/frozen" / f"a90s_{version}"
    if (out / "MANIFEST.json").exists():
        print(f"{out.name} 已存在：只校验不覆写（新数据请用新版本号）")
        sys.exit(0 if verify(out) else 1)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": version,
        "source": "ak_sina_index",
        "adjust": "none(index)",
        "end": END,
        "fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017
        "symbols": {},
    }
    for sym, (mk, six, start) in SYMBOLS.items():
        df = fetch(mk, six, start)
        if df.date.iloc[0] != pd.Timestamp(start):
            raise RuntimeError(f"{sym} 首日 {df.date.iloc[0].date()} ≠ 登记首日 {start}")
        f = out / f"{sym}.parquet"
        df.to_parquet(f, index=False)
        manifest["symbols"][sym] = dict(
            registered_start=start,
            rows=int(len(df)),
            start=str(df.date.iloc[0].date()),
            end=str(df.date.iloc[-1].date()),
            weekend_rows=int((df.date.dt.weekday >= 5).sum()),
            nonpositive=int((df.close <= 0).sum()),
            sha256=hashlib.sha256(f.read_bytes()).hexdigest(),
        )
        print(sym, len(df), df.date.iloc[0].date(), df.date.iloc[-1].date(), flush=True)
        time.sleep(3)
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps(manifest["symbols"], indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
