"""H3: test whether Markov volatility regimes improve the H2 first-touch baseline.

The regime is high, low, or unknown. H2 references include all mature outcomes;
H3 uses only known references in the test event's same regime, falling back to
H2 when fewer than 30 same-regime references are available.
"""

import argparse
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels

from research.dip import events, panel

DEFAULT_LIB_DIR = Path("/home/ubuntu/dd_study/lib_full")
DEFAULT_CACHE_DIR = Path("/home/ubuntu/dd_study/cache_all")
DEFAULT_OUT_DIR = Path("/home/ubuntu/dd_study/oos/h3")
TEST0 = "2019-01-01"
MIN_REF = 30
B = 2000
REGIME_VALUES = ("high", "low", "unknown")
REGIME_STATUSES = ("ok", "short_history", "nonconverged", "failed")
ROOT = Path(__file__).resolve().parents[2]


def _regime_label(p_hi: float | None) -> str:
    if p_hi is None or pd.isna(p_hi):
        return "unknown"
    return "high" if float(p_hi) >= 0.5 else "low"


def _h3_event(
    test_event: dict,
    reference_pool: pd.DataFrame,
    key: str,
) -> dict | None:
    outcome = test_event.get(key)
    regime = test_event.get("regime")
    if outcome is None or pd.isna(outcome) or regime not in ("high", "low"):
        return None

    reference = reference_pool[
        reference_pool[f"{key}_known"] < test_event["entry_date"]
    ]
    if len(reference) < MIN_REF:
        return None

    subset = reference[reference["regime"] == regime]
    n_ref = int(len(reference))
    n_sub = int(len(subset))
    n_ref_unknown = int((reference["regime"] == "unknown").sum())
    fallback = n_sub < MIN_REF
    observed = np.array(
        [outcome == category for category in ("U", "L", "none")],
        dtype=float,
    )
    p2 = np.array(
        [
            (reference[key] == category).mean()
            for category in ("U", "L", "none")
        ]
    )
    p3 = (
        np.array(
            [(subset[key] == category).mean() for category in ("U", "L", "none")]
        )
        if not fallback
        else p2
    )
    return {
        "test": "H3_" + key,
        "depth": test_event["depth"],
        "entry": test_event["entry_date"],
        "hi": regime == "high",
        "n_ref": n_ref,
        "n_sub": n_sub,
        "n_ref_unknown": n_ref_unknown,
        "fallback": fallback,
        "d": ((p2 - observed) ** 2).sum() - ((p3 - observed) ** 2).sum(),
    }


def _phi_cache_meta(lib_dir: Path, cache_dir: Path, syms: pd.Series) -> dict:
    manifest = json.loads((lib_dir / "manifest.json").read_text(encoding="utf-8"))
    events_path = lib_dir / manifest.get("events_file", "events.parquet")
    cache_input_lines = []
    for sym in sorted(syms.dropna().astype(str).unique()):
        name = f"{sym}.parquet"
        path = cache_dir / name
        digest = (
            hashlib.sha256(path.read_bytes()).hexdigest()
            if path.is_file()
            else "MISSING"
        )
        cache_input_lines.append(f"{name}\t{digest}")
    cache_inputs_sha256 = hashlib.sha256(
        "\n".join(cache_input_lines).encode("utf-8")
    ).hexdigest()
    panel_path = Path(panel.__file__).resolve()
    script_path = Path(__file__).resolve()
    return {
        "events_sha256": hashlib.sha256(events_path.read_bytes()).hexdigest(),
        "cache_dir": str(cache_dir.resolve()),
        "cache_inputs_sha256": cache_inputs_sha256,
        "panel_sha1": hashlib.sha1(panel_path.read_bytes()).hexdigest(),
        "oos_h3_sha1": hashlib.sha1(script_path.read_bytes()).hexdigest(),
        "statsmodels_version": statsmodels.__version__,
        "regime_seeds": list(panel.REGIME_SEEDS),
        "min_weeks": panel.REGIME_MIN_WEEKS,
    }


def _phi_cache_reusable(
    phi_path: Path, meta_path: Path, expected_meta: dict
) -> bool:
    if not phi_path.is_file() or not meta_path.is_file():
        return False
    try:
        return json.loads(meta_path.read_text(encoding="utf-8")) == expected_meta
    except (OSError, json.JSONDecodeError):
        return False


def phi(args):
    sym, dates, cache_dir = args
    try:
        data = events.load(cache_dir / f"{sym}.parquet")
        data["date"] = pd.to_datetime(data["date"])
    except Exception as exc:
        reason = f"{type(exc).__name__}: {str(exc)[:120]}"
        return [(sym, date, None, "failed", None, 0, reason) for date in dates]

    out = []
    for date in dates:
        regime_prices = data[data.date <= pd.Timestamp(date)][["date", "close"]]
        regime = panel._regime(regime_prices)
        out.append(
            (
                sym,
                date,
                regime["p_hi_filtered"],
                regime["status"],
                regime["seed"],
                regime["attempts"],
                regime["reason"],
            )
        )
    return out


def _load_or_build_phi(
    events_frame: pd.DataFrame,
    phi_path: Path,
    meta_path: Path,
    expected_meta: dict,
    cache_dir: Path,
) -> pd.DataFrame:
    if _phi_cache_reusable(phi_path, meta_path, expected_meta):
        try:
            cached = pd.read_parquet(phi_path)
            if {
                "sym",
                "sig_date",
                "p_hi",
                "status",
                "seed",
                "attempts",
                "reason",
            }.issubset(cached.columns):
                print("Reusing phi cache with matching metadata", flush=True)
                return cached
        except Exception:
            pass

    jobs = [
        (sym, sorted(group.sig_date.unique()), cache_dir)
        for sym, group in events_frame.groupby("sym")
    ]
    rows = []
    with ProcessPoolExecutor(8) as executor:
        for index, result in enumerate(executor.map(phi, jobs, chunksize=4)):
            rows += result
            if index % 200 == 0:
                print(index, len(jobs), flush=True)
    result = pd.DataFrame(
        rows,
        columns=["sym", "sig_date", "p_hi", "status", "seed", "attempts", "reason"],
    )
    result.to_parquet(phi_path, index=False)
    meta_path.write_text(
        json.dumps(expected_meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _status_counts(phi_frame: pd.DataFrame) -> dict[str, int]:
    counts = {
        status: int((phi_frame["status"] == status).sum())
        for status in REGIME_STATUSES
    }
    counts["unknown_status"] = int(
        (~phi_frame["status"].isin(REGIME_STATUSES)).sum()
    )
    return counts


def _reason_counts(phi_frame: pd.DataFrame) -> dict[str, int]:
    reasons = phi_frame.loc[
        phi_frame["status"].isin(("failed", "nonconverged")), "reason"
    ].dropna()
    counts = reasons.value_counts()
    return {
        str(reason): int(count)
        for reason, count in sorted(
            counts.items(), key=lambda item: (-item[1], str(item[0]))
        )[:10]
    }


def _aggregate_group(label: str, group: pd.DataFrame, rng: np.random.Generator) -> dict:
    months = group.month.unique()
    by_month = {
        month: group.loc[group.month == month, "d"].to_numpy() for month in months
    }
    bootstrap = [
        np.concatenate(
            [by_month[month] for month in rng.choice(months, len(months))]
        ).mean()
        for _ in range(B)
    ]
    years = group[group.year <= "2025"].groupby("year").d.mean()
    low, high = np.quantile(bootstrap, [0.05, 0.95])
    n_ref = int(group.n_ref.sum())
    n_ref_unknown = int(group.n_ref_unknown.sum())
    return {
        "pool": label,
        "test": group.test.iloc[0],
        "depth": group.depth.iloc[0],
        "n": int(len(group)),
        "share_hi": float(group.hi.mean()),
        "n_months": int(len(months)),
        "delta": float(group.d.mean()),
        "ci90": [float(low), float(high)],
        "years_pos": int((years > 0).sum()),
        "years": int(len(years)),
        "passed": bool(low > 0 and (years > 0).sum() >= 5),
        "n_fallback": int(group.fallback.sum()),
        "n_ref_unknown": n_ref_unknown,
        "n_ref_total": n_ref,
        "n_ref_unknown_share": (
            float(n_ref_unknown / n_ref) if n_ref else None
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="Run the H3 Markov-regime OOS test")
    parser.add_argument("--lib-dir", type=Path, default=DEFAULT_LIB_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((args.lib_dir / "manifest.json").read_text(encoding="utf-8"))
    events_path = args.lib_dir / manifest.get("events_file", "events.parquet")
    events_frame = pd.read_parquet(events_path)
    phi_path = args.out_dir / "phi.parquet"
    meta_path = args.out_dir / "phi.meta.json"
    cache_meta = _phi_cache_meta(args.lib_dir, args.cache_dir, events_frame["sym"])
    phi_frame = _load_or_build_phi(
        events_frame,
        phi_path,
        meta_path,
        cache_meta,
        args.cache_dir,
    )
    status_counts = _status_counts(phi_frame)
    reason_counts = _reason_counts(phi_frame)
    print("phi status counts", json.dumps(status_counts, ensure_ascii=False), flush=True)
    print("phi reason counts", json.dumps(reason_counts, ensure_ascii=False), flush=True)

    events_frame = events_frame.merge(
        phi_frame, on=["sym", "sig_date"], how="left"
    )
    events_frame["regime"] = events_frame["p_hi"].map(_regime_label)
    events_frame.loc[
        ~events_frame["status"].isin(REGIME_STATUSES), "status"
    ] = "failed"
    pools = {
        "全市场": pd.Series(True, index=events_frame.index),
        "剔除2015-16": ~events_frame.sig_date.str[:4].isin(["2015", "2016"]),
    }
    test_events = events_frame[
        (events_frame.entry_date >= TEST0)
        & events_frame.regime.isin(("high", "low"))
    ]
    results = []
    rng = np.random.default_rng(20261104)
    for label, mask in pools.items():
        pool = events_frame[mask]
        rows = []
        for test_event in test_events.itertuples():
            references = pool[pool.depth == test_event.depth]
            event = test_event._asdict()
            for key in ("fh60", "fh120"):
                row = _h3_event(event, references, key)
                if row is not None:
                    rows.append(row)
        frame = pd.DataFrame(rows)
        if frame.empty:
            continue
        frame["month"] = frame.entry.str[:7]
        frame["year"] = frame.entry.str[:4]
        for _, group in frame.groupby(["test", "depth"]):
            results.append(_aggregate_group(label, group, rng))

    phi_missing = int(events_frame.p_hi.isna().sum())
    result_path = args.out_dir / "h3.json"
    result_path.write_text(
        json.dumps(
            {
                "definition": __doc__,
                "lib": manifest,
                "min_ref": MIN_REF,
                "B": B,
                "phi_missing": phi_missing,
                "phi_status_counts": status_counts,
                "phi_reason_counts": reason_counts,
                "phi_meta": cache_meta,
                "results": results,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(pd.DataFrame(results).to_string(index=False))


if __name__ == "__main__":
    main()
