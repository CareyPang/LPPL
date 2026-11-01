#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SITE="$ROOT/_site"

rm -rf "$SITE"
mkdir -p "$SITE/lab"
cp -a "$ROOT/frontend/." "$SITE/"
cp -a "$ROOT/web/." "$SITE/lab/"
