"""Daily current/long orchestration without real network, models or scheduling."""
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.pipeline import global_daily as daily
from research.pipeline.global_terminal import atomic_json
from research.pipeline.long_horizon import input_identity, signature


@pytest.fixture
def config(tmp_path):
    return {**{name: str(tmp_path / name) for name in
               ('source_root', 'jobs_root', 'state_root', 'long_state_root', 'fit_cache')},
            'symbols': list(daily.long_rolling.DEFAULT_ASSETS),
            'long_assets': list(daily.long_rolling.DEFAULT_ASSETS),
            'minimum_rows': {s: 6700 for s in daily.long_rolling.DEFAULT_ASSETS}}


@pytest.fixture
def harness(config, monkeypatch):
    monkeypatch.setattr(daily.long_rolling, 'experiment_method', lambda: {'test': 'frozen-method'})
    method_hash = signature({'test': 'frozen-method'})
    data = {s: pd.DataFrame({'date': pd.bdate_range(end='2026-11-20', periods=6800),
                            'close': np.linspace(100., 200., 6800)}) for s in config['symbols']}
    versions = {s: 'v1' for s in data}
    failures, failed_profiles, bad_inputs, news_failures = set(), set(), set(), set()
    calls = {'current': [], 'long': [], 'news': []}

    def load(symbol, root):
        frame = data[symbol].copy()
        return frame, {'id': symbol, 'asof': str(frame.date.iloc[-1].date()),
                       'normalized_sha256': 'mismatched' if symbol in bad_inputs else versions[symbol]}

    def current(value):
        calls['current'].append(value)
        return {'assets': [{'symbol': s, 'status': 'failed' if s in failures else 'unchanged',
            'source_status': 'stale' if s in failures else 'ready', 'asof': str(data[s].date.iloc[-1].date()),
            'data_version': versions[s]} for s in data]}, 1 if failures else 0

    def asset(symbol, asof=None):
        frame = data[symbol].copy()
        frame.date = frame.date.dt.strftime('%Y-%m-%d')
        day = asof or frame.date.iloc[-1]
        return {'symbol': symbol, 'asof': day, 'status': 'complete', 'method_hash': method_hash,
                'source': {'data_version': versions[symbol], 'input_hash': input_identity(frame[frame.date <= day])},
                'first_visible_at': None, 'windows': [{'n': 6600, 'test_value': 1}], 'history': [],
                'counts': {'expected': 12, 'completed': 12, 'failed': 0, 'pending': 0}}

    def run(root, source_root, **kwargs):
        symbol = kwargs['assets'][0]
        calls['long'].append((Path(root), symbol, kwargs))
        result = {'status': 'incomplete' if symbol in failed_profiles else 'complete',
                  'counts': {'expected': 12, 'completed': 12, 'failed': 0, 'pending': 0, 'cache_reused': 2},
                  'profile_counts': {'expected': 62, 'completed': 61 if symbol in failed_profiles else 62,
                                     'failed': 1 if symbol in failed_profiles else 0, 'pending': 0},
                  'assets': {symbol: asset(symbol)}}
        result['report_version'] = signature(result)
        atomic_json(Path(root) / 'summary.json', result)
        return result

    def news(symbol, root, asof, **kwargs):
        calls['news'].append((symbol, asof, kwargs))
        if symbol in news_failures:
            raise OSError('news unavailable')
        return {'status': 'ok', 'fetched_at': '2026-11-23T00:30:00+00:00'}

    def execute():
        return daily.run_config(config, refresh_runner=current, long_runner=run, loader=load, event_collector=news)

    return dict(data=data, versions=versions, failures=failures, failed_profiles=failed_profiles,
                bad_inputs=bad_inputs, news_failures=news_failures, calls=calls, asset=asset,
                run=execute, method_hash=method_hash)


def test_dry_run_has_no_files_network_models_or_news(config, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail('dry run invoked an external action')
    result, code = daily.run_config(config, dry_run=True, refresh_runner=forbidden,
                                   long_runner=forbidden, loader=forbidden, event_collector=forbidden)
    assert code == 0 and result['expected_free_fits'] == 48 and result['expected_profiles'] == 248
    assert result['endpoints_per_asset'] == 1 and result['historical_sweep'] is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('change', [
    {'long_state_root': 'relative'}, {'fit_cache': 'relative'}, {'long_assets': []},
    {'long_assets': ['US_IXIC', 'US_IXIC']}, {'long_assets': ['US_MRVL']},
    {'long_assets': [{}]},
    {'long_workers': True}, {'long_workers': 0}, {'long_workers': 33},
])
def test_invalid_daily_configuration(config, change):
    with pytest.raises(ValueError):
        daily.parse_config({**config, **change})


def test_latest_only_current_and_long_sync_complete(config, harness):
    result, code = harness['run']()
    assert code == 0 and result['activated'] is True and result['counts']['success'] == 4
    assert result['counts']['free_completed'] == 48 and result['counts']['profile_completed'] == 248
    assert result['counts']['free_cache_reused'] == 8 and result['counts']['free_computed_now'] == 40
    assert all(c[2]['endpoints'] == 1 and c[2]['step'] == 5 and c[2]['profiles'] for c in harness['calls']['long'])
    assert all(c[2]['fit_cache'] == Path(config['fit_cache']) for c in harness['calls']['long'])
    assert harness['calls']['current'][0]['long_root'] == config['long_state_root']
    root = Path(config['long_state_root'])
    summary = json.loads((root / 'summary.json').read_text(encoding='utf-8'))
    assert len(summary['assets']) == 4 and summary['counts']['expected'] == 48
    for symbol, row in summary['assets'].items():
        snapshot = json.loads((root / row['snapshot_path']).read_text(encoding='utf-8'))
        assert snapshot['source'] == row['source']
        assert snapshot['snapshot_version'] == signature({k: v for k, v in snapshot.items()
                                                         if k not in ('snapshot_path', 'snapshot_version')})
        assert (root / 'snapshots' / symbol / (row['asof'] + '.json')).is_file()


def test_unchanged_inputs_skip_all_long_models_but_still_refresh_news(harness):
    harness['run']()
    result, code = harness['run']()
    assert code == 0 and result['counts']['skipped'] == 4
    assert len(harness['calls']['long']) == 4
    assert result['counts']['free_computed_now'] == result['counts']['profile_computed_now'] == 0
    assert len(harness['calls']['news']) == 8


def test_same_asof_revision_is_new_run_and_append_only_snapshot(config, harness):
    harness['run']()
    root = Path(config['long_state_root'])
    first = root / 'snapshots/US_IXIC/2026-11-20.json'
    original = first.read_bytes()
    harness['versions']['US_IXIC'] = 'v2'
    harness['data']['US_IXIC'].loc[0, 'close'] += .1
    result, code = harness['run']()
    assert code == 0 and result['counts']['success'] == 1 and result['counts']['skipped'] == 3
    assert first.read_bytes() == original
    assert len(list((root / 'snapshots/US_IXIC/2026-11-20').glob('*.json'))) == 2
    assert len(json.loads((root / 'summary.json').read_text(encoding='utf-8'))['archiveversions']['US_IXIC']['2026-11-20']) == 2


@pytest.mark.parametrize('failure', ['failures', 'bad_inputs', 'failed_profiles'])
def test_failed_asset_or_profile_retains_previous_active_summary(config, harness, failure):
    harness['run']()
    path = Path(config['long_state_root']) / 'summary.json'
    previous = path.read_bytes()
    harness['versions']['US_IXIC'] = 'v2'
    harness[failure].add('US_IXIC')
    result, code = harness['run']()
    assert code == 1 and not result['activated'] and result['counts']['error'] == 1
    assert result['last_good_retained'] is True and path.read_bytes() == previous
    assert result['counts']['skipped'] == 3


def test_seed_history_only_same_prefix_same_method_and_strictly_older(config, harness, tmp_path):
    seed = tmp_path / 'seed'
    config['seed_study_root'] = str(seed)
    asset = harness['asset']('US_IXIC')
    good = harness['asset']('US_IXIC', '2026-11-19')
    bad_prefix = harness['asset']('US_IXIC', '2026-11-18')
    bad_prefix['source']['input_hash'] = 'different-prefix'
    future = {**deepcopy(asset), 'asof': '2026-11-23'}
    asset['history'] = [good, bad_prefix, future]
    report = {'status': 'complete', 'assets': {'US_IXIC': asset}}
    report['report_version'] = signature(report)
    atomic_json(seed / 'summary.json', report)
    original = (seed / 'summary.json').read_bytes()
    result, code = harness['run']()
    assert code == 0 and result['assets'][0]['history_attached'] == 1
    summary = json.loads((Path(config['long_state_root']) / 'summary.json').read_text(encoding='utf-8'))
    history = summary['assets']['US_IXIC']['history']
    assert [r['asof'] for r in history] == ['2026-11-19']
    assert (Path(config['long_state_root']) / history[0]['snapshot_path']).is_file()
    assert (seed / 'summary.json').read_bytes() == original


def test_tampered_prior_summary_is_not_used_to_invent_verified_history(config, harness):
    harness['run']()
    path = Path(config['long_state_root']) / 'summary.json'
    saved = json.loads(path.read_text(encoding='utf-8'))
    saved['assets']['US_IXIC']['windows'][0]['test_value'] = 2
    path.write_text(json.dumps(saved))
    tampered = path.read_bytes()
    result, code = harness['run']()
    assert code == 1 and result['status'] == 'error'
    assert 'hash mismatch' in result['error'] and path.read_bytes() == tampered
    assert (path.parent / 'latest-attempt.json').is_file()


def test_news_failure_does_not_block_source_or_model_activation(harness):
    harness['news_failures'].add('US_IXIC')
    result, code = harness['run']()
    assert code == 0 and result['activated'] is True
    assert result['news'][0]['status'] == 'error'
    assert all(row['model_input'] is False for row in result['news'])
    assert all(call[2] == {'refresh': True, 'mode': 'current'} for call in harness['calls']['news'])


def test_archive_failure_before_activation_keeps_last_good_and_records_failure(config, harness, monkeypatch):
    harness['run']()
    state = Path(config['long_state_root'])
    original = (state / 'summary.json').read_bytes()
    writer = daily._immutable

    def fail_export(path, value):
        if path.parent.name == 'exports':
            raise OSError('disk unavailable for new export')
        return writer(path, value)

    monkeypatch.setattr(daily, '_immutable', fail_export)
    result, code = harness['run']()
    assert code == 1 and not result['activated']
    assert (state / 'summary.json').read_bytes() == original
    assert 'disk unavailable' in json.loads((state / 'latest-attempt.json').read_text(encoding='utf-8'))['error']


def test_daily_lock_blocks_overlapping_current_and_long_refresh(config, harness):
    with daily.global_refresh.refresh_lock(Path(config['long_state_root'])):
        with pytest.raises(daily.global_refresh.AlreadyRunning):
            harness['run']()
    assert harness['calls']['current'] == []


def test_profile_cells_are_shared_only_for_exact_asset_cutoff_input_and_method(config, harness, tmp_path):
    parsed = daily.parse_config(config)
    frame = harness['data']['US_IXIC'].copy()
    frame.date = frame.date.dt.strftime('%Y-%m-%d')
    identity = {'symbol': 'US_IXIC', 'asof': '2026-11-20'}
    expected = {**identity, 'ahead': daily.long_rolling.PROFILE_GRID[0], 'seed': daily.SEEDS[0],
                'input_hash': input_identity(frame.tail(6600)), 'method_hash': harness['method_hash']}
    expected['key'] = signature(expected)
    cell = {**expected, 'status': 'complete', 'fit': {'sse': .1}}
    shared = Path(config['fit_cache']) / 'profiles' / (expected['key'] + '.json')
    atomic_json(shared, cell)
    run_root = tmp_path / 'run'
    daily._profile_cache(parsed, run_root, frame, identity, harness['method_hash'])
    assert json.loads((run_root / 'profiles' / shared.name).read_text(encoding='utf-8')) == cell
    daily._profile_cache(parsed, run_root, frame, identity, harness['method_hash'], store=True)
    changed = tmp_path / 'changed'
    frame.loc[6799, 'close'] += .1
    daily._profile_cache(parsed, changed, frame, identity, harness['method_hash'])
    assert not changed.exists()
