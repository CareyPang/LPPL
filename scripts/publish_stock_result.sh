#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
CODE="${CODE:-${STOCK_CODE:-}}"
VARIANT="${VARIANT:-${STOCK_VARIANT:-stk_lite}}"
HISTORY_WEEKS="${HISTORY_WEEKS:-${STOCK_HISTORY_WEEKS:-104}}"
RESULT_DIR="${STOCK_RESULT_DIR:-$ROOT/out/stock}"
RUN_URL="${STOCK_RUN_URL:-${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-}}"

if [[ ! "$CODE" =~ ^[0-9]{6}$ ]]; then
  echo "CODE must be exactly six digits" >&2
  exit 1
fi
if [[ ! "$VARIANT" =~ ^(stk_lite|stk_full)$ ]]; then
  echo "VARIANT must be stk_lite or stk_full" >&2
  exit 1
fi
if [[ ! "$HISTORY_WEEKS" =~ ^[0-9]{1,3}$ ]] || (( 10#$HISTORY_WEEKS > 156 )); then
  echo "HISTORY_WEEKS must be an integer from 0 through 156" >&2
  exit 1
fi
HISTORY_WEEKS=$((10#$HISTORY_WEEKS))

LATEST_FILE="$RESULT_DIR/$CODE.json"
HISTORY_FILE="$RESULT_DIR/${CODE}_history.json"
ERROR_FILE="$RESULT_DIR/${CODE}_error.json"
if [[ ! -f "$LATEST_FILE" && ! -f "$ERROR_FILE" ]]; then
  echo "No stock result or error JSON found for $CODE in $RESULT_DIR" >&2
  exit 1
fi

STOCK_NAME_HINT="$(
  STOCK_CODE="$CODE" STOCK_NAMES_FILE="$ROOT/web/mock/data/stock_names.json" python - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["STOCK_NAMES_FILE"])
if path.exists():
    names = json.loads(path.read_text(encoding="utf-8"))
    print(names.get(os.environ["STOCK_CODE"], "") if isinstance(names, dict) else "")
else:
    print("")
PY
)"

GIT_DIR="$(git rev-parse --absolute-git-dir)"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/stock-result-publish.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

for attempt in 1 2 3; do
  base_commit=""
  if remote_ref="$(git ls-remote --exit-code origin refs/heads/stock-results 2>/dev/null)"; then
    if ! git fetch --no-tags origin \
      +refs/heads/stock-results:refs/remotes/origin/stock-results >/dev/null; then
      echo "Could not fetch stock-results on publish attempt $attempt" >&2
      continue
    fi
    base_commit="$(git rev-parse refs/remotes/origin/stock-results)"
  else
    remote_status=$?
    if (( remote_status != 2 )); then
      echo "Could not inspect stock-results on publish attempt $attempt" >&2
      continue
    fi
  fi

  build_dir="$TMP_ROOT/tree"
  index_file="$TMP_ROOT/index"
  rm -rf "$build_dir"
  rm -f "$index_file"
  mkdir -p "$build_dir"
  if [[ -n "$base_commit" ]]; then
    git archive "$base_commit" stock | tar -x -C "$build_dir"
    base_tree="$(git rev-parse "$base_commit^{tree}")"
  else
    base_tree=""
  fi
  mkdir -p "$build_dir/stock"

  if [[ -f "$LATEST_FILE" ]]; then
    cp "$LATEST_FILE" "$build_dir/stock/$CODE.json"
    if [[ -f "$HISTORY_FILE" ]]; then
      cp "$HISTORY_FILE" "$build_dir/stock/${CODE}_history.json"
    else
      rm -f "$build_dir/stock/${CODE}_history.json"
    fi
  fi
  if [[ -f "$ERROR_FILE" ]]; then
    cp "$ERROR_FILE" "$build_dir/stock/${CODE}_error.json"
  else
    rm -f "$build_dir/stock/${CODE}_error.json"
  fi

  STOCK_INDEX_FILE="$build_dir/stock/index.json" \
  STOCK_LATEST_FILE="$LATEST_FILE" \
  STOCK_ERROR_FILE="$ERROR_FILE" \
  STOCK_CODE="$CODE" \
  STOCK_VARIANT="$VARIANT" \
  STOCK_HISTORY_WEEKS="$HISTORY_WEEKS" \
  STOCK_RUN_URL="$RUN_URL" \
  STOCK_NAME_HINT="$STOCK_NAME_HINT" \
  python - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

index_path = Path(os.environ["STOCK_INDEX_FILE"])
if index_path.exists():
    index = json.loads(index_path.read_text(encoding="utf-8"))
else:
    index = {}
if not isinstance(index, dict):
    raise ValueError("stock/index.json must contain a code-to-record object")

code = os.environ["STOCK_CODE"]
latest_path = Path(os.environ["STOCK_LATEST_FILE"])
error_path = Path(os.environ["STOCK_ERROR_FILE"])
has_error = error_path.exists()
latest_record = (
    json.loads(latest_path.read_text(encoding="utf-8")) if latest_path.exists() else {}
)
error_record = json.loads(error_path.read_text(encoding="utf-8")) if has_error else {}
record = latest_record or error_record
previous = index.get(code, {})
previous = previous if isinstance(previous, dict) else {}
meta = record.get("stock_meta", {})
meta = meta if isinstance(meta, dict) else {}
status = "error" if has_error else str(meta.get("status") or "success")
name = (
    record.get("name")
    or error_record.get("name")
    or previous.get("name")
    or os.environ["STOCK_NAME_HINT"]
    or None
)
entry = {
    "name": name,
    "asof": latest_record.get("asof") or error_record.get("asof"),
    "variant": os.environ["STOCK_VARIANT"],
    "history_weeks": int(os.environ["STOCK_HISTORY_WEEKS"]),
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "run_url": os.environ["STOCK_RUN_URL"],
    "status": status,
}
index[code] = entry
index_path.write_text(
    json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
PY

  commit="$(
    (
      cd "$build_dir"
      export GIT_DIR GIT_WORK_TREE="$build_dir" GIT_INDEX_FILE="$index_file"
      if [[ -n "$base_tree" ]]; then
        git read-tree "$base_tree"
      else
        git read-tree --empty
      fi
      git add -A -- stock
      tree="$(git write-tree)"
      if [[ -n "$base_commit" ]]; then
        printf 'Update stock result %s\n' "$CODE" |
          GIT_AUTHOR_NAME="github-actions[bot]" \
          GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com" \
          GIT_COMMITTER_NAME="github-actions[bot]" \
          GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com" \
          git commit-tree "$tree" -p "$base_commit"
      else
        printf 'Initialize stock results with %s\n' "$CODE" |
          GIT_AUTHOR_NAME="github-actions[bot]" \
          GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com" \
          GIT_COMMITTER_NAME="github-actions[bot]" \
          GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com" \
          git commit-tree "$tree"
      fi
    )
  )"

  if git push origin "$commit:refs/heads/stock-results"; then
    printf 'Published %s to stock-results on attempt %s\n' "$CODE" "$attempt"
    exit 0
  fi
  echo "Push failed on attempt $attempt; rebuilding atop latest stock-results" >&2
done

echo "Failed to publish $CODE after three attempts" >&2
exit 1
