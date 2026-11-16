#!/usr/bin/env python3
"""Hash the frozen T00 legacy inputs into a new, never-overwritten run directory."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = "4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5"
PR50 = "7f7fe930ab4065295718dfcfe89b87cedcaaf1fb"
PR99 = "4986455cb9d8871bb7fda25a221db5a5a11ad009"
PR100 = "3f2de2e541c519e962d010055da8715733101e20"
DEFAULT_LOCAL_ROOT = Path("/home/ubuntu/repos/LPPL/data/features")
REPORT_REF = re.compile(r"reports/[A-Za-z0-9_./-]+")
RESULT_SUFFIXES = {".csv", ".gz", ".json", ".jsonl", ".npz", ".parquet", ".pkl"}
PR50_PATHS = (
    "research/eval/top_time/replay.py",
    "research/eval/top_time/contracts.py",
    "research/eval/top_time/scoring.py",
    "tools/lppl_top_time_replay.py",
    "docs/research/2026-11-06-oscillation-units-and-refilter.md",
    "docs/research/2026-11-06-top-time-replay-protocol.md",
    "docs/research/2026-11-06-top-time-replay-results.md",
    "docs/research/2026-11-06-first-window-failure-attribution.md",
    "docs/research/2026-11-06-claim-boundary-ablation-protocol.md",
    "docs/research/2026-11-06-claim-boundary-ablation-results.md",
    "docs/research/evidence/window-cluster-20261106/v1",
    "docs/research/evidence/top-time-replay-20261106/v1",
    "docs/research/evidence/top-time-first-window-20261106/v2",
    "docs/research/evidence/claim-boundary-20261106/v1",
)
PR99_PATHS = (
    "reports/f1_miss_map",
    "reports/f2_profile",
    "reports/f3_gls",
    "reports/f4_lagrange",
    "reports/fit_accuracy_f1_f4.md",
    "research/synth/lppls_synth.py",
)


def git_paths(ref: str, *pathspecs: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, "--", *pathspecs],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(set(result.stdout.splitlines()))


def git_bytes(ref: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def hash_git_blob(ref: str, path: str) -> tuple[str, int]:
    process = subprocess.Popen(
        ["git", "cat-file", "blob", f"{ref}:{path}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: process.stdout.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    error = process.stderr.read() if process.stderr else b""
    if process.wait() != 0:
        raise RuntimeError(f"git cat-file failed for {ref}:{path}: {error.decode(errors='replace')}")
    return digest.hexdigest(), size


def hash_local_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def report_references(main_paths: list[str]) -> tuple[list[dict], set[str], list[dict]]:
    docs = [p for p in main_paths if re.fullmatch(r"docs/preregistration.*\.md", p)]
    reports = {p for p in main_paths if p.startswith("reports/")}
    references: set[str] = set()
    for doc in docs:
        text = git_bytes(MAIN, doc).decode("utf-8")
        references.update(match.rstrip(".,;:") for match in REPORT_REF.findall(text))

    resolved: set[str] = set()
    details = []
    unresolved = []
    for reference in sorted(references):
        key = reference.rstrip("/")
        matches = sorted(
            p for p in reports if p == key or p.startswith(key.rstrip("/") + "/")
        )
        if not matches and not Path(key).suffix:
            matches = sorted(p for p in reports if p == key + ".md")
        if not matches:
            matches = sorted(p for p in reports if p.startswith(key))
        if matches:
            resolved.update(matches)
        else:
            unresolved.append({"path": reference, "reason": "no tracked reports/ path matched"})
        details.append({"reference": reference, "matched_paths": matches})
    return details, resolved, unresolved


def git_entries(ref: str, paths: list[str], category: str) -> list[dict]:
    rows = []
    for path in sorted(set(paths)):
        sha, size = hash_git_blob(ref, path)
        rows.append(
            {
                "path": path,
                "sha256": sha,
                "size_bytes": size,
                "tracking": "tracked",
                "category": category,
                "source_ref": ref,
            }
        )
    return rows


def local_entries(root: Path) -> tuple[list[dict], list[str], int]:
    rows = []
    skipped_symlinks = []
    total_bytes = 0
    if not root.is_dir():
        return rows, skipped_symlinks, total_bytes
    for directory in sorted(root.glob("lppls_*")):
        if directory.is_symlink() or not directory.is_dir():
            if directory.is_symlink():
                skipped_symlinks.append(str(directory))
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                skipped_symlinks.append(str(path))
                continue
            if not path.is_file():
                continue
            sha, size = hash_local_file(path)
            total_bytes += size
            rows.append(
                {
                    "path": str(path),
                    "relative_path": path.relative_to(root).as_posix(),
                    "sha256": sha,
                    "size_bytes": size,
                    "tracking": "local-only",
                    "category": "legacy_lppls_scan_output",
                    "source_ref": None,
                }
            )
    return rows, skipped_symlinks, total_bytes


def build_inventory(local_root: Path) -> dict:
    main_paths = git_paths(MAIN)
    refs, report_paths, unresolved_reports = report_references(main_paths)
    frozen_paths = [p for p in main_paths if p.startswith("data/frozen/")]
    universe_paths = [
        p for p in main_paths if re.fullmatch(r"data/universe/csi300_20\d{6}\.csv", p)
    ]
    research_candidates = [
        p
        for p in main_paths
        if p.startswith("research/")
        and Path(p).suffix.lower() in RESULT_SUFFIXES
        and Path(p).name.lower() != "readme.md"
    ]
    pr50_paths = git_paths(PR50, *PR50_PATHS)
    pr99_paths = git_paths(PR99, *PR99_PATHS)

    files = []
    files.extend(git_entries(MAIN, [p for p in main_paths if re.fullmatch(r"docs/preregistration.*\.md", p)], "preregistration"))
    files.extend(git_entries(MAIN, sorted(report_paths), "referenced_legacy_report"))
    files.extend(git_entries(MAIN, frozen_paths, "frozen_data"))
    files.extend(git_entries(MAIN, universe_paths, "registered_universe_snapshot"))
    files.extend(git_entries(MAIN, research_candidates, "tracked_research_result"))
    files.extend(git_entries(PR50, pr50_paths, "pr50_legacy_evidence"))
    files.extend(git_entries(PR99, pr99_paths, "pr99_legacy_evidence"))
    local, skipped_symlinks, local_bytes = local_entries(local_root)
    files.extend(local)
    files.sort(key=lambda row: (row["tracking"], row["source_ref"] or "", row["path"]))

    by_key = {(row["source_ref"], row["path"]): row for row in files}
    pr99_logs = {}
    for experiment in ("f2_profile", "f3_gls", "f4_lagrange"):
        original_path = f"reports/{experiment}/run_r1.log"
        corrected_path = f"reports/{experiment}/run.log"
        original = by_key.get((PR99, original_path))
        corrected = by_key.get((PR99, corrected_path))
        pr99_logs[experiment] = {
            "original_run_r1_exists": original is not None,
            "original_run_r1_sha256": original["sha256"] if original else None,
            "corrected_run_exists": corrected is not None,
            "corrected_run_sha256": corrected["sha256"] if corrected else None,
        }

    generator_path = "research/synth/lppls_synth.py"
    generator = by_key.get((PR99, generator_path))
    generator_text = git_bytes(PR99, generator_path).decode("utf-8") if generator else ""
    has_generator_version = bool(
        re.search(r"(?im)^\s*(?:GENERATOR_VERSION|SYNTH_GENERATOR_VERSION)\s*=", generator_text)
    )

    not_established = list(unresolved_reports)
    if not research_candidates:
        not_established.append(
            {
                "item": "tracked_research_result_files",
                "reason": "no non-README result-format files found under research/ at pinned main using the recorded suffix filter",
            }
        )
    if not local_root.is_dir():
        not_established.append(
            {"item": "local_lppls_scan_outputs", "reason": f"local scan root absent: {local_root}"}
        )
    if skipped_symlinks:
        not_established.append(
            {
                "item": "local_scan_symlinks",
                "reason": "symlinks were intentionally not followed or hashed",
                "paths": sorted(skipped_symlinks),
            }
        )
    if not has_generator_version:
        not_established.append(
            {
                "item": "pr99_synthetic_generator_version",
                "reason": "no explicit GENERATOR_VERSION or SYNTH_GENERATOR_VERSION constant found; generator content is hash-pinned",
            }
        )

    return {
        "_meta": {
            "schema_version": "lppls_t00_preserved_legacy_sha256_v1",
            "run_id": "t00_20261116_a1",
            "generated_at_utc": datetime.now(UTC).isoformat(timespec="microseconds"),
            "hash": "SHA-256; Git blobs and local files streamed in 1 MiB chunks",
            "pinned_refs": {"main": MAIN, "pr50": PR50, "pr99": PR99, "pr100_task_source": PR100},
        },
        "selection": {
            "preregistration_docs": [
                p for p in main_paths if re.fullmatch(r"docs/preregistration.*\.md", p)
            ],
            "referenced_reports": refs,
            "frozen_data_paths": frozen_paths,
            "registered_universe_snapshot_paths": universe_paths,
            "tracked_research_result_paths": research_candidates,
            "pr50_evidence_paths": pr50_paths,
            "pr99_evidence_paths": pr99_paths,
            "local_scan_root": str(local_root),
            "local_scan_directories": sorted(
                p.name for p in local_root.glob("lppls_*") if p.is_dir()
            )
            if local_root.is_dir()
            else [],
            "unresolved_report_references": unresolved_reports,
        },
        "pr99_notes": {
            "statuses": {
                "F1": "descriptive; threshold for re-proposing _g3 not met",
                "F2": "FAILED synthetic gate",
                "F3": "FAILED synthetic gate",
                "F4": "FAILED synthetic gate",
            },
            "f2_f3_f4_logs": pr99_logs,
            "generator": {
                "path": generator_path,
                "sha256": generator["sha256"] if generator else None,
                "explicit_version_constant_found": has_generator_version,
                "version": "NOT_ESTABLISHED" if not has_generator_version else "see source",
            },
            "log_note": "run_r1.log is the first/original run; run.log is the corrected-generator rerun when both are present.",
        },
        "local_only_summary": {
            "file_count": len(local),
            "total_bytes": local_bytes,
            "total_mib": round(local_bytes / (1024 * 1024), 2),
            "files_are_hashed_in_place": True,
            "files_copied_into_repository": False,
        },
        "files": files,
        "NOT_ESTABLISHED": not_established,
    }


def sha256_json_list(values: list[int]) -> str:
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def installed_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "NOT_INSTALLED"


def build_baseline(inventory: dict) -> dict:
    source_paths = [
        ".github/workflows/index_daily.yml",
        ".github/workflows/index_replay.yml",
        "pyproject.toml",
        "research/features/lppls_scan.py",
        "research/lppls/core.py",
        "research/features/lppls_rules.py",
        "research/optim/optimizers.py",
        "research/labels/run_top.py",
        "research/pipeline/daily.py",
        "research/eval/dataset.py",
        "research/eval/export_contract.py",
        "research/eval/original_standard.py",
    ]
    source_hashes = {
        path: hash_git_blob(MAIN, path)[0] for path in source_paths
    }
    pr50_source_paths = [
        "research/eval/top_time/replay.py",
        "research/eval/top_time/contracts.py",
        "research/eval/top_time/scoring.py",
        "tools/lppl_top_time_replay.py",
    ]
    window_lists = {
        "IDX_WINDOWS": list(range(125, 751, 5)),
        "STK_WINDOWS": list(range(125, 751, 25)),
        "SHORT_WINDOWS": list(range(30, 121, 5)),
        "XS_WINDOWS_effective": list(range(10, 21, 2)),
        "XL_WINDOWS": list(range(525, 1501, 25)),
    }
    window_lists["full_windows()"] = sorted(
        set(
            window_lists["XS_WINDOWS_effective"]
            + window_lists["SHORT_WINDOWS"]
            + window_lists["IDX_WINDOWS"]
            + window_lists["XL_WINDOWS"]
        )
    )
    window_sets = {
        name: {
            "values": values,
            "count": len(values),
            "json_sha256": sha256_json_list(values),
        }
        for name, values in window_lists.items()
    }

    frozen_inventory = []
    adjustment_types = {
        "v20261024": "qfq",
        "v20261104": "qfq",
        "a90s_v20261104": "none(index)",
        "stocks_v20261024": "close_hfq = raw close × Sina HFQ factor",
        "ext_v20261029": "NOT_ESTABLISHED",
    }
    for directory in (
        "v20261024",
        "v20261104",
        "a90s_v20261104",
        "stocks_v20261024",
        "ext_v20261029",
    ):
        base = f"data/frozen/{directory}"
        manifest_path = next(
            (p for p in (f"{base}/manifest.json", f"{base}/MANIFEST.json") if p in git_paths(MAIN, base)),
            None,
        )
        readme_path = f"{base}/README.md"
        manifest_sha = hash_git_blob(MAIN, manifest_path)[0] if manifest_path else None
        readme_sha = hash_git_blob(MAIN, readme_path)[0] if readme_path in git_paths(MAIN, base) else None
        manifest = json.loads(git_bytes(MAIN, manifest_path)) if manifest_path else {}
        assets = []
        if isinstance(manifest, list):
            for entry in manifest:
                symbol = entry["symbol"]
                adjust = entry.get("adjust", adjustment_types[directory])
                assets.append(
                    {
                        "symbol": symbol,
                        "path": f"{base}/{symbol}_{adjust}.parquet",
                        "adjustment_type": adjust,
                        "rows": entry.get("rows"),
                        "first_date": entry.get("first_date"),
                        "last_date": entry.get("last_date"),
                        "sha256_declared_in_manifest": entry.get("sha256"),
                        "source": entry.get("source"),
                    }
                )
        elif isinstance(manifest, dict) and isinstance(manifest.get("symbols"), dict):
            for symbol, entry in sorted(manifest["symbols"].items()):
                assets.append(
                    {
                        "symbol": symbol,
                        "path": f"{base}/{symbol}.parquet",
                        "adjustment_type": manifest.get("adjust", adjustment_types[directory]),
                        "rows": entry.get("rows"),
                        "first_date": entry.get("start", entry.get("registered_start")),
                        "last_date": entry.get("end"),
                        "sha256_declared_in_manifest": entry.get("sha256"),
                        "source": entry.get("source", manifest.get("source")),
                    }
                )
        if directory == "stocks_v20261024":
            assets = []
        if isinstance(manifest, list):
            asset_count = len(manifest)
        elif isinstance(manifest, dict) and isinstance(manifest.get("symbols"), (dict, list)):
            asset_count = len(manifest["symbols"])
        else:
            asset_count = None
        frozen_inventory.append(
            {
                "directory": base,
                "readme": {"path": readme_path, "sha256": readme_sha},
                "manifest": {"path": manifest_path, "sha256": manifest_sha},
                "adjustment_type": adjustment_types[directory],
                "asset_count": asset_count,
                "assets": assets,
                "asset_hashes_note": (
                    "577 per-symbol hashes are inside the pinned manifest; parquet files reside in untracked data/cache/stocks/."
                    if directory == "stocks_v20261024"
                    else "Per-file SHA-256 values are also listed in preserved_legacy_sha256.json."
                ),
                "adjustment_not_established_reason": (
                    "Neither README.md nor MANIFEST.json declares an adjustment type."
                    if directory == "ext_v20261029"
                    else None
                ),
            }
        )

    universe_snapshots = []
    inventory_file_hashes = {
        (row["source_ref"], row["path"]): row["sha256"] for row in inventory["files"]
    }
    for path in inventory["selection"]["registered_universe_snapshot_paths"]:
        rows = list(csv.DictReader(git_bytes(MAIN, path).decode("utf-8").splitlines()))
        universe_snapshots.append(
            {
                "path": path,
                "sha256": inventory_file_hashes[(MAIN, path)],
                "member_count": len(rows),
                "symbols": [
                    f"{row['market'].lower()}{row['code']}" for row in rows
                ],
            }
        )

    package_specs = [
        ("numpy", "numpy>=1.26"),
        ("scipy", "scipy>=1.11"),
        ("pandas", "pandas>=2.0"),
        ("pyarrow", "pyarrow>=14"),
        ("akshare", "akshare>=1.12"),
        ("baostock", "baostock>=0.8.9"),
        ("cma", "cma>=3.3"),
        ("requests", "requests>=2.31"),
        ("pypinyin", "pypinyin>=0.49"),
        ("xlrd", "xlrd>=2.0"),
        ("scikit-learn", "scikit-learn>=1.3"),
        ("statsmodels", "statsmodels>=0.14"),
        ("tabulate", "tabulate>=0.9"),
        ("pytest", "pytest>=7"),
        ("ruff", "ruff>=0.4"),
        ("matplotlib", "matplotlib>=3.7"),
        ("pyyaml", "pyyaml>=6"),
    ]
    dependencies = [
        {
            "package": package,
            "requirement": requirement,
            "installed_version": installed_version(package),
        }
        for package, requirement in package_specs
    ]

    old_main_params = {
        "m": [0.01, 2.0],
        "omega": [1.0, 50.0],
        "tc": "tc ∈ [t2 - 0.2*dt, t2 + 0.2*dt], dt=n-1",
        "allow_inside": True,
        "design_tau": "max(abs(tc-t), MIN_DT)",
        "n_random": 10,
        "seed": 0,
        "window_sets": {"index": "SHORT_WINDOWS + IDX_WINDOWS", "stock": "SHORT_WINDOWS + STK_WINDOWS"},
    }
    replay_protocol = {
        "fit_calls": 0,
        "saved_arm_names": [
            "ref_6_12m",
            "ref_12_24m",
            "or2_full",
            "or4_full",
            "or4_thin",
            "cluster_any_full",
            "cluster_cross_full",
            "cluster_cross_thin",
            "cluster_cross_stable2",
        ],
        "additional_baseline": "calendar_fixed_10",
        "scopes": ["stage", "short"],
        "evaluation": {
            "evaluator": "top_time_evaluator_v1_dev",
            "mode": "diagnostic",
            "actionability": "theoretical",
            "horizon_sessions": 63,
            "minimum_action_lead_sessions": 5,
            "maximum_inclusive_width_sessions": 10,
            "require_entire_window_lead": True,
            "stage_context": [63, 42],
            "local_context": [10, 10],
            "primary_metrics": ["E", "P", "TP", "FN", "recall", "precision"],
        },
        "time_domain": "saved historical intervals; no fresh fit or future-only claim; original scope/publication/actionability NOT_ESTABLISHED",
        "scan_grid": "five observed sessions; last original fit 2018-12-26; per-input-map prediction/evaluation end 2018-12-28; ledger cutoff 2018-12-31; labels mature using prices through 2019-12-31",
        "result": "0-3 strict stage TPs out of the same 91 known stage events; 88-91 FNs",
    }
    candidate = {
        "id": "candidate_future_fullcycles_1p5",
        "status": "SPEC_ONLY_NOT_EXECUTED",
        "tc_domain": "tc > t2; reject tc <= t2; no abs(tc-t) continuation",
        "minimum_full_cycles": 1.5,
        "cycles_formula": "omega/(2*pi) * ln((tc-t1)/(tc-t2))",
        "primary_target": "stage_top_after_1_to_6_month_rise",
        "secondary_target": "local_top_separately_scored",
        "minimum_action_lead_sessions": 5,
        "other_fit_parameters": "TBD in T01; do not infer from literature",
        "scoring": "research-contract metrics; scoring protocol must be frozen before B0 execution; no candidate scores exist",
        "data_version": "NOT_ESTABLISHED; T01/T02 sample protocol and confirmation authorization are not executed",
    }
    baselines = [
        {
            "id": "legacy_main_v2",
            "status": "legacy implementation/result family; not a new run",
            "parameters": old_main_params,
            "time_domain": "tc may be inside the fitting window; global ALLOW_INSIDE=True for v2; design uses |tc-t|",
            "scoring": {
                "scan": "fit generation only; no score in scan",
                "historical_evaluator": "research.eval.original_standard",
                "metrics": "A1/A2 alarm-to-qualified-top precision/recall; H={60,120}; thresholds={0.05,0.10,0.20}; 1000 circular shifts, minimum shift 250 sessions",
                "version_note": "This is not the PR #50 two-level top-time replay score.",
            },
            "data_version": "index: data/frozen/v20261024 (qfq); stock: stocks_v20261024 close_hfq cache. Production daily without --frozen refreshes a runtime vintage.",
        },
        {
            "id": "legacy_pr50_replay",
            "status": "historical saved-interval replay; HYPOTHETICAL_REPLAY_CLAIM_NOT_ORIGINAL",
            "parameters": replay_protocol,
            "time_domain": "old saved scan intervals; last original fit 2018-12-26; per-input-map prediction/evaluation end 2018-12-28, replay ledger cutoff 2018-12-31; 2019 prices only mature labels",
            "scoring": "two separate stage/short probes; one earliest formal claim; strict stage hit requires event coverage, >=5-session action lead, inclusive width <=10, and whole-window lead; no actual-publication claims",
            "data_version": "six A-share indices from v20261024 qfq; saved scan/material hashes are recorded in origin/pr50 evidence. PR50 output lists raw-fit Windows paths and hashes, but files are not present on this host.",
        },
        candidate,
    ]
    parameter_diff = [
        {
            "baseline": "legacy_main_v2",
            "search_or_params": "m=[0.01,2], omega=[1,50], tc=t2±0.2dt; 10 random starts; v2 rules",
            "time_domain": "inside-window allowed using absolute tau",
            "scoring": "A1/A2 historical original-standard evaluation; not a top-time replay score",
            "data_version": "v20261024 qfq indices; stocks_v20261024 close_hfq",
        },
        {
            "baseline": "legacy_pr50_replay",
            "search_or_params": "nine saved arms plus calendar_fixed_10; no refit",
            "time_domain": "saved intervals replayed hypothetically; prediction/evaluation to 2018-12-28",
            "scoring": "diagnostic first-claim strict stage/short probes; 0-3/91 stage hits",
            "data_version": "six-index v20261024 qfq snapshot; labels mature through 2019-12-31",
        },
        {
            "baseline": "candidate_future_fullcycles_1p5",
            "search_or_params": "tc>t2 and full cycles >=1.5; all other parameters TBD T01",
            "time_domain": "future-only",
            "scoring": "specification only; no result; freeze under T01/T02/T06a",
            "data_version": "NOT_ESTABLISHED; no candidate data/version selected",
        },
    ]

    code_shas = {
        "main": MAIN,
        "pr50": PR50,
        "pr99": PR99,
        "pr100_task_source": PR100,
        "pr100_pinned_main": "5d5fc7959e24b8eebaa34e3882c7b2ce069daeb0",
    }
    task_source_paths = [
        "docs/research/lppls-literature-handoff-20261116/DEVIN_TASKS.md",
        "docs/research/lppls-literature-handoff-20261116/research-contract.json",
        "docs/research/lppls-literature-handoff-20261116/README.md",
    ]
    main_diff = [
        "frontend/app/lppl-data.js",
        "frontend/app/od-watch.js",
        "frontend/app/stock-header.js",
        "frontend/home.html",
        "frontend/stock.html",
        "frontend/tests/live-quote.test.cjs",
        "workers/stock-query/src/index.js",
        "workers/stock-query/test/index.test.mjs",
    ]
    return {
        "_meta": {
            "schema_version": "lppls_t00_baseline_manifest_v1",
            "run_id": "t00_20261116_a1",
            "generated_at_utc": datetime.now(UTC).isoformat(timespec="microseconds"),
            "scope": "documentation and inventory only; no refit, model/workflow/production changes",
        },
        "version_relations": {
            "code_shas": code_shas,
            "task_source_paths": task_source_paths,
            "task_source_sha256": {
                path: hash_git_blob(PR100, path)[0] for path in task_source_paths
            },
            "current_main_vs_pr100_pinned_main": {
                "full_changed_paths": main_diff,
                "research_scripts_data_frozen_preregistration_changed_paths": [],
                "conclusion": "diff is frontend/worker only",
            },
        },
        "environment": {
            "python": {
                "version": sys.version.split()[0],
                "executable": sys.executable,
                "pyproject_requires_python": ">=3.11",
            },
            "dependencies": dependencies,
            "installed_version_source": "active project Python environment importlib.metadata (same distributions as pip list)",
            "pyproject_toml_sha256": source_hashes["pyproject.toml"],
        },
        "source_sha256": source_hashes,
        "pr50_source_sha256": {
            path: hash_git_blob(PR50, path)[0] for path in pr50_source_paths
        },
        "data_sources": {
            "frozen_datasets": frozen_inventory,
            "individual_frozen_file_hashes": "preserved_legacy_sha256.json",
            "registered_stock_universe_snapshots": universe_snapshots,
            "runtime_stock_cache": {
                "documented_path": "data/cache/stocks/",
                "present_in_this_worktree": False,
                "adjustment_type": "raw close multiplied by Sina HFQ factor -> close_hfq",
                "source": "data/frozen/stocks_v20261024/README.md; research/data/stocks.py",
            },
        },
        "trading_calendar": {
            "entry": "research.features.lppls_scan.calendar() -> price_series('sh000001').index",
            "source_file": "research/features/lppls_scan.py",
            "source_file_sha256": source_hashes["research/features/lppls_scan.py"],
            "price_series_source_file": "research/eval/dataset.py",
            "price_series_source_sha256": source_hashes["research/eval/dataset.py"],
            "data_path": "data/frozen/v20261024/sh000001_qfq.parquet",
            "data_sha256": "82bc8177ab3b5fb13dace1dbd54c200d477a7c473fdebd457ad0d483b19d5784",
            "adjustment_type": "qfq",
            "first_date": "1990-12-19",
            "last_date": "2026-10-23",
            "length": 8575,
            "calendar_semantics": "observed date index, not independently verified exchange calendar",
        },
        "model_entry_points": [
            {
                "entry": "python -m research.features.lppls_scan {index|stock}",
                "role": "batch fit scan",
                "source_sha256": source_hashes["research/features/lppls_scan.py"],
            },
            {
                "entry": "python -m research.pipeline.daily SYMBOL [--asof DATE]",
                "role": "production daily/replay fit and record",
                "source_sha256": source_hashes["research/pipeline/daily.py"],
            },
            {
                "entry": "python -m research.eval.original_standard [symbols...]",
                "role": "legacy A1/A2 research evaluation",
                "source_sha256": source_hashes["research/eval/original_standard.py"],
            },
        ],
        "search_bounds": {
            "boxes": {
                "v1": {
                    "m": [0.01, 2.0],
                    "omega": [1.0, 50.0],
                    "tc_lo_formula": "dt + 0.5",
                    "tc_hi_formula": "dt + 0.2*dt",
                    "inside": False,
                    "n_random": 0,
                    "short": False,
                    "effective_index_windows": "IDX_WINDOWS",
                    "effective_stock_windows": "STK_WINDOWS",
                },
                "proto": {
                    "m": [0.01, 0.99],
                    "omega": [2.0, 25.0],
                    "tc_lo_formula": "dt + 0.5",
                    "tc_hi_formula": "dt + min(0.2*dt, 115)",
                    "inside": False,
                    "tc_cap": 115.0,
                    "n_random": 0,
                    "short": False,
                    "effective_index_windows": "IDX_WINDOWS",
                    "effective_stock_windows": "STK_WINDOWS",
                },
                "v2": {
                    "m": [0.01, 2.0],
                    "omega": [1.0, 50.0],
                    "tc_lo_formula": "dt - 0.2*dt",
                    "tc_hi_formula": "dt + 0.2*dt",
                    "inside": True,
                    "n_random": 10,
                    "short": True,
                    "effective_index_windows": "SHORT_WINDOWS + IDX_WINDOWS",
                    "effective_stock_windows": "SHORT_WINDOWS + STK_WINDOWS",
                },
                "common_formula_context": {
                    "dt": "n-1",
                    "t2": "dt",
                    "anchor": "end (default)",
                    "start_anchor_alternative": "[t1 - 0.2*dt, t1 - 0.5]",
                    "tc_lower_rule": "dt + tc_lo if tc_lo >= 0.5 else dt + tc_lo*dt",
                    "high_rule": "dt + min(0.2*dt, tc_cap) when tc_cap exists; otherwise dt + 0.2*dt",
                },
            },
            "solver": {
                "name": "tcgrid_lm",
                "defaults": {"seed": 0, "budget": {"n_tc": 40, "n_m": 12, "n_w": 16, "topk": 5}, "n_random": 0},
                "scan_call": "fit_one passes seed=0 and BOX n_random; v2 therefore uses 10 random starts",
                "optimizer": "grid profile over tc/m/omega; top-5 tc profiles plus random starts; bounded scipy least_squares method=trf, x_scale=jac",
                "least_squares": {
                    "ftol": 1e-12,
                    "xtol": 1e-12,
                    "gtol": 1e-10,
                    "max_nfev": 400,
                },
                "winner": "lowest SSE",
            },
            "seed": 0,
            "parallelism": {
                "LPPLS_PROCS_default": 8,
                "actual_mechanism": "multiprocessing.Pool processes, not threads",
                "chunk_default": 10,
                "daily_production": "single-symbol sequential daily path; no LPPLS_PROCS setting",
            },
            "window_sets": window_sets,
            "window_json_serialization": "UTF-8 compact JSON list: json.dumps(values, ensure_ascii=False, separators=(',', ':'))",
            "asof_grid": {
                "calendar_grid_anchor": "calendar()[::step]",
                "IDX_STEP": 5,
                "STK_STEP": 20,
                "splits": {
                    "dev": {"start": "2000-01-01", "end": "2018-12-31", "stock_snapshot": "csi300_20100104.csv", "stock_entry": "2010-01-04"},
                    "cal": {"start": "2019-01-01", "end": "2021-12-31", "stock_snapshot": "csi300_20181228.csv", "stock_entry": "2019-01-01"},
                    "test": {"start": "2022-01-01", "end": "2025-08-31", "stock_snapshot": "csi300_20211231.csv", "stock_entry": "2022-01-01"},
                },
                "index_symbols": ["sh000001", "sh000016", "sh000300", "sh000905", "sh000688", "sz399001", "sz399006"],
            },
        },
        "filter_bounds": {
            "core": {
                "TOP_RULE": {"B": "<0", "m": [0.1, 0.95], "omega": [4.0, 15.0], "horizon": [1, 115], "full_cycles": ">=1.5", "damping": ">=0.3", "r2": ">=0.8"},
                "SORNETTE_RULE": {"B": "<0", "m": [0.1, 0.9], "omega": [6.0, 13.0], "horizon": [1, 1000000000], "full_cycles": ">=2.5", "damping": ">=1.0", "r2": ">=0.9"},
            },
            "rules": {
                "box": "B<0; m∈[0.1,0.9]; omega∈[6,13]; ahead∈[0,90]",
                "lit1": "B<0; m∈[0.1,0.9]; omega∈[6,13]; ahead∈[-0.15dt,0.13dt]; osc>=2.5; D>=1.2; rel_err<=0.035",
                "lit2": "B<0; m∈[0.01,1.2]; omega∈[2,25]; ahead∈[-0.2dt,0.12dt]; osc>=2.5; D>=0.8; rel_err<=0.14",
                "p_top": "B<0; TOP_RULE bounds; n_osc>=1.5",
                "p_ds": "B<0; m∈[0.01,0.99]; omega∈[2,15]; ahead<=max(5,0.1n); n_osc>=2.5; D>=0.5",
                "p_strict": "B<0; 0.1<m<0.9; 6<omega<13; ahead<=90; n_osc>=2.5; D>=1; r2>=0.9",
            },
            "derived_units": {
                "osc": "(omega/2)*ln(abs(tc)/max(abs(tc-t2),1e-3))",
                "n_osc": "osc/pi",
                "abs_semantics": "abs(tc) and abs(tc-t2) permit inside-window tc values; rules do not impose future-only by themselves",
            },
            "grid_rules": {
                "fco_standard": "B<0; 0<m<=1; omega∈[2,25]; D>=0.5; osc>=2.5",
                "fco_early": "B<0; 0<m<=1; omega∈[2,25]; D>=0; osc>=1.5",
                "fco_end": "B<0; 0<m<=1; omega∈[2,25]; D>=0.8; osc>=2.5",
                "fco_pure": "B<0; 0<m<=0.9; omega∈[5,13]; D>=0.5; osc>=2.5",
            },
            "scales": {
                "SCALES": {"S": [30, 120], "M": [100, 240], "L": [200, 720]},
                "SCALES_XS": {"XS": [15, 30]},
                "SCALES_FCO": {"1-3m": [21, 63], "6-12m": [127, 252], "12-24m": [253, 504]},
                "SCALES_FCO6": {"2-4w": [10, 20], "1-3m": [21, 63], "3-6m": [64, 126], "6-12m": [127, 252], "12-24m": [253, 504], "2-6y": [505, 1500]},
                "SCALE_EVIDENCE": {"2-4w": "none", "1-3m": "none", "3-6m": "none", "6-12m": "dev", "12-24m": "dev", "2-6y": "none"},
            },
            "grid_rule_parameters": {
                "GRID_D": [0.5, 0.8, 1.0, 1.2],
                "GRID_W": {"w4_25": [4, 25], "w6_13": [6, 13]},
                "GRID_M": {"m0_1": [0, 1], "m01_09": [0.1, 0.9]},
                "GRID_E": {"eNone": "no maximum", "e014": 0.14, "e0035": 0.035},
                "jiang": {"relative_lomb_frequency_tolerance": 0.1, "adf_residual_t_threshold": -2.86},
            },
        },
        "production_call_chain": {
            "index_daily": {
                "workflow": ".github/workflows/index_daily.yml",
                "entry": "LPPLS_BOX=v2 python -m research.pipeline.daily SYMBOL --asof DATE --out out/index",
                "symbols": ["sh000001", "sh000016", "sh000300", "sh000905", "sh000688", "sz399001", "sz399006"],
                "pull_request_symbol": "sh000001 only",
            },
            "index_replay": {
                "workflow": ".github/workflows/index_replay.yml",
                "entry": "LPPLS_BOX=v2 python -m research.pipeline.daily \"$SYM\" --asof \"$ASOF\" --out out/index",
                "request_validation": "seven supported index symbols; date syntax and past-date validation",
            },
            "daily_behavior": {
                "box": "BOX=v2 from workflow environment",
                "ALLOW_INSIDE": "_core.ALLOW_INSIDE = bool(BOXES[BOX]['inside']) -> True",
                "windows": "full_windows(len(logp)) when --windows omitted; not the scan CLI v2 window subset",
                "rules": "rules(_derived(fits)); build_record also computes grid_rules for product indicators",
                "frozen_flag": "workflow does not pass --frozen; load_ohlc calls cache.refresh then cache.load",
                "data_version": "runtime vintage_{vintage}_{source}; exact future workflow vintage NOT_ESTABLISHED",
                "daily_parallelism": "sequential single-symbol path; no LPPLS_PROCS",
            },
        },
        "registered_baselines": baselines,
        "parameter_time_scoring_data_diff": parameter_diff,
        "units_cross_check": {
            "core_Fit_n_osc": "omega/(2*pi)*ln((tc-t0)/(tc-t_end)); full cycles on the strict future domain",
            "TOP_RULE_threshold": "n_osc>=1.5 full cycles",
            "SORNETTE_RULE_threshold": "n_osc>=2.5 full cycles",
            "lppls_rules": {
                "osc": "(omega/2)*ln(abs(tc)/max(abs(tc-t2),1e-3)); n_osc=osc/pi",
                "lit1_lit2": "osc>=2.5 -> 2.5/pi = 0.795774715... full cycles under the repository formula",
                "p_ds_p_strict": "n_osc>=2.5 -> 2.5 full cycles",
                "p_top": "n_osc>=1.5 -> 1.5 full cycles",
                "inside": "abs() allows inside-window values; this is not a future-only filter",
            },
            "pr50_cross_check": {
                "source": "origin/pr50:docs/research/2026-11-06-oscillation-units-and-refilter.md",
                "result": "confirms the repository old osc half-phase threshold maps to 2.5/pi full cycles in the specified future domain",
                "important_caveat": "PR50 documents a different denominator in the public Zhang–Zhang–Sornette 2016 table; official intent/FCO server equivalence is NOT_ESTABLISHED",
            },
        },
        "NOT_ESTABLISHED": [
            {"item": "external_market_adjustment", "reason": "ext_v20261029 README/MANIFEST do not declare adjusted vs unadjusted field semantics"},
            {"item": "PR50_original_publication_and_actionability", "reason": "replay labels all forecasts hypothetical; original scope, publish time and executable action evidence are absent"},
            {"item": "PR50_raw_fit_original_files", "reason": "manifest points to D:\\CodexData paths; this host has only saved reports/manifests and their hashes, not those raw files"},
            {"item": "distinct_2016_to_2025_holdout", "reason": "no separate 2016-2025 sample identity was found; known dates overlap registered dev/cal/test periods, and PR50 replay predicts only through 2018"},
            {"item": "production_runtime_vintage", "reason": "daily workflow refreshes data at run time; T00 did not dispatch a workflow"},
            {"item": "stocks_v20261024_cache_files", "reason": "README says parquet files are under untracked data/cache/stocks; directory is absent from this worktree, only the pinned manifest with per-symbol hashes is present"},
            {"item": "PR99_generator_version_label", "reason": inventory["pr99_notes"]["generator"]["version"]},
            {"item": "public_oscillation_rule_equivalence", "reason": "PR50 records a mismatch between public paper formula and repository formula; official intent / commercial server details are not established"},
        ],
    }


def build_sample_register(inventory: dict) -> dict:
    index_symbols = [
        "sh000001",
        "sh000016",
        "sh000300",
        "sh000905",
        "sh000688",
        "sz399001",
        "sz399006",
    ]
    split_rows = []
    index_split_specs = [
        (
            "dev",
            "2000-01-01",
            "2018-12-31",
            "consumed_for_tuning",
            "development split used for historical selection and reported LPPLS results",
            ["research/labels/run_top.py:17-21", "docs/preregistration.md:§4", "docs/preregistration.md:§17.4-§17.14"],
        ),
        (
            "cal",
            "2019-01-01",
            "2021-12-31",
            "consumed_for_tuning",
            "calibration segment opened 2026-10-26; no longer confirmation data",
            ["research/labels/run_top.py:17-21", "docs/preregistration.md:§18"],
        ),
        (
            "test",
            "2022-01-01",
            "2025-08-31",
            "dev_diagnostic_only",
            "final test opened 2026-10-27 and reported; not tuned, but not unopened confirmation",
            ["research/labels/run_top.py:17-21", "docs/preregistration.md:§19", "docs/preregistration.md:§19.1"],
        ),
    ]
    for split, start, end, classification, role, evidence in index_split_specs:
        for symbol in index_symbols:
            split_rows.append(
                {
                    "dataset": f"preregistered_index_{split}",
                    "asset": symbol,
                    "date_range": [start, end],
                    "classification": classification,
                    "role": role,
                    "evidence": evidence,
                }
            )

    local_root = Path(inventory["selection"]["local_scan_root"])
    stock_sample_dir = local_root / "lppls_v2_lite_stk100"
    stock_symbols = sorted(path.stem for path in stock_sample_dir.glob("*.parquet"))
    if len(stock_symbols) == 100:
        for symbol in stock_symbols:
            split_rows.append(
                {
                    "dataset": "registered_stock_dev_sample",
                    "asset": symbol,
                    "date_range": ["2010-01-04", "2018-12-31"],
                    "classification": "dev_diagnostic_only",
                    "role": "development-only cross-sectional rank experiment; did not expand to all 577 after a negative result",
                    "evidence": ["docs/preregistration.md:§17.11", "data/frozen/stocks_v20261024/README.md:3-8"],
                }
            )
    else:
        split_rows.append(
            {
                "dataset": "registered_stock_dev_sample",
                "asset": "100-stock sample",
                "date_range": ["2010-01-04", "2018-12-31"],
                "classification": "NOT_ESTABLISHED",
                "reason": f"expected 100 stock scan outputs in {stock_sample_dir}; found {len(stock_symbols)}",
                "evidence": ["docs/preregistration.md:§17.11"],
            }
        )

    for snapshot, start, end in (
        ("csi300_20181228.csv", "2019-01-01", "2021-12-31"),
        ("csi300_20211231.csv", "2022-01-01", "2025-08-31"),
    ):
        path = f"data/universe/{snapshot}"
        rows = csv.DictReader(git_bytes(MAIN, path).decode("utf-8").splitlines())
        for row in rows:
            symbol = f"{row['market'].lower()}{row['code']}"
            split_rows.append(
                {
                    "dataset": f"registered_stock_{'cal' if start == '2019-01-01' else 'test'}_universe",
                    "asset": symbol,
                    "snapshot": path,
                    "date_range": [start, end],
                    "classification": "NOT_ESTABLISHED",
                    "reason": "historical snapshot is registered, but exact per-stock scan/evaluation consumption is not established by the cited reports",
                    "evidence": ["docs/preregistration.md:§1", "research/labels/run_top.py:17-21", "research/eval/dataset.py:35-54"],
                }
            )

    replay = json.loads(
        git_bytes(PR50, "docs/research/evidence/top-time-replay-20261106/v1/input_map.json")
    )["sources"]
    event_raw = git_bytes(
        PR50, "docs/research/evidence/top-time-replay-20261106/v1/event_scores.csv"
    ).decode("utf-8")
    event_rows = csv.DictReader(event_raw.splitlines())
    stage_events: dict[str, set[str]] = {}
    for row in event_rows:
        if row.get("scope_probe") != "stage":
            continue
        parts = row.get("event_id", "").split(":")
        if len(parts) >= 4:
            stage_events.setdefault(parts[0], set()).add(parts[-1])
    replay_assets = []
    for row in replay:
        dates = stage_events.get(row["symbol"], set())
        replay_assets.append(
            {
                "asset": row["symbol"],
                "prediction_range": [row["prediction_start"], row["prediction_end"]],
                "evaluation_range": [row["evaluation_start"], row["evaluation_end"]],
                "label_observation_end": row["label_observation_end"],
                "planned_scans": row["planned_scans"],
                "days_without_saved_fit": row["days_without_saved_fit"],
                "price_basis": row["price_basis"],
                "calendar_basis": row["calendar_basis"],
                "stage_event_count": len(dates),
                "stage_event_date_range": [min(dates), max(dates)] if dates else None,
                "classification": "dev_diagnostic_only",
                "evidence": [
                    "origin/pr50:docs/research/evidence/top-time-replay-20261106/v1/input_map.json",
                    "origin/pr50:docs/research/evidence/top-time-replay-20261106/v1/event_scores.csv",
                ],
            }
        )

    frozen_confirmation = [
        {
            "asset": "sh000001",
            "date_range": ["1990-12-19", "1999-12-31"],
            "available_data_through": "2000-12-29 (reserved label horizon)",
            "dataset": "data/frozen/a90s_v20261104/sh000001.parquet",
            "classification": "confirmation_still_closed",
            "evidence": ["data/frozen/a90s_v20261104/README.md:1-10", "docs/preregistration.md:§21.3(c)", "docs/preregistration.md:§21.7"],
        },
        {
            "asset": "sz399001",
            "date_range": ["1991-04-03", "1999-12-31"],
            "available_data_through": "2000-12-29 (reserved label horizon)",
            "dataset": "data/frozen/a90s_v20261104/sz399001.parquet",
            "classification": "confirmation_still_closed",
            "limitation": "1991-04-03 through 1994-07-19 is a backcast segment and must be reported separately",
            "evidence": ["data/frozen/a90s_v20261104/README.md:1-10,23-26", "docs/preregistration.md:§21.3(c)", "docs/preregistration.md:§21.7"],
        },
    ]
    ext_manifest = json.loads(git_bytes(PR50, "data/frozen/ext_v20261029/MANIFEST.json"))
    for symbol, entry in sorted(ext_manifest["symbols"].items()):
        frozen_confirmation.append(
            {
                "asset": symbol,
                "date_range": [entry["start"], entry["end"]],
                "dataset": f"data/frozen/ext_v20261029/{symbol}.parquet",
                "classification": "confirmation_still_closed",
                "evidence": ["data/frozen/ext_v20261029/README.md:1-11", "docs/preregistration.md:§21.3(c)", "docs/preregistration.md:§21.7"],
            }
        )

    local_dirs = inventory["selection"]["local_scan_directories"]
    local_scans = []
    for directory in local_dirs:
        if directory.endswith("_cal"):
            classification = "consumed_for_tuning"
            reason = "calibration scan output; see preregistration §18"
        elif directory.endswith("_test"):
            classification = "dev_diagnostic_only"
            reason = "final-test output already opened once; see preregistration §19"
        else:
            classification = "dev_diagnostic_only"
            reason = "legacy exploratory/development scan; not a new confirmation sample"
        local_scans.append(
            {
                "directory": f"/home/ubuntu/repos/LPPL/data/features/{directory}",
                "classification": classification,
                "reason": reason,
                "evidence": [
                    f"/home/ubuntu/repos/LPPL/data/features/{directory}/",
                    "docs/preregistration.md:§17-§19",
                ],
            }
        )

    return {
        "_meta": {
            "schema_version": "lppls_t00_sample_consumption_register_v1",
            "run_id": "t00_20261116_a1",
            "generated_at_utc": datetime.now(UTC).isoformat(timespec="microseconds"),
        },
        "classification_values": [
            "consumed_for_tuning",
            "dev_diagnostic_only",
            "confirmation_still_closed",
            "NOT_ESTABLISHED",
        ],
        "registered_splits": split_rows,
        "pr50_91_stage_top_replay": {
            "overall_stage_events": sum(len(v) for v in stage_events.values()),
            "assets": replay_assets,
            "prediction_end": "2018-12-28",
            "ledger_cutoff": "2018-12-31",
            "last_original_fit_date": "2018-12-26",
            "label_observation_end": "2019-12-31",
            "classification": "dev_diagnostic_only",
            "not_a_holdout": True,
            "evidence": [
                "origin/pr50:docs/research/2026-11-06-top-time-replay-results.md:13-25,39-64",
                "origin/pr50:docs/research/2026-11-06-first-window-failure-attribution.md:1-16",
            ],
        },
        "period_2016_to_2025_material": {
            "classification": "NOT_ESTABLISHED_AS_A_DISTINCT_SAMPLE",
            "known_split_mapping": [
                {"range": ["2016-01-01", "2018-12-31"], "split": "dev", "classification": "consumed_for_tuning"},
                {"range": ["2019-01-01", "2021-12-31"], "split": "cal", "classification": "consumed_for_tuning"},
                {"range": ["2022-01-01", "2025-08-31"], "split": "test", "classification": "dev_diagnostic_only"},
            ],
            "outside_registered_test_end": {
                "range": ["2025-09-01", "2025-12-31"],
                "status": "NOT_ESTABLISHED",
                "reason": "no separately registered split or execution record found; do not relabel it as fresh confirmation",
            },
            "not_a_holdout": True,
            "evidence": ["research/labels/run_top.py:17-21", "docs/preregistration.md:§18-§19", "origin/pr50:docs/research/2026-11-06-top-time-replay-results.md:18-24"],
        },
        "still_closed_confirmation_candidates": frozen_confirmation,
        "local_only_legacy_scans": {
            "file_count": inventory["local_only_summary"]["file_count"],
            "bytes": inventory["local_only_summary"]["total_bytes"],
            "directories": local_scans,
            "all_hashes": "preserved_legacy_sha256.json",
            "not_copied_to_git": True,
        },
        "conclusion": {
            "unopened_confirmation_sample_exists": True,
            "candidates": [
                "a90s_v20261104 1990s A-share index samples (with Shenzhen backcast separately reported)",
                "ext_v20261029 HSI/N225/NDX/SPX; README prohibits model evaluation before Round 2",
            ],
            "condition": "T00 only read manifests/metadata and hashed files; it did not run scans, labels, model evaluation, or open these samples.",
            "no_fresh_holdout_claim_for": ["PR50's 91 stage tops", "2016-2025 historical material"],
        },
        "NOT_ESTABLISHED": [
            {
                "item": "cal_test_stock_execution_coverage",
                "reason": "registered snapshots are known, but the cited reports do not establish per-stock run coverage",
            },
            {
                "item": "2016_2025_as_one_sample",
                "reason": "the only directly verifiable registered partitions are dev/cal/test above; no distinct corpus identity is recorded",
            },
            {
                "item": "2025-09_to_2025-12_consumption",
                "reason": "outside SPLITS[test] end; no separate sample registration/execution evidence identified",
            },
        ],
    }


README = """# T00 冻结基线与旧结果保护

本目录是 `t00_20261116_a1` 的只读研究登记；仅做文档/清单，无模型改动、重拟合、workflow dispatch、生产版本变更或合并。

## 版本关系

- 当前执行时 `origin/main`：`4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5`；PR #100 文档 pinned main：`5d5fc7959e24b8eebaa34e3882c7b2ce069daeb0`。
- 两者全路径差异只有 8 个 frontend/worker 文件；`research/`、`scripts/`、`data/frozen/`、`docs/preregistration*.md` 差异为空。
- 只读研究 refs：PR #50 `7f7fe930ab4065295718dfcfe89b87cedcaaf1fb`；PR #99 `4986455cb9d8871bb7fda25a221db5a5a11ad009`；PR #100 任务文档源 `3f2de2e541c519e962d010055da8715733101e20`。

完整 bounds、精确窗口列表与 SHA-256、依赖、冻结数据清单及调用链见 `baseline_manifest.json`；旧资料逐文件哈希见 `preserved_legacy_sha256.json`；样本消费见 `sample_consumption_register.json`。

## 生产调用链摘要

`index_daily.yml` 和 `index_replay.yml` 实际都执行 `LPPLS_BOX=v2 python -m research.pipeline.daily`。daily 入口按 BOX 将 `_core.ALLOW_INSIDE` 设为 `True`，默认取 `full_windows(len(logp))`，经 `_derived` / `rules()` 并由 `build_record()` 加 `grid_rules()` 构建记录。workflow 不传 `--frozen`：行情从运行时 cache refresh，精确 vintage 随运行变化；T00 未 dispatch。扫描 CLI 的 `LPPLS_PROCS=8` 实为进程池，不是线程参数；daily 路径不使用该进程池。

## 三个不同基线

| 注册名 | 参数/时间域 | 评分 | 数据 |
|---|---|---|---|
| `legacy_main_v2` | m=[0.01,2]、ω=[1,50]、tc=t2±0.2dt；允许窗内 tc，设计用绝对 τ；10 个随机起点 | 历史 `original_standard` A1/A2，不等于 PR #50 重放分数 | 指数 v20261024 qfq；个股 stocks_v20261024 close_hfq |
| `legacy_pr50_replay` | 九组保存的区间 + `calendar_fixed_10`；不拟合 | hypothetical diagnostic；首条区间需覆盖阶段峰、行动提前≥5、含端点宽度≤10、整窗提前；91 个事件仅 0–3 TP | 六指数 v20261024 qfq，最后原拟合日 2018-12-26、映射预测/评价至 2018-12-28、账本截止 2018-12-31；价格读至 2019-12-31 仅成熟标签 |
| `candidate_future_fullcycles_1p5` | 规格：tc>t2、future-only、完整周期 ω/(2π)·ln((tc−t1)/(tc−t2))≥1.5；其他参数留给 T01 | 未运行；评分契约需先冻结 | 未选数据版本；不构成结果 |

**单位核对**：`Fit.n_osc=ω/(2π)·ln((tc−t0)/(tc−t_end))` 是完整周期；`TOP_RULE` 门槛为 1.5。`lppls_rules._derived` 的 `osc=(ω/2)·ln(|tc|/max(|tc−t2|,1e−3))` 且 `n_osc=osc/π`，含 `abs()` 内域语义。`lit1/lit2` 的 `osc≥2.5` 等价于代码口径 `n_osc≥2.5/π≈0.795775` 周期；`p_ds/p_strict` 是 `n_osc≥2.5`；`p_top` 是 `n_osc≥1.5`。PR #50 的单位文档同时指出公开 Zhang 表格的分母与仓库公式不同，故官方/商业实现等价性 **NOT_ESTABLISHED**。

## 旧结果、样本与保护

- `preserved_legacy_sha256.json` 流式 SHA-256 固定 main 上 prereg 文档、被引用报告、全部 `data/frozen/**`、可识别的 tracked research results、PR #50 相关 replay/unit evidence、PR #99 F1–F4 报告/日志/生成器，以及 `/home/ubuntu/repos/LPPL/data/features/lppls_*` 本机扫描。
- PR #99 中 F2/F3/F4 仍为 **FAILED**。三项均保留首轮 `run_r1.log` 与更正生成器后的 `run.log`；F4 两日志 hash 相同。合成生成器有 SHA-256，但无明确版本常量。
- 本机扫描实测 10 个目录、323 个文件、367,492,055 字节（350.47 MiB），低于先前约 1.4 GB 的预估；原因 **NOT_ESTABLISHED**。这些文件仅哈希，没有复制进仓库。
- PR #50 的 91 个阶段顶是已消费开发诊断，不是新 holdout。原拟合最后日是 2018-12-26，输入映射的预测/评价结束日是 2018-12-28，账本边界为 2018-12-31；2019 数据只用于标签成熟。没有找到独立的“2016–2025 新留出集”登记。
- 仍有符合既有登记、尚未用于模型评价的确认样本候选：`a90s_v20261104` 的 1990 年代两指数（深证回算段单列）及 `ext_v20261029` 的 HSI/N225/NDX/SPX。T00 只读其说明/manifest 并哈希，未扫描或评价；按 Round 2/预登记授权继续保持关闭。

## NOT_ESTABLISHED

1. `ext_v20261029` 的调整方式：README/MANIFEST 未声明 adjusted/unadjusted。
2. PR #50 原始拟合 parquet：原清单指向 Windows `D:\\CodexData`；本机仅有保存报告、清单和哈希。
3. PR #50 的历史真实发布时间、原始 scope 与可行动性：旧回放明确是假想诊断，不是原预测证明。
4. PR #99 合成生成器的显式版本标签：未发现版本常量，只能以源文件哈希固定内容。
5. 独立 2016–2025 样本身份；2025-09 至 2025-12 是否被单独注册/消费；校准/测试段个股具体扫描覆盖。
6. 当前 production daily 的未来运行 vintage：workflow 会刷新行情，T00 没有 dispatch。
7. stocks_v20261024 的 `data/cache/stocks/*.parquet` 在当前 worktree 中不存在；只保留 frozen manifest 中的逐股 hashes。
8. Zhang–Zhang–Sornette 公布公式的作者意图以及其与商业 FCO 服务器规则的等价性。
9. 当前 main 的 `research/` 下没有符合已记录结果文件后缀筛选的 tracked result 文件；因此该类别没有可哈希对象。

新 run 目录一旦存在，生成器拒绝覆盖；后续重算须使用新的 run_id。失败尝试亦应另建新目录，不复用本目录。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--local-scan-root", default=DEFAULT_LOCAL_ROOT, type=Path)
    args = parser.parse_args()
    out_dir = args.out_dir.expanduser().resolve()
    if out_dir.exists():
        print(f"refusing to overwrite existing run directory: {out_dir}", file=sys.stderr)
        return 2
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir()
    inventory = build_inventory(args.local_scan_root.expanduser().resolve())
    artifacts = {
        "baseline_manifest.json": build_baseline(inventory),
        "preserved_legacy_sha256.json": inventory,
        "sample_consumption_register.json": build_sample_register(inventory),
        "README.md": README,
    }
    for name, value in artifacts.items():
        output = out_dir / name
        if isinstance(value, dict):
            output.write_text(
                json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        else:
            output.write_text(value, encoding="utf-8")
    print(
        json.dumps(
            {
                "output_dir": str(out_dir),
                "files": sorted(artifacts),
                "tracked_files": sum(row["tracking"] == "tracked" for row in inventory["files"]),
                "local_only_files": inventory["local_only_summary"]["file_count"],
                "local_only_bytes": inventory["local_only_summary"]["total_bytes"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
