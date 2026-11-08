#!/usr/bin/env python3
"""Inspect the P1 catalog or import saved provider JSON without network access.

Run from the project root: python -m scripts.import_p1_evidence --help
Output is research-only and is not accepted by the Worker seed gates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.data.p1_evidence import (
    SUPPORTED,
    archive_response,
    build_research_context,
    load_payload,
    read_response,
    write_research_context,
)
from research.data.p1_source_catalog import get_source, policy_problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser("catalog", help="Print parser and access policy, no requests")
    catalog.add_argument("--source", choices=sorted(SUPPORTED))
    imported = commands.add_parser("import-response", help="Seal an existing raw JSON response")
    imported.add_argument("--source", required=True, choices=sorted(SUPPORTED))
    imported.add_argument("--raw", required=True, type=Path)
    imported.add_argument("--archive", required=True, type=Path)
    imported.add_argument("--asof", required=True)
    imported.add_argument("--fetched-at", required=True, help="Caller-declared retrieval timestamp with timezone")
    imported.add_argument("--source-url", required=True)
    imported.add_argument("--subject", help="Canonical sh/sz/bj + six digits; required for stock fund flow")
    imported.add_argument("--origin", choices=("captured_response", "fixture"), default="captured_response")
    build = commands.add_parser("build-context", help="Build a new unpublished research context")
    build.add_argument("--base-payload", required=True, type=Path)
    build.add_argument("--record", required=True, action="append", type=Path)
    build.add_argument("--out", required=True, type=Path)
    build.add_argument("--available-at-cutoff", help="Knowledge cutoff; never claims historical publication")
    args = parser.parse_args(argv)
    try:
        if args.command == "catalog":
            sources = [args.source] if args.source else sorted(SUPPORTED)
            result = [{"source": get_source(source), "fetch_blockers": policy_problems(source, purpose="fetch"), "publish_blockers": policy_problems(source, purpose="publish")} for source in sources]
        elif args.command == "import-response":
            path = archive_response(args.archive, read_response(args.raw), source_id=args.source, asof=args.asof, fetched_at=args.fetched_at, source_url=args.source_url, subject=args.subject, origin=args.origin)
            result = {"record": str(path), "publication_eligible": False, "network_requests": 0}
        else:
            payload = load_payload(args.base_payload)
            context = build_research_context(payload, args.record, available_at_cutoff=args.available_at_cutoff)
            write_research_context(args.out, context)
            result = {"output": str(args.out), "snapshot_sha256": context["snapshot_sha256"], "run_mode": context["run_mode"], "publication_eligible": False, "network_requests": 0}
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
