"""Deterministic re-filtering of saved SK Hynix fits; never fits or labels prices.

The source's ``osc`` is ALREADY in full cycles. Its original raw_clean threshold
is 1.25, not the repository's legacy half-phase threshold 2.5. The box family
below is an added-gate experiment, not a reproduction of lit1 or FCO filtering.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from research.lppls.oscillations import OSC_UNITS_VERSION, future_oscillations

KEY = ["endpoint_pos", "window"]
SEED_KEY = KEY + ["seed"]
BOOL_COLUMNS = ["ok", "boundary", "right_censored", "b_sign_ok", "raw_clean"]
NUMERIC_COLUMNS = ["objective", "tc_offset", "m", "omega", "B", "r2", "osc", "damping"]
REQUIRED = set(SEED_KEY + BOOL_COLUMNS + NUMERIC_COLUMNS + [
    "endpoint_time_iso", "created_at_utc", "series_kind", "transform", "window_family",
])
RULES = (
    ("source_raw_clean", "source_cycles_1_25", 1.25),
    ("source_raw_clean", "source_cycles_1_5", 1.5),
    ("source_raw_clean", "source_cycles_2_5", 2.5),
    ("box_future_added_gate", "box_future_no_N", None),
    ("box_future_added_gate", "box_future_cycles_2_5_over_pi", 2.5 / np.pi),
    ("box_future_added_gate", "box_future_cycles_1_5", 1.5),
    ("box_future_added_gate", "box_future_cycles_2_5", 2.5),
)
SCALE_NAMES = ("short", "mid", "long", "macro")
EVENT_REASON = (
    "No pre-existing complete event ledger or verified publication timestamps are "
    "part of these inputs. No labels are generated. Fit retention and tc_offset "
    "are not event recall, actual warning lead, or ex-ante forecast accuracy."
)


def _bool_column(s: pd.Series, name: str) -> pd.Series:
    if s.isna().any():
        raise ValueError(f"Missing boolean values: {name}")
    values = s.astype(str).str.lower()
    if not values.isin(["true", "false"]).all():
        raise ValueError(f"Non-boolean values: {name}")
    return values.eq("true")


def _prepare(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    missing = REQUIRED - set(frame.columns)
    if missing:
        raise ValueError(f"{name}: missing required columns {sorted(missing)}")
    d = frame.copy()
    for column in BOOL_COLUMNS:
        d[column] = _bool_column(d[column], f"{name}.{column}")
    for column in SEED_KEY + NUMERIC_COLUMNS:
        d[column] = pd.to_numeric(d[column], errors="raise")
        if d[column].isna().any():
            raise ValueError(f"{name}: missing numeric values in {column}")
    for column in SEED_KEY:
        if not np.isfinite(d[column]).all() or not (d[column] == np.floor(d[column])).all():
            raise ValueError(f"{name}: invalid integer {column}")
        d[column] = d[column].astype(int)
    if not d.ok.all():
        raise ValueError(f"{name}: incomplete/failed fits; cannot silently shrink denominator")
    if not np.isfinite(d[NUMERIC_COLUMNS].drop(columns="damping").to_numpy()).all():
        raise ValueError(f"{name}: nonfinite numerical fit fields")
    if d.duplicated(SEED_KEY).any():
        raise ValueError(f"{name}: duplicate endpoint/window/seed")
    if not d.series_kind.eq("daily_top").all() or not d["transform"].eq("top_log").all():
        raise ValueError(f"{name}: only daily_top/top_log source inputs are supported")
    for column in ("endpoint_time_iso", "created_at_utc"):
        values = pd.to_datetime(d[column], errors="raise", utc=True)
        if values.isna().any():
            raise ValueError(f"{name}: missing dates in {column}")
    if d.groupby("endpoint_pos").endpoint_time_iso.nunique().ne(1).any():
        raise ValueError(f"{name}: conflicting dates for an endpoint")
    if d.groupby("endpoint_time_iso").endpoint_pos.nunique().ne(1).any():
        raise ValueError(f"{name}: conflicting endpoints for a date")
    expected_family = np.select(
        [d.window <= 75, d.window <= 150, d.window <= 260],
        ["short", "mid", "long"], default="macro",
    )
    if not np.array_equal(d.window_family.to_numpy(), expected_family):
        raise ValueError(f"{name}: source window_family does not match source boundaries")
    d["osc_cycles"], d["osc_cycles_status"] = future_oscillations(
        tc=d.window.to_numpy() - 1 + d.tc_offset.to_numpy(),
        t2=d.window.to_numpy() - 1, omega=d.omega.to_numpy(),
    )
    if not d.osc_cycles_status.eq("ok").all():
        raise ValueError(f"{name}: source includes invalid/nonfuture tc; cannot count as advance fits")
    if not np.allclose(d.osc, d.osc_cycles, rtol=1e-10, atol=1e-12):
        raise ValueError(f"{name}: source osc is not consistent with full cycles")
    if not np.array_equal(d.b_sign_ok.to_numpy(), (d.B < 0).to_numpy()):
        raise ValueError(f"{name}: b_sign_ok mismatch")
    source_base = source_nonosc_mask(d)
    # Reproducing the source decision must use its saved full-cycle value.
    # Equivalent log/log1p formulas can differ by an ULP at the exact threshold.
    if not np.array_equal((source_base & (d.osc >= 1.25)).to_numpy(), d.raw_clean.to_numpy()):
        raise ValueError(f"{name}: original raw_clean cannot be reproduced")
    d["source_cycle_conversion_gate_disagreement"] = (d.osc >= 1.25) != (d.osc_cycles >= 1.25)
    return d


def source_nonosc_mask(d: pd.DataFrame) -> pd.Series:
    # Source lppls_v47_local_fit.py:299-305 explicitly requires finite damping;
    # +inf is rejected despite satisfying the numerical comparison >= 0.5.
    return ((d.B < 0) & ~d.boundary & ~d.right_censored
            & np.isfinite(d.damping) & (d.damping >= 0.5)
            & np.isfinite(d.r2) & (d.r2 >= 0.8))


def validate_inputs(all_fits: pd.DataFrame, best_fits: pd.DataFrame, metadata: dict):
    """Require the declared complete Cartesian grid, and pre-filter objective winner."""
    grids = {}
    for field, column in (("asof_endpoint_positions", "endpoint_pos"), ("windows", "window"), ("seeds", "seed")):
        values = metadata.get(field)
        if not isinstance(values, list) or not values or len(set(values)) != len(values):
            raise ValueError(f"Metadata requires unique nonempty {field}")
        if any(not isinstance(v, int) or isinstance(v, bool) for v in values):
            raise ValueError(f"Metadata requires integer {field}")
        grids[column] = sorted(values)
    all_d, best = _prepare(all_fits, "all_fits"), _prepare(best_fits, "best_fits")
    expected = pd.MultiIndex.from_product([grids[k] for k in SEED_KEY], names=SEED_KEY)
    actual = pd.MultiIndex.from_frame(all_d[SEED_KEY])
    if len(actual) != len(expected) or not actual.sort_values().equals(expected.sort_values()):
        raise ValueError("all_fits: incomplete or unexpected endpoint/window/seed grid")
    expected_best = pd.MultiIndex.from_product([grids[k] for k in KEY], names=KEY)
    actual_best = pd.MultiIndex.from_frame(best[KEY])
    if best.duplicated(KEY).any() or not actual_best.sort_values().equals(expected_best.sort_values()):
        raise ValueError("best_fits: incomplete or duplicated endpoint/window grid")
    source = all_d.set_index(SEED_KEY).loc[pd.MultiIndex.from_frame(best[SEED_KEY])].reset_index()
    best = best.reset_index(drop=True)
    # Compare every shared original column: a best record cannot silently borrow
    # a different seed's parameters, flags, or objective after filtering.
    for column in sorted(set(all_fits.columns) & set(best_fits.columns)):
        if pd.api.types.is_numeric_dtype(source[column]) and not pd.api.types.is_bool_dtype(source[column]):
            same = np.isclose(source[column], best[column], rtol=1e-12, atol=1e-12, equal_nan=True)
        else:
            same = source[column].fillna("<NA>").astype(str).eq(best[column].fillna("<NA>").astype(str))
        if not np.all(same):
            raise ValueError(f"best_fits: selected seed row differs from all_fits in {column}")
    minimum = all_d.groupby(KEY).objective.min().reindex(pd.MultiIndex.from_frame(best[KEY])).to_numpy()
    if not np.array_equal(source.objective.to_numpy(), minimum):
        raise ValueError("best_fits: seed is not the objective minimum before filtering")
    dates = best.groupby("endpoint_pos").endpoint_time_iso.first().sort_index()
    if not pd.to_datetime(dates, utc=True).is_monotonic_increasing:
        raise ValueError("Endpoint dates must increase with endpoint position")
    return all_d, best.sort_values(KEY).reset_index(drop=True), grids


def analyze(all_fits: pd.DataFrame, best_fits: pd.DataFrame, metadata: dict):
    all_d, best, grids = validate_inputs(all_fits, best_fits, metadata)
    source_base = source_nonosc_mask(best)
    box_base = ((best.B < 0) & best.m.between(0.1, 0.9) & best.omega.between(6, 13)
                & (best.tc_offset > 0) & (best.tc_offset <= 90))
    baselines = {"source_raw_clean": source_base & (best.osc >= 1.25),
                 "box_future_added_gate": box_base}
    detail, dates, summary_rules = [], [], []
    for family, rule, threshold in RULES:
        base = source_base if family == "source_raw_clean" else box_base
        passed = base if threshold is None else base & (best.osc_cycles >= threshold)
        if rule == "source_cycles_1_25":
            passed = baselines["source_raw_clean"]
        original = baselines[family]
        part = best[[*SEED_KEY, "endpoint_time_iso", "window_family", "objective", "tc_offset",
                     "m", "omega", "B", "damping", "r2", "boundary", "right_censored",
                     "osc", "osc_cycles", "osc_cycles_status", "source_cycle_conversion_gate_disagreement"]].copy()
        part["family"], part["rule"], part["minimum_cycles"] = family, rule, threshold
        part["passed"], part["baseline_passed"] = passed, original
        part["retained_vs_baseline"], part["lost_vs_baseline"] = passed & original, original & ~passed
        part["gained_vs_baseline"] = passed & ~original
        part["tc_forward_at_least_5_bars"] = best.tc_offset >= 5
        part["next_bar_action_forward_at_least_5_bars"] = best.tc_offset - 1 >= 5
        # Algebraic upper bound on predicted tc distance, not actual event lead.
        part["gate_max_tc_offset_bars"] = (np.nan if threshold is None else
            (best.window - 1) / np.expm1(2 * np.pi * threshold / best.omega))
        detail.append(part)
        previous = None
        for endpoint, group in part.groupby("endpoint_pos", sort=True):
            selected = group[group.passed]
            baseline = group[group.baseline_passed]
            n = len(selected)
            quantiles = selected.tc_offset.quantile([0.2, 0.5, 0.8]).to_numpy() if n else np.full(3, np.nan)
            row = dict(family=family, rule=rule, minimum_cycles=threshold, endpoint_pos=int(endpoint),
                       endpoint_time_iso=group.endpoint_time_iso.iloc[0], n_windows=len(group),
                       n_pass=n, fraction_pass=n / len(group), n_baseline_pass=len(baseline),
                       n_retained=int(group.retained_vs_baseline.sum()), n_lost=int(group.lost_vs_baseline.sum()),
                       n_gained=int(group.gained_vs_baseline.sum()),
                       q20_tc_offset=quantiles[0], q50_tc_offset=quantiles[1], q80_tc_offset=quantiles[2],
                       q20_q80_width_bars=quantiles[2] - quantiles[0],
                       has_descriptive_interval=n >= 3,
                       descriptive_interval_width_le_10=bool(n >= 3 and quantiles[2] - quantiles[0] <= 10),
                       empty_after_filter=n == 0,
                       previous_endpoint_pos=None, previous_endpoint_gap_bars=None,
                       n_common_retained_previous=0, median_common_tc_offset_change=np.nan,
                       median_common_tc_absolute_bar_change=np.nan)
            for name, condition in (("tc_forward_ge_5", group.tc_forward_at_least_5_bars),
                                    ("action_forward_ge_5", group.next_bar_action_forward_at_least_5_bars)):
                row[f"n_pass_{name}"] = int((group.passed & condition).sum())
                row[f"n_retained_{name}"] = int((group.retained_vs_baseline & condition).sum())
                row[f"n_lost_{name}"] = int((group.lost_vs_baseline & condition).sum())
            for scale in SCALE_NAMES:
                row[f"n_windows_{scale}"] = int(group.window_family.eq(scale).sum())
                row[f"n_pass_{scale}"] = int(selected.window_family.eq(scale).sum())
            if previous is not None:
                prev_endpoint, prev_selected = previous
                common = selected.set_index("window").tc_offset.to_frame("now").join(
                    prev_selected.set_index("window").tc_offset.rename("previous"), how="inner")
                row.update(previous_endpoint_pos=prev_endpoint,
                           previous_endpoint_gap_bars=int(endpoint - prev_endpoint),
                           n_common_retained_previous=len(common))
                if len(common):
                    difference = common.now - common.previous
                    row["median_common_tc_offset_change"] = float(difference.median())
                    row["median_common_tc_absolute_bar_change"] = float((difference + endpoint - prev_endpoint).median())
            previous = (int(endpoint), selected)
            dates.append(row)
        report = dict(family=family, rule=rule, minimum_cycles=threshold, n_windows=len(part),
                      n_pass=int(passed.sum()), fraction_pass=float(passed.mean()),
                      n_baseline_pass=int(original.sum()), n_retained=int((passed & original).sum()),
                      n_lost=int((original & ~passed).sum()), n_gained=int((passed & ~original).sum()),
                      n_asof=len(grids["endpoint_pos"]),
                      n_empty_asof=sum(r["empty_after_filter"] for r in dates if r["rule"] == rule),
                      n_descriptive_intervals_width_le_10=sum(r["descriptive_interval_width_le_10"] for r in dates if r["rule"] == rule))
        for name, flag in (("tc_forward_ge_5", part.tc_forward_at_least_5_bars),
                           ("action_forward_ge_5", part.next_bar_action_forward_at_least_5_bars)):
            report[f"n_pass_{name}"] = int((passed & flag).sum())
            report[f"n_retained_{name}"] = int((passed & original & flag).sum())
            report[f"n_lost_{name}"] = int((original & ~passed & flag).sum())
        summary_rules.append(report)
    summary = {
        "status": "VERIFIED_DETERMINISTIC_REFILTER_ONLY", "osc_units_version": OSC_UNITS_VERSION,
        "source_osc_unit": "full_cycles", "source_original_threshold_cycles": 1.25,
        "source_baseline_comparison": "saved source osc >= 1.25; never reconstructed log1p for original decision",
        "source_conversion_disagreements": {
            "all_seed_gate_only": int(all_d.source_cycle_conversion_gate_disagreement.sum()),
            "all_seed_after_nonosc_mask": int((source_nonosc_mask(all_d) & all_d.source_cycle_conversion_gate_disagreement).sum()),
            "best_gate_only": int(best.source_cycle_conversion_gate_disagreement.sum()),
            "best_after_nonosc_mask": int((source_base & best.source_cycle_conversion_gate_disagreement).sum()),
            "meaning": "Saved source osc >=1.25 differs from recomputed canonical cycles >=1.25 at floating-point boundaries; source baseline always retains saved decision.",
        },
        "source_raw_clean_reproduced_all_seed_rows": len(all_d),
        "best_selected_before_filtering": True,
        "grid": {"n_asof": len(grids["endpoint_pos"]), "n_windows_per_asof": len(grids["window"]),
                 "n_seeds_per_window": len(grids["seed"]), "all_seed_rows": len(all_d), "best_rows": len(best)},
        "event_recall": None, "event_miss_rate": None, "actual_warning_lead": None,
        "event_metrics_status": "NOT_ESTABLISHED", "event_metrics_reason": EVENT_REASON,
        "rules": summary_rules,
        "interpretation": [
            "Each endpoint/window contributes one objective-best fit; seeds are optimizer restarts, not independent votes.",
            "All as-of rows remain, including zero-pass rows. Confidence denominator is the fixed window grid.",
            "Source raw_clean has its own 1.25-cycle baseline. Box+N is an added-gate experiment, not lit1 reproduction.",
            "The source baseline compares the saved osc value exactly; new 1.5/2.5-cycle rules use canonical recomputation.",
            "Unconditional cycle gates only; no |C/B| amplitude exemption is evaluated.",
            "tc_offset and next-bar tc_offset-1 are mechanical predicted distances, not realized warning lead.",
            "q20/q50/q80 are unweighted window-fit quantiles, not the source cluster algorithm or calibrated intervals.",
            "Width<=10 summaries require at least 3 retained window fits; overlapping windows are dependent.",
            "Adjacent-asof changes use only windows surviving at both endpoints and have survivor bias; gaps vary.",
            "No label construction, optimizer run, prices download, event scoring, or threshold selection occurs.",
            "Local historical results have no independently verified as-of publication lineage and are not prospective evidence.",
        ],
    }
    return summary, pd.DataFrame(dates), pd.concat(detail, ignore_index=True)


def file_record(path: Path) -> dict:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    stat = path.stat()
    return {"path": str(path.resolve()), "sha256": h.hexdigest(), "bytes": stat.st_size,
            "mtime_utc": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()}


def run(all_path: Path, best_path: Path, metadata_path: Path, output: Path, source_script: Path | None = None):
    if output.exists():
        raise ValueError("Output already exists: preserve evidence and choose a new directory")
    paths = {"all_seed_fits": all_path, "best_by_window": best_path, "run_metadata": metadata_path}
    paths["refilter_tool"] = Path(__file__)
    paths["oscillation_unit_api"] = Path(future_oscillations.__code__.co_filename)
    if source_script is not None:
        paths["source_script"] = source_script
    before = {name: file_record(path) for name, path in paths.items()}
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    all_fits = pd.read_csv(all_path, float_precision="round_trip")
    best = pd.read_csv(best_path, float_precision="round_trip")
    summary, asof, fit = analyze(all_fits, best, metadata)
    after = {name: file_record(path) for name, path in paths.items()}
    if before != after:
        raise ValueError("Input changed while analyzing; no evidence output written")
    manifest = {"created_at_utc": datetime.now(UTC).isoformat(), "inputs": before,
                "implementation_versions": {"python": platform.python_version(), "numpy": np.__version__,
                                            "pandas": pd.__version__, "osc_units_version": OSC_UNITS_VERSION,
                                            "input_float_parsing": "pandas float_precision=round_trip"},
                "source": "User-provided local SK Hynix daily-top historical saved fits",
                "input_metadata": metadata, "parameters": {
                    "rules": [{"family": f, "rule": r, "minimum_cycles": t} for f, r, t in RULES],
                    "minimum_windows_descriptive_interval": 3, "quantiles": [0.2, 0.5, 0.8],
                    "next_action_assumption": "next observed trading bar; no execution-time verification",
                    "source_window_families": {"short": "<=75", "mid": "76..150", "long": "151..260", "macro": ">260"},
                }, "sample_boundaries": {
                    "asof_first": str(best.endpoint_time_iso.min()), "asof_last": str(best.endpoint_time_iso.max()),
                    "fit_created_first": str(all_fits.created_at_utc.min()), "fit_created_last": str(all_fits.created_at_utc.max()),
                    "endpoint_positions": sorted(best.endpoint_pos.unique().tolist()),
                    "windows": sorted(best.window.unique().tolist()), "seeds": sorted(all_fits.seed.unique().tolist()),
                }, "evidence_boundary": EVENT_REASON,
                "timestamp_caveat": "Fit timestamps and file mtimes do not prove original forecast publication or strict point-in-time data."}
    output.mkdir(parents=True, exist_ok=False)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (output / "input_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    asof.to_csv(output / "per_asof.csv", index=False)
    fit.to_csv(output / "per_fit.csv", index=False)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-fits", type=Path, required=True)
    parser.add_argument("--best-fits", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--source-script", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = run(args.all_fits, args.best_fits, args.metadata, args.out, args.source_script)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(2, f"Refilter refused: {exc}\n")
    print(json.dumps({"status": summary["status"], "output": str(args.out), "grid": summary["grid"]}))


if __name__ == "__main__":
    main()
