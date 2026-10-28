#!/usr/bin/env bash
# §17.11 长程任务 B：等 post_scan_pipeline_v2b.sh 结束后跑个股样本（100 只）正/负泡沫 lite 扫描。
set -u
cd "$(dirname "$0")/.."
PID=${1:?queue b pid}
while kill -0 "$PID" 2>/dev/null; do sleep 120; done
run() { echo "[$(date +%T)] $*"; "$@" 2>&1 | grep -v Warning; }
export LPPLS_BOX=v2 LPPLS_WINDOWS=lite LPPLS_STOCK_SAMPLE=100
echo "[$(date +%T)] queue c start"
run /usr/bin/python3 -m research.features.lppls_scan stock dev
LPPLS_SIGN=neg run /usr/bin/python3 -m research.features.lppls_scan stock dev
echo "[$(date +%T)] queue c scans done"
