"""Controlled EOD capture/import; archived information never enters LPPL."""

from __future__ import annotations

import json
import time
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests

from .market_base import LIMIT_POOLS, EMClient, limit_pools
from .market_calendar import load_calendar, resolve_sessions
from .market_context import build_snapshot
from .market_context_persistence import load_calendar_metadata
from .market_eod_archive import EODArchive, canonical, day, digest, safe_source_url, stamp
from .market_eod_quality import POOLS, YESTERDAY_POOL, YESTERDAY_SOURCE, assess_eod_payload
from .market_p1 import attach_source_adapters, fetch_ths_reasons_topics, fetch_yesterday_pool
from .market_source_validation import SOURCE_ENDPOINTS, SourceValidationError, require_fetch_policy

CN = timezone(timedelta(hours=8))
REQUIRED_FETCH_SOURCES = set(SOURCE_ENDPOINTS)


def load_fetch_policy(path: str | Path | None, *, now: str | None = None) -> dict[str, Any]:
    return require_fetch_policy(path, now=now)


class RecordingSession(requests.Session):
    """Archive actual response.content before JSON parsing, including errors.

    No auth headers, cookies or secret URL parameters are journalled. Redirects
    are disabled; only the reviewed HTTPS hosts are allowed. Research permission
    is a prerequisite, not inferred from HTTP 200 or open-source licensing.
    """

    def __init__(self, archive: EODArchive, run_id: str, policy: dict[str, Any]):
        super().__init__()
        self.archive, self.run_id, self.policy = archive, run_id, policy
        self.records: list[dict[str, Any]] = []
        self.last_call: dict[str, float] = {}
        self.calls = 0

    def get(self, url, **kwargs):
        parsed = urlsplit(url)
        safe_source_url(url)
        if parsed.hostname == "push2ex.eastmoney.com":
            source_id = "eastmoney_yesterday_zt_pool" if parsed.path.endswith("getYesterdayZTPool") else "eastmoney_limit_pools"
            allowed = {"/getYesterdayZTPool", *("/" + p[1] for p in LIMIT_POOLS)}
            if parsed.path not in allowed:
                raise ValueError("UNREVIEWED_SOURCE_PATH")
        elif parsed.hostname == "data.10jqka.com.cn" and parsed.path == "/dataapi/limit_up/limit_up_pool":
            source_id = "ths_limit_up_pool"
        else:
            raise ValueError("UNREVIEWED_SOURCE_HOST")
        if self.calls >= 10:
            raise ValueError("CAPTURE_REQUEST_BUDGET_EXCEEDED")
        interval = self.policy["sources"][source_id]["min_interval_seconds"]
        previous = self.last_call.get(parsed.hostname)
        if previous is not None:
            time.sleep(max(0, interval - (time.monotonic() - previous)))
        self.calls += 1
        kwargs.update({"allow_redirects": False, "timeout": 15})
        try:
            response = super().get(url, **kwargs)
            fetched = stamp()
            sha = self.archive.response(self.run_id, source_id=source_id, url=response.url, raw=response.content,
                                        http_status=response.status_code, fetched_at=fetched)
            self.records.append({"source_id": source_id, "url": safe_source_url(response.url), "fetched_at": fetched,
                                 "raw_sha256": sha, "http_status": response.status_code, "raw": response.content})
            return response
        finally:
            self.last_call[parsed.hostname] = time.monotonic()


def pool_source_proof(records: list[dict[str, Any]], asof: str) -> dict[str, Any]:
    """A request's date is not proof of the response's date or full coverage."""
    proof = {}
    endpoints = [(kind, endpoint, "eastmoney_limit_pools") for kind, endpoint, _ in LIMIT_POOLS]
    endpoints.append((YESTERDAY_POOL, "getYesterdayZTPool", YESTERDAY_SOURCE))
    for kind, endpoint, source_id in endpoints:
        selected = [r for r in records if urlsplit(r["url"]).path == "/" + endpoint and r["http_status"] == 200
                    and (kind != YESTERDAY_POOL or r.get("source_id") == source_id)]
        if not selected:
            continue
        r = selected[-1]
        try:
            response = json.loads(r["raw"])
            data = response.get("data", {})
            returned_date = str(data.get("date", ""))
            if len(returned_date) == 8 and returned_date.isdigit():
                returned_date = f"{returned_date[:4]}-{returned_date[4:6]}-{returned_date[6:]}"
            rows = data.get("pool")
            total = data.get("total")
            complete = type(total) is int and isinstance(rows, list) and total == len(rows) and total < 10000
            proof[kind] = {"source_id": source_id, "source_url": r["url"], "fetched_at": r["fetched_at"],
                           "raw_sha256": r["raw_sha256"], "status": "fresh", "asof": returned_date or None,
                           "asof_status": "source_verified" if returned_date == asof else "NOT_ESTABLISHED",
                           "coverage": {"status": "complete" if complete else "NOT_ESTABLISHED", "declared_total": total,
                                        "pages_expected": 1 if complete else None, "pages_received": 1},
                           "evidence_note": "Only data.date/data.total verified; absent/other fields require a separately reviewed parser."}
            if kind == YESTERDAY_POOL:
                success = type(response.get("rc")) is int and response["rc"] == 0
                proof[kind].update({"status": "fresh" if success else "error", "provider_success": success,
                                    "provider_return_code": response.get("rc")})
        except (ValueError, TypeError, AttributeError):
            continue
    return proof


def capture_core(asof: str, archive: EODArchive, run_id: str, policy: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"asof": asof, "generated_at": stamp(), "sources": {}, "limit_pools": {}, "board_flow": {}}
    with RecordingSession(archive, run_id, policy) as session:
        try:
            payload["limit_pools"] = limit_pools(asof, EMClient(session=session))
        except Exception as exc:  # noqa: BLE001
            payload["sources"]["limit_pools"] = {"status": "error", "ok": False, "error": type(exc).__name__}
        try:
            reasons, topics, source = fetch_ths_reasons_topics(asof, session=session)
            topics_by_code = {r["code"]: r["topic_label"] for r in topics["rows"]}
            ths = {"asof": asof, "status": reasons["status"], "source": source,
                   "rows": [{**r, "topic_label": topics_by_code.get(r["code"])} for r in reasons["rows"]]}
        except Exception as exc:  # noqa: BLE001
            ths = {"asof": asof, "status": "error", "rows": [], "stale_reason": type(exc).__name__,
                   "source": {"source_id": "ths_limit_up_pool", "status": "error", "ok": False}}
        try:
            yesterday = fetch_yesterday_pool(asof, session=session)
        except Exception as exc:  # noqa: BLE001
            yesterday = {"asof": asof, "status": "error", "rows": [], "stale_reason": type(exc).__name__,
                         "source": {"source_id": "eastmoney_yesterday_zt_pool", "status": "error", "ok": False}}
        payload = attach_source_adapters(payload, ths_pool=ths, yesterday_pool=yesterday)
        # Stable separate field: provider's T-day view of yesterday's winners.
        payload["limit_pools"]["yesterday_performance"] = yesterday
        payload["limit_pools"].pop("prior_day", None)
        proof = pool_source_proof(session.records, asof)
        payload["limit_pools"]["pool_sources"] = proof
        for kind, meta in proof.items():
            payload["sources"]["limit_pool_" + kind] = meta
        # The legacy yesterday parser stamps the request date. Only the
        # independently archived fourth response may establish date/coverage.
        yesterday_proof = proof.get(YESTERDAY_POOL, {"source_id": YESTERDAY_SOURCE, "status": "error",
                                  "asof": None, "asof_status": "NOT_ESTABLISHED",
                                  "stale_reason": "yesterday_raw_response_proof_missing"})
        yesterday["source"] = deepcopy(yesterday_proof)
        yesterday["declared_count"] = yesterday_proof.get("coverage", {}).get("declared_total")
        payload["sources"][YESTERDAY_SOURCE] = deepcopy(yesterday_proof)
        if yesterday.get("status") == "fresh" and yesterday_proof.get("status") != "fresh":
            yesterday.update({"status": "error", "stale_reason": "provider_response_success_not_verified"})
        elif yesterday.get("status") == "fresh" and (yesterday_proof.get("asof_status") != "source_verified"
                or yesterday_proof.get("coverage", {}).get("status") != "complete"):
            yesterday.update({"status": "partial", "stale_reason": "source_date_or_pagination_not_verified"})
        # A query parameter is not provider-date proof. The existing THS parser
        # labels the requested date; retain its rows but downgrade unproven dates.
        ths_records = [r for r in session.records if r["source_id"] == "ths_limit_up_pool" and r["http_status"] == 200]
        source_date, source_count, covered = "", None, False
        try:
            ths_data = json.loads(ths_records[-1]["raw"])["data"] if ths_records else {}
            source_date = str(ths_data.get("date", ""))
            if len(source_date) == 8 and source_date.isdigit():
                source_date = f"{source_date[:4]}-{source_date[4:6]}-{source_date[6:]}"
            source_count = ths_data.get("total")
            info = ths_data.get("info")
            covered = type(source_count) is int and isinstance(info, list) and source_count == len(info) and source_count < 200
        except (ValueError, KeyError, TypeError, AttributeError):
            source_date, source_count, covered = "", None, False
        # Attach only proof read from the archived response, not the requested
        # date previously inserted by the legacy parser. Both label envelopes
        # and the source registry must carry the same dated raw-response proof.
        ths_proof = dict(payload["sources"].get("ths_limit_up_pool", {}))
        if ths_records:
            record = ths_records[-1]
            ths_proof.update({"source_id": "ths_limit_up_pool", "source_url": record["url"],
                              "fetched_at": record["fetched_at"], "raw_sha256": record["raw_sha256"]})
        ths_proof.update({"asof": source_date or None,
                          "asof_status": "source_verified" if source_date == asof else "NOT_ESTABLISHED",
                          "coverage": {"status": "complete" if covered else "NOT_ESTABLISHED",
                                       "declared_total": source_count, "pages_expected": 1 if covered else None,
                                       "pages_received": 1 if ths_records else 0}})
        payload["sources"]["ths_limit_up_pool"] = ths_proof
        for key in ("reasons", "topics"):
            section = payload["limit_pools"].get(key, {})
            section["source"] = deepcopy(ths_proof)
            if section.get("status") == "fresh" and (source_date != asof or not covered):
                section.update({"status": "partial", "stale_reason": "source_date_or_pagination_not_verified", "source_asof": source_date or None})
    return payload


def _yesterday_normalized_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Mirror the existing market_p1 parser's complete displayed row contract."""
    def text(value):
        return (str(value).strip() or None) if value is not None else None
    stat = raw.get("zttj") if isinstance(raw.get("zttj"), dict) else {}
    return {"code": text(raw.get("c")), "name": text(raw.get("n")), "pct": raw.get("zdp"),
            "turnover": raw.get("hs"), "amplitude": raw.get("zf"), "speed": raw.get("zs"),
            "y_first_seal": raw.get("yfbt"), "y_limit_days": raw.get("ylbc"), "industry": text(raw.get("hybk")),
            "zt_stat": {"days": stat.get("days"), "count": stat.get("ct")}}


def verify_yesterday_raw(archive: EODArchive, run_id: str, payload: dict[str, Any], asof: str,
                         *, checked_at: str | None = None) -> dict[str, Any]:
    """Bind fourth-pool metadata and members to this run's actual source bytes.

    A hash of an unrelated pool or self-reported date cannot pass. This does not
    establish provider licensing, exchange coverage or first-publication time.
    """
    section = payload.get("limit_pools", {}).get(YESTERDAY_POOL)
    section = section if isinstance(section, dict) else {}
    meta = section.get("source")
    meta = meta if isinstance(meta, dict) else {}
    result: dict[str, Any] = {"verified": False, "raw_bytes_verified": False, "reasons": []}
    if meta.get("source_id") != YESTERDAY_SOURCE:
        result["reasons"].append("yesterday_raw_source_id_missing_or_wrong")
    sha = meta.get("raw_sha256")
    if not isinstance(sha, str) or not archive.raw_verified(run_id, YESTERDAY_SOURCE, sha):
        result["reasons"].append("yesterday_raw_response_missing_or_hash_mismatch")
        return result
    with archive.connect() as db:
        rows = db.execute("SELECT body,url,fetched_at FROM responses WHERE run_id=? AND source_id=? AND raw_sha256=? AND http_status=200",
                          (run_id, YESTERDAY_SOURCE, sha)).fetchall()
    record = next((row for row in rows if digest(bytes(row["body"])) == sha
                   and urlsplit(row["url"]).scheme == "https"
                   and urlsplit(row["url"]).hostname == "push2ex.eastmoney.com"
                   and urlsplit(row["url"]).path == "/getYesterdayZTPool"), None)
    if record is None:
        result["reasons"].append("yesterday_raw_endpoint_mismatch")
        return result
    result["raw_bytes_verified"] = True
    if meta.get("source_url") != record["url"]:
        result["reasons"].append("yesterday_source_url_differs_from_raw_response")
    query = parse_qs(urlsplit(record["url"]).query, keep_blank_values=True)
    if any(query.get(key) != [value] for key, value in
           {"date": asof.replace("-", ""), "Pageindex": "0", "pagesize": "10000"}.items()):
        result["reasons"].append("yesterday_raw_request_date_or_pagination_mismatch")
    try:
        if not isinstance(meta.get("fetched_at"), str) or stamp(meta["fetched_at"]) != record["fetched_at"]:
            result["reasons"].append("yesterday_fetched_at_differs_from_raw_response")
        fetched = datetime.fromisoformat(record["fetched_at"])
        checked = datetime.fromisoformat(stamp(checked_at))
        local = fetched.astimezone(CN)
        if fetched > checked:
            result["reasons"].append("yesterday_raw_fetched_at_is_future")
        if local.date().isoformat() < asof or (local.date().isoformat() == asof and local.hour * 60 + local.minute < 930):
            result["reasons"].append("yesterday_raw_response_precedes_asof_close")
    except (ValueError, TypeError, OverflowError):
        result["reasons"].append("yesterday_raw_fetched_at_invalid")
    proof = pool_source_proof([{"source_id": YESTERDAY_SOURCE, "url": record["url"], "raw": bytes(record["body"]),
                                "raw_sha256": sha, "http_status": 200, "fetched_at": record["fetched_at"]}], asof)
    actual = proof.get(YESTERDAY_POOL, {})
    if actual.get("provider_success") is not True:
        result["reasons"].append("yesterday_raw_provider_return_code_not_success")
    if actual.get("asof_status") != "source_verified":
        result["reasons"].append("yesterday_raw_response_date_not_verified")
    if actual.get("coverage", {}).get("status") != "complete":
        result["reasons"].append("yesterday_raw_response_coverage_not_verified")
    if any(meta.get(key) != actual.get(key) for key in ("asof", "asof_status", "coverage", "provider_success", "provider_return_code")):
        result["reasons"].append("yesterday_source_receipt_differs_from_raw_response")
    try:
        raw_rows = json.loads(bytes(record["body"]))["data"]["pool"]
        raw_codes = [row["c"] for row in raw_rows]
        normalized_codes = [row["code"] for row in section["rows"]]
        if (not isinstance(raw_rows, list) or not isinstance(section["rows"], list)
                or any(not isinstance(code, str) for code in raw_codes + normalized_codes)
                or len(set(raw_codes)) != len(raw_codes) or sorted(raw_codes) != sorted(normalized_codes)):
            result["reasons"].append("yesterday_raw_members_missing_duplicate_or_different")
        else:
            expected = [_yesterday_normalized_row(row) for row in raw_rows]
            if canonical(sorted(expected, key=lambda row: row["code"])) != canonical(sorted(section["rows"], key=lambda row: row["code"])):
                result["reasons"].append("yesterday_normalized_fields_differ_from_raw_response")
    except (ValueError, KeyError, TypeError):
        result["reasons"].append("yesterday_raw_members_unreadable")
    result["verified"] = not result["reasons"]
    return result


def verify_prior_zt_raw(archive: EODArchive, prior: dict[str, Any] | None, *, asof: str | None,
                        checked_at: str | None = None, known_by: str | None = None) -> dict[str, Any]:
    """Verify the archived denominator specifically for the new four-pool gate."""
    result: dict[str, Any] = {"verified": False, "raw_bytes_verified": False, "reasons": []}
    if not prior or not asof:
        result["reasons"].append("prior_zt_archive_missing")
        return result
    earlier = prior["snapshot"]
    capture = earlier.get("daily_capture", {})
    limit = earlier.get("limit_pools", {})
    meta = limit.get("pool_sources", {}).get("zt", {})
    if (capture.get("quality", {}).get("core_complete") is not True
            or capture.get("raw_verification", {}).get("zt") is not True):
        result["reasons"].append("prior_zt_archive_verification_flags_missing")
    sha = meta.get("raw_sha256")
    if (meta.get("source_id") != "eastmoney_limit_pools" or not isinstance(sha, str)
            or not archive.raw_verified(capture.get("run_id"), "eastmoney_limit_pools", sha)):
        result["reasons"].append("prior_zt_archive_raw_missing_or_wrong_source")
        return result
    with archive.connect() as db:
        records = db.execute("SELECT body,url,fetched_at FROM responses WHERE run_id=? AND source_id=? AND raw_sha256=? AND http_status=200",
                             (capture.get("run_id"), "eastmoney_limit_pools", sha)).fetchall()
    record = next((row for row in records if digest(bytes(row["body"])) == sha
                   and urlsplit(row["url"]).scheme == "https" and urlsplit(row["url"]).hostname == "push2ex.eastmoney.com"
                   and urlsplit(row["url"]).path == "/getTopicZTPool"), None)
    if record is None:
        result["reasons"].append("prior_zt_raw_endpoint_mismatch")
        return result
    result["raw_bytes_verified"] = True
    query = parse_qs(urlsplit(record["url"]).query, keep_blank_values=True)
    if any(query.get(key) != [value] for key, value in
           {"date": asof.replace("-", ""), "Pageindex": "0", "pagesize": "10000"}.items()):
        result["reasons"].append("prior_zt_raw_request_date_or_pagination_mismatch")
    try:
        if (meta.get("source_url") != record["url"] or not isinstance(meta.get("fetched_at"), str)
                or stamp(meta["fetched_at"]) != record["fetched_at"]):
            result["reasons"].append("prior_zt_source_metadata_differs_from_raw_response")
        fetched = datetime.fromisoformat(record["fetched_at"])
        local = fetched.astimezone(CN)
        if not isinstance(prior.get("recorded_at"), str) or not isinstance(known_by, str):
            result["reasons"].append("prior_zt_archive_timeline_not_established")
        elif not fetched <= datetime.fromisoformat(stamp(prior["recorded_at"])) <= datetime.fromisoformat(stamp(known_by)):
            result["reasons"].append("prior_zt_fetched_after_archive_or_run_start")
        if (fetched > datetime.fromisoformat(stamp(checked_at)) or local.date().isoformat() < asof
                or (local.date().isoformat() == asof and local.hour * 60 + local.minute < 930)):
            result["reasons"].append("prior_zt_raw_fetched_at_future_or_before_asof_close")
        response = json.loads(bytes(record["body"]))
        if type(response.get("rc")) is not int or response["rc"] != 0:
            result["reasons"].append("prior_zt_raw_provider_return_code_not_success")
        actual = pool_source_proof([{"url": record["url"], "raw": bytes(record["body"]), "raw_sha256": sha,
                                     "fetched_at": record["fetched_at"], "http_status": 200}], asof).get("zt", {})
        if (actual.get("asof_status") != "source_verified" or actual.get("coverage", {}).get("status") != "complete"
                or any(meta.get(key) != actual.get(key) for key in ("asof", "asof_status", "coverage"))):
            result["reasons"].append("prior_zt_raw_date_count_or_receipt_mismatch")
        raw_rows, normalized = response["data"]["pool"], limit["pool_rows"]["zt"]
        if not isinstance(raw_rows, list) or not isinstance(normalized, list):
            raise ValueError("pool rows must be lists")
        expected = []
        for row in raw_rows:
            code, streak = row["c"], row["lbc"]
            if not isinstance(code, str) or isinstance(streak, bool) or not isinstance(streak, (int, str)):
                raise ValueError("invalid source code or streak")
            expected.append({"code": code.strip(), "streak": int(streak)})
        observed = [{"code": row["code"], "streak": row["streak"]} for row in normalized]
        if (len({row["code"] for row in expected}) != len(expected) or len(expected) != limit.get("zt")
                or canonical(sorted(expected, key=lambda row: row["code"])) != canonical(sorted(observed, key=lambda row: row["code"]))):
            result["reasons"].append("prior_zt_normalized_codes_or_streaks_differ_from_raw_response")
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        result["reasons"].append("prior_zt_raw_response_or_metadata_unreadable")
    result["verified"] = not result["reasons"]
    return result


def run_eod(*, archive: EODArchive, calendar_path: str | Path, asof: str | None = None,
            input_path: str | Path | None = None, policy_path: str | Path | None = None,
            now: str | None = None, run_id: str | None = None, collector=capture_core) -> dict[str, Any]:
    started_at = stamp(now)
    china = datetime.fromisoformat(started_at).astimezone(CN)
    requested = day(asof) if asof else china.date().isoformat()
    mode = "historical_import" if input_path else "capture"
    run_id = run_id or str(uuid.uuid4())
    archive.start(run_id, asof=requested, mode=mode, now=started_at)
    try:
        verified = load_calendar_metadata(calendar_path)
        raw_calendar = json.loads(Path(calendar_path).read_text(encoding="utf-8"))
        start = raw_calendar.get("coverage_start", verified["dates"][0])
        end = raw_calendar.get("coverage_end", verified["dates"][-1])
        if not start <= requested <= end:
            raise ValueError("CALENDAR_COVERAGE_EXPIRED_OR_MISSING")
        if requested not in verified["dates"]:
            return archive.finish(run_id, status="skipped", detail={"reason": "NOT_A_VERIFIED_TRADING_DAY"}, now=started_at)
        if requested > china.date().isoformat() or (requested == china.date().isoformat() and china.hour * 60 + china.minute < 15 * 60 + 30):
            return archive.finish(run_id, status="skipped", detail={"reason": "EOD_NOT_CLOSED"}, now=started_at)
        sessions = resolve_sessions(asof=requested, prior_asof=None, calendar=load_calendar(calendar_path), today=china.date().isoformat())
        if input_path:
            raw = Path(input_path).read_bytes()
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("INPUT_CONTEXT_NOT_OBJECT")
            declared = payload.get("snapshot_sha256")
            if declared and digest(canonical({k: v for k, v in payload.items() if k != "snapshot_sha256"}).encode()) != declared:
                raise ValueError("INPUT_SNAPSHOT_HASH_MISMATCH")
            import_ref = {"input_file_sha256": digest(raw), "input_snapshot_sha256": payload.get("snapshot_sha256"),
                          "original_run_mode": payload.get("run_mode"), "raw_responses_available": False}
        else:
            policy = load_fetch_policy(policy_path, now=started_at)
            payload = collector(requested, archive, run_id, policy)
            import_ref = None
        if not isinstance(payload, dict) or payload.get("asof") != requested:
            raise ValueError("SOURCE_ASOF_MISMATCH")
        payload = deepcopy(payload)
        payload["calendar"] = sessions
        prior = archive.best(sessions["prior_asof"], known_by=started_at) if sessions["prior_asof"] else None
        quality = assess_eod_payload(payload, asof=requested, prior_payload=prior["snapshot"] if prior else None, prior_asof=sessions["prior_asof"])
        prior_raw = verify_prior_zt_raw(archive, prior, asof=sessions["prior_asof"], checked_at=stamp(now), known_by=started_at)
        membership = quality["pools"][YESTERDAY_POOL]["prior_membership"]
        membership["raw_response_check"] = prior_raw
        membership["raw_bytes_verified"] = prior_raw["raw_bytes_verified"]
        if not prior_raw["verified"]:
            membership["status"] = "not_available"
            membership["reasons"].append("prior_zt_archive_raw_not_verified")
            quality["four_pool_complete"] = False
            quality["status"] = "partial"
            quality["reasons"].append("prior_zt_archive_raw_not_verified")
        raw_checks = {}
        for kind in POOLS:
            meta = payload.get("limit_pools", {}).get("pool_sources", {}).get(kind, {})
            raw_checks[kind] = archive.raw_verified(run_id, meta.get("source_id", "eastmoney_limit_pools"), meta.get("raw_sha256"))
        yesterday_raw = verify_yesterday_raw(archive, run_id, payload, requested, checked_at=stamp(now))
        raw_checks[YESTERDAY_POOL] = yesterday_raw["verified"]
        quality["pools"][YESTERDAY_POOL]["raw_response_check"] = yesterday_raw
        quality["pools"][YESTERDAY_POOL]["raw_bytes_verified"] = yesterday_raw["raw_bytes_verified"]
        if not yesterday_raw["verified"]:
            quality["pools"][YESTERDAY_POOL]["verified_complete"] = False
            quality["pools"][YESTERDAY_POOL]["status"] = "partial"
            quality["pools"][YESTERDAY_POOL]["reasons"].extend(yesterday_raw["reasons"])
        ths = payload.get("sources", {}).get("ths_limit_up_pool", {})
        raw_checks["reasons_topics"] = archive.raw_verified(run_id, "ths_limit_up_pool", ths.get("raw_sha256"))
        if not all(raw_checks[k] for k in POOLS) or input_path:
            quality["core_complete"] = False
            quality["three_pool_complete"] = False
            quality["status"] = "partial"
            quality["reasons"].append("raw_response_verification_missing_or_historical_import")
            quality["progression"] = {"status": "not_available", "asof": requested, "prior_asof": sessions["prior_asof"], "rows": [],
                                      "stale_reason": "raw_response_verification_missing_or_historical_import", "evidence": "descriptive"}
        if not all(raw_checks[k] for k in (*POOLS, YESTERDAY_POOL)) or input_path:
            quality["four_pool_complete"] = False
            quality["status"] = "partial"
            quality["reasons"].append("four_pool_raw_verification_missing_or_historical_import")
        # Raw bytes of both adjacent days are required, not only today's metadata.
        if prior and prior["snapshot"].get("daily_capture", {}).get("quality", {}).get("core_complete") is not True:
            quality["progression"] = {"status": "not_available", "asof": requested, "prior_asof": sessions["prior_asof"], "rows": [],
                                      "stale_reason": "prior_archive_core_not_verified", "evidence": "descriptive"}
        old_progression = deepcopy(payload.get("history", {}).get("progression"))
        context = build_snapshot(payload, requested_at=started_at, fetched_at=payload.get("generated_at"))
        # Preserve detailed proof omitted by the legacy wrapper's source whitelist.
        context["sources"] = payload.get("sources", {})
        context["calendar"] = sessions
        context["history"]["progression"] = quality["progression"]
        context["daily_capture"] = {"schema_version": "market-eod-capture.v1", "run_id": run_id, "mode": mode,
                                    "quality": quality, "raw_verification": raw_checks, "import_provenance": import_ref,
                                    "legacy_progression": old_progression, "prior_revision": prior["revision"] if prior else None,
                                    "first_local_archived_at": stamp(now), "first_public_visible_at": None,
                                    "vintage_status": "retrieved_after_asof" if input_path or requested < china.date().isoformat() else "captured_on_asof"}
        state = "sealed" if quality.get("status") == "ready" and quality.get("four_pool_complete") and raw_checks["reasons_topics"] else "partial"
        context.update({"run_mode": "research_import" if input_path else "research_capture", "publication_eligible": False, "model_input_eligible": False,
                        "status": "fresh" if state == "sealed" else "partial", "last_good_asof": requested if state == "sealed" else None})
        context.pop("snapshot_sha256", None)
        context["snapshot_sha256"] = digest(canonical(context).encode())
        return archive.finish(run_id, status=state, detail={"quality_status": quality["status"], "raw_verification": raw_checks,
                              "progression_status": quality["progression"]["status"], "prior_asof": sessions["prior_asof"]}, snapshot=context, now=now)
    except Exception as exc:  # noqa: BLE001 — failures are durable outcomes, never silent empty success
        detail = {"error_type": type(exc).__name__, "reason": str(exc)[:300]}
        if isinstance(exc, SourceValidationError):
            detail["source_validation"] = exc.report
        return archive.finish(run_id, status="failed", detail=detail, now=now)
