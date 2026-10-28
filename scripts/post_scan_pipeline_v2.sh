#!/usr/bin/env bash
# §17.4 扫描 v2 结束后无人值守流水线（开发段；不碰校准/测试段）。用法：scripts/post_scan_pipeline_v2.sh <scan_pid>
set -u
cd "$(dirname "$0")/.."
PID=${1:?scan pid}
while kill -0 "$PID" 2>/dev/null; do sleep 60; done
export LPPLS_BOX=v2
echo "[$(date +%T)] scan v2 finished; files: $(ls data/features/lppls_v2 | wc -l)"
run() { echo "[$(date +%T)] $*"; "$@" 2>&1 | grep -v Warning; }
# 1. 原版标准评分（主评价）
run /usr/bin/python3 -m research.eval.original_standard
# 2. 次要检验：CPCV Brier，20 日与 60 日视窗
run /usr/bin/python3 -m research.eval.ladder_lppls ci
LABEL_VARIANT=h60 run /usr/bin/python3 -m research.eval.ladder_lppls ci
run /usr/bin/python3 -m research.eval.ladder_lppls ci full
run /usr/bin/python3 -m research.eval.mt_report data/oof/ladder_dev_full_v2_losses.parquet ladder_dev_full_v2
echo "[$(date +%T)] pipeline v2 done"
