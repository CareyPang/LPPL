"""Frozen, resumable multi-market LPPLS long-window replay, with exact input hashes.

This is a historical reconstruction, not a claim that these outputs were
published in advance. Missing source history is never padded or substituted.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')

import numpy as np
import scipy

from ..data.global_terminal import ASSETS, fetch_snapshot
from ..lppls import frozen_v2588 as numerical
from .global_terminal import atomic_json, clean
from .long_horizon import (
    DE,
    LB,
    SEEDS,
    WINDOWS,
    check_fit,
    digest,
    fit_job,
    input_identity,
    math_ast_hash,
    prefix,
    signature,
    summarize_rules,
    summarize_windows,
)

VERSION = 'long_rolling_52x5_v1'
DEFAULT_ASSETS = ('US_IXIC', 'US_NDX', 'KR_KOSPI', 'KR_KOSDAQ')
PROFILE_GRID = tuple(range(1, 89, 3)) + (90,)


def endpoint_dates(frame, count=52, step=5):
    if count < 1 or step < 1:
        raise ValueError('Positive endpoint count and session step required')
    indices = [len(frame) - 1 - step * i for i in range(count)]
    if min(indices) < 0:
        raise ValueError('Insufficient observed sessions for endpoint grid')
    return [str(frame.date.iloc[i]) for i in sorted(indices)]


def market_date(dates, asof, ahead):
    """Realized-session mapping for scoring; estimates explicitly marked beyond data."""
    index = dates.index(asof) + int(round(float(ahead)))
    if index < len(dates):
        return dates[index], 'observed_session_calendar_for_retrospective_scoring'
    remaining = index - (len(dates) - 1)
    return str(np.busday_offset(np.datetime64(dates[-1]), remaining, roll='forward')), 'weekday_estimate_holidays_not_removed'


def experiment_method():
    return {'version': VERSION, 'math_ast_hash': math_ast_hash(numerical.__file__),
            'kernel_sha256': digest(numerical.__file__), 'de': DE, 'lbfgsb': LB,
            'numpy': np.__version__, 'scipy': scipy.__version__, 'windows': list(WINDOWS),
            'seeds': list(SEEDS), 'future_tc_sessions': [1, 90], 'm_bounds': [.1, .9],
            'omega_bounds': [6, 13], 'primary_rule': 'cycles_1_5', 'comparison_rule': 'cycles_2_5',
            'lead_5_days': 'report separately; never a filter',
            'family_width_max_sessions': 5, 'seed_gap_max_sessions': 2,
            'profile_grid': list(PROFILE_GRID), 'profile_n': 6600}


def make_snapshot(symbol, asof, frame, metadata, records, method_hash, method):
    windows = summarize_windows(records, asof)
    dates = frame.date.tolist()
    for window in windows:
        for seed in window['seeds']:
            if seed['status'] == 'complete':
                seed['tc_date'], seed['calendar_status'] = market_date(dates, asof, seed['tc_ahead'])
        good = [seed for seed in window['seeds'] if seed['status'] == 'complete']
        if good:
            window['seed_date_range'] = sorted([market_date(dates, asof, min(s['tc_ahead'] for s in good))[0],
                                               market_date(dates, asof, max(s['tc_ahead'] for s in good))[0]])
        if window['point_ahead'] is not None:
            window['point_date'], window['calendar_status'] = market_date(dates, asof, window['point_ahead'])
        if any(seed['status'] == 'not_available' for seed in window['seeds']):
            window['data_reason'] = '历史不足所选窗口；未填充、未替代其他资产'
    states = [seed['status'] for window in windows for seed in window['seeds']]
    counts = {'expected': len(WINDOWS) * len(SEEDS), 'completed': states.count('complete'),
              'failed': states.count('failed'), 'pending': states.count('pending'),
              'not_available': states.count('not_available')}
    status = ('running' if counts['pending'] else 'incomplete' if counts['failed'] else
              'complete_with_data_gaps' if counts['not_available'] else 'complete')
    rules = summarize_rules(windows)
    for rule in rules.values():
        for cluster in rule['cross_family_clusters']:
            members = [w for w in windows if w['n'] in cluster['members']]
            cluster['start_ahead'] = min(w['point_ahead'] for w in members)
            cluster['end_ahead'] = max(w['point_ahead'] for w in members)
    available = frame[frame.date <= asof]
    return clean({'schema_version': 'long_horizon_v1', 'symbol': symbol, 'asof': asof,
                  'asof_index': dates.index(asof), 'status': status, 'model_version': VERSION,
                  'method_hash': method_hash, 'method': method, 'counts': counts,
                  'source': {'label': metadata.get('source', 'provided daily close') + ' · 冻结输入历史重建',
                             'data_version': metadata['normalized_sha256'], 'input_hash': input_identity(available),
                             'rows': len(available), 'first_date': available.date.iloc[0],
                             'provider': metadata.get('provider', metadata.get('history_provider')), 'adjustment': metadata.get('adjustment'),
                             'data_quality': metadata.get('data_quality')},
                  'first_visible_at': None, 'windows': windows, 'rules': rules,
                  'calendar': {'status': 'observed_historical_sessions_else_weekday_estimate', 'verified': False,
                               'note': '历史评分按各资产实际交易日；数据截止日以后的日期仅为未扣除休市日的平日估算，不套用美股日历给韩股。'},
                  'limits': ['Seed agreement measures numerical stability, not probability.',
                             'One adjacent-window family is one scale, even if several lengths pass.',
                             '52个固定相隔5交易日的截止日构成滚动重建；不是逐日全历史扫描或盲测。',
                             '完整周期1.5为主规则；至少提前5日只单独报告，不作为隐藏研究结果的门槛。']})


def profile_job(task):
    started = time.perf_counter()
    identity = {k: task[k] for k in ('symbol', 'asof', 'ahead', 'seed', 'input_hash', 'method_hash', 'key')}
    try:
        y = np.log(np.asarray(task['close'], dtype=float))
        fit = numerical.profile_fit(y, len(y) - 1 + task['ahead'], task['seed'])
        check = numerical.lin(np.arange(len(y), dtype=float), y, len(y) - 1 + task['ahead'], fit['m'], fit['omega'])
        if not np.isclose(check['sse'], fit['sse'], rtol=1e-10, atol=1e-12):
            raise ValueError('Profile SSE mismatch')
        return clean({**identity, 'status': 'complete', 'fit': fit, 'seconds': time.perf_counter() - started})
    except Exception as error:
        return {**identity, 'status': 'failed', 'error': f'{type(error).__name__}: {error}'}


def stability(rows):
    result = {}
    for rule in ('cycles_1_5', 'cycles_2_5'):
        by_window = []
        for n in WINDOWS:
            selected = [(row, next(w for w in row['windows'] if w['n'] == n)) for row in rows]
            candidate = [(row, window) for row, window in selected if window['eligible'][rule]]
            migrations = []
            for (previous, a), (current, b) in zip(selected, selected[1:], strict=False):
                if a['eligible'][rule] and b['eligible'][rule]:
                    migrations.append({'from': previous['asof'], 'to': current['asof'],
                                       'tc_migration_sessions': (current['asof_index'] + b['point_ahead']) - (previous['asof_index'] + a['point_ahead']),
                                       'asof_step_sessions': current['asof_index'] - previous['asof_index']})
            available = sum(all(s['status'] == 'complete' for s in w['seeds']) for _, w in selected)
            by_window.append({'n': n, 'qualified_endpoints': len(candidate), 'tested_endpoints': available,
                              'requested_endpoints': len(rows), 'not_available_endpoints': len(rows) - available,
                              'candidate_rate_is_not_probability': True, 'consecutive_candidate_migrations': migrations,
                              'seed_gap_median': float(np.median([w['seed_gap_days'] for _, w in selected if w['seed_gap_days'] is not None]))
                              if any(w['seed_gap_days'] is not None for _, w in selected) else None})
        result[rule] = {'windows': by_window,
                        'cross_family_endpoint_count': sum(bool(r['rules'][rule]['cross_family_clusters']) for r in rows),
                        'endpoints': len(rows)}
    return result


def run(root, source_root, *, assets=DEFAULT_ASSETS, endpoints=52, step=5, workers=4,
        refresh=False, fit_cache=None, profiles=True):
    root, source_root = Path(root).resolve(), Path(source_root).resolve()
    checkout = Path(__file__).resolve().parents[2]
    if root.is_relative_to(checkout) or source_root.is_relative_to(checkout):
        raise ValueError('Research data/output roots must stay outside checkout')
    if any(symbol not in ASSETS for symbol in assets) or len(set(assets)) != len(assets):
        raise ValueError('Unsupported or duplicate asset')
    root.mkdir(parents=True, exist_ok=True)
    cache = Path(fit_cache).resolve() if fit_cache else root / 'fits'
    if cache.is_relative_to(checkout):
        raise ValueError('Fit cache must stay outside checkout')
    cache.mkdir(parents=True, exist_ok=True)
    method = experiment_method()
    method_hash = signature(method)
    frames, metadata, grids = {}, {}, {}
    for symbol in assets:
        frame, meta = fetch_snapshot(symbol, source_root, refresh=refresh, full_history=True)
        frame = frame.copy()
        frame['date'] = frame.date.dt.strftime('%Y-%m-%d')
        if frame.date.duplicated().any() or not frame.date.is_monotonic_increasing or not np.isfinite(frame.close).all() or (frame.close <= 0).any():
            raise ValueError('Invalid input series')
        frames[symbol], metadata[symbol] = frame, meta
        grids[symbol] = endpoint_dates(frame, endpoints, step)
    protocol = {'schema_version': VERSION, 'assets': list(assets), 'endpoints_per_asset': endpoints,
                'endpoint_step_sessions': step, 'endpoint_dates': grids, 'method': method, 'method_hash': method_hash,
                'inputs': {s: {'data_version': metadata[s]['normalized_sha256'], 'input_hash': input_identity(frames[s]),
                               'rows': len(frames[s]), 'first_date': frames[s].date.iloc[0], 'asof': frames[s].date.iloc[-1]} for s in assets},
                'expected_fits': len(assets) * endpoints * len(WINDOWS) * len(SEEDS),
                'expected_profiles': len(assets) * len(PROFILE_GRID) * len(SEEDS) if profiles else 0,
                'scope': 'frozen historical reconstruction; no parameter selection from outcome; original artifacts retained'}
    protocol['protocol_hash'] = signature(protocol)
    path = root / 'protocol.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8')).get('protocol_hash') != protocol['protocol_hash']:
        raise ValueError('Frozen protocol/input changed; use a new run directory')
    if not path.exists():
        atomic_json(path, {**protocol, 'registered_at': datetime.now(UTC).isoformat()})
    for symbol in assets:
        input_path = root / 'inputs' / (symbol + '.json')
        if input_path.exists():
            saved = json.loads(input_path.read_text(encoding='utf-8'))
            if (saved.get('symbol') != symbol or saved.get('dates') != frames[symbol].date.tolist()
                    or saved.get('close') != frames[symbol].close.tolist()
                    or saved.get('source_meta', {}).get('normalized_sha256') != metadata[symbol]['normalized_sha256']):
                raise ValueError('Frozen input archive mismatch')
        if not input_path.exists():
            atomic_json(input_path, {'symbol': symbol, 'dates': frames[symbol].date.tolist(), 'close': frames[symbol].close.tolist(), 'source_meta': metadata[symbol]})
    records = {s: {} for s in assets}
    tasks, reused = [], 0
    for symbol in assets:
        for asof in grids[symbol]:
            for n in WINDOWS:
                for seed in SEEDS:
                    try:
                        part = prefix(frames[symbol], asof, n)
                    except ValueError as error:
                        records[symbol][(asof, n, seed)] = {'seed': seed, 'status': 'not_available', 'error': str(error)}
                        continue
                    task = {'symbol': symbol, 'asof': asof, 'n': n, 'seed': seed,
                            'input_hash': input_identity(part), 'method_hash': method_hash,
                            'kernel_path': numerical.__file__, 'kernel_sha256': method['kernel_sha256'], 'close': part.close.tolist()}
                    key = signature({k: task[k] for k in ('symbol', 'asof', 'n', 'seed', 'input_hash', 'method_hash')})
                    saved_path = cache / (key + '.json')
                    if saved_path.exists():
                        saved = json.loads(saved_path.read_text(encoding='utf-8'))
                        if any(saved.get(k) != task[k] for k in ('symbol', 'asof', 'n', 'seed', 'input_hash', 'method_hash')):
                            raise ValueError('Fit cache identity mismatch')
                        if saved['status'] == 'complete':
                            saved['independent_readback'] = check_fit(saved['fit'], part.close, {'lin': numerical.lin, 'Xmat': numerical.Xmat})
                            records[symbol][(asof, n, seed)] = saved
                            reused += 1
                            continue
                    tasks.append((task, saved_path))
    started = time.perf_counter()

    def save_progress():
        flat = [r for table in records.values() for r in table.values()]
        status = [r['status'] for r in flat]
        counts = {'expected': protocol['expected_fits'], 'completed': status.count('complete'),
                  'failed': status.count('failed'), 'not_available': status.count('not_available'),
                  'pending': protocol['expected_fits'] - len(flat), 'cache_reused': reused}
        atomic_json(root / 'progress.json', {**counts, 'seconds': time.perf_counter() - started, 'updated_at': datetime.now(UTC).isoformat()})
        return counts

    print(json.dumps({'protocol': str(path), 'pending': len(tasks), 'counts': save_progress()}), flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fit_job, task): (task, target) for task, target in tasks}
        for position, future in enumerate(as_completed(futures), 1):
            task, target = futures[future]
            try:
                value = future.result()
                if value['status'] == 'complete':
                    value['independent_readback'] = check_fit(value['fit'], task['close'], {'lin': numerical.lin, 'Xmat': numerical.Xmat})
            except Exception as error:
                value = {k: task[k] for k in ('symbol', 'asof', 'n', 'seed', 'input_hash', 'method_hash')}
                value.update(status='failed', error=str(error))
            atomic_json(target, value)
            records[task['symbol']][(task['asof'], task['n'], task['seed'])] = value
            counts = save_progress()
            if position % 24 == 0 or position == len(tasks):
                print(json.dumps(counts), flush=True)
    ledger = {s: [make_snapshot(s, day, frames[s], metadata[s], records[s], method_hash, method) for day in grids[s]] for s in assets}
    summary = {'schema_version': 'long_horizon_v1', 'counts': save_progress(), 'protocol_hash': protocol['protocol_hash'],
               'generated_at': datetime.now(UTC).isoformat(), 'assets': {}, 'stability': {s: stability(ledger[s]) for s in assets}}
    for symbol in assets:
        for row in ledger[symbol]:
            atomic_json(root / 'snapshots' / symbol / (row['asof'] + '.json'), row)
        summary['assets'][symbol] = {**ledger[symbol][-1], 'history': ledger[symbol][:-1],
                                    'stability': {'history': ledger[symbol][:-1], 'note': '相隔5交易日的冻结历史重建，非当时发布；同族相邻窗口不视为独立证据。'}}
    atomic_json(root / 'ledger.json', ledger)
    if profiles:
        profile_tasks, profile_cells = [], []
        for symbol in assets:
            if len(frames[symbol]) < 6600:
                profile_cells += [{'symbol': symbol, 'status': 'not_available'} for _ in range(len(PROFILE_GRID) * len(SEEDS))]
                continue
            part = frames[symbol].tail(6600)
            for ahead in PROFILE_GRID:
                for seed in SEEDS:
                    task = {'symbol': symbol, 'asof': grids[symbol][-1], 'ahead': ahead, 'seed': seed,
                            'input_hash': input_identity(part), 'method_hash': method_hash}
                    task['key'] = signature(task)
                    target = root / 'profiles' / (task['key'] + '.json')
                    if target.exists():
                        saved = json.loads(target.read_text(encoding='utf-8'))
                        if any(saved.get(k) != task[k] for k in task):
                            raise ValueError('Profile cache identity mismatch')
                        if saved['status'] == 'complete':
                            q = numerical.lin(np.arange(6600, dtype=float), np.log(part.close.to_numpy()), 6599 + ahead, saved['fit']['m'], saved['fit']['omega'])
                            if not np.isclose(q['sse'], saved['fit']['sse'], rtol=1e-10, atol=1e-12):
                                raise ValueError('Profile cached SSE mismatch')
                            profile_cells.append(saved)
                            continue
                    profile_tasks.append(({**task, 'close': part.close.tolist()}, target))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(profile_job, task): target for task, target in profile_tasks}
            for future in as_completed(futures):
                cell = future.result()
                atomic_json(futures[future], cell)
                profile_cells.append(cell)
                atomic_json(root / 'profile-progress.json', {'expected': protocol['expected_profiles'],
                    'completed': sum(c['status'] == 'complete' for c in profile_cells),
                    'failed': sum(c['status'] == 'failed' for c in profile_cells),
                    'not_available': sum(c['status'] == 'not_available' for c in profile_cells),
                    'pending': protocol['expected_profiles'] - len(profile_cells)})
        summary['profile_counts'] = {'expected': protocol['expected_profiles'],
                    'completed': sum(c['status'] == 'complete' for c in profile_cells),
                    'failed': sum(c['status'] == 'failed' for c in profile_cells),
                    'not_available': sum(c['status'] == 'not_available' for c in profile_cells),
                    'pending': protocol['expected_profiles'] - len(profile_cells)}
        for symbol in assets:
            cells = [c for c in profile_cells if c['symbol'] == symbol and c['status'] == 'complete']
            if not cells:
                continue
            latest = summary['assets'][symbol]
            converged = [c for c in cells if c['fit']['de_success'] and c['fit']['lbfgs_success']]
            free = [s['sse'] for w in latest['windows'] if w['n'] == 6600 for s in w['seeds']
                    if s['status'] == 'complete' and s['optimizer_success']]
            minimum = min([c['fit']['sse'] for c in converged] + free) if converged else None
            latest['profile_diagnostic'] = {'symbol': symbol, 'asof': latest['asof'], 'n': 6600,
                'data_version': metadata[symbol]['normalized_sha256'],
                'status': 'complete' if converged else 'numerically_unresolved',
                'counts': {'expected': len(PROFILE_GRID) * len(SEEDS), 'completed': len(cells), 'converged': len(converged)},
                'points': [{'ahead': ahead, 'sse': min(c['fit']['sse'] for c in converged if c['ahead'] == ahead),
                            'delta_sse_pct': (min(c['fit']['sse'] for c in converged if c['ahead'] == ahead) / minimum - 1) * 100,
                            'completed_seeds': sum(c['ahead'] == ahead for c in cells),
                            'converged_seeds': sum(c['ahead'] == ahead for c in converged)}
                           for ahead in PROFILE_GRID if any(c['ahead'] == ahead for c in converged)]}
    summary['status'] = 'complete_with_data_gaps' if summary['counts']['not_available'] else 'complete'
    if (summary['counts']['failed'] or summary['counts']['pending']
            or summary.get('profile_counts', {}).get('failed') or summary.get('profile_counts', {}).get('pending')):
        summary['status'] = 'incomplete'
    summary['report_version'] = signature(summary)
    atomic_json(root / 'exports' / (summary['report_version'] + '.json'), summary)
    atomic_json(root / 'summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--assets', nargs='+', default=DEFAULT_ASSETS)
    parser.add_argument('--endpoints', type=int, default=52)
    parser.add_argument('--step', type=int, default=5)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--fit-cache', type=Path)
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--no-profiles', action='store_true')
    args = parser.parse_args()
    result = run(args.root, args.source_root, assets=tuple(args.assets), endpoints=args.endpoints,
                 step=args.step, workers=args.workers, refresh=args.refresh, fit_cache=args.fit_cache, profiles=not args.no_profiles)
    print(json.dumps({'status': result['status'], 'counts': result['counts']}), flush=True)
    if result['status'] == 'incomplete':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
