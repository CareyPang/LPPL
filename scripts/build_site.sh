#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SITE="$ROOT/_site"

rm -rf "$SITE"
mkdir -p "$SITE/lab"
cp -a "$ROOT/frontend/." "$SITE/"
cp -a "$ROOT/web/." "$SITE/lab/"
if git -C "$ROOT" show-ref --quiet --verify refs/heads/stock-results; then
  mkdir -p "$SITE/lab/mock/data"
  git -C "$ROOT" archive stock-results stock | tar -x -C "$SITE/lab/mock/data/"
fi
