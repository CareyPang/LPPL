from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from ..data.us_watchlist import US_NAMES, US_WATCHLIST
from .stock import history, predict


def _write(path: Path, record: dict) -> None:
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )


def run(out: Path, weeks: int = 104, procs: int | None = None) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for ticker in US_WATCHLIST:
        code = f"US_{ticker}"
        name = US_NAMES[ticker]
        try:
            current = predict(code, variant="stk_lite", procs=procs)
            historical = history(
                code, weeks=weeks, variant="stk_lite", procs=procs
            )
            generated = datetime.now(timezone.utc).isoformat()  # noqa: UP017
            current["generated_at"] = generated
            historical["generated_at"] = generated
            _write(out / f"{code}.json", current)
            _write(out / f"{code}_history.json", historical)
            (out / f"{code}_error.json").unlink(missing_ok=True)
            index.append(
                {"ticker": ticker, "name": name, "asof": current["asof"], "ok": True}
            )
            print(f"{code}: ok {current['asof']}")
        except Exception as exc:  # noqa: BLE001 - a ticker failure must not stop the watchlist
            _write(
                out / f"{code}_error.json",
                {
                    "ticker": ticker,
                    "name": name,
                    "error": f"{type(exc).__name__}: {exc}",
                    "source": "sina_us_daily+sina_qfq_factor",
                    "license_note": "新浪美股数据，许可未确认，仅供个人研究",
                    "adjust": "multiplicative back-adjusted (splits + cash dividends)",
                },
            )
            index.append({"ticker": ticker, "name": name, "asof": None, "ok": False})
            print(f"{code}: err {type(exc).__name__}: {exc}")
    _write(out / "us_index.json", index)
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the fixed US stock watchlist")
    parser.add_argument("--out", type=Path, default=Path("out/stock"))
    parser.add_argument("--history-weeks", type=int, default=104)
    parser.add_argument("--procs", type=int, default=2)
    args = parser.parse_args()
    run(args.out, weeks=args.history_weeks, procs=args.procs)


if __name__ == "__main__":
    main()
