"""Frozen window/cluster sensitivity audit on saved development fits only.

No optimizer, market download, or label construction occurs. The existing main
event ledger is a segment-end-plus-one-session proxy, not published forecasts
or a new product definition. All strategies share a primary opportunity set;
strategy-specific coverage is reported separately, never silently substituted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from research.lppls import oscillations, window_clusters
from research.lppls.window_clusters import analyze_asof
from tools.lppl_repo_oscillation_refilter import (
    DEV_END,
    DEV_START,
    LABEL_SOURCE,
    SYMBOLS,
    calendar,
)

PROTOCOL_VERSION = "window_cluster_dev_v1"
ARMS = (
    "ref_6_12m", "ref_12_24m", "or2_full", "or4_full", "or4_thin",
    "cluster_any_full", "cluster_cross_full", "cluster_cross_thin",
    "cluster_cross_stable2",
)
PAIR_REFERENCES = {
    "ref_12_24m": "ref_6_12m", "or2_full": "ref_6_12m",
    "or4_full": "or2_full", "or4_thin": "or4_full",
    "cluster_any_full": "or4_full", "cluster_cross_full": "cluster_any_full",
    "cluster_cross_thin": "cluster_cross_full", "cluster_cross_stable2": "cluster_cross_full",
}
HORIZONS = (60, 120)
WINDOWS = np.arange(30, 501, 5)
Q = .05
STABLE_IOU = .25


def expected_windows(dates, global_dates, date):
    """Original calendar/history/gap eligibility, including saved short windows."""
    pos = dates.get_indexer([date])[0]
    if pos < 0:
        return []
    end = global_dates.get_indexer([date])[0]
    out = []
    for n in WINDOWS[WINDOWS <= pos + 1]:
        start = global_dates.get_indexer([dates[pos + 1 - n]])[0]
        count = end - start + 1 if start >= 0 and end >= 0 else n
        if n >= .9 * count:
            out.append(int(n))
    return out


def interval_iou(first, second):
    """IoU of closed intervals on the absolute observed trading-position axis."""
    if first is None or second is None:
        return 0.
    lo = max(first[0], second[0])
    hi = min(first[1], second[1])
    union = max(first[1], second[1]) - min(first[0], second[0])
    if union == 0:
        return float(first == second)
    return float(max(0., hi - lo) / union)


def _scale_result(result, names):
    stats = [result["scales"][name] for name in names]
    ok = all(item["status"] == "ok" for item in stats)
    reasons = sorted({item["status"] for item in stats if item["status"] != "ok"})
    values = [r["ahead"] for r in result["fits"] if r["qualified"] and r["scale"] in names]
    low, high = np.quantile(values, [.2, .8]) if values else (np.nan, np.nan)
    return dict(own_evaluable=ok, status="ok" if ok else ";".join(reasons),
                own_alarm=bool(ok and any(item["alarm"] for item in stats)),
                interval_lo=low, interval_hi=high, interval_width=high - low,
                interval_support=len(values), interval_kind="unweighted_fit_q20_q80",
                cluster_id=None, cluster_mass=np.nan,
                model_forward_at_least_6=bool(values and low >= 6))


def _cluster_result(result, kind):
    chosen = result["clusters"][kind]["primary"]
    ok = bool(result["evaluable"])
    reasons = sorted({s["status"] for s in result["scales"].values() if s["status"] != "ok"})
    return dict(own_evaluable=ok, status="ok" if ok else ";".join(reasons),
                own_alarm=bool(ok and chosen is not None),
                interval_lo=chosen["lo"] if chosen else np.nan,
                interval_hi=chosen["hi"] if chosen else np.nan,
                interval_width=chosen["width"] if chosen else np.nan,
                interval_support=chosen["n_members"] if chosen else 0,
                interval_kind="selected_dense_cluster_extent",
                cluster_id=chosen["id"] if chosen else None,
                cluster_mass=chosen["mass"] if chosen else np.nan,
                model_forward_at_least_6=bool(chosen and chosen["lo"] >= 6))


def aggregate_asofs(scan, dates, global_dates, symbol):
    """All planned dates survive, even no-fit, no-cluster, and missing-input dates."""
    required = {"date", "n", "tc", "m", "w", "B"}
    if not required <= set(scan):
        raise ValueError(f"scan missing fields: {sorted(required - set(scan))}")
    scan = scan.copy()
    scan["date"] = pd.to_datetime(scan.date, errors="raise")
    if scan.date.isna().any() or scan.duplicated(["date", "n"]).any():
        raise ValueError("scan must have nonmissing dates and one stored best fit per date/window")
    scan = scan[scan.date.between(DEV_START, DEV_END)]
    scheduled = global_dates[::5].intersection(dates)
    scheduled = scheduled[(scheduled >= DEV_START) & (scheduled <= DEV_END)]
    order = {date: i for i, date in enumerate(scheduled)}
    all_dates = scheduled.union(pd.DatetimeIndex(scan.date.unique())).sort_values()
    groups = {date: d for date, d in scan.groupby("date", sort=False)}
    empty = scan.iloc[:0]
    rows, candidates, members, scales = [], [], [], []
    previous = None
    previous_plan = None
    previous_evaluable = False
    for date in all_dates:
        position = int(dates.get_indexer([date])[0])
        planned = date in order
        expected = expected_windows(dates, global_dates, date)
        started = time.perf_counter()
        full = analyze_asof(groups.get(date, empty), expected, mode="full")
        full_seconds = time.perf_counter() - started
        started = time.perf_counter()
        thin = analyze_asof(groups.get(date, empty), expected, mode="thin")
        thin_seconds = time.perf_counter() - started
        result = {
            "ref_6_12m": _scale_result(full, ("medium",)),
            "ref_12_24m": _scale_result(full, ("long",)),
            "or2_full": _scale_result(full, ("medium", "long")),
            "or4_full": _scale_result(full, ("short", "mid", "medium", "long")),
            "or4_thin": _scale_result(thin, ("short", "mid", "medium", "long")),
            "cluster_any_full": _cluster_result(full, "any"),
            "cluster_cross_full": _cluster_result(full, "cross"),
            "cluster_cross_thin": _cluster_result(thin, "cross"),
        }
        current = result["cluster_cross_full"]
        absolute = ((position + current["interval_lo"], position + current["interval_hi"])
                    if planned and position >= 0 and current["own_alarm"] else None)
        consecutive = planned and previous_plan is not None and order[date] == previous_plan + 1
        overlap = interval_iou(previous, absolute) if consecutive else 0.
        stable = dict(current)
        stable["own_evaluable"] = bool(current["own_evaluable"] and consecutive and previous_evaluable)
        if current["own_evaluable"] and not stable["own_evaluable"]:
            stable["status"] = "stable_warmup" if not consecutive else "previous_scan_unavailable"
        stable["own_alarm"] = bool(stable["own_evaluable"] and current["own_alarm"] and overlap >= STABLE_IOU)
        stable["stability_iou"] = overlap
        result["cluster_cross_stable2"] = stable
        if planned:
            previous, previous_plan = absolute, order[date]
            previous_evaluable = bool(current["own_evaluable"] and position >= 0)
        for item in result.values():
            item.setdefault("stability_iou", np.nan)
            if not planned or position < 0:
                item["own_evaluable"] = False
                item["own_alarm"] = False
                item["status"] = "off_original_schedule" if position >= 0 else "unknown_price_date"
        common = all(item["own_evaluable"] for item in result.values())
        common_reason = ";".join(sorted({i["status"] for i in result.values() if not i["own_evaluable"]}))
        for arm in ARMS:
            item = result[arm]
            rows.append(dict(symbol=symbol, date=date, position=position,
                             scheduled=planned, plan_order=order.get(date, -1), arm=arm,
                             common_evaluable=common, common_status="ok" if common else common_reason,
                             common_alarm=bool(common and item["own_alarm"]),
                             analysis_seconds=thin_seconds if arm.endswith("thin") else full_seconds,
                             **item))
        for mode, r in (("full", full), ("thin", thin)):
            for scale, stat in r["scales"].items():
                scales.append(dict(symbol=symbol, date=date, mode=mode, scale=scale,
                                   status=stat["status"], denominator=stat["denominator"],
                                   qualified_count=stat["qualified_count"], fraction=stat["fraction"],
                                   alarm=stat["alarm"], expected_windows=json.dumps(stat["expected_windows"]),
                                   qualified_windows=json.dumps(stat["qualified_windows"])))
            for kind in ("any", "cross"):
                primary = r["clusters"][kind]["primary"]
                for c in r["clusters"][kind]["candidates"]:
                    ident = dict(symbol=symbol, date=date, mode=mode, kind=kind, cluster_id=c["id"])
                    candidates.append(dict(**ident, selected=bool(primary and c["id"] == primary["id"]),
                                           lo=c["lo"], hi=c["hi"], width=c["width"], mass=c["mass"],
                                           n_members=c["n_members"], members=json.dumps(c["members"]),
                                           supported_scales=json.dumps(c["supported_scales"]),
                                           scale_fractions=json.dumps(c["scale_fractions"], sort_keys=True)))
                    for member in c["member_details"]:
                        members.append(dict(**ident, **member))
    cluster_columns = ["symbol", "date", "mode", "kind", "cluster_id", "selected", "lo", "hi",
                       "width", "mass", "n_members", "members", "supported_scales", "scale_fractions"]
    member_columns = ["symbol", "date", "mode", "kind", "cluster_id", "n", "scale", "ahead", "weight"]
    return (pd.DataFrame(rows), pd.DataFrame(scales), pd.DataFrame(candidates, columns=cluster_columns),
            pd.DataFrame(members, columns=member_columns))


def evaluate_events(asofs, event_dates, dates, symbol):
    """First alert per old proxy event, on common and own coverage separately."""
    event_dates = pd.DatetimeIndex(pd.to_datetime(event_dates, errors="raise"))
    if event_dates.hasnans or not event_dates.is_unique:
        raise ValueError("proxy event ledger requires unique nonmissing dates")
    rows = []
    for arm in ARMS:
        a = asofs[(asofs.arm == arm) & asofs.scheduled & (asofs.position >= 0)].sort_values("date")
        for scope in ("common", "own"):
            eligible_col, alarm_col = f"{scope}_evaluable", f"{scope}_alarm"
            for horizon in HORIZONS:
                for event in event_dates:
                    event_pos = int(dates.get_indexer([event])[0])
                    candidate = a[(a.position >= event_pos - horizon) & (a.position < event_pos)]
                    reasons = []
                    if event_pos < 0:
                        reasons.append("unknown_event_date")
                    elif not DEV_START <= event <= DEV_END:
                        reasons.append("event_outside_dev")
                    elif event_pos < horizon or dates[event_pos - horizon] < DEV_START:
                        reasons.append("incomplete_H_lookback")
                    if candidate.empty:
                        reasons.append("no_scheduled_asof")
                    elif not candidate[eligible_col].all():
                        reasons.append("incomplete_strategy_opportunity_in_H")
                    evaluable = not reasons
                    alarms = candidate[candidate[alarm_col]]
                    first = alarms.iloc[0] if len(alarms) else None
                    observed = first is not None
                    lead = event_pos - int(first.position) if observed and event_pos >= 0 else np.nan
                    actionable = lead - 1
                    support = int(first.interval_support) if observed else 0
                    lo, hi = (first.interval_lo, first.interval_hi) if observed else (np.nan, np.nan)
                    covers = bool(observed and lo <= lead <= hi)
                    joint = bool(observed and support >= 3 and actionable >= 5 and hi - lo <= 10 and covers)
                    rows.append(dict(
                        symbol=symbol, arm=arm, scope=scope, H=horizon, event=event,
                        label_source=LABEL_SOURCE, event_position=event_pos,
                        evaluable=evaluable, status="ok" if evaluable else ";".join(reasons),
                        n_scheduled_asofs=len(candidate),
                        n_unavailable_asofs=int((~candidate[eligible_col]).sum()),
                        observed_hit=observed, hit=observed if evaluable else None,
                        first_alarm=first.date if observed else pd.NaT,
                        execution_date=dates[int(first.position) + 1] if observed and event_pos >= 0 else pd.NaT,
                        first_alarm_lead=lead, actionable_lead=actionable,
                        hit_actionable_5=bool(observed and actionable >= 5) if evaluable else None,
                        interval_lo=lo, interval_hi=hi, interval_width=hi - lo,
                        interval_support=support, interval_covers_proxy=covers if observed else None,
                        joint_hit=joint if evaluable else None,
                    ))
    return pd.DataFrame(rows)


def evaluate_alarms(asofs, event_dates, dates):
    """Emit ALL opportunities: zero alerts must not remove cost denominators."""
    event_positions = dates.get_indexer(pd.DatetimeIndex(pd.to_datetime(event_dates)))
    unknown = bool((event_positions < 0).any())
    rows = []
    for arm in ARMS:
        a = asofs[(asofs.arm == arm) & asofs.scheduled].sort_values("date")
        for scope in ("common", "own"):
            for horizon in HORIZONS:
                previous_alarm = False
                previous_order = None
                episode = 0
                for item in a.itertuples(index=False):
                    available = bool(getattr(item, f"{scope}_evaluable"))
                    alarm = bool(getattr(item, f"{scope}_alarm"))
                    end = item.position + horizon
                    full_future = item.position >= 0 and end < len(dates) and dates[end] <= DEV_END
                    evaluable = available and full_future and not unknown
                    active = alarm and evaluable
                    consecutive = previous_order is not None and item.plan_order == previous_order + 1
                    episode_start = bool(active and not (previous_alarm and consecutive))
                    if episode_start:
                        episode += 1
                    future = event_positions[(event_positions > item.position) & (event_positions <= end)]
                    status = ("strategy_unavailable" if not available else "unknown_event_date" if unknown
                              else "incomplete_future_H" if not full_future else "ok")
                    rows.append(dict(
                        symbol=item.symbol, arm=arm, scope=scope, H=horizon, date=item.date,
                        evaluable=evaluable, status=status, alarm=alarm,
                        future_proxy_events=len(future),
                        false_alarm=bool(len(future) == 0) if active else None,
                        episode_start=episode_start, episode_id=episode if active else None,
                    ))
                    previous_alarm, previous_order = active, item.plan_order
    return pd.DataFrame(rows)


def summaries(asofs, events, opportunities):
    rows = []
    symbols = sorted(asofs.symbol.unique()) + ["ALL"]
    for symbol in symbols:
        a = asofs if symbol == "ALL" else asofs[asofs.symbol == symbol]
        e = events if symbol == "ALL" else events[events.symbol == symbol]
        o = opportunities if symbol == "ALL" else opportunities[opportunities.symbol == symbol]
        for arm in ARMS:
            aa = a[a.arm == arm]
            for scope in ("common", "own"):
                for horizon in HORIZONS:
                    ee = e[(e.arm == arm) & (e.scope == scope) & (e.H == horizon)]
                    oo = o[(o.arm == arm) & (o.scope == scope) & (o.H == horizon)]
                    valid = ee[ee.evaluable]
                    hits = valid[valid.hit.eq(True)]
                    available = oo[oo.evaluable]
                    alerts = available[available.alarm]
                    n, nhit = len(valid), len(hits)
                    nlead = int(valid.hit_actionable_5.eq(True).sum())
                    njoint = int(valid.joint_hit.eq(True).sum())
                    nfalse = int(alerts.false_alarm.eq(True).sum())
                    rows.append(dict(
                        symbol=symbol, arm=arm, scope=scope, H=horizon,
                        n_events=len(ee), n_evaluable=n, n_not_evaluable=len(ee) - n,
                        n_hit=nhit, n_missed=n - nhit, recall=nhit / n if n else np.nan,
                        n_actionable_5=nlead, n_missed_actionable_5=n - nlead,
                        recall_actionable_5=nlead / n if n else np.nan,
                        n_joint=njoint, joint_recall=njoint / n if n else np.nan,
                        actionable_lead_median=hits.actionable_lead.median(),
                        n_first_alert_lt3_windows=int((hits.interval_support < 3).sum()),
                        n_asofs_strategy_available=int(aa[f"{scope}_evaluable"].sum()),
                        n_asofs_strategy_unavailable=int((~aa[f"{scope}_evaluable"]).sum()),
                        n_opportunities=len(available), n_alert_asofs=len(alerts),
                        alerts_per_100_asofs=100 * len(alerts) / len(available) if len(available) else np.nan,
                        n_false_alert_asofs=nfalse,
                        false_alert_fraction=nfalse / len(alerts) if len(alerts) else np.nan,
                        n_alert_episodes=int(available.episode_start.sum()),
                    ))
    return pd.DataFrame(rows)


def paired(events):
    keys = ["symbol", "scope", "H", "event"]
    rows = []
    for arm, reference in PAIR_REFERENCES.items():
        a = events[events.arm == reference]
        b = events[events.arm == arm]
        joined = a.merge(b, on=keys, suffixes=("_ref", "_other"), validate="one_to_one")
        for r in joined.itertuples(index=False):
            valid = bool(r.evaluable_ref and r.evaluable_other)
            common = bool(valid and r.hit_ref and r.hit_other)
            rows.append(dict(
                symbol=r.symbol, scope=r.scope, H=r.H, event=r.event,
                reference=reference, arm=arm, evaluable=valid, common_hit=common,
                gained_hit=bool(not r.hit_ref and r.hit_other) if valid else None,
                lost_hit=bool(r.hit_ref and not r.hit_other) if valid else None,
                gained_actionable_5=bool(not r.hit_actionable_5_ref and r.hit_actionable_5_other) if valid else None,
                lost_actionable_5=bool(r.hit_actionable_5_ref and not r.hit_actionable_5_other) if valid else None,
                reference_first_alarm=r.first_alarm_ref, other_first_alarm=r.first_alarm_other,
                reference_actionable_lead=r.actionable_lead_ref,
                other_actionable_lead=r.actionable_lead_other,
                actionable_lead_delta=r.actionable_lead_other - r.actionable_lead_ref if common else np.nan,
            ))
    return pd.DataFrame(rows)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(scan_root, prices_root, labels_path, output):
    started = time.perf_counter()
    output = Path(output)
    if output.exists():
        raise FileExistsError("output must be a new directory; never overwrite old evidence")
    scan_root, prices_root, labels_path = map(Path, (scan_root, prices_root, labels_path))
    scans = {symbol: scan_root / f"{symbol}.parquet" for symbol in SYMBOLS}
    prices = {symbol: prices_root / f"{symbol}_qfq.parquet" for symbol in SYMBOLS}
    source = [Path(__file__), Path(window_clusters.__file__), Path(oscillations.__file__),
              Path(__file__).with_name("lppl_repo_oscillation_refilter.py")]
    inputs = [*scans.values(), *prices.values(), labels_path, *source]
    upstream_manifest = scan_root / "input_manifest.json"
    if upstream_manifest.exists():
        inputs.append(upstream_manifest)
    before = {str(p.resolve()): _sha(p) for p in inputs}
    labels = pd.read_csv(labels_path)
    if not {"sym", "label", "top"} <= set(labels):
        raise ValueError("existing labels require sym,label,top")
    labels = labels[labels.label == "main"]
    global_dates = calendar(pd.read_parquet(prices["sh000001"]))
    tables = {name: [] for name in ("asofs", "scales", "clusters", "members", "events", "opportunities")}
    stats = []
    for symbol in SYMBOLS:
        scan = pd.read_parquet(scans[symbol])
        dates = calendar(pd.read_parquet(prices[symbol]))
        ledger = labels.loc[labels.sym == symbol, "top"]
        if ledger.empty:
            raise ValueError(f"missing existing event ledger for {symbol}")
        a, s, c, m = aggregate_asofs(scan, dates, global_dates, symbol)
        e = evaluate_events(a, ledger, dates, symbol)
        o = evaluate_alarms(a, ledger, dates)
        for name, table in zip(tables, (a, s, c, m, e, o), strict=True):
            tables[name].append(table)
        stats.append(dict(symbol=symbol, input_fit_rows=len(scan), old_proxy_events=len(ledger)))
        print(f"{symbol}: {len(scan)} stored fits, {len(ledger)} old proxies, nine frozen arms", flush=True)
    final = {name: pd.concat(items, ignore_index=True) for name, items in tables.items()}
    final["summary"] = summaries(final["asofs"], final["events"], final["opportunities"])
    final["paired_events"] = paired(final["events"])
    after = {str(p.resolve()): _sha(p) for p in inputs}
    if before != after:
        raise ValueError("input or executed source changed during analysis")
    common = final["summary"].query("scope == 'common'")
    if common.groupby(["symbol", "H"]).n_evaluable.nunique().gt(1).any():
        raise ValueError("common opportunity protocol produced unequal event denominators")
    manifest = dict(
        protocol_version=PROTOCOL_VERSION,
        baseline_version=window_clusters.RESEARCH_BASELINE_VERSION,
        evidence="VERIFIED saved-fit arithmetic; predictive skill NOT_ESTABLISHED",
        runtime=dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__,
                     pyarrow=version("pyarrow")),
        elapsed_seconds_before_output=time.perf_counter() - started,
        timing_boundary="module mode timing per asof excludes fitting/I/O; total includes reads, coverage and evaluation; no hardware isolation or online SLA claim",
        before_sha256=before, after_sha256=after, input_and_source_unchanged=True,
        executed_source_sha256={str(p.resolve()): _sha(p) for p in source},
        arms=list(ARMS), pair_references=PAIR_REFERENCES, H=list(HORIZONS), q=Q,
        scales={"short": [30, 60], "mid": [65, 125], "medium": [130, 250], "long": [255, 500]},
        thin="seven np.rint(linspace index) anchors per fixed full scale, then intersect eligibility",
        cluster="width<=10, at least3 distinct windows, scale-supported fraction>=.05; any>=1/cross>=2 scales",
        weight="1/(4*original eligible windows in the chosen mode and scale), never surviving-fit denominator",
        stability="primary cross cluster IoU>=.25 in absolute asset trading positions across adjacent scheduled asofs; both scans must be evaluable; previous valid empty cluster is no confirmation, previous missing scan is unavailable",
        forecast_domain="future box plus canonical full cycles>=1.5; no new h>=6 hard filter",
        label_source=LABEL_SOURCE, event_policy="first alarm within [event-H,event); next observed session execution",
        common_scope="each asof evaluable by all nine arms; event needs complete H opportunity; zero alarms retained",
        own_scope="separate coverage diagnostics only; not substituted for common denominators",
        joint="first alert with>=3 windows, action lead>=5, width<=10, first interval contains event proxy",
        alarm_cost="all scheduled evaluable future-H opportunities; alerts/100, false alert fraction, contiguous-plan alert episodes",
        source_statistics=stats,
        fixed_q_caveat="q=.05 means one qualified window can trigger a seven-window band, versus two in a 25-window band and three in a 50-window band; OR expansion effects are not clustering gains",
        limits=["consumed development data; no independent validation", "old main events are proxies, not raw consensus peaks",
                "no original prediction publication timestamp verification", "no new optimizer run or labels",
                "window/scale dependence; support mass is not probability", "fixed adjusted history does not prove PIT",
                "five-session scan grid cannot establish daily alert timing", "no production policy or deployment change"],
    )
    output.mkdir(parents=True, exist_ok=False)
    formats = {}
    for name, frame in final.items():
        compressed = name in {"asofs", "scales", "clusters", "members", "opportunities"}
        path = output / (f"{name}.csv.gz" if compressed else f"{name}.csv")
        frame.to_csv(path, index=False,
                     compression={"method": "gzip", "mtime": 0, "compresslevel": 6} if compressed else None)
        formats[name] = dict(file=path.name, format="gzip CSV" if compressed else "CSV",
                             rows=len(frame), sha256=_sha(path), bytes=path.stat().st_size)
    manifest["outputs"] = formats
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return final["summary"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan-root", type=Path, required=True)
    parser.add_argument("--prices-root", type=Path, default=Path("data/frozen/v20261024"))
    parser.add_argument("--labels", type=Path, default=Path("reports/label_diag_dev/tops.csv"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.scan_root, args.prices_root, args.labels, args.output)


if __name__ == "__main__":
    main()
