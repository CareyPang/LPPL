"""Prevent current long-window research leaking into historical model records."""
import hashlib
import json
from copy import deepcopy

from scripts.preview_global_terminal import (
    decorate_long_horizon,
    record_input_hash,
    with_long_horizon,
)


def fixtures():
    record = {'symbol': 'US_NDX', 'asof': '2026-11-20', 'data_version': 'input-a',
              'top': {'scale_clusters': {'2-6y': []}}, 'research': {'cycles_1_5': {'old': True}}}
    study = {'assets': {'US_NDX': {'asof': '2026-11-20', 'source': {'data_version': 'input-a'},
                                  'windows': [{'n': 6600}], 'first_visible_at': 'invalid-backfill'}}}
    return record, study


def test_exact_snapshot_overlay_preserves_original_results():
    record, study = fixtures()
    before = deepcopy(record)
    result = with_long_horizon(record, study)
    assert record == before
    assert result['top'] == before['top']
    assert result['research']['cycles_1_5'] == before['research']['cycles_1_5']
    assert result['research']['long_horizon']['first_visible_at'] is None
    result['research']['long_horizon']['windows'].clear()
    assert study['assets']['US_NDX']['windows'] == [{'n': 6600}]


def test_history_identity_and_data_revision_do_not_fall_back_to_current():
    record, study = fixtures()
    for key, value in [('asof', '2026-11-13'), ('symbol', 'US_IXIC'), ('data_version', 'input-b')]:
        changed = {**record, key: value}
        assert 'long_horizon' not in with_long_horizon(changed, study)['research']
    del study['assets']['US_NDX']['source']['data_version']
    assert 'long_horizon' not in with_long_horizon(record, study)['research']


def test_comparison_is_also_exact_asof():
    record, study = fixtures()
    comp = {'assets': {'US_NDX': {'asof': '2026-11-19', 'data_version': 'input-a', 'windows': []}}}
    assert 'g3_comparison' not in with_long_horizon(record, study, comp)['research']['long_horizon']
    comp['assets']['US_NDX']['asof'] = record['asof']
    assert with_long_horizon(record, study, comp)['research']['long_horizon']['g3_comparison']['windows'] == []
    comp['assets']['US_NDX']['data_version'] = 'input-b'
    assert 'g3_comparison' not in with_long_horizon(record, study, comp)['research']['long_horizon']


def test_incomplete_study_does_not_break_existing_prices():
    record, study = fixtures()
    for payload in [[], {'assets': []}, {}]:
        assert with_long_horizon(record, payload) == record
    study['assets']['US_NDX']['source'] = 'legacy text'
    assert with_long_horizon(record, study) == record


def test_profile_diagnostics_are_not_backfilled_into_other_vintages():
    record, study = fixtures()
    profile = {'assets': {'US_NDX': {'asof': '2026-11-20', 'data_version': 'input-a', 'points': []}}}
    assert with_long_horizon(record, study, profile=profile)['research']['long_horizon']['profile_diagnostic']['points'] == []
    profile['assets']['US_NDX']['asof'] = '2026-11-19'
    assert 'profile_diagnostic' not in with_long_horizon(record, study, profile=profile)['research']['long_horizon']


def test_corrupt_optional_long_summary_preserves_primary_result(tmp_path):
    record, _ = fixtures()
    (tmp_path / 'summary.json').write_text('{incomplete', encoding='utf-8')
    result = decorate_long_horizon(record, tmp_path)
    assert result['top'] == record['top']
    assert result['research']['cycles_1_5'] == record['research']['cycles_1_5']
    assert result['research']['long_horizon_load_error']['status'] == 'failed'
    assert 'long_horizon_load_error' not in record['research']


def rolling_fixture(asof='2026-11-13', symbol='KR_KOSPI'):
    record = {'symbol': symbol, 'asof': asof, 'data_version': 'old-whole-file',
              'price_history': {'dates': ['2026-11-12', asof], 'close': [100., 101.]},
              'top': {'preserve': True}, 'research': {}}
    snapshot = {'schema_version': 'long_horizon_v1', 'symbol': symbol, 'asof': asof,
                'source': {'data_version': 'new-whole-file', 'input_hash': record_input_hash(record)},
                'windows': [], 'counts': {'expected': 12, 'completed': 12}}
    return record, snapshot


def test_prefix_hash_accepts_identical_asof_input_after_whole_file_extended():
    record, snapshot = rolling_fixture()
    result = with_long_horizon(record, {'assets': {'KR_KOSPI': snapshot}})
    assert result['research']['long_horizon']['symbol'] == 'KR_KOSPI'
    assert result['top'] == record['top']
    assert record['research'] == {}


def test_prefix_hash_rejects_revision_even_if_top_level_data_version_matches():
    record, snapshot = rolling_fixture()
    snapshot['source']['data_version'] = record['data_version']
    record['price_history']['close'][-1] = 102.
    assert 'long_horizon' not in with_long_horizon(record, {'assets': {'KR_KOSPI': snapshot}})['research']


def test_longer_history_cannot_attach_to_a_truncated_old_prefix():
    record, snapshot = rolling_fixture()
    full = deepcopy(record)
    full['price_history']['dates'].insert(0, '2026-11-11')
    full['price_history']['close'].insert(0, 99.)
    snapshot['source']['input_hash'] = record_input_hash(full)
    assert 'long_horizon' not in with_long_horizon(record, {'assets': {'KR_KOSPI': snapshot}})['research']


def test_future_or_malformed_price_rows_do_not_pass_prefix_verification():
    record, _ = rolling_fixture()
    for dates, closes in [(['2026-11-12', '2026-11-20'], [100., 101.]),
                          (['2026-11-13', '2026-11-13'], [100., 101.]),
                          ([['2026-11-12'], '2026-11-13'], [100., 101.]),
                          (['2026-11-12', '2026-11-13'], [100., float('nan')])]:
        assert record_input_hash({**record, 'price_history': {'dates': dates, 'close': closes}}) is None


def test_exact_rolling_snapshot_selected_without_newer_profile_or_history(tmp_path):
    record, historical = rolling_fixture()
    _, current = rolling_fixture('2026-11-20')
    current['profile_diagnostic'] = {'asof': '2026-11-20', 'n': 6600, 'future': True}
    earlier_record = {**record, 'asof': '2026-11-12',
                      'price_history': {'dates': ['2026-11-12'], 'close': [100.]}}
    current['history'] = [{'symbol': 'KR_KOSPI', 'asof': '2026-11-12',
                           'source': {'input_hash': record_input_hash(earlier_record)}}, historical,
                          {'symbol': 'KR_KOSPI', 'asof': '2026-11-19'},
                          {'symbol': 'US_NDX', 'asof': '2026-11-06'}]
    (tmp_path / 'summary.json').write_text(json.dumps({'assets': {'KR_KOSPI': current}}))
    folder = tmp_path / 'snapshots/KR_KOSPI'
    folder.mkdir(parents=True)
    (folder / '2026-11-13.json').write_text(json.dumps(historical))
    result = decorate_long_horizon(record, tmp_path)['research']['long_horizon']
    assert result['asof'] == '2026-11-13'
    assert 'profile_diagnostic' not in result
    assert [r['asof'] for r in result['stability']['history']] == ['2026-11-12']


def test_current_snapshot_can_receive_same_asof_profile_from_final_summary(tmp_path):
    record, snapshot = rolling_fixture()
    latest = {**snapshot, 'profile_diagnostic': {'asof': snapshot['asof'], 'n': 6600}}
    (tmp_path / 'summary.json').write_text(json.dumps({'assets': {'KR_KOSPI': latest}}))
    folder = tmp_path / 'snapshots/KR_KOSPI'
    folder.mkdir(parents=True)
    (folder / '2026-11-13.json').write_text(json.dumps(snapshot))
    result = decorate_long_horizon(record, tmp_path)['research']['long_horizon']
    assert result['profile_diagnostic']['asof'] == snapshot['asof']


def test_missing_exact_snapshot_never_falls_back_to_current(tmp_path):
    record, _ = rolling_fixture()
    _, current = rolling_fixture('2026-11-20')
    (tmp_path / 'summary.json').write_text(json.dumps({'assets': {'KR_KOSPI': current}}))
    assert 'long_horizon' not in decorate_long_horizon(record, tmp_path)['research']


def test_same_date_revision_uses_matching_version_pointer_but_old_input_keeps_original(tmp_path):
    original_record, original = rolling_fixture()
    revised_record = deepcopy(original_record)
    revised_record['price_history']['close'][-1] = 102.
    revised = deepcopy(original)
    revised['source']['input_hash'] = record_input_hash(revised_record)
    revised['revision_marker'] = 'revised'
    revised['snapshot_path'] = 'snapshots/KR_KOSPI/2026-11-13/revised.json'
    folder = tmp_path / 'snapshots/KR_KOSPI'
    (folder / '2026-11-13').mkdir(parents=True)
    (folder / '2026-11-13.json').write_text(json.dumps(original))
    (tmp_path / revised['snapshot_path']).write_text(json.dumps(revised))
    (tmp_path / 'summary.json').write_text(json.dumps({'assets': {'KR_KOSPI': revised}}))
    result = decorate_long_horizon(revised_record, tmp_path)['research']['long_horizon']
    assert result['revision_marker'] == 'revised'
    old = decorate_long_horizon(original_record, tmp_path)['research']['long_horizon']
    assert 'revision_marker' not in old
    assert old['source']['input_hash'] == original['source']['input_hash']


def test_version_pointer_cannot_escape_root_or_replace_cutoff(tmp_path):
    record, snapshot = rolling_fixture()
    snapshot['snapshot_path'] = '../outside.json'
    (tmp_path / 'summary.json').write_text(json.dumps({'assets': {'KR_KOSPI': snapshot}}))
    result = decorate_long_horizon(record, tmp_path)
    assert 'long_horizon' not in result['research']
    assert result['research']['long_horizon_load_error']['status'] == 'failed'


def test_versioned_snapshot_checks_content_not_just_source_hash(tmp_path):
    record, snapshot = rolling_fixture()
    version = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    snapshot.update(snapshot_version=version, snapshot_path=f'snapshots/KR_KOSPI/2026-11-13/{version}.json')
    path = tmp_path / snapshot['snapshot_path']
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(snapshot))
    (tmp_path / 'summary.json').write_text(json.dumps({'assets': {'KR_KOSPI': snapshot}}))
    assert decorate_long_horizon(record, tmp_path)['research']['long_horizon']['snapshot_version'] == version
    changed = {**snapshot, 'windows': [{'n': 6600, 'fake_parameters': True}]}
    path.write_text(json.dumps(changed))
    result = decorate_long_horizon(record, tmp_path)
    assert 'long_horizon' not in result['research']
    assert 'content hash mismatch' in result['research']['long_horizon_load_error']['reason']


def test_summary_hash_failure_preserves_model_and_does_not_display_history(tmp_path):
    record, snapshot = rolling_fixture()
    summary = {'assets': {'KR_KOSPI': snapshot}, 'report_version': 'corrupted'}
    (tmp_path / 'summary.json').write_text(json.dumps(summary))
    result = decorate_long_horizon(record, tmp_path)
    assert result['top'] == record['top']
    assert 'long_horizon' not in result['research']
    assert result['research']['long_horizon_load_error']['status'] == 'failed'


def test_valid_new_summary_cannot_inject_revised_history_into_old_first_snapshot(tmp_path):
    record, original = rolling_fixture()
    record['price_history'] = {'dates': ['2026-11-11', '2026-11-12', '2026-11-13'],
                               'close': [99., 100., 101.]}
    original['source']['input_hash'] = record_input_hash(record)
    original['snapshot_version'] = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    first = tmp_path / 'snapshots/KR_KOSPI/2026-11-13.json'
    first.parent.mkdir(parents=True)
    first.write_text(json.dumps(original))
    before = first.read_bytes()
    revised_record = deepcopy(record)
    revised_record['price_history']['close'][1] = 100.5
    revised = {**original, 'source': {'input_hash': record_input_hash(revised_record)}}
    good_prefix = {**record, 'asof': '2026-11-11',
                   'price_history': {'dates': ['2026-11-11'], 'close': [99.]}}
    revised_prefix = {**record, 'asof': '2026-11-12',
                      'price_history': {'dates': ['2026-11-11', '2026-11-12'], 'close': [99., 100.5]}}
    revised['history'] = [
        {'symbol': record['symbol'], 'asof': '2026-11-11',
         'source': {'input_hash': record_input_hash(good_prefix)}},
        {'symbol': record['symbol'], 'asof': '2026-11-12',
         # Even an equal whole-file ID cannot override a mismatching prefix hash.
         'source': {'input_hash': record_input_hash(revised_prefix), 'data_version': record['data_version']}},
    ]
    revised_payload = {k: v for k, v in revised.items() if k not in ('history', 'snapshot_version')}
    revised_version = hashlib.sha256(json.dumps(revised_payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    revised.update(snapshot_version=revised_version,
                   snapshot_path=f'snapshots/KR_KOSPI/2026-11-13/{revised_version}.json')
    revised_path = tmp_path / revised['snapshot_path']
    revised_path.parent.mkdir(parents=True)
    revised_path.write_text(json.dumps({k: v for k, v in revised.items() if k != 'history'}))
    summary = {'assets': {'KR_KOSPI': revised}}
    summary['report_version'] = hashlib.sha256(json.dumps(summary, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    (tmp_path / 'summary.json').write_text(json.dumps(summary))
    output = decorate_long_horizon(record, tmp_path)
    study = output['research']['long_horizon']
    assert study['source']['input_hash'] == original['source']['input_hash']
    assert [row['asof'] for row in study['history']] == ['2026-11-11']
    assert study['history'] == study['stability']['history']
    assert study['stability']['excluded_history_rows'] == 1
    assert '已排除 1 期' in study['stability']['note']
    assert first.read_bytes() == before and output['top'] == record['top']


def test_embedded_legacy_history_requires_same_version_and_an_observed_cutoff():
    record, snapshot = rolling_fixture()
    snapshot['history'] = [
        {'symbol': record['symbol'], 'asof': '2026-11-12', 'source': {'data_version': record['data_version']}},
        {'symbol': record['symbol'], 'asof': '2026-11-12', 'source': {'data_version': 'different-vintage'}},
        {'symbol': record['symbol'], 'asof': '2026-11-11', 'source': {'data_version': record['data_version']}},
    ]
    result = with_long_horizon(record, {'assets': {record['symbol']: snapshot}})['research']['long_horizon']
    assert result['history'] == snapshot['history'][:1]
    assert result['stability']['excluded_history_rows'] == 2
    assert len(snapshot['history']) == 3  # The source archive remains unchanged.
