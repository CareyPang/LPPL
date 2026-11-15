"""Validated stock job identity and atomic result metadata (standard library only)."""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = "stock_result_v1"


def utc_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("requested_at must be an ISO UTC timestamp")
    return parsed


def cli_job(job_id=None, requested_at=None, source_sha=None) -> dict:
    if job_id is None and requested_at is None and source_sha is None:
        return {}
    if not all(isinstance(item, str) and item for item in (job_id, requested_at, source_sha)):
        raise ValueError("job_id, requested_at and source_sha must be supplied together")
    if str(uuid.UUID(job_id)) != job_id:
        raise ValueError("job_id must be a canonical UUID")
    utc_time(requested_at)
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise ValueError("source_sha must be a full lowercase commit SHA")
    return {"job_id": job_id, "requested_at": requested_at, "source_sha": source_sha}


def attach_job(record: dict, job: dict, code: str, mode: str) -> None:
    record.update(job)
    record.update(code=code, mode=mode, schema_version=SCHEMA_VERSION,
                  generated_at=datetime.now(UTC).isoformat())
    for frame in record.get("frames", []):
        frame.update({key: record[key] for key in (
            "schema_version", "model_version", "fit_code_version", "data_version", "source_sha"
        ) if key in record})


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".stock-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=1, default=str, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def workflow_inputs(event: str, values: dict, fallback_sha: str) -> dict:
    code = str(values.get("code") or ("600519" if event == "pull_request" else ""))
    variant = str(values.get("variant") or "stk_lite")
    mode = str(values.get("mode") or "current")
    raw_weeks = str(values.get("history_weeks") or "0")
    if re.fullmatch(r"[0-9]{6}", code) is None:
        raise ValueError("code must be exactly six ASCII digits")
    if mode not in ("current", "history") or variant not in ("stk_lite", "stk_full"):
        raise ValueError("invalid mode or variant")
    if event == "repository_dispatch" and variant != "stk_lite":
        raise ValueError("public stock jobs must use stk_lite")
    if re.fullmatch(r"[0-9]{1,3}", raw_weeks) is None:
        raise ValueError("history_weeks must be an integer")
    weeks = int(raw_weeks)
    if (mode == "current" and weeks != 0) or (mode == "history" and not 1 <= weeks <= 156):
        raise ValueError("current requires 0 history weeks; history requires 1 through 156")
    if event == "repository_dispatch":
        job = cli_job(values.get("job_id"), values.get("requested_at"), values.get("source_sha"))
        if not job:
            raise ValueError("dispatched jobs require server-generated identity")
    else:
        job = cli_job(str(uuid.uuid4()), datetime.now(UTC).isoformat(), fallback_sha)
    return dict(code=code, variant=variant, mode=mode, weeks=str(weeks), **job)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("validate-workflow", "error"))
    args = parser.parse_args()
    if args.action == "validate-workflow":
        event = os.environ["GITHUB_EVENT_NAME"]
        payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        values = payload.get("client_payload", {}) if event == "repository_dispatch" else payload.get("inputs", {})
        result = workflow_inputs(event, values, os.environ["GITHUB_SHA"])
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            for key, value in result.items():
                output.write(f"{key}={value}\n")
    else:
        code, mode = os.environ["CODE"], os.environ["MODE"]
        job = cli_job(os.environ["JOB_ID"], os.environ["REQUESTED_AT"], os.environ["SOURCE_SHA"])
        record = {"error_code": "COMPUTE_FAILED", "error": "本次计算未完成，已有结果仍可查看。", "stage": mode,
                  "run_url": os.environ.get("STOCK_RUN_URL")}
        attach_job(record, job, code, mode)
        atomic_json(Path("out/stock") / f"{code}_error.json", record)


if __name__ == "__main__":
    main()
