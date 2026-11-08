"""Read the deliberately limited P1 source catalog without making requests.

Code provenance is not a data license.  A parser being implemented does not
enable its source.  Existing fetchers do not consult this new catalog yet;
callers must explicitly check ``policy_problems`` before adding a new fetch or
publication path.  Parsing an already saved response needs no network policy
override and still does not grant permission to publish that response.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SCHEMA_VERSION = "p1-source-catalog.v1"
CATALOG_PATH = Path(__file__).with_name("p1_source_catalog.json")
_PURPOSES = frozenset({"fetch", "publish"})


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate P1 catalog key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"non-finite P1 catalog value: {value}")


def load_catalog() -> dict[str, Any]:
    """Return an independent catalog copy; reject malformed policy metadata.

    This small local JSON file is reread rather than cached, so an explicit
    reviewed policy change cannot leave a process using a stale permission.
    No URL in the catalog is fetched and no parser is dynamically imported.
    """

    catalog = json.loads(
        CATALOG_PATH.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_invalid_constant,
    )
    if not isinstance(catalog, dict) or catalog.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported P1 source catalog schema")
    sources = catalog.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("P1 source catalog requires a non-empty sources list")
    if type(catalog.get("source_count")) is not int or catalog["source_count"] != len(sources):
        raise ValueError("source_count must count only the selected catalog entries")
    upstreams = catalog.get("pinned_upstreams")
    if not isinstance(upstreams, dict) or not upstreams:
        raise ValueError("P1 source catalog requires pinned upstreams")
    for upstream in upstreams.values():
        if not isinstance(upstream, dict) or not re.fullmatch(r"[0-9a-f]{40}", str(upstream.get("commit", ""))):
            raise ValueError("upstream commit must be a full Git SHA")
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("source must be an object")
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id or source_id in seen:
            raise ValueError("source IDs must be non-empty and unique")
        seen.add(source_id)
        if type(source.get("implemented")) is not bool:
            raise ValueError(f"{source_id}: implemented must be a boolean")
        parser = source.get("parser")
        if source["implemented"] and (not isinstance(parser, str) or ":" not in parser):
            raise ValueError(f"{source_id}: implemented source requires a parser reference")
        hosts, urls = source.get("hosts"), source.get("source_urls")
        if not isinstance(hosts, list) or not hosts or not isinstance(urls, list) or not urls:
            raise ValueError(f"{source_id}: source URLs and hosts are required")
        if any(not isinstance(host, str) or not host or "/" in host for host in hosts):
            raise ValueError(f"{source_id}: invalid source host")
        for url in urls:
            if not isinstance(url, str):
                raise ValueError(f"{source_id}: invalid source URL")
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password:
                raise ValueError(f"{source_id}: source URL does not match declared hosts")
        if not isinstance(source.get("data_policy"), dict):
            raise ValueError(f"{source_id}: data policy is required")
        provenance = source.get("code_provenance")
        refs = provenance.get("upstream_refs") if isinstance(provenance, dict) else None
        if not isinstance(refs, list) or not refs or any(ref not in upstreams for ref in refs):
            raise ValueError(f"{source_id}: unknown code provenance")
    return deepcopy(catalog)


def get_source(source_id: str) -> dict[str, Any]:
    """Look up one explicit source; an unknown ID never selects a fallback."""

    if not isinstance(source_id, str) or not source_id:
        raise KeyError("unknown P1 source")
    for source in load_catalog()["sources"]:
        if source["source_id"] == source_id:
            return source
    raise KeyError(f"unknown P1 source: {source_id}")


def _verified(review: Any) -> bool:
    if not isinstance(review, dict) or review.get("status") != "verified":
        return False
    refs = review.get("evidence_refs")
    return isinstance(refs, list) and bool(refs) and all(isinstance(ref, str) and bool(ref.strip()) for ref in refs)


def policy_problems(source_id: str, purpose: str = "fetch") -> list[str]:
    """Return stable blocking codes; only an empty list passes this policy gate.

    A review needs both ``status=verified`` and non-empty evidence references.
    These references document a human review; this accessor cannot establish
    license validity or fetch freshness.  Publication additionally needs the
    separate evidence/asof/append-only checks at the calling boundary.
    Unknown IDs fail closed.  Invalid purposes and malformed catalogs raise.
    """

    if not isinstance(purpose, str) or purpose not in _PURPOSES:
        raise ValueError("purpose must be 'fetch' or 'publish'")
    try:
        source = get_source(source_id)
    except KeyError:
        return ["unknown_source"]
    problems: list[str] = []
    if source.get("implemented") is not True:
        problems.append("parser_not_implemented")
    policy = source.get("data_policy")
    policy = policy if isinstance(policy, dict) else {}
    if policy.get(f"{purpose}_enabled") is not True:
        problems.append(f"{purpose}_disabled")
    for field, code in (
        ("access", "data_access_not_verified"),
        ("frequency_review", "source_frequency_not_verified"),
        ("mainland_network", "mainland_network_not_verified"),
    ):
        if not _verified(policy.get(field)):
            problems.append(code)
    if purpose == "publish" and not _verified(policy.get("redistribution")):
        problems.append("redistribution_not_verified")
    return problems
