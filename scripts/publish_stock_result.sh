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

retry_delay() {
  local delay=$((RANDOM % 9 + 2))
  echo "Retrying publish after ${delay}s" >&2
  sleep "$delay"
}

for attempt in {1..8}; do
  base_commit=""
  if remote_ref="$(git ls-remote --exit-code origin refs/heads/stock-results 2>/dev/null)"; then
    if ! git fetch --no-tags origin \
      +refs/heads/stock-results:refs/remotes/origin/stock-results >/dev/null; then
      echo "Could not fetch stock-results on publish attempt $attempt" >&2
      retry_delay
      continue
    fi
    base_commit="$(git rev-parse refs/remotes/origin/stock-results)"
  else
    remote_status=$?
    if (( remote_status != 2 )); then
      echo "Could not inspect stock-results on publish attempt $attempt" >&2
      retry_delay
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

  SKIPPED_CODES=()
  for c in "${CODES[@]}"; do
    latest="$RESULT_DIR/$c.json"
    hist="$RESULT_DIR/${c}_history.json"
    errf="$RESULT_DIR/${c}_error.json"
    if [[ -z "$CODE" && -f "$build_dir/stock/$c.json" ]]; then
      incoming="$latest"
      if [[ ! -f "$incoming" ]]; then
        incoming="$errf"
      fi
      comparison="$(
        python - "$build_dir/stock/$c.json" "$incoming" <<'PY'
import json
import sys
from datetime import date
from pathlib import Path


def _asof(path):
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    value = record.get("asof")
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


published_asof = _asof(sys.argv[1])
batch_asof = _asof(sys.argv[2])
if published_asof is not None and batch_asof is not None and published_asof > batch_asof:
    print(f"{published_asof.isoformat()}\t{batch_asof.isoformat()}")
PY
      )"
      if [[ -n "$comparison" ]]; then
        published_asof="${comparison%%$'\t'*}"
        batch_asof="${comparison#*$'\t'}"
        echo "skip $c: published asof $published_asof newer than batch $batch_asof"
        SKIPPED_CODES+=("$c")
        continue
      fi
    fi
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
  STOCK_SINGLE_CODE="$CODE" \
  STOCK_SKIPPED_CODES="${SKIPPED_CODES[*]}" \
  STOCK_RUN_URL="$RUN_URL" \
  python - <<'PY'
import json
import os
from datetime import date, datetime, timezone
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
single_code_mode = bool(os.environ["STOCK_SINGLE_CODE"])
skipped_codes = set(os.environ["STOCK_SKIPPED_CODES"].split())


def _iso_date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _history_matches_latest(history_path, latest_record):
    try:
        history_record = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(history_record, dict):
        return False
    latest_meta = latest_record.get("stock_meta")
    latest_meta = latest_meta if isinstance(latest_meta, dict) else {}
    latest_variant = latest_record.get("variant") or latest_meta.get("variant")
    latest_asof = _iso_date(latest_record.get("asof"))
    frames = history_record.get("frames")
    if (
        latest_variant is None
        or history_record.get("variant") != latest_variant
        or latest_asof is None
        or not isinstance(frames, list)
    ):
        return False
    for frame in frames:
        if not isinstance(frame, dict):
            return False
        frame_asof = _iso_date(frame.get("asof"))
        if frame_asof is None or frame_asof > latest_asof:
            return False
    return True


def _history_frame_count(history_path):
    try:
        history_record = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(history_record, dict):
        return 0
    frames = history_record.get("frames")
    return len(frames) if isinstance(frames, list) else 0


for code in os.environ["STOCK_CODES"].split():
    if code in skipped_codes:
        continue
    latest_path = result_dir / f"{code}.json"
    error_path = result_dir / f"{code}_error.json"
    has_error = error_path.exists()
    latest_record = (
        json.loads(latest_path.read_text(encoding="utf-8")) if latest_path.exists() else {}
    )
    error_record = json.loads(error_path.read_text(encoding="utf-8")) if has_error else {}
    if not single_code_mode and latest_path.exists():
        history_path = index_path.parent / f"{code}_history.json"
        if history_path.exists() and not _history_matches_latest(history_path, latest_record):
            history_path.unlink()
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
    history_weeks = int(os.environ["STOCK_HISTORY_WEEKS"])
    if not single_code_mode:
        history_weeks = _history_frame_count(
            index_path.parent / f"{code}_history.json"
        )
    index[code] = {
        "name": name,
        "asof": latest_record.get("asof") or error_record.get("asof"),
        "variant": os.environ["STOCK_VARIANT"],
        "history_weeks": history_weeks,
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
  retry_delay
done

echo "Failed to publish ${#CODES[@]} result(s) after eight attempts" >&2
exit 1
