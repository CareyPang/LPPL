#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SITE="$ROOT/_site"

rm -rf "$SITE"
mkdir -p "$SITE/lab"
cp -a "$ROOT/frontend/." "$SITE/"
rm -rf "$SITE/vendor-src/lwc/node_modules"
cp -a "$ROOT/web/." "$SITE/lab/"
rm -rf "$SITE/assets/visual-suite/masters" "$SITE/docs/visual-evidence"
if git -C "$ROOT" show-ref --quiet --verify refs/heads/stock-results; then
  mkdir -p "$SITE/lab/mock/data"
  git -C "$ROOT" archive stock-results stock | tar -x -C "$SITE/lab/mock/data/"
  if git -C "$ROOT" cat-file -e stock-results:nt_etf/nt_etf_latest.json 2>/dev/null; then
    mkdir -p "$SITE/lab/mock/data/nt_etf"
    git -C "$ROOT" archive stock-results nt_etf | tar -x -C "$SITE/lab/mock/data/"
  fi
  if git -C "$ROOT" cat-file -e stock-results:global/catalog.json 2>/dev/null; then
    mkdir -p "$SITE/lab/mock/data/global"
    git -C "$ROOT" archive stock-results global | tar -x -C "$SITE/lab/mock/data/"
  fi
  if git -C "$ROOT" cat-file -e stock-results:market 2>/dev/null; then
    git -C "$ROOT" archive stock-results market | tar -x -C "$SITE/lab/mock/data/"
  fi
  if git -C "$ROOT" cat-file -e stock-results:events/events_latest.json 2>/dev/null; then
    mkdir -p "$SITE/lab/mock/data/events"
    git -C "$ROOT" archive stock-results events | tar -x -C "$SITE/lab/mock/data/"
  fi
  if git -C "$ROOT" cat-file -e stock-results:macro/macro_latest.json 2>/dev/null; then
    mkdir -p "$SITE/lab/mock/data/macro"
    git -C "$ROOT" archive stock-results macro | tar -x -C "$SITE/lab/mock/data/"
  fi
  if git -C "$ROOT" cat-file -e stock-results:growth/growth_latest.json 2>/dev/null; then
    mkdir -p "$SITE/lab/mock/data/growth"
    git -C "$ROOT" archive stock-results growth | tar -x -C "$SITE/lab/mock/data/"
  fi
  if git -C "$ROOT" cat-file -e stock-results:strategy 2>/dev/null; then
    mkdir -p "$SITE/lab/mock/data/strategy"
    git -C "$ROOT" archive stock-results strategy | tar -x -C "$SITE/lab/mock/data/"
  fi
  if git -C "$ROOT" cat-file -e stock-results:index 2>/dev/null; then
    git -C "$ROOT" archive stock-results index | tar -x -C "$SITE/lab/mock/data/"
    python3 - "$SITE/lab/mock/data/index" "$SITE/lab/mock/data" <<'PY'
import json
import shutil
import sys
from datetime import date
from pathlib import Path

source_dir, target_dir = map(Path, sys.argv[1:])


def asof(path: Path) -> date | None:
    try:
        return date.fromisoformat(json.loads(path.read_text(encoding="utf-8"))["asof"])
    except (KeyError, OSError, TypeError, ValueError):
        return None


for source in sorted(source_dir.glob("*_latest.json")):
    target = target_dir / source.name
    published_asof = asof(source)
    committed_asof = asof(target) if target.exists() else None
    if published_asof is None:
        print(f"skip index {source.name}: invalid published asof")
        continue
    if target.exists() and (
        committed_asof is None or published_asof < committed_asof
    ):
        print(f"skip index {source.name}: published asof {published_asof} older or invalid")
        continue
    shutil.copyfile(source, target)
PY
  fi
fi
mkdir -p "$SITE/lab/mock/data"
cp "$ROOT/reports/bottom_calibration.json" "$SITE/lab/mock/data/"
cp "$ROOT/reports/bottom_location.json" "$SITE/lab/mock/data/"
cp "$ROOT/reports/long_window_pit.json" "$SITE/lab/mock/data/"
