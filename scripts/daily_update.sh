#!/usr/bin/env bash
# D1 日更：刷新 6 指数行情（AkShare，限速）→ 最新 as-of 日 LPPLS 拟合 → 契约 JSON（web/mock/data/<sym>_latest.json）
# 用法：scripts/daily_update.sh [--frozen]   （--frozen 不联网，用冻结数据，供离线自检）
set -euo pipefail
cd "$(dirname "$0")/.."
export LPPLS_BOX=v2
for s in sh000001 sh000016 sh000300 sh000905 sz399001 sz399006; do
  python -m research.pipeline.daily "$s" "$@"
done
