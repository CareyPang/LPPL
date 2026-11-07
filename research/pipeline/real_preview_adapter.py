"""Isolated current-only, two-asset LPPLS research preview.

This is a new, explicitly versioned experiment, not a replacement for stock.py.
It retains raw vendor responses and one best fit per preselected window. It does
not dispatch GitHub jobs, publish results, or call any historical evaluator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import time
import uuid
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from ..data.preview_calendar import calendar_for, weekday_estimate
from ..lppls import core
from ..lppls.window_clusters import analyze_asof, prepare, selected_windows
from ..optim.optimizers import tcgrid_lm

MODEL_VERSION = "real_preview_future_cycles1_5_thin28_v1"
ASSETS = {
    "sh000001": {"name": "上证指数", "asset_type": "index", "adjustment": "none"},
    "sh600519": {"name": "贵州茅台", "asset_type": "stock", "adjustment": "hfq"},
}
BUDGET = {"n_tc": 40, "n_m": 12, "n_w": 16, "topk": 5}
MAX_FIT_SECONDS = 180


def canonical(value: str) -> str:
    code = str(value).strip().lower()
    code = {"600519": "sh600519", "贵州茅台": "sh600519", "上证指数": "sh000001"}.get(code, code)
    if code not in ASSETS:
        raise ValueError("本轮仅支持上证指数 sh000001 与贵州茅台 sh600519；裸 000001 不用于指数，避免与平安银行混淆。")
    return code


def utc_now() -> str:
    return pd.Timestamp.now(tz="UTC").isoformat()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(raw, encoding="utf-8")
    temporary.replace(path)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_manifest() -> dict:
    repo = Path(__file__).resolve().parents[2]
    paths = ("research/pipeline/real_preview_adapter.py", "research/data/preview_calendar.py",
             "research/lppls/core.py", "research/lppls/oscillations.py", "research/lppls/window_clusters.py",
             "research/optim/optimizers.py")
    return {path: digest((repo / path).read_bytes()) for path in paths}


def source_identity(source_sha: str) -> dict:
    """Only claim exact checkout if every model file is tracked and unchanged."""
    repo = Path(__file__).resolve().parents[2]
    paths = list(source_manifest())
    exact = False
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
        tracked = subprocess.check_output(["git", "ls-files", "--", *paths], cwd=repo, text=True).splitlines()
        clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *paths], cwd=repo).returncode == 0
        exact = head == source_sha and clean and set(tracked) == set(paths)
    except (OSError, subprocess.CalledProcessError):
        pass
    return {"source_sha_kind": "exact_checkout" if exact else "base_commit_with_file_hashes",
            "source_sha_scope": "exact checked-out model sources" if exact else "caller-supplied base commit; actual source bytes recorded separately"}


def validate_job(job: dict) -> None:
    identity = str(job.get("job_id", ""))
    if str(uuid.UUID(identity)) != identity:
        raise ValueError("job_id must be a canonical UUID")
    requested = pd.Timestamp(job["requested_at"])
    if requested.tzinfo is None or requested > pd.Timestamp(utc_now()) + pd.Timedelta(seconds=5):
        raise ValueError("requested_at must be timezone-aware and cannot be in the future")


def _fetch(url: str, params: dict | None, directory: Path, label: str) -> tuple[bytes, dict]:
    started = utc_now()
    response = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}, timeout=(8, 15))
    body = response.content
    sha = digest(body)
    directory.mkdir(parents=True, exist_ok=True)
    raw_path = directory / f"{label}-{sha}.raw"
    raw_path.write_bytes(body)
    meta = {"url": response.url, "requested_at": started, "received_at": utc_now(),
            "http_status": response.status_code, "sha256": sha, "bytes": len(body), "file": raw_path.name}
    write_json(directory / f"{label}-{sha}.json", meta)
    response.raise_for_status()
    return body, meta


def separate_price_bases(observed: dict, root: Path) -> dict:
    """Recover raw quote OHLC from saved bytes; preserve exact fitted closes.

    Supports the first preview snapshots that displayed HFQ prices. This pure
    migration never refits or refetches, and the original job input is retained.
    """
    if "model_adjustment" in observed:
        return observed
    code = canonical(observed["code"])
    model_bars = observed["price"]
    raw_bars = model_bars
    if observed.get("adjustment") == "hfq":
        evidence = next(item for item in observed["provenance"] if "fqkline" in item["url"])
        path = root / code / "raw" / evidence["file"]
        body = path.read_bytes()
        if digest(body) != evidence["sha256"]:
            raise ValueError("archived quote bytes failed SHA256 check")
        rows = json.loads(body)["data"][code]["day"]
        raw_by_date = {str(row[0]): {"date": str(row[0]), **dict(zip(("open", "close", "high", "low", "volume"), map(float, row[1:6]), strict=True))} for row in rows}
        raw_bars = [raw_by_date[bar["date"]] for bar in model_bars]
    return {**observed, "price": raw_bars, "model_price": model_bars,
            "adjustment": "none", "model_adjustment": observed.get("adjustment", "none"),
            "price_basis_note": "K线为未复权行情；模型对个股使用后复权价格，只叠时间区间，不叠模型价格。"}


def market(code: str, root: Path, refresh: bool = False) -> dict:
    """At most 640 daily bars; archived vendor bytes are never replaced."""
    code = canonical(code)
    path = root / code / "market.json"
    if path.exists() and not refresh:
        result = separate_price_bases(json.loads(path.read_text(encoding="utf-8")), root)
        write_json(path, result)
        return result
    provenance, errors, rows = [], [], None
    for host in ("https://web.ifzq.gtimg.cn", "https://proxy.finance.qq.com/ifzqgtimg"):
        try:
            body, evidence = _fetch(host + "/appstock/app/fqkline/get", {"param": f"{code},day,,,640,"}, root / code / "raw", "daily")
            payload = json.loads(body)
            rows = ((payload.get("data") or {}).get(code) or {}).get("day")
            if not rows:
                raise ValueError("vendor daily response empty")
            provenance.append(evidence)
            break
        except (requests.RequestException, ValueError, KeyError) as exc:
            errors.append(str(exc))
    if not rows:
        raise ValueError("行情源读取失败: " + "; ".join(errors))
    now = pd.Timestamp.now(tz="Asia/Shanghai")
    cutoff = now.tz_localize(None).normalize()
    if now.hour * 60 + now.minute < 930:
        cutoff -= pd.Timedelta(days=1)
    bars = {}
    for row in rows:
        date = str(pd.Timestamp(row[0]).date())
        if pd.Timestamp(date) > cutoff:
            continue
        item = dict(zip(("open", "close", "high", "low", "volume"), map(float, row[1:6]), strict=True))
        if not all(math.isfinite(v) for v in item.values()) or min(item[k] for k in ("open", "close", "high", "low")) <= 0:
            raise ValueError("行情包含非有限或非正价格")
        if item["high"] < max(item["open"], item["close"]) or item["low"] > min(item["open"], item["close"]) or item["volume"] < 0:
            raise ValueError("行情OHLCV约束错误")
        bars[date] = {"date": date, **item}
    ordered = [bars[date] for date in sorted(bars)]
    if len(ordered) < 500:
        raise ValueError(f"当前研究需要至少500根闭盘日线，实际{len(ordered)}根")
    adjustment = ASSETS[code]["adjustment"]
    raw_ordered = [dict(bar) for bar in ordered]
    if adjustment == "hfq":
        body, evidence = _fetch(f"https://finance.sina.com.cn/realstock/company/{code}/hfq.js", None, root / code / "raw", "hfq")
        text = body.decode("utf-8-sig")
        factor_payload, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
        factors = sorted((str(pd.Timestamp(row["d"]).date()), float(row["f"])) for row in factor_payload.get("data", []))
        if not factors or any(not math.isfinite(value) or value <= 0 for _, value in factors):
            raise ValueError("后复权因子不完整")
        dates = [date for date, _ in factors]
        for bar in ordered:
            index = int(np.searchsorted(dates, bar["date"], side="right")) - 1
            if index < 0:
                raise ValueError("某日缺少当日或更早生效的复权因子；不以后日因子补齐")
            for key in ("open", "high", "low", "close"):
                bar[key] *= factors[index][1]
        provenance.append(evidence)
    raw_hashes = [item["sha256"] for item in provenance]
    result = {"code": code, "symbol": code, **ASSETS[code], "asof": ordered[-1]["date"], "price": raw_ordered,
              "model_price": ordered, "adjustment": "none", "model_adjustment": adjustment,
              "price_basis_note": "K线为未复权行情；模型对个股使用后复权价格，只叠时间区间，不叠模型价格。",
              "source": "tencent_daily_sina_factors" if adjustment == "hfq" else "tencent_daily",
              "volume_unit": "vendor_native", "evidence": "observed", "model_computed": False,
              "data_version": digest("|".join(raw_hashes).encode()), "provenance": provenance,
              "fetched_at": utc_now(), "closed_bars_only": True, "cache": "fresh",
              "expected_model_version": MODEL_VERSION,
              "note": "真实供应商日线；因子为本次取得的修订版本，不是历史时点可得性证明。"}
    write_json(path, result)
    return result


def _calendar(asof: str, horizon: int = 100) -> dict:
    return calendar_for(asof)


def _window(cluster: dict, calendar: dict, cross: bool) -> dict:
    # Outward rounding preserves every member; never crop a wide interval.
    lower, upper = math.floor(cluster["lo"]), math.ceil(cluster["hi"])
    if upper >= len(calendar["dates"]):
        calendar = weekday_estimate(calendar["dates"][0], horizon=max(100, upper))
    dates = calendar["dates"]
    return {"id": cluster["id"], "start": dates[lower], "end": dates[upper],
            "evidence": "research_candidate", "tier": "early_observation",
            "width_sessions": upper - lower + 1, "lead_sessions": lower - 1,
            "lead_convention": "next estimated session is first possible action; signed lead to interval start",
            "calendar_verified": calendar["status"] == "exchange_verified", "calendar": calendar,
            "claim_kind": "new", "claim_kind_scope": "this_isolated_first_current_run",
            "ahead_min": cluster["lo"], "ahead_max": cluster["hi"], "cross_scale": cross,
            "supported_scales": cluster["supported_scales"], "members": cluster["members"],
            "n_members": cluster["n_members"], "descriptive_support_mass": cluster["mass"],
            "reason": "跨尺度研究候选；不能判定最终阶段顶" if cross else "仅单尺度研究观察，未达到跨尺度支持",
            "width_note": "原始成员极值向外取整；没有裁窄日期区间；支持质量不是概率。"}


def fit_current(code: str, root: Path, job: dict, source_sha: str = "NOT_ESTABLISHED") -> dict:
    code = canonical(code)
    execution_started_at = utc_now()
    validate_job(job)
    started = time.perf_counter()
    observed = market(code, root)
    out = root / code / "jobs" / job["job_id"]
    if (out / "result.json").exists():
        raise ValueError("immutable job result already exists; no repeat fitting was started")
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "input_market.json", observed)
    values = np.log([bar["close"] for bar in observed["model_price"]])
    windows = sorted({n for grid in selected_windows("thin").values() for n in grid})
    # Existing optimizer, explicit strict future box; no global production file changes.
    core.ALLOW_INSIDE = False
    fits, timings = [], []
    for index, n in enumerate(windows):
        if time.perf_counter() - started > MAX_FIT_SECONDS:
            raise TimeoutError(f"本次计算超过{MAX_FIT_SECONDS}秒预算；不使用不完整扫描形成区间")
        t = np.arange(n, dtype=float)
        y = values[-n:]
        lo = np.array([n - 1 + .5, .01, 1.])
        hi = np.array([n - 1 + .2 * (n - 1), 2., 50.])
        result = tcgrid_lm(t, y, lo, hi, seed=0, budget=BUDGET, n_random=10)
        tc, m, omega = map(float, result.theta)
        sse, beta = core.lin_fit(t, y, tc, m, omega)
        denominator = float(((y - y.mean()) ** 2).sum())
        fits.append({"date": observed["asof"], "n": n, "tc": tc, "m": m, "w": omega,
                     "A": float(beta[0]), "B": float(beta[1]), "C1": float(beta[2]), "C2": float(beta[3]),
                     "sse": float(sse), "r2": 1 - float(sse) / denominator if denominator else None,
                     "nfev": result.nfev, "seconds": result.seconds})
        timings.append(result.seconds)
        write_json(out / "progress.json", {"completed_windows": index + 1, "total_windows": len(windows),
                   "elapsed_seconds": time.perf_counter() - started, "last_window_seconds": result.seconds})
        if index == 0:
            write_json(out / "capacity_sample.json", {"first_window": n, "seconds": result.seconds,
                       "estimated_serial_seconds": result.seconds * len(windows), "max_fit_seconds": MAX_FIT_SECONDS,
                       "n_windows": len(windows), "daily_bars": len(values), "bootstrap": False,
                       "history_replay": False, "estimate_limit": "first short window only; longer windows may cost more"})
    frame = pd.DataFrame(fits)
    frame.to_csv(out / "fits.csv", index=False)
    return export_fits(code, root, job, observed, frame, source_sha=source_sha,
                       execution_started_at=execution_started_at, fit_seconds=time.perf_counter() - started)


def export_fits(code: str, root: Path, job: dict, observed: dict, frame: pd.DataFrame, *,
                source_sha: str, execution_started_at: str, fit_seconds: float,
                parent_result: dict | None = None) -> dict:
    """Pure export of saved fits, with a new identity when revising presentation."""
    code = canonical(code)
    validate_job(job)
    observed = separate_price_bases(observed, root)
    out = root / code / "jobs" / job["job_id"]
    if (out / "result.json").exists():
        raise ValueError("immutable job result already exists; use a new job identity")
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "input_market.json", observed)
    frame.to_csv(out / "fits.csv", index=False)
    values = np.log([bar["close"] for bar in observed["model_price"]])
    windows = sorted({n for grid in selected_windows("thin").values() for n in grid})
    analysis = analyze_asof(frame, windows, mode="thin")
    write_json(out / "clusters.json", analysis)
    enriched = prepare(frame)
    gates = {
        "nonfinite_parameters": ~np.isfinite(enriched[["tc", "m", "w", "B"]]).all(axis=1),
        "not_positive_bubble_shape": enriched.B >= 0,
        "m_outside_filter": ~enriched.m.between(.1, .9),
        "omega_outside_filter": ~enriched.w.between(6, 13),
        "future_horizon_outside_filter": ~((enriched.ahead > 0) & (enriched.ahead <= 90)),
        "fewer_than_1_5_complete_cycles": (enriched.osc_cycles_status != "ok") | (enriched.osc_cycles < 1.5),
    }
    exclusions = [{"reason": name, "count": int(mask.sum())} for name, mask in gates.items()]
    calendar = _calendar(observed["asof"])
    cross = analysis["clusters"]["cross"]["primary"]
    primary = cross or analysis["clusters"]["any"]["primary"]
    candidate_windows = [_window(primary, calendar, bool(cross))] if primary else []
    boundary_rows = enriched[(enriched.ahead - .2 * (enriched.n - 1)).abs() <= 1e-6]
    boundary_members = sorted(set(boundary_rows.n.astype(int)) & set(primary["members"])) if primary else []
    for candidate in candidate_windows:
        candidate["search_boundary_members"] = boundary_members
        candidate["search_boundary_note"] = "部分成员t_c触及搜索上界，需要扩域敏感性检查；不能据此确认顶部" if boundary_members else ""
        if parent_result:
            candidate["claim_kind"] = "revision"
            candidate["claim_kind_scope"] = "fixed_fit_export_revision_not_new_forecast"
    result = {"code": code, "symbol": code, "name": ASSETS[code]["name"], "asof": observed["asof"],
        "schema_version": "stock_result_v1", "mode": "current", "variant": "research_thin28_future", **job,
        "source_sha": source_sha, "generated_at": utc_now(), "model_version": MODEL_VERSION,
        "execution_started_at": execution_started_at,
        "source_file_sha256": digest(Path(__file__).read_bytes()),
        "source_files_sha256": source_manifest(),
        **source_identity(source_sha),
        "runtime_versions": {"python": platform.python_version(), **{name: version(name) for name in ("numpy", "pandas", "scipy", "requests")}},
        "fit_code_version": MODEL_VERSION, "data_version": observed["data_version"],
        "market_adjustment": observed["adjustment"], "model_adjustment": observed["model_adjustment"],
        "fit_input_hash": digest(np.asarray(values[-500:], dtype="<f8").tobytes()),
        "evidence": "research_candidate", "model_computed": True, "demo": False,
        "execution_origin": "FIXED_FIT_EXPORT_REVISION" if parent_result else "ISOLATED_REAL_CURRENT_RUN", "elapsed_seconds": fit_seconds,
        "price_history": {key: [row[key] for row in observed["price"]] for key in ("open", "high", "low", "close", "volume")},
        "top": {"signal_status": "signal" if candidate_windows else "no_qualified_fit", "evidence_override": "research_candidate",
                "window": candidate_windows[0] if candidate_windows else {"start": None, "end": None, "evidence": "none"},
                "scenarios": [], "lppls_confidence": {"evidence": "research_candidate"},
                "drawdown_price": {"value": None, "evidence": "none"}},
        "analysis": {"schema": "stock_analysis_v1", "status": "research_candidate" if candidate_windows else "no_signal",
                     "evidence": "research_candidate", "as_of": observed["asof"], "model_version": MODEL_VERSION,
                     "fit_code_version": MODEL_VERSION, "minimum_full_cycles": 1.5, "calendar": calendar,
                     "windows": candidate_windows, "exclusions": exclusions, "exclusion_counts_may_overlap": True,
                     "qualified_windows": int(enriched.qualified.sum()), "total_windows": len(windows), "scales": analysis["scales"],
                     "reason": "发现研究候选区间，尚未验证逃顶效果" if candidate_windows else "完成真实拟合，但没有至少3个合格窗口形成的候选簇；不生成顶部日期",
                     "search_boundary_members": boundary_members,
                     "boundary": "不是概率，不保证顶部或跌幅；尚不能判定局部高点与1–6个月阶段顶。"},
        "research_config": {"windows": windows, "window_mode": "thin", "optimizer": "tcgrid_lm_trf",
                            "optimizer_budget": BUDGET, "random_starts": 10, "seed": 0,
                            "search_bounds": {"m": [.01, 2.], "omega": [1., 50.], "ahead": [0.5, "0.2*(n-1)"]},
                            "future_only": True, "comparison_to_old": "new future-only fitting domain; not identical to old v2 absolute extension",
                            "bootstrap": False, "history_weeks": 0},
        "validation": [], "stock_meta": {"evidence": "research_candidate", "note": "隔离真实当前拟合；未通过样本外预警能力验证"}}
    result["price_history"]["dates"] = [row["date"] for row in observed["price"]]
    if parent_result:
        result["fit_provenance"] = {"original_job_id": parent_result["job_id"],
                                    "original_generated_at": parent_result["generated_at"],
                                    "original_source_file_sha256": parent_result.get("source_file_sha256"),
                                    "refitted": False, "change": "inclusive width, actionable lead, boundary diagnostics, verified 2026 calendar, raw quote display preserving fitted HFQ closes"}
    write_json(out / "result.json", result)
    write_json(root / code / "latest.json", result)
    write_json(root / "bundle.json", {"market": observed, "result": result})
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("code", nargs="?", help="symbol, or 'run' when using --asset")
    parser.add_argument("--asset")
    parser.add_argument("--data-dir", "--out", dest="data_dir", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--requested-at", default=None)
    parser.add_argument("--source-sha", default="NOT_ESTABLISHED")
    parser.add_argument("--reexport-from", type=Path, help="existing immutable result.json; no fitting or network")
    args = parser.parse_args()
    job = {"job_id": args.job_id, "requested_at": args.requested_at or utc_now()}
    code = args.asset or args.code
    if not code or code == "run":
        parser.error("provide a symbol or run --asset SYMBOL")
    if args.reexport_from:
        original = json.loads(args.reexport_from.read_text(encoding="utf-8"))
        if canonical(code) != original["code"]:
            parser.error("reexport asset identity mismatch")
        observed = json.loads((args.reexport_from.parent / "input_market.json").read_text(encoding="utf-8"))
        frame = pd.read_csv(args.reexport_from.parent / "fits.csv")
        result = export_fits(code, args.data_dir, job, observed, frame, source_sha=args.source_sha,
                             execution_started_at=utc_now(), fit_seconds=original["elapsed_seconds"], parent_result=original)
    else:
        result = fit_current(code, args.data_dir, job, args.source_sha)
    print(json.dumps({"code": result["code"], "status": result["analysis"]["status"], "elapsed_seconds": result["elapsed_seconds"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
