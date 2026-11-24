"""Index daily record runner with a published PIT aftershock supplement."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from ..data import cache
from ..features.aftershock import analyze_aftershock
from . import daily


def _data_version(source: pd.DataFrame, frozen: bool) -> str:
    if frozen:
        return f"frozen_{daily.FROZEN}"
    return f"vintage_{source.attrs['vintage']}_{source.attrs['source']}"


def enrich_record(record: dict, source: pd.DataFrame, version: str) -> dict:
    symbol = record["symbol"]
    asof = record["asof"]
    cutoff = pd.Timestamp(asof)
    frame = source.sort_values("date").reset_index(drop=True)
    frame = frame.loc[frame.date <= cutoff, ["date", "close"]].copy()
    analysis = analyze_aftershock(
        symbol,
        frame,
        str(cutoff.date()),
        {
            "symbol": symbol,
            "asset_id": symbol,
            "data_version": record.get("data_version") or version,
            "source": record.get("source")
            or (record.get("price_history") or {}).get("source")
            or version,
            "timezone": record.get("timezone"),
        },
        archive_root=None,
    )
    return {
        **record,
        "research": {**(record.get("research") or {}), "aftershock": analysis},
    }


def run(
    sym: str,
    frozen: bool = False,
    asof: str | None = None,
    windows: tuple[int, ...] | None = None,
    out: Path = daily.OUT,
    trust_boot: int = 100,
    opt: str | None = None,
) -> Path:
    path = daily.run(
        sym,
        frozen=frozen,
        asof=asof,
        windows=windows,
        out=out,
        trust_boot=trust_boot,
        opt=opt,
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    try:
        source = cache.load(
            sym,
            frozen=daily.FROZEN if frozen else None,
            auto_refresh=False,
        )
        version = _data_version(source, frozen)
        if version != record.get("data_version"):
            reason = "price_vintage_mismatch"
        else:
            record = enrich_record(record, source, version)
            reason = None
    except Exception as error:
        reason = f"{type(error).__name__}: {error}"
    if reason is not None:
        record["research"] = {
            **(record.get("research") or {}),
            "aftershock_status": {"status": "unavailable", "reason": reason},
        }
        print(
            f"Warning: aftershock enrichment unavailable for {sym}: {reason}",
            file=sys.stderr,
        )
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1, default=str))
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sym")
    parser.add_argument("--frozen", action="store_true")
    parser.add_argument("--asof")
    parser.add_argument("--windows", help="逗号分隔窗口长度（自检用）")
    parser.add_argument("--out", type=Path, default=daily.OUT)
    parser.add_argument("--opt", default="g3", choices=sorted(daily.OPTIMIZER_NAMES))
    args = parser.parse_args()
    windows = tuple(int(value) for value in args.windows.split(",")) if args.windows else None
    path = run(
        args.sym,
        frozen=args.frozen,
        asof=args.asof,
        windows=windows,
        out=args.out,
        opt=args.opt,
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    print(path, json.dumps(record["top"]["lppls_confidence"], ensure_ascii=False))


if __name__ == "__main__":
    main()
