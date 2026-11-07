"""Merge stock artifacts into a result tree without replacing newer good results."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

if __package__:
    from .stock_jobs import atomic_json, cli_job, utc_time
else:  # The publisher also runs without installing the research dependencies.
    from stock_jobs import atomic_json, cli_job, utc_time


def read_record(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _timestamp(record):
    value = record.get("requested_at") or record.get("generated_at")
    try:
        return utc_time(value) if value else None
    except (TypeError, ValueError):
        return None


def older(incoming: dict, published: dict) -> bool:
    def asof(record):
        frames = record.get("frames") or []
        return _date(record.get("asof") or (frames[-1].get("asof") if frames else None))

    new_date, old_date = asof(incoming), asof(published)
    if new_date and old_date and new_date < old_date:
        return True
    new_time, old_time = _timestamp(incoming), _timestamp(published)
    return bool(new_time and old_time and new_time < old_time)


def history_compatible(history: dict, current: dict) -> bool:
    if not current:
        return True
    meta = current.get("stock_meta") or {}
    variant = current.get("variant") or meta.get("variant")
    if not variant or history.get("variant") != variant:
        return False
    for key in ("schema_version", "model_version", "fit_code_version"):
        if (key in history or key in current) and history.get(key) != current.get(key):
            return False
    asof, frames = _date(current.get("asof")), history.get("frames")
    if ("data_version" in history or "data_version" in current) and history.get("data_version") != current.get("data_version"):
        fingerprints = current.get("history_input_hashes") or {}
        if not isinstance(frames, list) or not frames or not all(
            isinstance(frame, dict) and frame.get("fit_input_hash")
            and frame["fit_input_hash"] == fingerprints.get(frame.get("asof"))
            for frame in frames
        ):
            return False
    return bool(asof and isinstance(frames, list) and all(
        isinstance(frame, dict) and _date(frame.get("asof"))
        and _date(frame["asof"]) <= asof for frame in frames
    ))


def immutable_copy(source: Path, target: Path) -> None:
    if target.exists():
        if source.read_bytes() != target.read_bytes():
            raise ValueError(f"immutable result already exists with different bytes: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _archive(path: Path, stock_dir: Path) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    immutable_copy(path, stock_dir / "archive" / f"{path.stem}-{digest}.json")


def merge_results(stock_dir: Path, result_dir: Path, codes: list[str], *, variant="stk_lite",
                  run_url="", names: dict | None = None) -> None:
    stock_dir.mkdir(parents=True, exist_ok=True)
    index_path = stock_dir / "index.json"
    index = read_record(index_path)
    names = names or {}
    for code in codes:
        if re.fullmatch(r"[0-9]{6}", code) is None:
            raise ValueError("invalid stock code")
        incoming = {}
        for suffix in ("", "_history", "_error"):
            path = result_dir / f"{code}{suffix}.json"
            if not path.exists():
                continue
            value = read_record(path)
            if value.get("code", code) != code:
                raise ValueError("result code does not match its filename")
            if any(key in value for key in ("job_id", "requested_at", "source_sha")):
                job = cli_job(value.get("job_id"), value.get("requested_at"), value.get("source_sha"))
                expected = "history" if suffix == "_history" else "current"
                if suffix != "_error" and value.get("mode") != expected:
                    raise ValueError("result mode does not match its filename")
                if value.get("mode") not in ("current", "history"):
                    raise ValueError("invalid result mode")
                immutable_copy(path, stock_dir / "jobs" / job["job_id"] / path.name)
            incoming[suffix] = value
        if not incoming:
            raise ValueError(f"no current, history or error result for {code}")
        current_path = stock_dir / f"{code}.json"
        history_path = stock_dir / f"{code}_history.json"
        error_path = stock_dir / f"{code}_error.json"
        current, history, error = map(read_record, (current_path, history_path, error_path))
        old_index = index.get(code, {})
        changed = False
        new_current = incoming.get("")
        if new_current is not None:
            if older(new_current, current):
                print(f"skip {code}: published asof {current.get('asof')} newer than batch {new_current.get('asof')}")
            else:
                shutil.copyfile(result_dir / current_path.name, current_path)
                current, changed = new_current, True
        new_history = incoming.get("_history")
        if new_history is not None and not older(new_history, history) and history_compatible(new_history, current):
            shutil.copyfile(result_dir / history_path.name, history_path)
            history, changed = new_history, True
        if history and current and not history_compatible(history, current):
            _archive(history_path, stock_dir)
            history_path.unlink()
            history, changed = {}, True
        new_error = incoming.get("_error")
        if new_error is not None and not older(new_error, current) and not older(new_error, error):
            shutil.copyfile(result_dir / error_path.name, error_path)
            error, changed = new_error, True
        elif new_error is None and error:
            successful = new_history if error.get("mode") == "history" else new_current
            if successful is not None and not older(successful, error):
                error_path.unlink()
                error, changed = {}, True
        if not changed:
            continue
        primary = current or history or error
        meta = primary.get("stock_meta") or {}
        frames = history.get("frames", [])
        entry = {
            "name": primary.get("name") or old_index.get("name") or names.get(code),
            "asof": primary.get("asof"),
            "variant": primary.get("variant") or meta.get("variant") or variant,
            "history_weeks": len(frames),
            "history_compatible": bool(history and current),
            "history_asof": frames[-1].get("asof") if frames else None,
            "generated_at": datetime.now(UTC).isoformat(),
            "run_url": run_url,
            "status": (str(meta.get("status") or "success") if current
                       else "history_ready" if history else "error"),
        }
        entry.update({key: primary[key] for key in (
            "job_id", "requested_at", "source_sha", "model_version", "fit_code_version", "schema_version", "data_version"
        ) if key in primary})
        if error:
            entry["last_error"] = {key: error.get(key) for key in (
                "job_id", "requested_at", "mode", "stage", "error_code", "generated_at"
            )}
        index[code] = entry
    atomic_json(index_path, index)
    for source in result_dir.glob("breadth_*.json"):
        incoming = read_record(source)
        target = stock_dir / source.name
        published = read_record(target)
        if older(incoming, published) or (_date(published.get("asof")) and not _date(incoming.get("asof"))):
            print(f"skip {source.name}: newer breadth already published")
            continue
        shutil.copyfile(source, target)


def main() -> None:
    names_path = Path(os.environ["STOCK_NAMES_FILE"])
    names = read_record(names_path)
    merge_results(Path(os.environ["STOCK_TREE_DIR"]), Path(os.environ["STOCK_RESULT_DIR"]),
                  os.environ["STOCK_CODES"].split(), variant=os.environ["STOCK_VARIANT"],
                  run_url=os.environ.get("STOCK_RUN_URL", ""), names=names)


if __name__ == "__main__":
    main()
