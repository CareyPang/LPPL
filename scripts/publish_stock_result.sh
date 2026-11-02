#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
CODE="${CODE:-${STOCK_CODE:-}}"
VARIANT="${VARIANT:-${STOCK_VARIANT:-stk_lite}}"
HISTORY_WEEKS="${HISTORY_WEEKS:-${STOCK_HISTORY_WEEKS:-104}}"
RESULT_DIR="${STOCK_RESULT_DIR:-$ROOT/out/stock}"
RUN_URL="${STOCK_RUN_URL:-${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-}}"

CODES=()
if [[ -n "$CODE" ]]; then
  if [[ ! "$CODE" =~ ^[0-9]{6}$ ]]; then
    echo "CODE must be exactly six digits" >&2
    exit 1
  fi
  CODES=("$CODE")
else
  # Batch mode: every <code>.json / <code>_error.json in the result directory
  while IFS= read -r f; do
    base="$(basename "$f" .json)"
    base="${base%_error}"
    [[ "$base" =~ ^[0-9]{6}$ ]] && CODES+=("$base")
  done < <(find "$RESULT_DIR" -maxdepth 1 -name '[0-9][0-9][0-9][0-9][0-9][0-9].json' -o -maxdepth 1 -name '[0-9][0-9][0-9][0-9][0-9][0-9]_error.json' | sort)
  mapfile -t CODES < <(printf '%s\n' "${CODES[@]}" | sort -u)
  if (( ${#CODES[@]} == 0 )); then
    echo "No stock result JSON found in $RESULT_DIR" >&2
    exit 1
  fi
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

for c in "${CODES[@]}"; do
  if [[ ! -f "$RESULT_DIR/$c.json" && ! -f "$RESULT_DIR/${c}_error.json" ]]; then
    echo "No stock result or error JSON found for $c in $RESULT_DIR" >&2
    exit 1
  fi
done
mapfile -t BREADTH_FILES < <(find "$RESULT_DIR" -maxdepth 1 -name 'breadth_*.json' | sort)

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

  for c in "${CODES[@]}"; do
    latest="$RESULT_DIR/$c.json"
    hist="$RESULT_DIR/${c}_history.json"
    errf="$RESULT_DIR/${c}_error.json"
    if [[ -f "$latest" ]]; then
      cp "$latest" "$build_dir/stock/$c.json"
      if [[ -f "$hist" ]]; then
        cp "$hist" "$build_dir/stock/${c}_history.json"
      elif [[ -n "$CODE" ]]; then
        # Single on-demand query: a run without history replaces any stale history.
        rm -f "$build_dir/stock/${c}_history.json"
      fi
    fi
    if [[ -f "$errf" ]]; then
      cp "$errf" "$build_dir/stock/${c}_error.json"
    else
      rm -f "$build_dir/stock/${c}_error.json"
    fi
  done
  for bf in "${BREADTH_FILES[@]}"; do
    cp "$bf" "$build_dir/stock/$(basename "$bf")"
  done

  STOCK_INDEX_FILE="$build_dir/stock/index.json" \
  STOCK_RESULT_DIR="$RESULT_DIR" \
  STOCK_CODES="${CODES[*]}" \
  STOCK_NAMES_FILE="$ROOT/web/mock/data/stock_names.json" \
  STOCK_VARIANT="$VARIANT" \
  STOCK_HISTORY_WEEKS="$HISTORY_WEEKS" \
  STOCK_RUN_URL="$RUN_URL" \
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

names_path = Path(os.environ["STOCK_NAMES_FILE"])
names = json.loads(names_path.read_text(encoding="utf-8")) if names_path.exists() else {}
names = names if isinstance(names, dict) else {}
result_dir = Path(os.environ["STOCK_RESULT_DIR"])
now = datetime.now(timezone.utc).isoformat()

for code in os.environ["STOCK_CODES"].split():
    latest_path = result_dir / f"{code}.json"
    error_path = result_dir / f"{code}_error.json"
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
        or names.get(code)
        or None
    )
    index[code] = {
        "name": name,
        "asof": latest_record.get("asof") or error_record.get("asof"),
        "variant": os.environ["STOCK_VARIANT"],
        "history_weeks": int(os.environ["STOCK_HISTORY_WEEKS"]),
        "generated_at": now,
        "run_url": os.environ["STOCK_RUN_URL"],
        "status": status,
    }
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
        printf 'Update stock results: %s\n' "${CODES[*]}" | cut -c1-200 |
          GIT_AUTHOR_NAME="github-actions[bot]" \
          GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com" \
          GIT_COMMITTER_NAME="github-actions[bot]" \
          GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com" \
          git commit-tree "$tree" -p "$base_commit"
      else
        printf 'Initialize stock results with %s\n' "${CODES[*]}" | cut -c1-200 |
          GIT_AUTHOR_NAME="github-actions[bot]" \
          GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com" \
          GIT_COMMITTER_NAME="github-actions[bot]" \
          GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com" \
          git commit-tree "$tree"
      fi
    )
  )"

  if git push origin "$commit:refs/heads/stock-results"; then
    printf 'Published %s result(s) to stock-results on attempt %s\n' "${#CODES[@]}" "$attempt"
    exit 0
  fi
  echo "Push failed on attempt $attempt; rebuilding atop latest stock-results" >&2
done

echo "Failed to publish ${#CODES[@]} result(s) after three attempts" >&2
exit 1
