#!/usr/bin/env bash
# §17.6 补齐队列：等 post_scan_pipeline_v2.sh 结束后依次跑 XS 探索尺度、负泡沫（lite）、反泡沫（lite）指数扫描与评价。
set -u
cd "$(dirname "$0")/.."
PID=${1:?pipeline v2 pid}
while kill -0 "$PID" 2>/dev/null; do sleep 120; done
run() { echo "[$(date +%T)] $*"; "$@" 2>&1 | grep -v Warning; }
export LPPLS_BOX=v2
echo "[$(date +%T)] queue b start"
LPPLS_WINDOWS=xs run /usr/bin/python3 -m research.features.lppls_scan index dev
LPPLS_SIGN=neg LPPLS_WINDOWS=lite run /usr/bin/python3 -m research.features.lppls_scan index dev
LPPLS_SIGN=neg LPPLS_WINDOWS=lite OS_TARGET=bottom run /usr/bin/python3 -m research.eval.original_standard
LPPLS_ANCHOR=start LPPLS_WINDOWS=lite run /usr/bin/python3 -m research.features.lppls_scan index dev
LPPLS_ANCHOR=start LPPLS_WINDOWS=lite OS_TARGET=bottom run /usr/bin/python3 -m research.eval.original_standard
echo "[$(date +%T)] queue b done"
run /usr/bin/python3 -m research.eval.summary_v2 v2
