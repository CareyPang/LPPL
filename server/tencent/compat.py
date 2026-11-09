"""Local contract adapter for a future Tencent Cloud backend.

The adapter intentionally has no Tencent SDK, HTTP server, database driver, or
network client.  It gives a CloudBase function/Run implementation the same
route and persistence semantics as the existing Workers:

* `/market`, `/query`, `/status`, `/result`
* `/context`, `/context/status`, `/context/seed`, `/context/refresh`

The in-memory store is only a deterministic contract test double.  A production
adapter must replace its methods with conditional database/COS operations while
retaining the same no-fallback and append-only rules.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from research.data.investor_context import (
    build_investor_context,
    valid_symbol,
    validate_public_context,
)

API_SCHEMA = "tencent-api.v1"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CODE_RE = re.compile(r"^(?:60|68|00|30|43|83|87|92)\d{4}$")
JOB_RE = re.compile(r"^[a-f0-9-]{36}$")
HASH_RE = re.compile(r"^[a-f0-9]{64}$", re.IGNORECASE)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json_hash(value: Mapping[str, Any]) -> str:
    payload = {key: value[key] for key in sorted(value) if key != "snapshot_sha256"}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


def _valid_code(value: Any) -> bool:
    return isinstance(value, str) and bool(CODE_RE.fullmatch(value))


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return False
    return parsed.weekday() < 5


@dataclass(frozen=True)
class TencentResponse:
    """Small response object used by local tests and an HTTP wrapper."""

    status: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=lambda: {"content-type": "application/json"})


class InMemoryTencentStore:
    """Contract-test store; production code must provide atomic equivalents."""

    def __init__(self) -> None:
        self.markets: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.active: dict[tuple[str, str], str] = {}
        self.results: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.public_results: dict[tuple[str, str], dict[str, Any]] = {}
        self.snapshots: dict[str, dict[str, Any]] = {}
        self.latest: dict[str, Any] | None = None
        self.refresh_jobs: dict[str, dict[str, Any]] = {}
        # Populated only by an explicit trusted backend workflow/test fixture.
        # No public seed endpoint or implicit fetch writes this information.
        self.investor_snapshots: dict[tuple[str, str | None], dict[str, Any]] = {}

    def put_result(self, *, code: str, job_id: str, kind: str, value: Mapping[str, Any]) -> None:
        item = copy.deepcopy(dict(value))
        self.results[(job_id, code, kind)] = item
        self.public_results[(code, kind)] = item
        job = self.jobs.get(job_id)
        if job:
            ready_key = {"latest": "current_ready", "history": "history_ready", "error": "error_ready"}[kind]
            job[ready_key] = True
            job["status"] = "completed"
            job["conclusion"] = "success"
            job["phase"] = {"latest": "current_ready", "history": "history_ready", "error": "error_ready"}[kind]


class TencentCompat:
    """Route-compatible backend facade for CloudBase/Run implementations."""

    def __init__(
        self,
        *,
        store: InMemoryTencentStore | None = None,
        seed_token: str | None = None,
        refresh_token: str | None = None,
        source_url: str | None = None,
        queue_dispatcher: Callable[[dict[str, Any]], None] | None = None,
        refresh_dispatcher: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.store = store or InMemoryTencentStore()
        self.seed_token = seed_token
        self.refresh_token = refresh_token
        self.source_url = source_url
        self.queue_dispatcher = queue_dispatcher
        self.refresh_dispatcher = refresh_dispatcher

    def dispatch(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> TencentResponse:
        """Dispatch one route without binding to a web framework."""

        query = query or {}
        body = body or {}
        headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        method = method.upper()
        if path == "/market" and method == "GET":
            return self._market(query)
        if path == "/query" and method == "POST":
            return self._query(body)
        if path == "/status" and method == "GET":
            return self._status(query)
        if path == "/result" and method == "GET":
            return self._result(query)
        if path == "/investor-context" and method == "GET":
            return self._investor_context(query)
        if path in {"/context", "/context/snapshot"} and method == "GET":
            return self._context(query)
        if path == "/context/seed" and method == "POST":
            return self._seed(body, headers)
        if path == "/context/refresh" and method == "POST":
            return self._refresh(body, headers)
        if path == "/context/status" and method == "GET":
            return self._context_status(query)
        return self._error("NOT_FOUND", "接口不存在", 404)

    @staticmethod
    def _error(code: str, message: str, http_status: int, **extra: Any) -> TencentResponse:
        return TencentResponse(http_status, {"error_code": code, "error": message, **extra})

    def _market(self, query: Mapping[str, Any]) -> TencentResponse:
        code = str(query.get("code", ""))
        if not _valid_code(code):
            return self._error("INVALID_CODE", "查询参数无效，请检查股票代码。", 400)
        item = self.store.markets.get(code)
        if item is None:
            return self._error("SOURCE_UNAVAILABLE", "行情暂不可用", 503)
        result = copy.deepcopy(item)
        asof = result.get("asof")
        symbol = ("sh" if code.startswith(("60", "68")) else "sz" if code.startswith(("00", "30")) else "bj") + code
        # Never let a stored, unvalidated embedded object bypass the dedicated
        # information cache's source-permission and availability checks.
        result.pop("investor_context", None)
        if self._information_date(asof):
            try:
                result["investor_context"] = self._investor_projection(asof, symbol)
            except (ValueError, TypeError, KeyError, OverflowError):
                # Information metadata must never turn a cached quote into a
                # failed quote request. The UI treats absence as unavailable.
                result["investor_context"] = None
        return TencentResponse(200, result)

    @staticmethod
    def _information_date(value: Any) -> bool:
        if not isinstance(value, str) or not DATE_RE.fullmatch(value):
            return False
        try:
            return datetime.fromisoformat(value).date().isoformat() == value
        except ValueError:
            return False

    def _read_investor(self, asof: str, symbol: str | None) -> dict[str, Any] | None:
        item = self.store.investor_snapshots.get((asof, symbol))
        if item is None:
            return None
        try:
            validate_public_context(item, asof=asof, symbol=symbol, available_at_cutoff=_now())
        except (ValueError, TypeError, KeyError, OverflowError):
            return None
        return copy.deepcopy(item)

    def _investor_projection(self, asof: str, symbol: str | None) -> dict[str, Any]:
        found = self._read_investor(asof, symbol)
        if found is not None:
            return found
        return build_investor_context(asof=asof, symbol=symbol, available_at_cutoff=_now(), purpose="publish")

    def _investor_context(self, query: Mapping[str, Any]) -> TencentResponse:
        requested = query.get("date", "latest")
        symbol = query.get("symbol")
        if symbol is not None and not valid_symbol(symbol):
            return self._error("INVALID_SYMBOL", "资产须为交易所前缀与六位代码", 400)
        if requested != "latest" and not self._information_date(requested):
            return self._error("INVALID_DATE", "日期须为 latest 或有效日期", 400)
        if requested == "latest":
            dates = [key[0] for key in self.store.investor_snapshots
                     if isinstance(key, tuple) and len(key) == 2 and key[1] == symbol and self._information_date(key[0])]
            asof = max(dates) if dates else None
        else:
            asof = requested
        item = self._read_investor(asof, symbol) if asof else None
        if item is None:
            return self._error("INVESTOR_CONTEXT_NOT_READY", "该日期暂无可公开的资讯快照", 404,
                               date=requested, symbol=symbol, status="not_available")
        return TencentResponse(200, item)

    def _query(self, body: Mapping[str, Any]) -> TencentResponse:
        code = str(body.get("code", ""))
        mode = body.get("mode", "current")
        if not _valid_code(code) or mode not in {"current", "history"}:
            return self._error("INVALID_QUERY", "查询参数无效", 400)
        if mode == "current":
            history_weeks = 0
        else:
            try:
                history_weeks = int(body.get("history_weeks", 104))
            except (TypeError, ValueError):
                return self._error("INVALID_HISTORY_WEEKS", "历史周数无效", 400)
            if not 1 <= history_weeks <= 156:
                return self._error("INVALID_HISTORY_WEEKS", "历史周数必须在1至156之间", 400)
        active_key = (code, mode)
        active_id = self.store.active.get(active_key)
        if active_id:
            job = self.store.jobs[active_id]
            return TencentResponse(202, self._job_payload(job, deduped=True))
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "code": code,
            "mode": mode,
            "history_weeks": history_weeks,
            "variant": "stk_lite",
            "source_sha": str(body.get("source_sha") or "tencent-compat"),
            "requested_at": _now(),
            "since": None,
            "status": "queued",
            "conclusion": None,
            "phase": "queued",
            "current_ready": False,
            "history_ready": False,
            "error_ready": False,
        }
        job["since"] = job["requested_at"]
        self.store.jobs[job_id] = job
        self.store.active[active_key] = job_id
        if self.queue_dispatcher:
            try:
                self.queue_dispatcher(copy.deepcopy(job))
            except Exception:
                job.update(status="failed", conclusion="failure", phase="dispatch_failed")
                self.store.active.pop(active_key, None)
                return self._error("DISPATCH_FAILED", "计算任务暂时无法排队", 503)
        return TencentResponse(202, self._job_payload(job, deduped=False))

    @staticmethod
    def _job_payload(job: Mapping[str, Any], *, deduped: bool) -> dict[str, Any]:
        return {
            "queued": job["status"] in {"queued", "pending", "running"},
            "deduped": deduped,
            "code": job["code"],
            "mode": job["mode"],
            "history_weeks": job["history_weeks"],
            "job_id": job["job_id"],
            "requested_at": job["requested_at"],
            "since": job["since"],
            "source_sha": job["source_sha"],
            "variant": job["variant"],
            "status": job["status"],
        }

    def _status(self, query: Mapping[str, Any]) -> TencentResponse:
        job_id = str(query.get("job_id", ""))
        if not JOB_RE.fullmatch(job_id):
            return self._error("INVALID_JOB_ID", "任务编号无效", 400)
        job = self.store.jobs.get(job_id)
        if not job or (query.get("code") and query.get("code") != job["code"]):
            return self._error("JOB_NOT_FOUND", "找不到该任务", 404)
        return TencentResponse(200, copy.deepcopy(job))

    def _result(self, query: Mapping[str, Any]) -> TencentResponse:
        code = str(query.get("code", ""))
        kind = str(query.get("kind", "latest"))
        job_id = query.get("job_id")
        if not _valid_code(code) or kind not in {"latest", "history", "error"}:
            return self._error("INVALID_RESULT", "结果参数无效", 400)
        if job_id:
            if not JOB_RE.fullmatch(str(job_id)):
                return self._error("INVALID_JOB_ID", "任务编号无效", 400)
            item = self.store.results.get((str(job_id), code, kind))
        else:
            item = self.store.public_results.get((code, kind))
        if item is None:
            return self._error("RESULT_NOT_FOUND", "找不到该任务结果", 404)
        return TencentResponse(200, copy.deepcopy(item))

    def _context(self, query: Mapping[str, Any]) -> TencentResponse:
        date = str(query.get("date", "latest"))
        if date != "latest" and not _valid_date(date):
            return self._error("INVALID_DATE", "日期必须是已验证工作日或 latest", 400)
        item = self.store.latest if date == "latest" else self.store.snapshots.get(date)
        if item is None:
            return TencentResponse(404, {"error_code": "CONTEXT_NOT_READY", "error": "该日期尚无已封存市场背景快照", "date": date, "status": "not_ready"})
        if date != "latest" and item.get("asof") != date:
            return self._error("DATE_MISMATCH", "已封存快照日期与请求不一致", 503)
        result = copy.deepcopy(item)
        result["cache"] = "hit"
        result["investor_context"] = self._investor_projection(result["asof"], None)
        # Projection changes content. Preserve the sealed base hash separately
        # and hash the response envelope instead of mislabelling the old hash.
        result["base_snapshot_sha256"] = result.get("snapshot_sha256")
        result["snapshot_sha256"] = _json_hash(result)
        return TencentResponse(200, result)

    def _seed(self, body: Mapping[str, Any], headers: Mapping[str, str]) -> TencentResponse:
        if not self.seed_token or headers.get("x-market-context-seed-token") != self.seed_token:
            return self._error("SEED_FORBIDDEN", "快照导入接口只允许受控服务端调用", 403)
        snapshot = body.get("snapshot") if isinstance(body.get("snapshot"), Mapping) else body
        if not isinstance(snapshot, Mapping):
            return self._error("INVALID_SNAPSHOT", "快照必须是对象", 422)
        validation = self._validate_snapshot(snapshot)
        if validation:
            return self._error(validation, "快照未通过契约校验", 422)
        asof = str(snapshot["asof"])
        if asof in self.store.snapshots:
            return self._error("SNAPSHOT_EXISTS", "该日期快照已经封存，不允许覆盖", 409, asof=asof)
        item = copy.deepcopy(dict(snapshot))
        self.store.snapshots[asof] = item
        latest_updated = self.store.latest is None or str(self.store.latest.get("asof", "")) <= asof
        if latest_updated:
            self.store.latest = copy.deepcopy(item)
        return TencentResponse(201, {"seeded": True, "asof": asof, "latest_updated": latest_updated, "snapshot_sha256": item["snapshot_sha256"]})

    @staticmethod
    def _validate_snapshot(snapshot: Mapping[str, Any]) -> str | None:
        p1 = snapshot.get("p1") if isinstance(snapshot.get("p1"), Mapping) else {}
        if (
            "evidence_import" in snapshot
            or snapshot.get("publication_eligible") is False
            or snapshot.get("run_mode") in {"research_import", "fixture"}
            or "supplemental_sources" in p1
            or "investor_context" in snapshot
        ):
            return "UNPUBLISHED_EVIDENCE"
        if snapshot.get("schema_version") != "market-context.v1":
            return "SCHEMA_MISMATCH"
        if not _valid_date(snapshot.get("asof")):
            return "INVALID_DATE"
        if snapshot.get("evidence") != "descriptive":
            return "EVIDENCE_REQUIRED"
        calendar = snapshot.get("calendar")
        if not isinstance(calendar, Mapping) or calendar.get("calendar_status") != "provided" or calendar.get("asof_status") != "exchange_verified" or not HASH_RE.fullmatch(str(calendar.get("calendar_source_sha256") or "")):
            return "CALENDAR_UNVERIFIED"
        history = snapshot.get("history") if isinstance(snapshot.get("history"), Mapping) else {}
        progression = history.get("progression") if isinstance(history.get("progression"), Mapping) else {}
        if progression.get("status") == "fresh" and calendar.get("prior_status") != "exchange_verified":
            return "CALENDAR_UNVERIFIED"
        if not HASH_RE.fullmatch(str(snapshot.get("snapshot_sha256", ""))):
            return "SNAPSHOT_HASH_REQUIRED"
        sources = snapshot.get("sources")
        if not isinstance(sources, Mapping) or not any(HASH_RE.fullmatch(str(v.get("raw_sha256", ""))) for v in sources.values() if isinstance(v, Mapping)):
            return "SOURCE_HASH_REQUIRED"
        expected = _json_hash(snapshot)
        if expected.lower() != str(snapshot["snapshot_sha256"]).lower():
            return "SNAPSHOT_HASH_MISMATCH"
        return None

    def _refresh(self, body: Mapping[str, Any], headers: Mapping[str, str]) -> TencentResponse:
        if not self.refresh_token or headers.get("x-market-context-token") != self.refresh_token:
            return self._error("REFRESH_FORBIDDEN", "刷新接口只允许服务端任务调用", 403)
        if not self.source_url or not self.refresh_dispatcher:
            return self._error("SOURCE_NOT_CONFIGURED", "腾讯云后端尚未配置已核验数据源", 503)
        date = body.get("date", "latest")
        if date != "latest" and not _valid_date(date):
            return self._error("INVALID_DATE", "日期必须是已验证工作日或 latest", 400)
        job_id = str(uuid.uuid4())
        job = {"job_id": job_id, "date": date, "status": "queued", "requested_at": _now(), "error_code": None}
        self.store.refresh_jobs[job_id] = job
        try:
            self.refresh_dispatcher(copy.deepcopy(job))
        except Exception:
            job.update(status="failed", error_code="CONTEXT_REFRESH_FAILED")
            return self._error("CONTEXT_REFRESH_FAILED", "市场背景刷新失败", 503, job_id=job_id)
        return TencentResponse(202, {"queued": True, "deduped": False, **job})

    def _context_status(self, query: Mapping[str, Any]) -> TencentResponse:
        job_id = str(query.get("job_id", ""))
        if not JOB_RE.fullmatch(job_id):
            return self._error("INVALID_JOB_ID", "任务编号无效", 400)
        job = self.store.refresh_jobs.get(job_id)
        if job is None:
            return self._error("JOB_NOT_FOUND", "找不到市场背景刷新任务", 404)
        return TencentResponse(200, copy.deepcopy(job))


__all__ = ["API_SCHEMA", "InMemoryTencentStore", "TencentCompat", "TencentResponse"]
