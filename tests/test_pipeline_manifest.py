import hashlib
import json

import pandas as pd

from research.pipeline.manifest import build_manifest, write_manifest


def test_manifest_keeps_stage_flags_independent_and_records_hashes(tmp_path):
    frozen = tmp_path / "data" / "frozen" / "v20261024"
    frozen.mkdir(parents=True)
    price_path = frozen / "sh000001_qfq.parquet"
    price_path.write_bytes(b"frozen price bytes")
    price_hash = hashlib.sha256(price_path.read_bytes()).hexdigest()
    manifest_path = frozen / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            [
                {
                    "symbol": "sh000001",
                    "adjust": "qfq",
                    "sha256": price_hash,
                }
            ]
        ),
        encoding="utf-8",
    )

    scan_path = tmp_path / "data" / "features" / "lppls_v2" / "sh000001.parquet"
    scan_path.parent.mkdir(parents=True)
    scan_path.write_bytes(b"fit scan bytes")
    label_path = tmp_path / "data" / "labels" / "top_v1" / "sh000001.parquet"
    label_path.parent.mkdir(parents=True)
    label_path.write_bytes(b"label bytes")
    confirmed_path = (
        tmp_path / "data" / "labels" / "confirmed_v1" / "sh000001.parquet"
    )
    confirmed_path.parent.mkdir(parents=True)
    confirmed_path.write_bytes(b"confirmed labels")
    oof_path = tmp_path / "data" / "oof" / "sh000001.parquet"
    oof_path.parent.mkdir(parents=True)
    pd.DataFrame({"symbol": ["sh000001"], "p": [0.2]}).to_parquet(
        oof_path, index=False
    )
    report_path = (
        tmp_path / "reports" / "original_standard_dev_v2" / "alarm_grid.csv"
    )
    report_path.parent.mkdir(parents=True)
    report_path.write_text("symbol,indicator\nsh000001,box__6-12m\n", encoding="utf-8")
    output_path = tmp_path / "web" / "mock" / "data" / "sh000001_latest.json"
    output_path.parent.mkdir(parents=True)
    output_path.write_text(
        json.dumps(
            {
                "symbol": "sh000001",
                "model_version": "prereg_v1.7_v2",
                "data_version": "frozen_v20261024",
            }
        ),
        encoding="utf-8",
    )

    manifest = build_manifest(tmp_path)
    row = next(
        item
        for item in manifest["records"]
        if item["symbol"] == "sh000001"
        and item["model_version"] == "prereg_v1.7_v2"
    )

    assert {
        stage: row[stage]
        for stage in ("frozen", "scanned", "labeled", "evaluated", "calibrated", "confirmed")
    } == {
        "frozen": True,
        "scanned": True,
        "labeled": True,
        "evaluated": True,
        "calibrated": True,
        "confirmed": True,
    }
    assert (
        row["input_hashes"]["data/frozen/v20261024/sh000001_qfq.parquet"]
        == price_hash
    )
    assert row["artifact_hashes"]["web/mock/data/sh000001_latest.json"]
    assert row["commands"]["confirmed"].startswith("python -m research.pipeline.stock")
    assert "--phase history" in row["commands"]["confirmed"]
    assert "--history-only" not in row["commands"]["confirmed"]
    assert "done" not in row
    assert all(row["missing_reasons"][stage] is None for stage in row["missing_reasons"])


def test_manifest_explains_missing_stages_and_writes_default_output(tmp_path):
    output_path = tmp_path / "web" / "mock" / "data" / "sh000002_latest.json"
    output_path.parent.mkdir(parents=True)
    output_path.write_text(
        json.dumps(
            {
                "symbol": "sh000002",
                "model_version": "prereg_v1.7_v2",
                "data_version": "vintage_20261112_source",
            }
        ),
        encoding="utf-8",
    )

    path = write_manifest(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    row = next(item for item in manifest["records"] if item["symbol"] == "sh000002")

    assert path == tmp_path / "data" / "coverage_manifest.json"
    assert row["frozen"] is False and row["scanned"] is False
    assert row["labeled"] is False and row["calibrated"] is False
    assert row["missing_reasons"]["frozen"]
    assert row["missing_reasons"]["scanned"]
    assert set(manifest["summary"]) == {
        "frozen",
        "scanned",
        "labeled",
        "evaluated",
        "calibrated",
        "confirmed",
    }
