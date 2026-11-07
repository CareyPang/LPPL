"""Re-filter stored repository fits against existing *proxy* event dates only.

This is a development-sample sensitivity audit, not fitting or a fresh backtest
of published forecasts. main events are old positive-label-segment end + one
session proxies (research/eval/original_standard.py:top_dates), NOT the raw
consensus peak ledger. No optimizer, labels, prices, or original results change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from research.lppls.oscillations import OSC_UNITS_VERSION, compare_cycle_thresholds

SYMBOLS = ("sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006")
SCALES = {"6-12m": (127, 252), "12-24m": (253, 504)}
ARMS = (
    "box_future_no_N", "box_future_legacy_half_phase_2_5",
    "box_future_cycles_1_5", "box_future_cycles_2_5",
)
REFERENCE = ARMS[1]
HORIZONS = (60, 120)
Q = .05
DEV_START, DEV_END = pd.Timestamp("2000-01-01"), pd.Timestamp("2018-12-31")
WINDOWS = np.arange(125, 751, 5)
REQUIRED = {"date", "n", "tc", "m", "w", "B"}
LABEL_SOURCE = "existing_main_segment_end_plus_one_session_proxy"


def calendar(frame: pd.DataFrame) -> pd.DatetimeIndex:
    dates = pd.DatetimeIndex(pd.to_datetime(frame["date"], errors="raise"))
    if dates.hasnans or not dates.is_unique or not dates.is_monotonic_increasing:
        raise ValueError("price calendar must contain unique, sorted, nonmissing dates")
    return dates


def prepare(scan: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED - set(scan)
    if missing:
        raise ValueError(f"stored scan missing columns: {sorted(missing)}")
    d = scan.copy()
    d["date"] = pd.to_datetime(d.date, errors="raise")
    if d.date.isna().any():
        raise ValueError("scan dates must not be missing")
    for key in REQUIRED - {"date"}:
        d[key] = pd.to_numeric(d[key], errors="raise")
    if not np.isfinite(d.n).all() or (d.n < 2).any() or (d.n != np.floor(d.n)).any():
        raise ValueError("window lengths must be finite integers >= 2")
    if d.duplicated(["date", "n"]).any():
        raise ValueError("duplicate date/window rows: original best-fit selection must be preserved")
    d["ahead"] = d.tc - (d.n - 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        half = d.w / 2 * np.log(np.abs(d.tc) / np.maximum(np.abs(d.ahead), 1e-3))
    gates = compare_cycle_thresholds(d.tc, d.w, t2=d.n - 1, legacy_half_phase=half)
    base = (np.isfinite(d[["tc", "m", "w", "B"]]).all(axis=1) & (d.B < 0)
            & d.m.between(.1, .9) & d.w.between(6, 13) & (d.ahead > 0) & (d.ahead <= 90))
    d[ARMS[0]] = base
    d[ARMS[1]] = base & gates["legacy"]
    d[ARMS[2]] = base & gates["cycles_1_5"]
    d[ARMS[3]] = base & gates["cycles_2_5"]
    d["osc_cycles"] = gates["osc_cycles"]
    d["osc_cycles_status"] = gates["osc_cycles_status"]
    return d


def fit_diagnostics(scan):
    """Search-domain diagnostics on all input rows, not evidence of accuracy."""
    d = prepare(scan)
    base = d[ARMS[0]]
    return dict(
        future_box_count=int(base.sum()),
        min_osc_cycles_future_box=float(d.loc[base, "osc_cycles"].min()) if base.any() else None,
        max_h_over_span_future_box=float((d.loc[base, "ahead"] / (d.loc[base, "n"] - 1)).max())
        if base.any() else None,
        no_N_vs_legacy_mask_disagreement=int((d[ARMS[0]] != d[ARMS[1]]).sum()),
        no_N_vs_cycles_1_5_mask_disagreement=int((d[ARMS[0]] != d[ARMS[2]]).sum()),
        legacy_vs_cycles_1_5_mask_disagreement=int((d[ARMS[1]] != d[ARMS[2]]).sum()),
        cycles_2_5_not_subset_of_legacy=int((d[ARMS[3]] & ~d[ARMS[1]]).sum()),
        analytic_minimum_if_w_ge_6_and_h_le_0_2_span=float(6 / (2 * np.pi) * np.log(6)),
    )


def expected_windows(dates, global_dates, date, lo, hi):
    """Reproduce original history/gap eligibility, without fitting anything."""
    pos = dates.get_indexer([date])[0]
    if pos < 0:
        return set()
    windows = WINDOWS[(WINDOWS >= lo) & (WINDOWS <= hi) & (WINDOWS <= pos + 1)]
    end = global_dates.get_indexer([date])[0]
    expected = set()
    for n in windows:
        start = global_dates.get_indexer([dates[pos + 1 - n]])[0]
        n_calendar = end - start + 1 if start >= 0 and end >= 0 else n
        if n >= .9 * n_calendar:
            expected.add(int(n))
    return expected


def aggregate_asofs(scan, dates, global_dates, symbol):
    """Include zero-pass and missing scheduled as-of rows; never shrink denominator."""
    d = prepare(scan)
    d = d[d.date.between(DEV_START, DEV_END)]
    scheduled = global_dates[::5].intersection(dates)
    scheduled = scheduled[(scheduled >= DEV_START) & (scheduled <= DEV_END)]
    all_dates = scheduled.union(pd.DatetimeIndex(d.date.unique())).sort_values()
    schedule_set = set(scheduled)
    groups = {date: frame for date, frame in d.groupby("date", sort=False)}
    empty = d.iloc[:0]
    rows = []
    for date in all_dates:
        group = groups.get(date, empty)
        position = dates.get_indexer([date])[0]
        for scale, (lo, hi) in SCALES.items():
            within = group[group.n.between(lo, hi)]
            expected = expected_windows(dates, global_dates, date, lo, hi)
            actual = set(within.n.astype(int))
            if position < 0:
                status = "unknown_price_date"
            elif date not in schedule_set:
                status = "off_original_schedule"
            elif not expected:
                status = "insufficient_window_history"
            elif not len(within):
                status = "missing_scan"
            elif actual != expected:
                status = "incomplete_window_grid"
            else:
                status = "ok"
            for arm in ARMS:
                accepted = within.loc[within[arm], "ahead"].to_numpy(float)
                fraction = len(accepted) / len(within) if len(within) else np.nan
                low, high = np.quantile(accepted, [.2, .8]) if len(accepted) else (np.nan, np.nan)
                rows.append(dict(
                    symbol=symbol, date=date, position=int(position), scale=scale, arm=arm,
                    scheduled=date in schedule_set, status=status, expected_windows=len(expected),
                    stored_windows=len(within), accepted_windows=len(accepted), fraction=fraction,
                    missing_windows=";".join(map(str, sorted(expected - actual))),
                    unexpected_windows=";".join(map(str, sorted(actual - expected))),
                    alarm=bool(status == "ok" and fraction >= Q),
                    observed_fraction_alarm=bool(np.isfinite(fraction) and fraction >= Q),
                    tc_q20=low, tc_q80=high, tc_width=high - low,
                ))
    return pd.DataFrame(rows)


def evaluate_events(asofs, event_dates, dates, symbol):
    """One event vote per arm/scale/H, always using its FIRST alarm in that H."""
    rows = []
    event_dates = pd.DatetimeIndex(pd.to_datetime(event_dates, errors="raise"))
    if event_dates.hasnans or not event_dates.is_unique:
        raise ValueError("proxy event dates must be nonmissing and unique per symbol")
    for scale in SCALES:
        for arm in ARMS:
            a = asofs[(asofs.scale == scale) & (asofs.arm == arm)]
            a = a[a.scheduled & (a.position >= 0)].sort_values("date")
            for horizon in HORIZONS:
                for event in event_dates:
                    event_pos = dates.get_indexer([event])[0]
                    candidate = a[(a.position >= event_pos - horizon) & (a.position < event_pos)]
                    reasons = []
                    if event_pos < 0:
                        reasons.append("unknown_event_date")
                    elif not DEV_START <= event <= DEV_END:
                        reasons.append("event_outside_development_period")
                    elif event_pos < horizon or dates[event_pos - horizon] < DEV_START:
                        reasons.append("incomplete_H_lookback")
                    if candidate.empty:
                        reasons.append("no_scheduled_asof")
                    else:
                        if candidate.status.eq("insufficient_window_history").any():
                            reasons.append("insufficient_window_history_in_H")
                        if (~candidate.status.isin(["ok", "insufficient_window_history"])).any():
                            reasons.append("missing_or_invalid_scan_coverage")
                    eligible = not reasons
                    alarms = candidate[candidate.alarm]
                    first = alarms.iloc[0] if len(alarms) else None
                    observed_hit = first is not None
                    lead, actionable, execution = np.nan, np.nan, pd.NaT
                    q20, q80, width, covers, support = np.nan, np.nan, np.nan, False, 0
                    if first is not None and event_pos >= 0:
                        alarm_pos = int(first.position)
                        lead = event_pos - alarm_pos
                        actionable = event_pos - (alarm_pos + 1)
                        execution = dates[alarm_pos + 1]
                        q20, q80, width = first.tc_q20, first.tc_q80, first.tc_width
                        support = int(first.accepted_windows)
                        covers = bool(q20 <= lead <= q80)
                    rows.append(dict(
                        symbol=symbol, scale=scale, arm=arm, H=horizon, event=event,
                        event_position=int(event_pos), label_source=LABEL_SOURCE,
                        status="ok" if eligible else ";".join(reasons), evaluable=eligible,
                        scheduled_asofs=len(candidate),
                        unavailable_asofs=int(candidate.status.ne("ok").sum()),
                        observed_hit=observed_hit, hit=observed_hit if eligible else None,
                        first_alarm=first.date if first is not None else pd.NaT,
                        execution_date=execution, first_alarm_lead=lead,
                        actionable_lead=actionable, tc_q20=q20, tc_q80=q80, tc_width=width,
                        first_alarm_accepted_windows=support,
                        first_interval_covers_proxy=covers if observed_hit else None,
                        hit_actionable_5=bool(observed_hit and actionable >= 5) if eligible else None,
                        joint_hit=bool(observed_hit and support >= 3 and actionable >= 5 and width <= 10 and covers)
                        if eligible else None,
                    ))
    return pd.DataFrame(rows)


def evaluate_alarms(asofs, event_dates, dates):
    """Alarm-as-of false alarm rate, with an entirely observed future H window."""
    event_positions = dates.get_indexer(pd.DatetimeIndex(pd.to_datetime(event_dates)))
    unknown_events = bool((event_positions < 0).any())
    event_positions = event_positions[event_positions >= 0]
    rows = []
    for row in asofs[asofs.alarm].itertuples(index=False):
        for horizon in HORIZONS:
            end = row.position + horizon
            status = "ok"
            if unknown_events:
                status = "unknown_event_date_in_ledger"
            elif end >= len(dates) or dates[end] > DEV_END:
                status = "incomplete_future_H"
            future = event_positions[(event_positions > row.position) & (event_positions <= end)]
            rows.append(dict(
                symbol=row.symbol, scale=row.scale, arm=row.arm, H=horizon, date=row.date,
                status=status, evaluable=status == "ok", future_proxy_events=len(future),
                false_alarm=bool(len(future) == 0) if status == "ok" else None,
            ))
    return pd.DataFrame(rows, columns=["symbol", "scale", "arm", "H", "date", "status",
                                      "evaluable", "future_proxy_events", "false_alarm"])


def summaries(asofs, events, alarms):
    rows = []
    groups = [(symbol, asofs[asofs.symbol == symbol], events[events.symbol == symbol],
               alarms[alarms.symbol == symbol]) for symbol in sorted(asofs.symbol.unique())]
    groups.append(("ALL", asofs, events, alarms))
    for symbol, a, e, f in groups:
        for scale in SCALES:
            for arm in ARMS:
                aa = a[(a.scale == scale) & (a.arm == arm)]
                for horizon in HORIZONS:
                    ee = e[(e.scale == scale) & (e.arm == arm) & (e.H == horizon)]
                    ff = f[(f.scale == scale) & (f.arm == arm) & (f.H == horizon)]
                    valid = ee[ee.evaluable]
                    hit = valid[valid.hit.eq(True)]
                    valid_alarm = ff[ff.evaluable]
                    denominator = len(valid)
                    n_hit, n_lead5, n_joint = (int(valid[c].eq(True).sum())
                                               for c in ("hit", "hit_actionable_5", "joint_hit"))
                    n_false = int(valid_alarm.false_alarm.eq(True).sum())
                    rows.append(dict(
                        symbol=symbol, scale=scale, arm=arm, H=horizon, q=Q,
                        n_events=len(ee), n_evaluable=denominator,
                        n_not_evaluable=len(ee) - denominator,
                        n_hit=n_hit, n_missed=denominator - n_hit,
                        recall=n_hit / denominator if denominator else np.nan,
                        n_actionable_5=n_lead5, n_missed_actionable_5=denominator - n_lead5,
                        recall_actionable_5=n_lead5 / denominator if denominator else np.nan,
                        n_joint=n_joint, joint_recall=n_joint / denominator if denominator else np.nan,
                        n_first_alarm_lt3_windows=int((hit.first_alarm_accepted_windows < 3).sum()),
                        first_alarm_lead_median=hit.first_alarm_lead.median(),
                        actionable_lead_median=hit.actionable_lead.median(),
                        n_alarm_asofs_evaluable=len(valid_alarm),
                        n_alarm_asofs_not_evaluable=len(ff) - len(valid_alarm),
                        n_false_alarm_asofs=n_false,
                        false_alarm_rate=n_false / len(valid_alarm) if len(valid_alarm) else np.nan,
                        n_asofs_ok=int(aa.status.eq("ok").sum()),
                        n_asofs_zero_pass=int((aa.status.eq("ok") & aa.accepted_windows.eq(0)).sum()),
                        n_asofs_unavailable=int(aa.status.ne("ok").sum()),
                    ))
    return pd.DataFrame(rows)


def paired(events):
    keys = ["symbol", "scale", "H", "event"]
    reference = events[events.arm == REFERENCE]
    rows = []
    for arm in ARMS:
        if arm == REFERENCE:
            continue
        other = events[events.arm == arm]
        merged = reference.merge(other, on=keys, suffixes=("_ref", "_other"), validate="one_to_one")
        for r in merged.itertuples(index=False):
            valid = bool(r.evaluable_ref and r.evaluable_other)
            common = bool(valid and r.hit_ref is not None and r.hit_other is not None
                          and r.hit_ref and r.hit_other)
            rows.append(dict(
                symbol=r.symbol, scale=r.scale, H=r.H, event=r.event, reference=REFERENCE, arm=arm,
                evaluable=valid, common_hit=common,
                lost_hit=bool(r.hit_ref and not r.hit_other) if valid else None,
                gained_hit=bool(not r.hit_ref and r.hit_other) if valid else None,
                reference_first_alarm=r.first_alarm_ref, other_first_alarm=r.first_alarm_other,
                reference_actionable_lead=r.actionable_lead_ref,
                other_actionable_lead=r.actionable_lead_other,
                actionable_lead_delta=(r.actionable_lead_other - r.actionable_lead_ref)
                if common else np.nan,
            ))
    return pd.DataFrame(rows)


def _sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(scan_root, prices_root, labels_path, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError("output must be a new directory; historical reports are never overwritten")
    scan_root, prices_root, labels_path = map(Path, (scan_root, prices_root, labels_path))
    scan_paths = {}
    for symbol in SYMBOLS:
        paths = list(scan_root.rglob(f"{symbol}.parquet"))
        if len(paths) != 1:
            raise ValueError(f"expected one original scan file for {symbol}, found {len(paths)}")
        scan_paths[symbol] = paths[0]
    source_root = Path(__file__).resolve().parents[1]
    sources = [Path(__file__).resolve(), source_root / "research/lppls/oscillations.py"]
    protected = [labels_path, *scan_paths.values(),
                 *(prices_root / f"{symbol}_qfq.parquet" for symbol in SYMBOLS), *sources]
    artifact_manifest = scan_root / "input_manifest.json"
    if artifact_manifest.exists():
        protected.append(artifact_manifest)
    before_hashes = {str(path.resolve()): _sha(path) for path in protected}
    labels = pd.read_csv(labels_path)
    if not {"sym", "label", "top"} <= set(labels):
        raise ValueError("existing label file requires sym,label,top")
    labels = labels[labels.label == "main"]
    global_path = prices_root / "sh000001_qfq.parquet"
    global_dates = calendar(pd.read_parquet(global_path))
    asofs, events, alarms, inputs = [], [], [], []
    for symbol in SYMBOLS:
        path = scan_paths[symbol]
        price_path = prices_root / f"{symbol}_qfq.parquet"
        prices = pd.read_parquet(price_path)
        dates = calendar(prices)
        scan = pd.read_parquet(path)
        ledger = labels.loc[labels.sym == symbol, "top"]
        if ledger.empty:
            raise ValueError(f"missing existing main event ledger for {symbol}")
        a = aggregate_asofs(scan, dates, global_dates, symbol)
        e = evaluate_events(a, ledger, dates, symbol)
        f = evaluate_alarms(a, ledger, dates)
        asofs.append(a)
        events.append(e)
        alarms.append(f)
        inputs.append(dict(symbol=symbol, scan_path=str(path.resolve()), scan_sha256=_sha(path),
                           scan_rows=len(scan), scan_min=str(scan.date.min()), scan_max=str(scan.date.max()),
                           prices_path=str(price_path.resolve()), prices_sha256=_sha(price_path),
                           rows_outside_dev=int((~pd.to_datetime(scan.date).between(DEV_START, DEV_END)).sum()),
                           fit_diagnostics=fit_diagnostics(scan)))
        print(f"{symbol}: {len(scan)} stored fits; {len(ledger)} existing main proxies", flush=True)
    aa, ee, ff = (pd.concat(frames, ignore_index=True) for frames in (asofs, events, alarms))
    result = summaries(aa, ee, ff)
    pp = paired(ee)
    after_hashes = {str(path.resolve()): _sha(path) for path in protected}
    if before_hashes != after_hashes:
        raise RuntimeError("input or executed source changed during audit; refusing to write results")
    output.mkdir(parents=True)
    for name, frame in (("asofs", aa), ("events", ee), ("alarms", ff), ("summary", result), ("paired_events", pp)):
        frame.to_csv(output / f"{name}.csv", index=False)
    manifest = dict(
        evidence="VERIFIED deterministic arithmetic on existing fits; forecast skill NOT_ESTABLISHED",
        runtime=dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__,
                     pyarrow=version("pyarrow")),
        input_and_source_unchanged=before_hashes == after_hashes,
        before_sha256=before_hashes, after_sha256=after_hashes,
        executed_source_sha256={str(path.resolve()): before_hashes[str(path.resolve())] for path in sources},
        label_source=LABEL_SOURCE, label_file=str(labels_path.resolve()), label_sha256=_sha(labels_path),
        proxy_definition_source="research/eval/original_standard.py:top_dates / research/eval/by_year.py:event_dates",
        limitations=["development sample; no held-out validation", "no verified ex-ante publication timestamps",
                     "main event is segment-end-plus-one proxy, not original consensus peak",
                     "frozen adjusted prices do not establish point-in-time data availability",
                     "alarm rate is per scheduled as-of, not independent alarm episodes",
                     "overlapping windows and correlated indexes are not independent observations"],
        q=Q, H=list(HORIZONS), scales=SCALES, arms=list(ARMS), units=OSC_UNITS_VERSION,
        domain="B<0,m in [.1,.9],omega in [6,13],0<tc-(n-1)<=90",
        denominator="all original eligible windows in scale; missing grid makes as-of not evaluable",
        scan_schedule="full sh000001 frozen calendar [::5] intersect asset calendar and development dates",
        event_evaluation="all scheduled as-of rows in [event-H,event) must be complete",
        actionability="next asset-calendar session; event_position-execution_position>=5",
        joint="FIRST alarm: at least 3 accepted windows, actionable>=5, q80-q20<=10, q20<=event-asof<=q80",
        false_alarm="alarm as-of with complete (asof,asof+H] inside dev, no main proxy event",
        inputs=inputs,
    )
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan-root", required=True, type=Path)
    parser.add_argument("--prices-root", default=Path("data/frozen/v20261024"), type=Path)
    parser.add_argument("--labels", default=Path("reports/label_diag_dev/tops.csv"), type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.scan_root, args.prices_root, args.labels, args.output)


if __name__ == "__main__":
    main()
