#!/usr/bin/env bash
# 扫描结束后无人值守流水线（开发段；不碰校准/测试段）。用法：scripts/post_scan_pipeline.sh <scan_pid>
set -u
cd "$(dirname "$0")/.."
PID=${1:?scan pid}
while kill -0 "$PID" 2>/dev/null; do sleep 60; done
echo "[$(date +%T)] scan finished; indices: $(ls data/features/lppls_v1 | wc -l)"
run() { echo "[$(date +%T)] $*"; "$@" 2>&1 | grep -v Warning; }
# 1. §12.2 算力门：R3/R4 相对当前保留链（主链 + 次要链）
run /usr/bin/python3 -m research.eval.ladder_lppls ci
run /usr/bin/python3 -m research.eval.ladder_lppls point
# 2. 预登记顺序完整重算（主链 + 次要链），并输出逐日损失矩阵
run /usr/bin/python3 -m research.eval.ladder_lppls ci full
run /usr/bin/python3 -m research.eval.ladder_lppls point full
# 3. 多重比较诊断
run /usr/bin/python3 -m research.eval.mt_report data/oof/ladder_dev_full_losses.parquet ladder_dev_full
run /usr/bin/python3 -m research.eval.mt_report data/oof/ladder_dev_full_point_losses.parquet ladder_dev_full_point
# 4. T-INT 顶部区间（开发段）
run /usr/bin/python3 -m research.eval.run_interval
# 5. D-TOP 在新保留链末级 OOF 上重跑
for t in ladder_dev_full ladder_dev_full_point; do
  oof=$(/usr/bin/python3 -c "import json;print(json.load(open('reports/$t.json')).get('last_oof') or '')")
  [ -n "$oof" ] && run /usr/bin/python3 -m research.eval.decision "$oof" "dtop_${t#ladder_}"
done
echo "[$(date +%T)] pipeline done"
