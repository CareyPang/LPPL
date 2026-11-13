"""Build a stage-by-stage inventory of versioned research coverage.

Generate it with ``python -m research.pipeline.manifest``; ``--root`` selects
the repository root and ``--out`` overrides the default data/coverage_manifest.json.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

STAGES = ("frozen", "scanned", "labeled", "evaluated", "calibrated", "confirmed")
COMMANDS = {
    "frozen": "python -c 'from research.data.cache import freeze; freeze(\"<version>\", codes=[\"<symbol>\"], adjust=\"qfq\")'",
    "scanned": "LPPLS_BOX=v2 LPPLS_SYMBOLS=<symbol> python -m research.features.lppls_scan <index|stock>",
    "labeled": "python -m research.labels.run_top",
    "evaluated": "LPPLS_BOX=v2 python -m research.eval.original_standard <symbol>",
    "calibrated": "python -m research.eval.calibration_lppls",
    "confirmed": "python -m research.pipeline.stock <code6> --phase history --history-weeks 104",
}
STAGE_DEFINITIONS = {
    "frozen": "A manifest-linked price parquet exists and its sha256 matches.",
    "scanned": "A per-symbol LPPLS fit parquet exists for the output version.",
    "labeled": "A per-symbol top or bottom label parquet exists.",
    "evaluated": "A per-symbol row exists in the v2 evaluation reports.",
    "calibrated": "An OOF/calibration parquet contains this symbol.",
    "confirmed": "A confirmed-label parquet or non-empty confirmed_tops artifact exists.",
}
EVALUATION_REPORTS = (
    Path("reports/original_standard_dev_v2/fco_sets.csv"),
    Path("reports/original_standard_dev_v2/alarm_grid.csv"),
    Path("reports/calibration_2019_2021/lppls_a1a2.csv"),
    Path("reports/final_test_2022_2025/lppls_a1a2.csv"),
)


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _new_record(symbol: str, model_version: str, data_version: str) -> dict:
    index_symbols = {
        "sh000001",
        "sh000016",
        "sh000300",
        "sh000688",
        "sh000905",
        "sz399001",
        "sz399006",
    }
    commands = COMMANDS.copy()
    group = "index" if symbol in index_symbols else "stock"
    commands["scanned"] = (
        f"LPPLS_BOX=v2 LPPLS_SYMBOLS={symbol} "
        f"python -m research.features.lppls_scan {group}"
    )
    return {
        "symbol": symbol,
        "model_version": model_version,
        "data_version": data_version,
        **{stage: False for stage in STAGES},
        "input_hashes": {},
        "artifact_hashes": {},
        "artifact_paths": [],
        "stage_artifacts": {stage: [] for stage in STAGES},
        "commands": commands,
        "missing_reasons": {stage: "No matching artifact was found." for stage in STAGES},
    }


def _add_artifact(
    record: dict, root: Path, path: Path, *, is_input: bool = False
) -> None:
    relative = _relative(root, path)
    if relative not in record["artifact_paths"]:
        record["artifact_paths"].append(relative)
    if path.is_file():
        digest = _sha256(path)
        record["artifact_hashes"][relative] = digest
        if is_input:
            record["input_hashes"][relative] = digest


def _set_stage(
    record: dict,
    root: Path,
    stage: str,
    expected_paths: list[Path],
    valid_paths: list[Path],
    missing_reason: str,
    input_paths: list[Path] | None = None,
) -> None:
    paths = sorted({_relative(root, path) for path in expected_paths})
    record["stage_artifacts"][stage] = paths
    record[stage] = bool(valid_paths)
    record["missing_reasons"][stage] = None if valid_paths else missing_reason
    inputs = set(input_paths) if input_paths is not None else set(expected_paths)
    for path in expected_paths:
        _add_artifact(record, root, path, is_input=path in inputs)


def _manifest_entries(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    symbols = payload.get("symbols", [])
    if isinstance(symbols, list):
        return [row for row in symbols if isinstance(row, dict)]
    if isinstance(symbols, dict):
        entries = []
        for symbol, value in symbols.items():
            if isinstance(value, dict):
                entries.append({"symbol": symbol, **value})
        return entries
    return []


def _frozen_artifact(root: Path, version: str, row: dict) -> Path:
    symbol = str(row["symbol"])
    if version.startswith("stocks_"):
        return root / "data" / "cache" / "stocks" / f"{symbol}.parquet"
    if version.startswith(("a90s_", "ext_")):
        return root / "data" / "frozen" / version / f"{symbol}.parquet"
    adjust = str(row.get("adjust", "qfq"))
    return root / "data" / "frozen" / version / f"{symbol}_{adjust}.parquet"


def _frozen_records(root: Path) -> tuple[list[dict], dict[tuple[str, str], dict]]:
    frozen_root = root / "data" / "frozen"
    manifests = sorted(set(frozen_root.glob("*/manifest.json")) | set(frozen_root.glob("*/MANIFEST.json")))
    records = []
    lookup = {}
    for manifest_path in manifests:
        version = manifest_path.parent.name
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        for row in _manifest_entries(payload):
            symbol = row.get("symbol")
            if not symbol:
                continue
            symbol = str(symbol)
            artifact = _frozen_artifact(root, version, row)
            expected_hash = row.get("sha256")
            actual_hash = _sha256(artifact) if artifact.is_file() else None
            checksum_ok = (
                actual_hash is not None
                and expected_hash is not None
                and expected_hash == actual_hash
            )
            if not artifact.is_file():
                reason = f"Manifest lists the frozen input, but parquet is missing: {_relative(root, artifact)}."
            elif expected_hash is None:
                reason = "Frozen parquet exists, but its manifest has no sha256."
            elif not checksum_ok:
                reason = f"Frozen parquet sha256 mismatch: expected {expected_hash}, got {actual_hash}."
            else:
                reason = ""

            record = _new_record(symbol, "not_scanned", version)
            if version.startswith("stocks_"):
                record["commands"]["frozen"] = "python -m research.data.stocks"
            record["coverage_source"] = "frozen_manifest"
            record["source_manifest"] = _relative(root, manifest_path)
            record["source"] = row.get("source")
            record["expected_sha256"] = expected_hash
            _add_artifact(record, root, manifest_path, is_input=True)
            _set_stage(
                record,
                root,
                "frozen",
                [artifact],
                [artifact] if checksum_ok else [],
                reason or f"No verified frozen parquet for {symbol} {version}.",
            )
            for stage in STAGES[1:]:
                _set_stage(
                    record,
                    root,
                    stage,
                    [],
                    [],
                    f"No {stage} artifact is associated with frozen-only input {symbol} {version}.",
                )
            frozen_item = {
                "record": record,
                "artifact": artifact,
                "manifest": manifest_path,
                "ok": checksum_ok,
                "reason": reason,
            }
            records.append(record)
            lookup[(symbol, version)] = frozen_item
    return records, lookup


def _csv_has_symbol(path: Path, symbol: str) -> bool:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if any(row.get(column) == symbol for column in ("symbol", "sym", "code")):
                    return True
    except (OSError, UnicodeDecodeError, csv.Error):
        return False
    return False


def _scan_paths(
    root: Path, symbol: str, data: dict, output_path: Path
) -> list[Path]:
    paths = []
    model_version = str(data.get("model_version", ""))
    if "+" in model_version and symbol[:2] in {"sh", "sz", "bj"}:
        code = symbol[2:]
        variant = data.get("variant") or model_version.rsplit("+", 1)[-1]
        paths.append(root / "data" / "stock" / code / str(variant) / "fits.parquet")
    else:
        features = root / "data" / "features"
        scan_names = ["lppls_v2" if "v2" in model_version else "lppls_v1"]
        if output_path.name.endswith("_history.json"):
            scan_names.extend(f"{scan_names[0]}_{split}" for split in ("cal", "test"))
        paths.extend(
            features / name / f"{symbol}.parquet"
            for name in scan_names
        )
    fits = root / "web" / "mock" / "data" / "fits"
    asof = data.get("asof")
    if output_path.name.endswith("_latest.json"):
        paths.append(fits / f"{symbol}_latest.parquet")
    elif asof:
        paths.append(fits / f"{symbol}_{asof}.parquet")
    return sorted(set(paths))


def _label_paths(root: Path, symbol: str) -> list[Path]:
    return [
        root / "data" / "labels" / name / f"{symbol}.parquet"
        for name in ("top_v1", "bottom_v1")
    ]


def _oof_paths(root: Path, symbol: str) -> list[Path]:
    directory = root / "data" / "oof"
    paths = sorted(directory.glob(f"*{symbol}*.parquet")) if directory.exists() else []
    if directory.exists():
        for path in sorted(directory.glob("*.parquet")):
            if path in paths:
                continue
            try:
                import pandas as pd

                columns = pd.read_parquet(path, columns=["symbol"])
                if symbol in columns.symbol.astype(str).values:
                    paths.append(path)
            except Exception:
                continue
    return sorted(set(paths))


def _confirmed_paths(root: Path, symbol: str) -> list[Path]:
    directory = root / "data" / "labels"
    return sorted(directory.glob(f"confirmed*/{symbol}.parquet")) if directory.exists() else []


def _matching_frozen(
    lookup: dict[tuple[str, str], dict], symbol: str, data_version: str
) -> dict | None:
    version = data_version.removeprefix("frozen_")
    return lookup.get((symbol, version))


def _export_records(root: Path, frozen_lookup: dict[tuple[str, str], dict]) -> list[dict]:
    records: dict[tuple[str, str, str], dict] = {}
    data_root = root / "web" / "mock" / "data"
    for output_path in sorted(data_root.rglob("*.json")):
        try:
            data = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or not data.get("symbol") or not data.get("model_version"):
            continue
        symbol = str(data["symbol"])
        model_version = str(data["model_version"])
        data_version = str(data.get("data_version") or "unknown")
        key = (symbol, model_version, data_version)
        record = records.setdefault(key, _new_record(symbol, model_version, data_version))
        _add_artifact(record, root, output_path)

        frozen = _matching_frozen(frozen_lookup, symbol, data_version)
        if frozen is None:
            frozen_reason = (
                "Export does not declare a matching frozen data_version."
                if data_version == "unknown"
                else f"No frozen manifest entry matches data_version {data_version}."
            )
            _set_stage(record, root, "frozen", [], [], frozen_reason)
        else:
            entry = frozen
            _add_artifact(record, root, entry["manifest"], is_input=True)
            _set_stage(
                record,
                root,
                "frozen",
                [entry["artifact"]],
                [entry["artifact"]] if entry["ok"] else [],
                entry["reason"] or f"No verified frozen parquet for {symbol} {data_version}.",
            )

        scans = _scan_paths(root, symbol, data, output_path)
        existing_scans = [path for path in scans if path.is_file()]
        _set_stage(
            record,
            root,
            "scanned",
            scans,
            existing_scans,
            f"No per-symbol fit parquet found; expected a scan/cache artifact for {symbol}.",
        )

        labels = _label_paths(root, symbol)
        existing_labels = [path for path in labels if path.is_file()]
        _set_stage(
            record,
            root,
            "labeled",
            labels,
            existing_labels,
            f"No top_v1 or bottom_v1 label parquet found for {symbol}.",
        )

        report_paths = [root / path for path in EVALUATION_REPORTS]
        matching_reports = [
            path for path in report_paths if path.is_file() and _csv_has_symbol(path, symbol)
        ]
        if data_version not in {"frozen_v20261024", "v20261024"}:
            matching_reports = []
            eval_reason = (
                f"No symbol-level evaluation artifact for data_version {data_version}."
            )
        else:
            eval_reason = f"No per-symbol evaluation row found for {symbol}."
        _set_stage(
            record,
            root,
            "evaluated",
            report_paths,
            matching_reports,
            eval_reason,
            input_paths=matching_reports,
        )

        oof = _oof_paths(root, symbol)
        expected_oof = oof or [root / "data" / "oof" / f"*{symbol}*.parquet"]
        _set_stage(
            record,
            root,
            "calibrated",
            expected_oof,
            oof,
            f"No OOF/calibration parquet containing {symbol} was found.",
        )

        confirmed_labels = _confirmed_paths(root, symbol)
        confirmed = confirmed_labels.copy()
        if data.get("confirmed_tops"):
            confirmed.append(output_path)
        _set_stage(
            record,
            root,
            "confirmed",
            confirmed,
            confirmed,
            f"No confirmed-label artifact found for {symbol}.",
            input_paths=confirmed_labels,
        )

    return list(records.values())


def build_manifest(root: Path = Path(".")) -> dict:
    root = Path(root).resolve()
    frozen_records, frozen_lookup = _frozen_records(root)
    export_records = _export_records(root, frozen_lookup)
    records = frozen_records + export_records
    records.sort(
        key=lambda row: (row["symbol"], row["model_version"], row["data_version"])
    )
    summary = {
        stage: {
            "true": sum(bool(row[stage]) for row in records),
            "false": sum(not bool(row[stage]) for row in records),
        }
        for stage in STAGES
    }
    for record in records:
        record["artifact_paths"].sort()
        record["input_hashes"] = dict(sorted(record["input_hashes"].items()))
        record["artifact_hashes"] = dict(sorted(record["artifact_hashes"].items()))
        for stage in STAGES:
            record["stage_artifacts"][stage].sort()
    return {
        "schema_version": 1,
        "stage_definitions": STAGE_DEFINITIONS,
        "summary": summary,
        "records": records,
    }


def write_manifest(root: Path = Path("."), output_path: Path | None = None) -> Path:
    root = Path(root).resolve()
    target = Path(output_path) if output_path is not None else root / "data" / "coverage_manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(root)
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the research coverage manifest")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    path = write_manifest(args.root, args.out)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    print(path, "records", len(manifest["records"]))


if __name__ == "__main__":
    main()
