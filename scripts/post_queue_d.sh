#!/usr/bin/env bash
# 长程任务收尾：等队列 C（个股样本扫描）结束后，跑负泡沫/反泡沫按年拆分、个股排名评价、合并报告。
set -u
cd "$(dirname "$0")/.."
PID=${1:?queue c pid}
while kill -0 "$PID" 2>/dev/null; do sleep 120; done
run() { echo "[$(date +%T)] $*"; "$@" 2>&1 | grep -v Warning; }
export LPPLS_BOX=v2
echo "[$(date +%T)] queue d start"
run /usr/bin/python3 -m research.eval.by_year data/features/lppls_v2_neg_lite bottom
run /usr/bin/python3 -m research.eval.by_year data/features/lppls_v2_ab_lite bottom
run /usr/bin/python3 -m research.eval.stock_rank_eval data/features/lppls_v2_lite_stk100 pos stk100_pos
run /usr/bin/python3 -m research.eval.stock_rank_eval data/features/lppls_v2_neg_lite_stk100 neg stk100_neg
run /usr/bin/python3 -m research.eval.summary_v2 v2
echo "[$(date +%T)] queue d done"
