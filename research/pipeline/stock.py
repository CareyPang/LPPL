"""Point-in-time LPPLS records for individual A-share stocks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from ..data import cache
from ..data.tencent_sina import apply_factors, sina_factors, tencent_raw
from ..eval.export_contract import (
    _derived,
    _history_frame,
    build_record,
)
from ..eval.label_diag import ps_tops
from ..features import lppls_scan
from ..features.lppls_rules import rules
from ..lppls import core as _core
from ..pipeline import universe
from ..pipeline.daily import fit_asof

ROOT = Path(__file__).resolve().parents[2]
NAMES_PATH = ROOT / "web/mock/data/stock_names.json"
DEFAULT_START = "1990-01-01"
STOCK_EVIDENCE = "research_candidate"
STOCK_NOTE = "个股未经过样本外检验；证据等级 research_candidate，不继承指数证据"
FIT_CACHE_COLUMNS = [*lppls_scan.COLS, "asof", "data_version", "code_version"]
FIT_CACHE_KEY = ["asof", "n", "data_version", "code_version"]

_FIT_LOGP: pd.Series | None = None
_FIT_INSIDE = False


def _fit_worker_init(logp: pd.Series, inside: bool) -> None:
    global _FIT_LOGP, _FIT_INSIDE
    _FIT_LOGP = logp
    _FIT_INSIDE = inside
    _core.ALLOW_INSIDE = inside


def _fit_worker(task: tuple[pd.Timestamp, int]) -> pd.DataFrame:
    if _FIT_LOGP is None:
        raise RuntimeError("fit worker has no price series")
    asof, window = task
    return fit_asof(_FIT_LOGP, pd.Timestamp(asof), (int(window),))


def _set_allow_inside() -> bool:
    inside = bool(lppls_scan.BOXES[lppls_scan.BOX]["inside"])
    _core.ALLOW_INSIDE = inside
    return inside


def _fit_pairs(
    logp: pd.Series, pairs: list[tuple[pd.Timestamp, int]], procs: int | None
) -> pd.DataFrame:
    if not pairs:
        return pd.DataFrame(columns=[*lppls_scan.COLS, "y_std"])
    inside = _set_allow_inside()
    workers = os.cpu_count() if procs is None else procs
    if workers is None:
        workers = 1
    if workers < 1:
        raise ValueError("procs must be a positive integer")
    workers = min(workers, len(pairs))
    if workers == 1:
        _fit_worker_init(logp, inside)
        frames = [_fit_worker(pair) for pair in pairs]
    else:
        with Pool(workers, initializer=_fit_worker_init, initargs=(logp, inside)) as pool:
            frames = pool.map(_fit_worker, pairs)
    result = pd.concat(frames, ignore_index=True)
    if len(result):
        result = result.sort_values(["date", "n"], kind="stable").reset_index(drop=True)
    return result


def _validate_code(code6: str) -> str:
    code = str(code6).strip()
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"stock code must be six digits: {code6!r}")
    return code


def _normalise_prices(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col in out:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out = (
        out.dropna(subset=["close"])
        .loc[lambda d: d.close > 0]
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    return out


def load_stock(
    code6: str, start: str | None = None
) -> tuple[pd.DataFrame, str, dict]:
    code = _validate_code(code6)
    sym = universe._sym(code)
    requested_start = str(pd.Timestamp(start or DEFAULT_START).date())
    try:
        factors = sina_factors(sym, "hfq")
    except Exception as exc:
        raise RuntimeError(f"cannot load Sina HFQ factors for {sym}: {exc}") from exc
    factors_csv = factors.to_csv(index=False).encode("utf-8")
    factor_hash = hashlib.sha1(factors_csv).hexdigest()[:8]
    source = "tencent_sina_hfq"
    try:
        raw = tencent_raw(sym, start=requested_start)
        adjusted = apply_factors(raw, factors, "hfq")
    except Exception as primary_error:
        try:
            adjusted, fallback_source = cache.download(
                sym, adjust="hfq", order=("tencent_sina",)
            )
            if fallback_source != "tencent_sina":
                raise RuntimeError(f"unexpected HFQ fallback source: {fallback_source}")
            adjusted = adjusted.loc[
                pd.to_datetime(adjusted.date) >= pd.Timestamp(requested_start)
            ]
            source = "cache_tencent_sina_hfq"
        except Exception as fallback_error:
            raise RuntimeError(
                f"HFQ stock data unavailable for {sym}; primary Tencent raw × Sina HFQ "
                f"failed ({type(primary_error).__name__}: {primary_error}); "
                f"HFQ-only cache fallback failed ({type(fallback_error).__name__}: "
                f"{fallback_error}); QFQ/raw fallback was not used"
            ) from fallback_error

    ohlc = _normalise_prices(adjusted)
    if ohlc.empty:
        raise RuntimeError(f"no positive HFQ closes available for {sym}")
    source_first = pd.Timestamp(ohlc.date.iloc[0])
    ipo_in_range = source_first > pd.Timestamp(requested_start)
    if ipo_in_range:
        ohlc = ohlc.iloc[60:].reset_index(drop=True)
    if ohlc.empty:
        raise RuntimeError(f"{sym} has fewer than 60 bars after its in-range listing date")
    last = pd.Timestamp(ohlc.date.iloc[-1])
    data_version = f"vintage_{last:%Y%m%d}_tencent_sina_hfq_{factor_hash}"
    meta = {
        "first_date": str(source_first.date()),
        "n_bars": int(len(ohlc)),
        "ipo_in_range": bool(ipo_in_range),
        "fit_first_date": str(pd.Timestamp(ohlc.date.iloc[0]).date()),
        "dropped_ipo_bars": 60 if ipo_in_range else 0,
        "source": source,
    }
    return ohlc, data_version, meta


def _variant_windows(variant: str, n_bars: int) -> tuple[int, ...]:
    if variant == "stk_lite":
        return tuple(universe.WINDOWS)
    if variant == "stk_full":
        windows = (
            lppls_scan.XS_WINDOWS
            + lppls_scan.SHORT_WINDOWS
            + lppls_scan.IDX_WINDOWS
            + lppls_scan.XL_WINDOWS
        )
        return tuple(sorted({int(n) for n in windows if n <= n_bars}))
    raise ValueError(f"unknown stock variant: {variant}")


def _name_and_st(code6: str) -> tuple[str | None, bool | None]:
    if not NAMES_PATH.exists():
        return None, None
    try:
        names = json.loads(NAMES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    name = names.get(code6) if isinstance(names, dict) else None
    if name is None:
        return None, None
    return str(name), "ST" in str(name).upper()


def _eligibility(ohlc: pd.DataFrame, st: bool | None) -> dict:
    close = ohlc["close"].astype(float)
    sample = ohlc.tail(505)
    returns = close.pct_change().reindex(sample.index)
    if len(sample):
        share = float(
            ((sample.high == sample.low) & (returns.abs() >= 0.095)).sum()
            / len(sample)
        )
    else:
        share = 0.0
    degenerate = share > 0.20
    n_bars = int(len(ohlc))
    in_stats = n_bars >= 500 and not degenerate and st is not True
    if n_bars < 500:
        status = "insufficient_history"
        note = f"有效交易日 {n_bars} 少于 500，未进行拟合"
    elif degenerate and st is True:
        status = "st_degenerate"
        note = "ST 名称且一字板异常占比超过 20%；仍计算，不纳入统计"
    elif degenerate:
        status = "degenerate"
        note = "一字板异常占比超过 20%；仍计算，不纳入统计"
    elif st is True:
        status = "st"
        note = "ST 名称；仍计算，不纳入统计"
    else:
        status = "eligible"
        note = "符合统计纳入条件"
    return {
        "n_bars": n_bars,
        "status": status,
        "degenerate": bool(degenerate),
        "degenerate_share": round(share, 4),
        "st": st,
        "in_stats": bool(in_stats),
        "eligibility_note": note,
    }


def _version() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _fit_logp(ohlc: pd.DataFrame) -> pd.Series:
    return pd.Series(
        np.log(ohlc.close.to_numpy(dtype=float)),
        index=pd.DatetimeIndex(ohlc.date),
        name="log_close",
    )


def _record(
    code6: str,
    variant: str,
    asof: pd.Timestamp,
    ohlc: pd.DataFrame,
    logp: pd.Series,
    data_version: str,
    meta: dict,
    fits: pd.DataFrame,
    trust_boot: int = 0,
    procs: int | None = None,
) -> dict:
    sym = universe._sym(code6)
    derived = _derived(fits)
    rule_frame = rules(derived)
    record = build_record(
        sym,
        str(asof.date()),
        derived,
        rule_frame,
        logp.index,
        ohlc,
        data_version=data_version,
    )
    name, st = _name_and_st(code6)
    eligibility = _eligibility(ohlc, st)
    record["model_version"] = f"{record['model_version']}+{variant}"
    if name:
        record["name"] = name
    record["top"]["evidence_override"] = STOCK_EVIDENCE
    record["validation"] = []
    record["stock_meta"] = {
        "variant": variant,
        "status": eligibility["status"],
        "degenerate": eligibility["degenerate"],
        "st": eligibility["st"],
        "in_stats": eligibility["in_stats"],
        "ipo_in_range": bool(meta["ipo_in_range"]),
        "n_bars": eligibility["n_bars"],
        "degenerate_share": eligibility["degenerate_share"],
        "eligibility_note": eligibility["eligibility_note"],
        "evidence": STOCK_EVIDENCE,
        "note": STOCK_NOTE,
    }
    if trust_boot > 0 and len(fits):
        from ..lppls.trust import trust

        record["top"]["trust"] = trust(
            logp, asof, _derived(fits), b=trust_boot, procs=procs or 1
        )
    return record


def predict(
    code6: str,
    variant: str = "stk_lite",
    asof: str | None = None,
    procs: int | None = None,
    trust_boot: int = 0,
) -> dict:
    code = _validate_code(code6)
    if variant not in ("stk_lite", "stk_full"):
        raise ValueError(f"unknown stock variant: {variant}")
    ohlc, data_version, meta = load_stock(code)
    full_logp = _fit_logp(ohlc)
    cutoff = pd.Timestamp(asof).normalize() if asof is not None else full_logp.index[-1]
    available = full_logp.loc[full_logp.index <= cutoff]
    if available.empty:
        raise ValueError(f"no {code} bars on or before {cutoff.date()}")
    date = available.index[-1]
    ohlc_pit = ohlc.loc[ohlc.date <= date].reset_index(drop=True)
    eligibility = _eligibility(ohlc_pit, _name_and_st(code)[1])
    windows = _variant_windows(variant, len(available))
    if eligibility["n_bars"] < 500:
        windows = ()
    fits = _fit_pairs(available, [(date, n) for n in windows if n <= len(available)], procs)
    return _record(
        code,
        variant,
        date,
        ohlc_pit,
        full_logp,
        data_version,
        meta,
        fits,
        trust_boot=trust_boot,
        procs=procs,
    )


def _weekly_asofs(logp: pd.Series, weeks: int) -> list[pd.Timestamp]:
    if weeks < 0:
        raise ValueError("weeks must be non-negative")
    dates = logp.index
    iso = dates.isocalendar()
    calendar = pd.DataFrame(
        {"year": iso.year.to_numpy(), "week": iso.week.to_numpy(), "date": dates}
    )
    return (
        calendar.groupby(["year", "week"], sort=True).date.max().tail(weeks).tolist()
        if weeks
        else []
    )


def _add_y_std(fits: pd.DataFrame, logp: pd.Series) -> pd.DataFrame:
    out = fits.copy()
    if not len(out):
        out["y_std"] = pd.Series(dtype=float)
        return out
    lp = logp.to_numpy(dtype=float)
    positions = logp.index.get_indexer(pd.to_datetime(out.date))
    out["y_std"] = [
        float(lp[int(i) + 1 - int(n) : int(i) + 1].std())
        for i, n in zip(positions, out.n, strict=True)
    ]
    return out


def _cache_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=FIT_CACHE_COLUMNS)
    cached = pd.read_parquet(path)
    missing = set(FIT_CACHE_COLUMNS) - set(cached.columns)
    if missing:
        raise ValueError(f"stock fit cache missing columns: {sorted(missing)}")
    return cached[FIT_CACHE_COLUMNS]


def _confirmed_tops(logp: pd.Series) -> list[dict]:
    x = logp.to_numpy(dtype=float)
    indices = ps_tops(logp)
    events = []
    for i in indices:
        dd = float(np.exp(x[i + 1 : i + 127].min() - x[i]) - 1)
        events.append(
            {
                "date": str(logp.index[i].date()),
                "max_dd": round(dd, 3),
                "evidence": "after_the_fact",
            }
        )
    return events


def history(
    code6: str,
    weeks: int = 104,
    variant: str = "stk_lite",
    procs: int | None = None,
    cache_dir: Path = Path("data/stock"),
) -> dict:
    code = _validate_code(code6)
    if variant not in ("stk_lite", "stk_full"):
        raise ValueError(f"unknown stock variant: {variant}")
    ohlc, data_version, meta = load_stock(code)
    logp = _fit_logp(ohlc)
    asofs = _weekly_asofs(logp, weeks)
    windows = _variant_windows(variant, len(logp))
    code_version = _version()
    cache_path = Path(cache_dir) / code / variant / "fits.parquet"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cached = _cache_frame(cache_path)
    existing_keys = {
        (
            str(pd.Timestamp(row.asof).date()),
            int(row.n),
            str(row.data_version),
            str(row.code_version),
        )
        for row in cached.itertuples()
    }
    missing_pairs = []
    for date in asofs:
        available = logp.loc[logp.index <= date]
        if len(available) < 500:
            continue
        missing_pairs.extend(
            (date, n)
            for n in windows
            if n <= len(available)
            and (str(date.date()), int(n), data_version, code_version) not in existing_keys
        )
    new_fits = _fit_pairs(logp, missing_pairs, procs)
    if len(new_fits):
        append = new_fits[lppls_scan.COLS].copy()
        append["asof"] = pd.to_datetime(append.date).dt.normalize()
        append["data_version"] = data_version
        append["code_version"] = code_version
        if cached.empty:
            cached = append[FIT_CACHE_COLUMNS].copy()
        else:
            cached = pd.concat([cached, append[FIT_CACHE_COLUMNS]], ignore_index=True)
        cached = cached.drop_duplicates(subset=FIT_CACHE_KEY, keep="first")
        cached = cached.sort_values(["asof", "n"], kind="stable").reset_index(drop=True)
        cached.to_parquet(cache_path, index=False)

    sym = universe._sym(code)
    frames = []
    for date in asofs:
        available = logp.loc[logp.index <= date]
        key_rows = cached[
            (pd.to_datetime(cached["asof"]) == date)
            & (cached.data_version == data_version)
            & (cached.code_version == code_version)
            & (cached.n <= len(available))
        ]
        fits = _add_y_std(key_rows[lppls_scan.COLS], logp)
        derived = _derived(fits)
        rule_frame = rules(derived)
        close = float(ohlc.loc[ohlc.date == date, "close"].iloc[-1])
        frame = _history_frame(
            derived,
            rule_frame,
            date,
            logp.index,
            close,
            STOCK_EVIDENCE,
            include_scenarios=True,
        )
        frames.append(frame)

    confirmed_tops = _confirmed_tops(logp)
    tops = [{k: v for k, v in event.items() if k != "evidence"} for event in confirmed_tops]
    return {
        "symbol": sym,
        "model_version": f"prereg_v1.7_v2+{variant}",
        "evidence": STOCK_EVIDENCE,
        "rule": "每个截止日仅用此前个股拟合生成的情景区间；个股未经过样本外检验",
        "variant": variant,
        "data_version": data_version,
        "frames": frames,
        "tops": tops,
        "confirmed_tops": confirmed_tops,
        "confirmed_tops_note": "PS-15% 标签顶，需观察未来 126 个交易日后确认；事后标签，不是预测",
        "stock_meta": {
            **_eligibility(ohlc, _name_and_st(code)[1]),
            "ipo_in_range": bool(meta["ipo_in_range"]),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate per-stock LPPLS records")
    parser.add_argument("code6")
    parser.add_argument("--variant", choices=("stk_lite", "stk_full"), default="stk_lite")
    parser.add_argument("--asof")
    parser.add_argument("--history-weeks", type=int, default=0)
    parser.add_argument("--procs", type=int)
    parser.add_argument("--trust-boot", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("web/mock/data/stock"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    record = predict(
        args.code6,
        variant=args.variant,
        asof=args.asof,
        procs=args.procs,
        trust_boot=args.trust_boot,
    )
    path = args.out / f"{args.code6}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(path)
    if args.history_weeks > 0:
        history_record = history(
            args.code6,
            weeks=args.history_weeks,
            variant=args.variant,
            procs=args.procs,
        )
        history_path = args.out / f"{args.code6}_history.json"
        history_path.write_text(
            json.dumps(history_record, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8",
        )
        print(history_path)


if __name__ == "__main__":
    main()
