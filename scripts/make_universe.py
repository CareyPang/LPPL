"""Generate a latest-member, non-PIT stock universe from universe_current.json."""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "web" / "mock" / "data"
UNIVERSE_NAMES = {"sh000905": "csi500"}
INDEX_NAMES = {"sh000905": "中证500"}


def make_universe(
    index: str,
    source_path: Path | None = None,
    output_dir: Path | None = None,
) -> Path:
    if not re.fullmatch(r"(sh|sz)\d{6}", index):
        raise ValueError(f"invalid index symbol: {index!r}")
    source = source_path or DATA_DIR / "universe_current.json"
    current = json.loads(source.read_text(encoding="utf-8"))
    codes = current.get("indices", {}).get(index)
    snapshot = current.get("source_date", {}).get(index)
    if not isinstance(codes, list) or not codes:
        raise ValueError(f"no current constituents for {index}")
    if not isinstance(snapshot, str):
        raise ValueError(f"no source date for {index}")
    try:
        parsed_snapshot = date.fromisoformat(snapshot)
    except ValueError as exc:
        raise ValueError(f"invalid source date for {index}: {snapshot!r}") from exc
    if parsed_snapshot.isoformat() != snapshot:
        raise ValueError(f"invalid source date for {index}: {snapshot!r}")
    if any(not isinstance(code, str) or not re.fullmatch(r"\d{6}", code) for code in codes):
        raise ValueError(f"invalid member code in {index}")
    if len(codes) != len(set(codes)):
        raise ValueError(f"duplicate member codes in {index}")
    if index == "sh000905" and len(codes) != 500:
        raise ValueError(f"sh000905 must contain 500 members, found {len(codes)}")

    index_name = INDEX_NAMES.get(index, index)
    universe_name = UNIVERSE_NAMES.get(index, index)
    payload = {
        "index": index,
        "snapshot": snapshot,
        "note": f"{index_name} 最近公布成分（非 PIT，{snapshot}）",
        "codes": codes,
    }
    target_dir = output_dir or DATA_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"universe_{universe_name}.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", help="index symbol, e.g. sh000905")
    args = parser.parse_args()
    print(make_universe(args.index))


if __name__ == "__main__":
    main()
