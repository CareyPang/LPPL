import json

import pandas as pd
import pytest

from research.data import global_terminal as source
from research.data import nasdaq_yfinance
from research.pipeline import global_terminal, nasdaq_data


def snapshot():
    return pd.DataFrame({'date': pd.to_datetime(['2026-11-19', '2026-11-20']),
                         'close': [100.0, 101.0]}), {
        'asof': '2026-11-20', 'source': 'fixture', 'normalized_sha256': 'fixture-hash',
        'fetched_at': '2026-11-20T22:00:00+00:00', 'metadata_file': 'fixture.metadata.json',
        'download_mode': 'incremental_overlap',
    }


def test_cache_only_is_strictly_offline(monkeypatch, tmp_path):
    monkeypatch.setattr(nasdaq_data, 'load_cached_snapshot', lambda *_: snapshot())

    def forbid(*_a, **_k):
        pytest.fail('cache-only attempted a network fetch')

    monkeypatch.setattr(nasdaq_data, 'fetch_snapshot', forbid)
    report, code = nasdaq_data.run(tmp_path, ['US_IXIC'], cache_only=True, minimum_rows=2)
    assert code == 0 and report['assets'][0]['status'] == 'cached'
    assert report['model_execution'] is False and report['publication'] == 'none'
    assert report['assets'][0]['fetch_mode'] == 'incremental_overlap'


def test_failure_preserves_cache_and_continues_other_asset(monkeypatch, tmp_path):
    def fetch(symbol, *_a, **kwargs):
        assert kwargs == dict(refresh=True, full_history=True, minimum_rows=2, provider='yfinance')
        if symbol == 'US_IXIC':
            raise TimeoutError('fixture outage')
        return snapshot()

    monkeypatch.setattr(nasdaq_data, 'fetch_snapshot', fetch)
    monkeypatch.setattr(nasdaq_data, 'load_cached_snapshot', lambda *_: snapshot())
    report, code = nasdaq_data.run(tmp_path, ['US_IXIC', 'US_NDX'], minimum_rows=2)
    assert code == 1
    assert report['assets'][0]['status'] == 'failed_cached_available'
    assert report['assets'][0]['cached_asof'] == '2026-11-20'
    assert report['assets'][1]['status'] == 'updated'
    assert len(list((tmp_path / 'fetch-audit').glob('*.json'))) == 1
    assert json.loads((tmp_path / 'nasdaq_fetch_latest.json').read_text()) == report


def test_short_cache_is_not_reported_as_success(monkeypatch, tmp_path):
    monkeypatch.setattr(nasdaq_data, 'load_cached_snapshot', lambda *_: snapshot())
    report, code = nasdaq_data.run(tmp_path, ['US_NDX'], cache_only=True, minimum_rows=6600)
    assert code == 1 and report['assets'][0]['cached_rows'] == 2


@pytest.mark.parametrize('assets', [[], ['US_IXIC', 'US_IXIC'], ['US_MRVL'], ['sh000300']])
def test_only_requested_nasdaq_indices_are_valid(tmp_path, assets):
    with pytest.raises(ValueError):
        nasdaq_data.run(tmp_path, assets)


def test_nasdaq_primary_transport_does_not_reclassify_other_markets():
    assert global_terminal.primary_provider_for_asset('US_IXIC') == 'yfinance'
    assert global_terminal.primary_provider_for_asset('US_NDX') == 'yfinance'
    assert global_terminal.primary_provider_for_asset('US_SPX') == 'yahoo'
    assert global_terminal.primary_provider_for_asset('KR_SKHYNIX') == 'naver'


def test_legacy_symbol_argument_maps_to_explicit_index_id(monkeypatch, tmp_path):
    calls = []

    def run(root, assets, **kwargs):
        calls.append((root, assets, kwargs))
        return {'status': 'complete'}, 0

    monkeypatch.setattr(nasdaq_data, 'run', run)
    assert nasdaq_data.main(['--root', str(tmp_path), '--symbol', '^NDX']) == 0
    assert calls[0][1] == ['US_NDX']


@pytest.mark.parametrize('asset_id,minimum', [('US_IXIC', 6600), ('US_NDX', 6600), ('US_SPX', None)])
def test_daily_pipeline_requests_required_nasdaq_coverage(monkeypatch, tmp_path, asset_id, minimum):
    calls = []

    def fetch(symbol, root, **kwargs):
        calls.append(kwargs)
        raise RuntimeError('stop before model execution')

    monkeypatch.setattr(global_terminal, 'fetch_snapshot', fetch)
    global_terminal.run(tmp_path, [asset_id], 1, 1, refresh=True)
    assert len(calls) == 1
    assert calls[0]['minimum_rows'] == minimum
    assert calls[0]['full_history'] is (minimum == 6600)
    assert calls[0]['refresh'] is True


@pytest.mark.parametrize('failure', ['timeout', 'too_short', 'lost_old_date'])
def test_failed_fetch_never_replaces_verified_latest(monkeypatch, tmp_path, failure):
    frame, info = snapshot()
    info.update(id='US_IXIC', **source.ASSETS['US_IXIC'], provider='yfinance',
                normalizer_version=nasdaq_yfinance.NORMALIZER_VERSION,
                full_history_requested=True, rows=2, first_date='2026-11-19')
    saved = source.save_snapshot(tmp_path / 'source/US_IXIC', b'{"original":true}', frame, info)
    pointer = tmp_path / 'source/US_IXIC/latest.json'
    before = pointer.read_bytes()

    def failed_download(*args, **kwargs):
        if failure == 'timeout':
            raise TimeoutError('fixture outage')
        incoming = frame.iloc[1:].copy() if failure == 'too_short' else frame.copy()
        if failure == 'lost_old_date':
            incoming.loc[0, 'date'] = pd.Timestamp('2026-11-18')
        return b'{"new":true}', incoming, info

    monkeypatch.setattr(nasdaq_yfinance, 'download_nasdaq', failed_download)
    with pytest.raises((ValueError, TimeoutError)):
        source.fetch_snapshot('US_IXIC', tmp_path, refresh=True, full_history=True,
                              minimum_rows=2, provider='yfinance')
    assert pointer.read_bytes() == before
    restored, metadata = source.load_cached_snapshot('US_IXIC', tmp_path)
    pd.testing.assert_frame_equal(restored, frame)
    assert metadata['normalized_sha256'] == saved['normalized_sha256']
