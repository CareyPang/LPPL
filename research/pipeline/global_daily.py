"""Local daily current analysis plus one latest long endpoint; never a 52-day sweep.

Frozen research runs remain untouched. A public-facing local summary advances
only after every configured long asset passes input, fit and profile checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ..data.global_events import collect_market_events
from ..data.global_terminal import load_cached_snapshot
from . import global_refresh, long_rolling
from .global_terminal import ROOT, atomic_json
from .long_horizon import SEEDS, WINDOWS, input_identity, signature

SCHEMA = 'global_daily_current_and_long_v1'


def _now():
    return datetime.now(UTC).isoformat()


def parse_config(value):
    config = global_refresh.parse_config(value)
    for name in ('long_state_root', 'fit_cache', 'seed_study_root'):
        raw = value.get(name)
        if raw is None and name == 'seed_study_root':
            config[name] = None
            continue
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise ValueError(f'{name} must be an absolute path')
        path = Path(raw).resolve()
        if path.is_relative_to(ROOT) or (os.name == 'nt' and path.drive.lower() != 'd:'):
            raise ValueError(f'{name} must be outside checkout on D:')
        config[name] = path
    if config['long_state_root'] in (config['source_root'], config['state_root'], config['jobs_root'], config['seed_study_root']):
        raise ValueError('Daily long state must be separate from source, current state, jobs and frozen study')
    assets = value.get('long_assets', list(long_rolling.DEFAULT_ASSETS))
    if (not isinstance(assets, list) or not assets or any(not isinstance(s, str) for s in assets)
            or len(assets) != len(set(assets))
            or any(s not in config['symbols'] or s not in long_rolling.DEFAULT_ASSETS for s in assets)):
        raise ValueError('long_assets must be unique supported assets included in symbols')
    config['long_assets'] = assets
    workers = value.get('long_workers', 4)
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 32:
        raise ValueError('long_workers must be an integer from 1 to 32')
    config['long_workers'] = workers
    return config


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _read_summary(path):
    value = _read(path)
    if value.get('report_version') != signature({k: v for k, v in value.items() if k != 'report_version'}):
        raise ValueError('Stored summary content hash mismatch')
    return value


def _immutable(path, value):
    """Exclusive creation; an existing version must have identical JSON values."""
    content = json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as target:
            target.write(content)
    except FileExistsError:
        if _read(path) != value:
            raise ValueError(f'Append-only artifact differs: {path.name}') from None


def _verified_input(symbol, config, row, loader):
    if row.get('status') not in ('updated', 'unchanged') or row.get('source_status') != 'ready':
        raise ValueError('Current refresh did not verify a usable source and result')
    frame, metadata = loader(symbol, config['source_root'])
    frame = frame.copy()
    frame['date'] = frame.date.dt.strftime('%Y-%m-%d')
    if (metadata.get('id') != symbol or len(frame) < config['long_window_rows']
            or frame.date.duplicated().any() or not frame.date.is_monotonic_increasing
            or not np.isfinite(frame.close).all() or (frame.close <= 0).any()
            or metadata.get('asof') != frame.date.iloc[-1]
            or row.get('asof') != metadata.get('asof')
            or row.get('data_version') != metadata.get('normalized_sha256')):
        raise ValueError('Long input is insufficient, invalid or differs from the current refresh')
    identity = {'symbol': symbol, 'asof': metadata['asof'], 'rows': len(frame),
                'data_version': metadata['normalized_sha256'], 'input_hash': input_identity(frame)}
    return frame, identity


def _valid_summary(value, symbol, identity, method_hash):
    expected = len(WINDOWS) * len(SEEDS)
    profiles = len(long_rolling.PROFILE_GRID) * len(SEEDS)
    if value.get('report_version') != signature({k: v for k, v in value.items() if k != 'report_version'}):
        raise ValueError('Long summary content hash mismatch')
    for name, required in (('counts', expected), ('profile_counts', profiles)):
        counts = value.get(name, {})
        if (counts.get('expected') != required or counts.get('completed') != required
                or any(counts.get(k, 0) for k in ('failed', 'pending', 'not_available'))):
            raise ValueError(f'Long {name} is incomplete')
    asset = value.get('assets', {}).get(symbol, {})
    source = asset.get('source', {})
    if (value.get('status') != 'complete' or asset.get('status') != 'complete'
            or asset.get('symbol') != symbol or asset.get('asof') != identity['asof']
            or asset.get('method_hash') != method_hash
            or source.get('data_version') != identity['data_version']
            or source.get('input_hash') != identity['input_hash']):
        raise ValueError('Long result does not match the verified input and method')
    return asset


def _history_candidates(summary, symbol):
    value = summary.get('assets', {}).get(symbol, {})
    return [*value.get('history', []), value] if value else []


def _attach_history(latest, candidates, frame, method_hash):
    accepted, rejected = {}, 0
    for row in candidates:
        asof = row.get('asof', '')
        if not asof or asof >= latest['asof']:
            continue
        part = frame[frame.date <= asof]
        if (part.empty or part.date.iloc[-1] != asof or row.get('symbol') != latest['symbol']
                or row.get('method_hash') != method_hash or row.get('status') != 'complete'
                or row.get('source', {}).get('input_hash') != input_identity(part)):
            rejected += 1
            continue
        # Strip nested history so daily revisions do not grow exponentially.
        accepted[asof] = {k: v for k, v in row.items() if k not in ('history', 'stability')}
    history = [accepted[date] for date in sorted(accepted)]
    return {**latest, 'history': history, 'stability': {
        'history': history, 'note': '历史只复用同方法、同截止日前缀的冻结结果；历史重建不等于当时发布。'},
        'execution_scope': 'daily latest endpoint only; historical snapshots reused without refitting'}, rejected


def _profile_completed(run_root):
    count = 0
    for path in (run_root / 'profiles').glob('*.json'):
        if _read(path).get('status') == 'complete':
            count += 1
    return count


def _profile_cache(config, run_root, frame, identity, method_hash, *, store=False):
    """Share exact-key profile cells without changing the frozen runner protocol."""
    shared = config['fit_cache'] / 'profiles'
    sources = [shared]
    if config['seed_study_root']:
        sources.append(config['seed_study_root'] / 'profiles')
    input_hash = input_identity(frame.tail(6600))
    for ahead in long_rolling.PROFILE_GRID:
        for seed in SEEDS:
            expected = {'symbol': identity['symbol'], 'asof': identity['asof'], 'ahead': ahead,
                        'seed': seed, 'input_hash': input_hash, 'method_hash': method_hash}
            key = signature(expected)
            expected['key'] = key
            destination = shared / (key + '.json') if store else run_root / 'profiles' / (key + '.json')
            candidates = [run_root / 'profiles'] if store else sources
            for folder in candidates:
                candidate = folder / (key + '.json')
                if not candidate.is_file():
                    continue
                value = _read(candidate)
                if any(value.get(k) != v for k, v in expected.items()):
                    raise ValueError('Shared profile cache identity mismatch')
                if value.get('status') != 'complete':
                    continue
                # The runner independently checks SSE before using each copied cell.
                _immutable(destination, value)
                break


def _snapshot(state, row):
    payload = {k: v for k, v in row.items() if k not in ('history', 'stability', 'snapshot_path', 'snapshot_version')}
    version = signature(payload)
    relative = Path('snapshots') / payload['symbol'] / payload['asof'] / (version + '.json')
    result = {**payload, 'snapshot_version': version, 'snapshot_path': relative.as_posix()}
    _immutable(state / relative, result)
    first = state / 'snapshots' / payload['symbol'] / (payload['asof'] + '.json')
    if first.exists():
        saved = _read(first)
        if saved.get('symbol') != payload['symbol'] or saved.get('asof') != payload['asof']:
            raise ValueError('First snapshot identity mismatch')
    else:
        _immutable(first, result)
    return result


def _run_locked(value, config, refresh_runner, long_runner, loader, event_collector):
    state = config['long_state_root']
    started = _now()
    audit = {'schema_version': SCHEMA, 'started_at': started, 'status': 'running',
             'publication': 'none', 'historical_sweep': False, 'assets': [], 'activated': False,
             'counts': {'expected_assets': len(config['long_assets']), 'success': 0, 'skipped': 0, 'error': 0,
                        'free_expected': len(config['long_assets']) * len(WINDOWS) * len(SEEDS),
                        'profile_expected': len(config['long_assets']) * len(long_rolling.PROFILE_GRID) * len(SEEDS),
                        'free_completed': 0, 'free_failed': 0, 'free_pending': 0, 'free_cache_reused': 0,
                        'free_not_available': 0, 'profile_not_available': 0,
                        'free_computed_now': 0, 'profile_completed': 0, 'profile_failed': 0,
                        'profile_pending': 0, 'profile_reused': 0, 'profile_computed_now': 0}}
    forwarded = {**value, 'long_root': str(state)}
    current, current_code = refresh_runner(forwarded)
    audit['current'] = current
    current_rows = {row['symbol']: row for row in current.get('assets', [])}
    audit['news'] = []
    for symbol, row in current_rows.items():
        if row.get('status') not in ('updated', 'unchanged') or row.get('source_status') != 'ready':
            continue
        try:
            events = event_collector(symbol, config['source_root'], row['asof'], refresh=True, mode='current')
            audit['news'].append({'symbol': symbol, **{k: events.get(k) for k in
                ('status', 'fetched_at', 'queried_at', 'news_asof', 'stale_reason', 'last_attempt_at')},
                'model_input': False})
        except Exception as error:
            audit['news'].append({'symbol': symbol, 'status': 'error', 'model_input': False,
                                  'error': f'{type(error).__name__}: {error}'})
    previous = _read_summary(state / 'summary.json') if (state / 'summary.json').is_file() else {}
    seed = {}
    if config['seed_study_root'] and (config['seed_study_root'] / 'summary.json').is_file():
        seed = _read_summary(config['seed_study_root'] / 'summary.json')
    method_hash = signature(long_rolling.experiment_method())
    implementation = hashlib.sha256(Path(long_rolling.__file__).read_bytes()).hexdigest()
    assets, candidate_summary = {}, None
    for symbol in config['long_assets']:
        row = {'symbol': symbol, 'status': 'running'}
        audit['assets'].append(row)
        try:
            frame, identity = _verified_input(symbol, config, current_rows.get(symbol, {}), loader)
            run_key = signature({'input': identity, 'method_hash': method_hash, 'runner_sha256': implementation,
                                 'endpoints': 1, 'step': 5, 'profiles': True})
            run_root = state / 'runs' / run_key
            row.update(input=identity, run_root=str(run_root), run_key=run_key)
            saved_path = run_root / 'summary.json'
            result, reused = None, False
            if saved_path.is_file():
                saved = _read(saved_path)
                if saved.get('status') == 'complete':
                    _valid_summary(saved, symbol, identity, method_hash)
                    result, reused = saved, True
            if result is None:
                _profile_cache(config, run_root, frame, identity, method_hash)
            before_profiles = _profile_completed(run_root)
            if result is None:
                result = long_runner(run_root, config['source_root'], assets=(symbol,), endpoints=1, step=5,
                                     workers=config['long_workers'], refresh=False, fit_cache=config['fit_cache'], profiles=True)
            row['fit_counts'], row['profile_counts'] = result.get('counts', {}), result.get('profile_counts', {})
            for prefix, name in (('free', 'counts'), ('profile', 'profile_counts')):
                counts = result.get(name, {})
                for status in ('completed', 'failed', 'pending', 'not_available'):
                    audit['counts'][f'{prefix}_{status}'] += counts.get(status, 0)
            free_reused = result['counts'].get('completed', 0) if reused else result['counts'].get('cache_reused', 0)
            profile_reused = result.get('profile_counts', {}).get('completed', 0) if reused else min(before_profiles, result.get('profile_counts', {}).get('completed', 0))
            audit['counts']['free_cache_reused'] += free_reused
            audit['counts']['profile_reused'] += profile_reused
            audit['counts']['free_computed_now'] += max(0, result['counts'].get('completed', 0) - free_reused)
            audit['counts']['profile_computed_now'] += max(0, result.get('profile_counts', {}).get('completed', 0) - profile_reused)
            latest = _valid_summary(result, symbol, identity, method_hash)
            _profile_cache(config, run_root, frame, identity, method_hash, store=True)
            # A concurrent source change after the fit cannot advance the active summary.
            _, after_identity = _verified_input(symbol, config, current_rows[symbol], loader)
            if after_identity != identity:
                raise ValueError('Source changed during long calculation')
            candidates = [*_history_candidates(seed, symbol), *_history_candidates(previous, symbol)]
            latest, rejected = _attach_history(latest, candidates, frame, method_hash)
            latest['daily_run_root'] = str(run_root)
            assets[symbol] = latest
            row.update(status='skipped' if reused else 'success', reason='same_input_and_method' if reused else 'latest_endpoint_complete',
                       history_attached=len(latest['history']), history_rejected=rejected)
            audit['counts'][row['status']] += 1
        except Exception as error:
            row.update(status='error', error=f'{type(error).__name__}: {error}')
            audit['counts']['error'] += 1
    for prefix in ('free', 'profile'):
        audit['counts'][f'{prefix}_not_run'] = max(0, audit['counts'][f'{prefix}_expected'] -
            sum(audit['counts'][f'{prefix}_{status}'] for status in ('completed', 'failed', 'pending', 'not_available')))
    if not current_code and not audit['counts']['error'] and len(assets) == len(config['long_assets']):
        summary = {'schema_version': 'long_horizon_v1', 'status': 'complete', 'generated_at': _now(),
                   'execution_scope': 'latest endpoint per asset; no historical sweep', 'assets': assets,
                   'method_hash': method_hash, 'counts': {k: audit['counts'][f'free_{k}'] for k in ('completed', 'failed', 'pending')},
                   'profile_counts': {k: audit['counts'][f'profile_{k}'] for k in ('completed', 'failed', 'pending')},
                   'seed_study_root': str(config['seed_study_root']) if config['seed_study_root'] else None}
        summary['counts']['expected'] = len(assets) * len(WINDOWS) * len(SEEDS)
        summary['profile_counts']['expected'] = len(assets) * len(long_rolling.PROFILE_GRID) * len(SEEDS)
        versions = previous.get('archiveversions', {})
        for symbol, latest in assets.items():
            history = [_snapshot(state, row) for row in latest['history']]
            snapshot = _snapshot(state, latest)
            assets[symbol] = {**latest, **snapshot, 'history': history,
                              'stability': {**latest['stability'], 'history': history}}
            versions.setdefault(symbol, {})
            for row in [*history, snapshot]:
                existing = versions[symbol].setdefault(row['asof'], [])
                if row['snapshot_version'] not in existing:
                    existing.append(row['snapshot_version'])
        summary['archiveversions'] = versions
        summary['report_version'] = signature(summary)
        _immutable(state / 'exports' / (summary['report_version'] + '.json'), summary)
        candidate_summary = summary
        audit.update(activated=True, active_report_version=summary['report_version'], status='complete')
    else:
        audit.update(status='partial_failure', last_good_retained=bool(previous),
                     active_report_version=previous.get('report_version'))
    audit['completed_at'] = _now()
    _immutable(state / 'audits' / (signature(audit) + '.json'), audit)
    atomic_json(state / 'latest-attempt.json', audit)
    if candidate_summary is not None:
        atomic_json(state / 'summary.json', candidate_summary)
    return audit, 0 if audit['status'] == 'complete' else 1


def run_config(value, *, dry_run=False, refresh_runner=None, long_runner=None, loader=None, event_collector=None):
    config = parse_config(value)
    if dry_run:
        return {'schema_version': SCHEMA, 'status': 'configuration_valid', 'dry_run': True,
                'symbols': config['symbols'], 'long_assets': config['long_assets'], 'publication': 'none',
                'historical_sweep': False, 'endpoints_per_asset': 1, 'profiles': True,
                'expected_free_fits': len(config['long_assets']) * len(WINDOWS) * len(SEEDS),
                'expected_profiles': len(config['long_assets']) * len(long_rolling.PROFILE_GRID) * len(SEEDS)}, 0
    with global_refresh.refresh_lock(config['long_state_root']):
        try:
            return _run_locked(value, config, refresh_runner or global_refresh.run_config,
                               long_runner or long_rolling.run, loader or load_cached_snapshot,
                               event_collector or collect_market_events)
        except Exception as error:
            audit = {'schema_version': SCHEMA, 'status': 'error', 'activated': False, 'publication': 'none',
                     'historical_sweep': False, 'completed_at': _now(), 'error': f'{type(error).__name__}: {error}',
                     'active_summary_exists': (config['long_state_root'] / 'summary.json').is_file()}
            try:
                _immutable(config['long_state_root'] / 'audits' / (signature(audit) + '.json'), audit)
                atomic_json(config['long_state_root'] / 'latest-attempt.json', audit)
            except OSError as persistence_error:
                audit['audit_persistence_error'] = str(persistence_error)
            return audit, 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not args.config.is_absolute():
        parser.error('--config must be absolute')
    try:
        audit, code = run_config(json.loads(args.config.read_text(encoding='utf-8-sig')), dry_run=args.dry_run)
    except global_refresh.AlreadyRunning as error:
        print(json.dumps({'status': 'already_running', 'error': str(error)}))
        return 75
    except (ValueError, OSError) as error:
        print(json.dumps({'status': 'error', 'error': str(error)}))
        return 2
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
