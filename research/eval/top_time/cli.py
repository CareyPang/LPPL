"""Explicit JSON ledger input; new output directories only, no market downloads."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .contracts import VERSION, Forecast, Protocol, ScheduledRun
from .labels import build_labels
from .scoring import evaluate

REQUIRED = {"schema_version", "symbol", "sessions", "prices", "price_basis",
            "calendar_status", "price_basis_status", "publication_status", "input_status",
            "forecasts", "runs", "protocol", "mode"}
ALLOWED = REQUIRED | {"available_sessions", "asof_session", "start_session", "end_session"}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def load_bundle(path: Path) -> dict:
    bundle = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(bundle, dict):
        raise ValueError("input must be one JSON object")
    if REQUIRED - bundle.keys() or bundle.keys() - ALLOWED:
        raise ValueError(f"missing keys={sorted(REQUIRED-bundle.keys())}; "
                         f"unknown keys={sorted(bundle.keys()-ALLOWED)}")
    if bundle["schema_version"] != VERSION:
        raise ValueError("unknown schema_version")
    if bundle["mode"] not in {"strict", "diagnostic", "fixture"}:
        raise ValueError("mode must be strict, diagnostic or fixture")
    if not isinstance(bundle["sessions"], list) or not isinstance(bundle["prices"], list):
        raise ValueError("an explicit calendar and aligned price vector are required")
    if not bundle["sessions"] or len(bundle["sessions"]) != len(bundle["prices"]):
        raise ValueError("calendar and prices must be nonempty and aligned")
    if not isinstance(bundle["symbol"], str) or not bundle["symbol"].strip():
        raise ValueError("symbol must be a nonempty string")
    if not isinstance(bundle["price_basis"], str) or not bundle["price_basis"].strip():
        raise ValueError("price_basis must be declared")
    for field in ("calendar_status", "price_basis_status", "publication_status", "input_status"):
        if not isinstance(bundle[field], str) or not bundle[field].strip():
            raise ValueError(f"{field} must be a nonempty evidence declaration")
    for field in ("forecasts", "runs"):
        if not isinstance(bundle[field], list):
            raise ValueError(f"{field} must be an explicit list, even when empty")
    if not isinstance(bundle["protocol"], dict):
        raise ValueError("protocol must be an object")
    if bundle["mode"] == "fixture" and bundle["input_status"] != "SYNTHETIC":
        raise ValueError("fixture mode is only for explicitly synthetic inputs")
    if bundle["mode"] == "strict":
        for field in ("calendar_status", "price_basis_status", "publication_status"):
            if bundle[field] != "VERIFIED":
                raise ValueError(f"strict mode requires {field}=VERIFIED; use diagnostic otherwise")
        if bundle.get("available_sessions") is None:
            raise ValueError("strict mode requires explicit data availability; no same-day assumption")
        if bundle["input_status"] == "SYNTHETIC":
            raise ValueError("synthetic inputs must use fixture mode")
        if bundle["input_status"] != "VERIFIED_LEDGER":
            raise ValueError("strict mode requires input_status=VERIFIED_LEDGER; use diagnostic otherwise")
    return bundle


def run_bundle(input_path: Path, output_dir: Path) -> dict:
    input_path, output_dir = Path(input_path), Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("output directory already exists; previous results are immutable")
    before = _digest(input_path)
    bundle = load_bundle(input_path)
    config = Protocol(**bundle["protocol"])
    book = build_labels(bundle["symbol"], bundle["sessions"], bundle["prices"],
                        config=config, asof_session=bundle.get("asof_session"),
                        available_sessions=bundle.get("available_sessions"),
                        input_status=bundle["input_status"])
    forecasts = [Forecast(**row) for row in bundle["forecasts"]]
    runs = [ScheduledRun(**row) for row in bundle["runs"]]
    # Fixture arithmetic uses strict action requirements, but is never performance evidence.
    mode = "strict" if bundle["mode"] == "fixture" else bundle["mode"]
    result = evaluate(book, forecasts, runs, config=config, mode=mode,
                      start_session=bundle.get("start_session", 0),
                      end_session=bundle.get("end_session"))
    evidence = {"strict": "SOURCE_ASSERTED_STRICT_LEDGER_NOT_INDEPENDENTLY_ATTESTED",
                "diagnostic": "DIAGNOSTIC_NOT_PROSPECTIVE",
                "fixture": "SYNTHETIC_IMPLEMENTATION_CHECK_NOT_MODEL_SKILL"}[bundle["mode"]]
    result.metadata.update({"input_mode": bundle["mode"], "evidence_status": evidence,
                            "price_basis": bundle["price_basis"],
                            "calendar_status": bundle["calendar_status"],
                            "price_basis_status": bundle["price_basis_status"],
                            "publication_status": bundle["publication_status"],
                            "input_sha256": before,
                            "predictive_skill": "NOT_ESTABLISHED"})
    if before != _digest(input_path):
        raise RuntimeError("input changed during evaluation")
    # Do not create an output until validation and evaluation complete successfully.
    output_dir.mkdir(parents=True, exist_ok=False)
    _write(output_dir / "protocol.json", config.to_dict())
    _write(output_dir / "labels.json", asdict(book))
    _write(output_dir / "evaluation.json", result.to_dict())
    manifest = {"evaluator_version": VERSION, "evidence_status": evidence,
                "input_sha256": before, "input_unchanged": True,
                "source_sha256": {p.name: _digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
                "output_sha256": {p.name: _digest(p) for p in sorted(output_dir.iterdir())}}
    _write(output_dir / "manifest.json", manifest)
    return {"output": str(output_dir), "evidence_status": evidence,
            "metrics": result.metrics}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_bundle(args.input, args.out)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
