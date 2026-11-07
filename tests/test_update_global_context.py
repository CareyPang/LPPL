from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import update_global_context as runner

ASOF = "2026-11-06"
GENERATED = "2026-11-07T00:30:00+00:00"


def _write_manifest(root: Path, *, file_name: str = "treasury.json") -> None:
    (root / file_name).write_text(
        json.dumps({"data": [{"record_date": ASOF, "10 Yr": "4.25"}]}),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "asof": ASOF,
                "generated_at": GENERATED,
                "run_id": "artifact-test",
                "sources": {
                    "us_treasury": {
                        "file": file_name,
                        "source_url": "https://home.treasury.gov/",
                        "fetched_at": GENERATED,
                        "status": "ok",
                        "license_tier": "NOT_ESTABLISHED",
                        "license_status": "NOT_ESTABLISHED",
                        "frequency_status": "NOT_ESTABLISHED",
                        "mainland_network_status": "NOT_ESTABLISHED",
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_runner_is_artifact_only_and_seals_source_policy(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    out = tmp_path / "out"
    incoming.mkdir()
    _write_manifest(incoming)

    result = runner.run(input_dir=incoming, out_dir=out)
    assert result["status"] == "ok"
    snapshot = json.loads((out / "global_context_2026-11-06.json").read_text(encoding="utf-8"))
    assert snapshot["policy"] == {
        "artifact_only": True,
        "browser_direct_fetch": "forbidden",
        "lppls_input": "forbidden",
        "license_status": "NOT_ESTABLISHED",
        "frequency_status": "NOT_ESTABLISHED",
        "mainland_network_status": "NOT_ESTABLISHED",
    }
    source = snapshot["sources"]["us_treasury"]
    expected_hash = hashlib.sha256((incoming / "treasury.json").read_bytes()).hexdigest()
    assert source["raw_sha256"] == expected_hash
    assert source["license_status"] == "NOT_ESTABLISHED"
    assert source["browser_direct_fetch"] == "forbidden"
    assert source["lppls_input"] == "forbidden"
    assert snapshot["rates"]["treasury_curve"]["rows"][0]["tenors"]["10y"] == "4.25"
    assert runner.validate_global_context(snapshot)["source_hash_count"] == 1


def test_missing_manifest_is_explicitly_not_requested(tmp_path: Path) -> None:
    result = runner.run(input_dir=tmp_path / "incoming", out_dir=tmp_path / "out", asof=ASOF, generated_at=GENERATED)
    assert result["status"] == "not_requested"
    snapshot = json.loads((tmp_path / "out" / "global_context_latest.json").read_text(encoding="utf-8"))
    assert snapshot["sources"] == {}
    assert snapshot["probability"]["status"] == "not_requested"
    assert snapshot["policy"]["lppls_input"] == "forbidden"


def test_runner_rejects_artifacts_outside_input_directory(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    _write_manifest(incoming, file_name="../outside.json")
    with pytest.raises(ValueError, match="escapes input directory"):
        runner.run(input_dir=incoming, out_dir=tmp_path / "out")


def test_validator_rejects_missing_policy_and_hash() -> None:
    with pytest.raises(ValueError, match="snapshot policy metadata"):
        runner.validate_global_context(
            {
                "schema_version": "global-context.v1",
                "kind": "global_context",
                "evidence": "descriptive",
            }
        )
