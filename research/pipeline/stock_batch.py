"""Nightly / sharded batch of per-stock LPPLS records with one fixed as-of date.

Every stock in the batch is cut at the same closed trading day so that the
published library and its breadth summary are internally consistent.  Member
lists are PIT snapshots (``web/mock/data/universe_*.json``); the breadth summary
is descriptive only and never enters fitting, alarms or model features.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import stock as stock_pipeline
from .stock_jobs import attach_job, cli_job

UTC = timezone.utc  # noqa: UP017 — 运行环境 Python 3.10

DEV_SCALES = ("6-12m", "12-24m")
ALL_SCALES = ("2-4w", "1-3m", "3-6m", "6-12m", "12-24m", "2-6y")
BREADTH_NOTE = (
    "成分股广度：按同一截止日统计成分股中有合格拟合的比例，描述性统计，"
    "不进入拟合、报警或模型特征；不是预测。R8 横截面广度为 Round 2 候选，未登记。"
)


def load_universe(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    codes = data.get("codes")
    if not isinstance(codes, list) or not codes:
        raise ValueError(f"{path} has no codes list")
    seen: list[str] = []
    for code in codes:
        code6 = str(code).strip()
        if len(code6) != 6 or not code6.isdigit():
            raise ValueError(f"universe code must be six digits: {code!r}")
        if code6 not in seen:
            seen.append(code6)
    data["codes"] = sorted(seen)
    return data


def shard(codes: list[str], index: int, count: int) -> list[str]:
    if count < 1 or not 0 <= index < count:
        raise ValueError(f"shard index must satisfy 0 <= index < count, got {index}/{count}")
    return list(codes[index::count])


def default_asof() -> str:
    cutoff = stock_pipeline._close_cutoff(stock_pipeline._now())
    calendar = stock_pipeline._reference_calendar(cutoff)
    return str(pd.Timestamp(calendar[-1]).date())


def _write_json_atomic(path: Path, record: dict, indent: int) -> None:
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=indent, default=str),
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def run_batch(
    codes: list[str],
    asof: str,
    out: Path,
    variant: str = "stk_lite",
    procs: int | None = None,
    run_url: str | None = None,
    job: dict | None = None,
) -> dict:
    batch = cli_job(**job) if job else {}
    out.mkdir(parents=True, exist_ok=True)
    summary = {"asof": asof, "variant": variant, "ok": [], "failed": []}
    if batch:
        summary.update(batch_id=batch["job_id"], requested_at=batch["requested_at"], source_sha=batch["source_sha"])
    for code in codes:
        stock_job = {**batch, "job_id": str(uuid.uuid4())} if batch else {}
        t0 = time.time()
        result_path = out / f"{code}.json"
        error_path = out / f"{code}_error.json"
        try:
            record = stock_pipeline.predict(code, variant=variant, asof=asof, procs=procs)
            attach_job(record, stock_job, code, "current")
            if batch:
                record["batch_id"] = batch["job_id"]
            _write_json_atomic(result_path, record, indent=1)
            error_path.unlink(missing_ok=True)
            summary["ok"].append(code)
            status = record.get("stock_meta", {}).get("status")
        except Exception as exc:  # noqa: BLE001 —— 单只失败不拖垮整批，显式写入 error 文件
            result_path.unlink(missing_ok=True)
            error = {
                "code": code,
                "asof": asof,
                "error": "本次日更未完成，已有结果仍可查看。",
                "error_code": "COMPUTE_FAILED",
                "stage": "current",
                "run_url": run_url,
                "generated_at": datetime.now(UTC).isoformat(),
            }
            attach_job(error, stock_job, code, "current")
            if batch:
                error["batch_id"] = batch["job_id"]
            print(f"{code}: {type(exc).__name__}", flush=True)
            _write_json_atomic(error_path, error, indent=2)
            summary["failed"].append(code)
            status = "error"
        print(f"{code} {status} {time.time() - t0:.1f}s", flush=True)
    return summary


def _qualified(record: dict) -> tuple[set[str], set[str]]:
    top = record.get("top") or {}
    indicators = top.get("indicators") or {}
    confidence = top.get("lppls_confidence") or {}
    fit_scales: set[str] = set()
    conf_scales: set[str] = set()
    for scale in ALL_SCALES:
        ind = indicators.get(scale) or {}
        if ind.get("display_only"):
            continue
        standard = (ind.get("confidence") or {}).get("standard")
        if standard is not None and standard > 0:
            fit_scales.add(scale)
        value = confidence.get(scale)
        if isinstance(value, (int, float)) and value >= 0.5:
            conf_scales.add(scale)
    return fit_scales, conf_scales


def breadth(
    result_dir: Path,
    universe: dict,
    variant: str = "stk_lite",
    planned_asof: str | None = None,
) -> dict:
    codes = universe["codes"]
    asofs: dict[str, int] = {}
    excluded_asofs: dict[str, int] = {}
    per_scale_fit = {s: 0 for s in ALL_SCALES}
    per_scale_conf = {s: 0 for s in ALL_SCALES}
    n_result = n_in_stats = n_fit_dev = n_conf_dev = n_error = n_missing = 0
    statuses: dict[str, int] = {}
    for code in codes:
        path = result_dir / f"{code}.json"
        if not path.exists():
            if (result_dir / f"{code}_error.json").exists():
                n_error += 1
            else:
                n_missing += 1
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        n_result += 1
        meta = record.get("stock_meta") or {}
        statuses[str(meta.get("status"))] = statuses.get(str(meta.get("status")), 0) + 1
        asof = str(record.get("asof"))
        if not meta.get("in_stats"):
            excluded_asofs[asof] = excluded_asofs.get(asof, 0) + 1
            continue
        asofs[asof] = asofs.get(asof, 0) + 1
        n_in_stats += 1
        fit_scales, conf_scales = _qualified(record)
        for scale in fit_scales:
            per_scale_fit[scale] += 1
        for scale in conf_scales:
            per_scale_conf[scale] += 1
        if fit_scales & set(DEV_SCALES):
            n_fit_dev += 1
        if conf_scales & set(DEV_SCALES):
            n_conf_dev += 1
    share = lambda k: round(k / n_in_stats, 4) if n_in_stats else None  # noqa: E731
    asof_consistent = (
        all(asof == planned_asof for asof in asofs)
        if planned_asof is not None
        else len(asofs) <= 1
    )
    return {
        "index": universe.get("index"),
        "universe_snapshot": universe.get("snapshot"),
        "universe_note": universe.get("note"),
        "variant": variant,
        "planned_asof": planned_asof,
        "asof": max(asofs, key=asofs.get) if asofs else None,
        "asof_counts": dict(sorted(asofs.items())),
        "asof_consistent": asof_consistent,
        "excluded_asof_counts": dict(sorted(excluded_asofs.items())),
        "n": n_in_stats,
        "n_members": len(codes),
        "n_results": n_result,
        "n_error": n_error,
        "n_missing": n_missing,
        "status_counts": dict(sorted(statuses.items())),
        "dev_scales": list(DEV_SCALES),
        "n_qualified_fit_dev": n_fit_dev,
        "share_qualified_fit_dev": share(n_fit_dev),
        "n_confidence_ge_0_5_dev": n_conf_dev,
        "share_confidence_ge_0_5_dev": share(n_conf_dev),
        "per_scale_qualified_fit": per_scale_fit,
        "per_scale_confidence_ge_0_5": per_scale_conf,
        "evidence": "descriptive",
        "note": BREADTH_NOTE,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sharded fixed-asof stock batch")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="fit one shard of a universe at a fixed asof")
    run.add_argument("--universe", type=Path, required=True)
    run.add_argument("--asof", help="YYYY-MM-DD; default = last closed sh000001 trading day")
    run.add_argument("--shard", default="0/1", help="k/n, zero-based")
    run.add_argument("--variant", choices=("stk_lite", "stk_full"), default="stk_lite")
    run.add_argument("--procs", type=int)
    run.add_argument("--out", type=Path, default=Path("out/stock"))
    run.add_argument("--run-url")
    run.add_argument("--limit", type=int)
    run.add_argument("--batch-id")
    run.add_argument("--requested-at")
    run.add_argument("--source-sha")

    br = sub.add_parser("breadth", help="summarise a result directory into breadth JSON")
    br.add_argument("--universe", type=Path, required=True)
    br.add_argument("--results", type=Path, default=Path("out/stock"))
    br.add_argument("--variant", choices=("stk_lite", "stk_full"), default="stk_lite")
    br.add_argument("--asof", help="planned YYYY-MM-DD date for this batch")
    br.add_argument("--out", type=Path)

    args = parser.parse_args()
    universe = load_universe(args.universe)
    if args.cmd == "run":
        k, n = (int(x) for x in args.shard.split("/"))
        codes = shard(universe["codes"], k, n)
        if args.limit:
            codes = codes[: args.limit]
        asof = args.asof or default_asof()
        print(f"asof={asof} shard={k}/{n} codes={len(codes)}", flush=True)
        job = cli_job(args.batch_id, args.requested_at, args.source_sha)
        summary = run_batch(codes, asof, args.out, args.variant, args.procs, args.run_url, job=job)
        (args.out / f"_batch_{k}_of_{n}.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"ok={len(summary['ok'])} failed={len(summary['failed'])}")
        return
    result = breadth(args.results, universe, args.variant, args.asof)
    out = args.out or args.results / f"breadth_{universe['index']}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(out)
    print(
        f"n={result['n']} qualified_fit_dev={result['n_qualified_fit_dev']} "
        f"conf>=0.5={result['n_confidence_ge_0_5_dev']} asof_consistent={result['asof_consistent']}"
    )


if __name__ == "__main__":
    main()
