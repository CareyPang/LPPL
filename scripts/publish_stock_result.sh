#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${STOCK_PYTHON:-python}"
CODE="${CODE:-${STOCK_CODE:-}}"
VARIANT="${VARIANT:-${STOCK_VARIANT:-stk_lite}}"
HISTORY_WEEKS="${HISTORY_WEEKS:-${STOCK_HISTORY_WEEKS:-0}}"
RESULT_DIR="${STOCK_RESULT_DIR:-$ROOT/out/stock}"
RUN_URL="${STOCK_RUN_URL:-${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-}}"

CODES=()
if [[ -n "$CODE" ]]; then
  [[ "$CODE" =~ ^[0-9]{6}$ ]] || { echo "CODE must be exactly six digits" >&2; exit 1; }
  CODES=("$CODE")
else
  while IFS= read -r f; do
    base="$(basename "$f" .json)"
    base="${base%_history}"
    base="${base%_error}"
    [[ "$base" =~ ^[0-9]{6}$ ]] && CODES+=("$base")
  done < <(find "$RESULT_DIR" -maxdepth 1 -type f -name '*.json' | sort)
  (( ${#CODES[@]} > 0 )) || { echo "No stock result JSON found in $RESULT_DIR" >&2; exit 1; }
  mapfile -t CODES < <(printf '%s\n' "${CODES[@]}" | sort -u)
fi
[[ "$VARIANT" =~ ^(stk_lite|stk_full)$ ]] || { echo "Invalid VARIANT" >&2; exit 1; }
if [[ ! "$HISTORY_WEEKS" =~ ^[0-9]{1,3}$ ]] || (( 10#$HISTORY_WEEKS > 156 )); then
  echo "HISTORY_WEEKS must be from 0 through 156" >&2; exit 1
fi
for c in "${CODES[@]}"; do
  if [[ ! -f "$RESULT_DIR/$c.json" && ! -f "$RESULT_DIR/${c}_history.json" && ! -f "$RESULT_DIR/${c}_error.json" ]]; then
    echo "No stock result or error JSON for $c" >&2; exit 1
  fi
done
GIT_DIR="$(git rev-parse --absolute-git-dir)"
TMP_PARENT="$(cd "${TMPDIR:-/tmp}" && pwd -P)"
TMP_ROOT="$(mktemp -d "$TMP_PARENT/stock-result-publish.XXXXXX")"
[[ "$TMP_ROOT" == "$TMP_PARENT"/stock-result-publish.* && "$TMP_ROOT" != "$TMP_PARENT" ]] || exit 1
trap 'rm -rf "$TMP_ROOT"' EXIT

retry_delay() {
  local delay=$((RANDOM % 9 + 2))
  echo "Retrying publish after ${delay}s" >&2
  sleep "$delay"
}

for attempt in {1..8}; do
  base_commit=""
  if git ls-remote --exit-code origin refs/heads/stock-results >/dev/null 2>&1; then
    if ! git fetch --no-tags origin +refs/heads/stock-results:refs/remotes/origin/stock-results >/dev/null; then
      retry_delay; continue
    fi
    base_commit="$(git rev-parse refs/remotes/origin/stock-results)"
  else
    remote_status=$?
    if (( remote_status != 2 )); then retry_delay; continue; fi
  fi
  build_dir="$TMP_ROOT/tree"
  index_file="$TMP_ROOT/index"
  rm -rf "$build_dir"
  rm -f "$index_file"
  mkdir -p "$build_dir/stock"
  if [[ -n "$base_commit" ]]; then
    git archive "$base_commit" stock | tar -x -C "$build_dir"
    base_tree="$(git rev-parse "$base_commit^{tree}")"
  else
    base_tree=""
  fi

  STOCK_TREE_DIR="$build_dir/stock" \
  STOCK_RESULT_DIR="$RESULT_DIR" \
  STOCK_CODES="${CODES[*]}" \
  STOCK_NAMES_FILE="$ROOT/web/mock/data/stock_names.json" \
  STOCK_VARIANT="$VARIANT" \
  STOCK_RUN_URL="$RUN_URL" \
  "$PYTHON" "$SCRIPT_ROOT/research/pipeline/stock_publish.py"

  commit="$(
    (
      cd "$build_dir"
      export GIT_DIR GIT_WORK_TREE="$build_dir" GIT_INDEX_FILE="$index_file"
      if [[ -n "$base_tree" ]]; then git read-tree "$base_tree"; else git read-tree --empty; fi
      git add -A -- stock
      tree="$(git write-tree)"
      parents=()
      if [[ -n "$base_commit" ]]; then parents=(-p "$base_commit"); fi
      printf 'Update stock results: %s\n' "${CODES[*]}" | cut -c1-200 |
        GIT_AUTHOR_NAME="github-actions[bot]" \
        GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com" \
        GIT_COMMITTER_NAME="github-actions[bot]" \
        GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com" \
        git commit-tree "$tree" "${parents[@]}"
    )
  )"
  if git push origin "$commit:refs/heads/stock-results"; then
    printf 'Published %s result(s) to stock-results on attempt %s\n' "${#CODES[@]}" "$attempt"
    exit 0
  fi
  echo "Push failed on attempt $attempt; rebuilding atop latest stock-results" >&2
  retry_delay
done
echo "Failed to publish after eight attempts" >&2
exit 1
