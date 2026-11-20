"""Recreate the frozen 510210 research sample from Sohu or an archived response."""

import argparse
import csv
import hashlib
import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE = (
    "https://q.stock.sohu.com/hisHq?code=cn_510210&start=20251127"
    "&end=20261118&stat=1&order=D&period=d"
)
CSV_SHA256 = "804467fc8d19b417e460944bbabdecfc6e2fbe80ec22dd3b09634299d83c07b3"
FIRST, LAST, SESSIONS = "2025-11-27", "2026-11-18", 236


def frozen_csv(raw: bytes) -> bytes:
    pages = json.loads(raw.decode("gb18030"))
    if len(pages) != 1 or pages[0]["status"] != 0 or pages[0]["code"] != "cn_510210":
        raise ValueError("unexpected Sohu symbol or response status")
    rows = {}
    for item in pages[0]["hq"]:
        day = date.fromisoformat(item[0]).isoformat()
        if day in rows or not FIRST <= day <= LAST:
            raise ValueError(f"duplicate or out-of-range session: {day}")
        opening, high, low, close = (Decimal(item[i]) for i in (1, 6, 5, 2))
        volume = int(item[7])
        if not (0 < low <= min(opening, close) <= max(opening, close) <= high) or volume <= 0:
            raise ValueError(f"invalid price or volume: {day}")
        prices = (opening, high, low, close)
        if any(value != value.quantize(Decimal(".001")) for value in prices):
            raise ValueError(f"price outside tick precision: {day}")
        rows[day] = [day, *(f"{value:.3f}" for value in prices), volume]

    if len(rows) != SESSIONS or min(rows) != FIRST or max(rows) != LAST:
        raise ValueError("incomplete session coverage")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(("date", "open", "high", "low", "close", "volume_lots"))
    writer.writerows(rows[day] for day in sorted(rows))
    data = stream.getvalue().encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    if digest != CSV_SHA256:
        raise ValueError(f"quote revision or field mismatch: expected {CSV_SHA256}, got {digest}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="local research CSV path")
    parser.add_argument("--from-raw", type=Path, help="use a saved Sohu JSON response offline")
    args = parser.parse_args()
    if args.from_raw:
        raw = args.from_raw.read_bytes()
    else:
        request = Request(SOURCE, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=30) as response:
            raw = response.read()
    data = frozen_csv(raw)
    if args.output.exists():
        if args.output.read_bytes() != data:
            raise ValueError(f"output already contains a different sample: {args.output}")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as target:
            target.write(data)
    print(f"{args.output}: {SESSIONS} sessions, sha256={CSV_SHA256}")


if __name__ == "__main__":
    main()
