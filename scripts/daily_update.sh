#!/usr/bin/env bash
# D1 日更：刷新 6 指数行情（AkShare，限速）→ 最新 as-of 日 LPPLS 拟合 → 契约 JSON（web/mock/data/<sym>_latest.json）
# SYMS 可用空格分隔的指数列表覆盖默认列表；SKIP_SEAL=1 跳过 guide、forward_log seal 和 market_base。
# 用法：scripts/daily_update.sh [--frozen]   （--frozen 不联网，用冻结数据，供离线自检）
set -euo pipefail
cd "$(dirname "$0")/.."
export LPPLS_BOX=v2
default_syms="sh000001 sh000016 sh000300 sh000905 sz399001 sz399006"
read -r -a syms <<< "${SYMS:-$default_syms}"
for s in "${syms[@]}"; do
  python -m research.pipeline.daily "$s" "$@"
  missing=()
  for split_dir in data/features/lppls_v2_g3 data/features/lppls_v2_g3_cal data/features/lppls_v2_g3_test; do
    [[ -f "$split_dir/$s.parquet" ]] || missing+=("$split_dir/$s.parquet")
  done
  if ((${#missing[@]} == 0)); then
    python -m research.eval.export_contract history "$s"
  else
    printf 'Skipping history export for %s; missing scans: %s (existing history kept)\n' "$s" "${missing[*]}" >&2
  fi
done
if [[ "${SKIP_SEAL:-0}" != "1" ]]; then
  cp docs/user_guide.md web/mock/guide.md   # 教育页 web/guide.html 读取的副本，随日更同步
  python -m research.pipeline.forward_log seal
  python -m research.data.market_base || echo "market_base failed (non-fatal)"
fi
