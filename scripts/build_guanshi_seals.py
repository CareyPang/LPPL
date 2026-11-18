"""Project recent, same-day Shanghai-index seals from immutable git blobs for the research UI."""

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

SYMBOL = "sh000001"
SHANGHAI = timezone(timedelta(hours=8))
MAX_RECORDS = 12
BAR_LIMIT = 100


def iso_day(value: str) -> date:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("noncanonical date")
    return parsed


def project(row: dict, raw: bytes, commit: str) -> dict:
    asof = iso_day(row["asof"])
    if row["symbol"] != SYMBOL or row["path"] != f"forward_log/{asof}/{SYMBOL}.json":
        raise ValueError("unexpected asset or ledger path")
    sealed = datetime.fromisoformat(row["sealed_at"])
    if sealed.utcoffset() is None:
        raise ValueError("seal is missing its UTC offset")
    local = sealed.astimezone(SHANGHAI)
    if local.date() != asof or local.time() < time(15):
        raise ValueError("seal is not from the local trading day's close or later")
    if hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise ValueError("blob does not match the ledger SHA-256")
    original = json.loads(raw)
    if any(not row.get(k) or original.get(k) != row[k]
           for k in ("asof", "symbol", "model_version", "data_version")):
        raise ValueError("record does not match ledger identity or versions")

    prices = original.get("price_history") or {}
    days = prices.get("dates") or []
    if not days or days != sorted(set(days)) or iso_day(days[-1]) != asof:
        raise ValueError("no unique chronological price history ending at the cutoff")
    for value in days:
        iso_day(value)
    # The latest known price series belongs to the original seal's vintage.
    # Missing OHLC or volume stay missing. Never borrow an earlier bar from a later seal.
    if not isinstance(prices.get("close"), list):
        raise ValueError("missing closing-price series")
    trimmed = {"dates": days[-BAR_LIMIT:]}
    for k in ("open", "high", "low", "close", "volume"):
        series = prices.get(k)
        if series is None:
            continue
        if not isinstance(series, list) or len(series) != len(days):
            raise ValueError(f"misaligned {k} series")
        trimmed[k] = series[-BAR_LIMIT:]
    if "note" in prices:
        trimmed["note"] = prices["note"]
    top = original["top"]
    output_top = {k: top[k] for k in ("signal_status", "scale_windows", "scale_clusters",
                                        "evidence_override") if k in top}
    if "scale_evidence" in top.get("lppls_confidence", {}):
        output_top["lppls_confidence"] = {"scale_evidence": top["lppls_confidence"]["scale_evidence"]}
    if "indicators" in top:
        output_top["indicators"] = {
            k: {"signal_status": entry.get("signal_status")}
            for k, entry in top["indicators"].items() if isinstance(entry, dict)
        }
    record = {k: original[k] for k in ("symbol", "name", "asof", "model_version", "data_version")}
    record.update(top=output_top, price_history=trimmed)
    return {
        "asof": row["asof"], "sealed_at": row["sealed_at"], "sha256": row["sha256"],
        "path": f"https://github.com/CareyPang/LPPL/blob/{commit}/{row['path']}", "record": record,
    }


def build(root: Path) -> dict:
    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", "-C", str(root), *args])

    commit = git("rev-parse", "--verify", "HEAD").decode("ascii").strip()

    def blob(path: str) -> bytes:
        return git("cat-file", "blob", f"{commit}:{path}")

    ledger = [json.loads(line) for line in blob("forward_log/ledger.jsonl").splitlines() if line.strip()]
    rows = [row for row in ledger if row["symbol"] == SYMBOL]
    counts = Counter(row["asof"] for row in rows)
    records = []
    for row in sorted(rows, key=lambda item: item["asof"], reverse=True):
        try:
            asof = iso_day(row["asof"])
            if counts[row["asof"]] != 1:
                raise ValueError("duplicate ledger key")
            # Build the path from the validated key, never from unverified ledger text.
            raw = blob(f"forward_log/{asof}/{SYMBOL}.json")
            records.append(project(row, raw, commit))
        except (KeyError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
            print(f"Guanshi skipped seal {row.get('asof')}: {exc}", file=sys.stderr)
            continue
        if len(records) >= MAX_RECORDS:
            break
    return {"symbol": SYMBOL, "records": records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    catalog = build(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(catalog, ensure_ascii=False, allow_nan=False,
                                   separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
