"""Full daily-history coverage contracts; small fixtures do not represent markets."""
import json
from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest

from research.data import global_terminal as source


def payload(dates=('1999-12-30', '2000-01-03', '2000-01-04'), close=None, interval='1d'):
    n = len(dates)
    return {'chart': {'error': None, 'result': [{
        'meta': {'symbol': '^IXIC', 'exchangeTimezoneName': 'America/New_York',
                 'currency': 'USD', 'dataGranularity': interval},
        'timestamp': [int(datetime.fromisoformat(d + 'T14:30:00+00:00').timestamp()) for d in dates],
        'indicators': {'quote': [{'open': [100.] * n, 'high': [110.] * n, 'low': [90.] * n,
                                  'close': close or [101.] * n, 'volume': [1000.] * n}]},
    }]}}


def response(monkeypatch, data):
    calls = []

    def get(url, params, **kwargs):
        calls.append(dict(params))

        class Response:
            content = json.dumps(data).encode()
            status_code = 200

            def json(self):
                return data

            def raise_for_status(self):
                pass

        item = Response()
        item.url = url + '?' + urlencode(params)
        return item

    monkeypatch.setattr(source.requests, 'get', get)
    return calls


def test_full_history_uses_explicit_period_daily_and_retains_source_identity(monkeypatch, tmp_path):
    calls = response(monkeypatch, payload())
    frame, info = source.fetch_snapshot('US_IXIC', tmp_path, full_history=True, minimum_rows=3)
    assert calls[0]['period1'] == -2208988800
    assert calls[0]['interval'] == '1d' and 'range' not in calls[0]
    assert len(frame) == 3 and info['first_date'] == '1999-12-30'
    assert info['asof'] == '2000-01-04'
    assert info['timezone'] == 'America/New_York'
    assert datetime.fromisoformat(info['fetched_at']).tzinfo is not None
    assert info['coverage_scope'] == 'provider_available_daily_history'
    assert info['history_vintage'] == 'current_download_reconstruction'
    assert info['public_redistribution'] == 'NOT_ESTABLISHED'


def test_full_history_cache_read_makes_no_request_and_rechecks_minimum(monkeypatch, tmp_path):
    calls = response(monkeypatch, payload())
    first, info = source.fetch_snapshot('US_IXIC', tmp_path, full_history=True)
    second, cached = source.fetch_snapshot('US_IXIC', tmp_path, full_history=True, minimum_rows=3)
    assert len(calls) == 1 and first.to_dict('records') == second.to_dict('records') and cached == info
    with pytest.raises(ValueError, match='required 4, received 3'):
        source.fetch_snapshot('US_IXIC', tmp_path, full_history=True, minimum_rows=4)
    assert len(calls) == 1


def test_upgrade_preserves_previous_vintage_and_later_refresh_keeps_full_scope(monkeypatch, tmp_path):
    response(monkeypatch, payload(('2000-01-03', '2000-01-04')))
    _, old = source.fetch_snapshot('US_IXIC', tmp_path)
    folder = tmp_path / 'source' / 'US_IXIC'
    old_raw = (folder / old['raw_file']).read_bytes()
    old_normalized = (folder / old['normalized_file']).read_bytes()
    calls = response(monkeypatch, payload())
    full, new = source.fetch_snapshot('US_IXIC', tmp_path, full_history=True, minimum_rows=3)
    assert len(calls) == 1 and len(full) == 3
    assert new['normalized_sha256'] != old['normalized_sha256']
    assert (folder / old['raw_file']).read_bytes() == old_raw
    assert (folder / old['normalized_file']).read_bytes() == old_normalized
    assert (folder / old['metadata_file']).is_file()
    source.fetch_snapshot('US_IXIC', tmp_path, refresh=True)
    assert calls[-1]['period1'] == source.FULL_HISTORY_PERIOD1


def test_insufficient_fresh_response_is_archived_as_rejection_without_latest(monkeypatch, tmp_path):
    response(monkeypatch, payload())
    with pytest.raises(ValueError, match='Insufficient daily history'):
        source.fetch_snapshot('US_IXIC', tmp_path, full_history=True, minimum_rows=6700)
    folder = tmp_path / 'source' / 'US_IXIC'
    assert not (folder / 'latest.json').exists()
    rejections = list((folder / 'rejected').glob('*.json'))
    assert len(rejections) == 2
    audit = next(json.loads(p.read_text(encoding='utf-8')) for p in rejections if not p.name.endswith('.raw.json'))
    assert audit['rows'] == 3 and audit['latest_pointer_updated'] is False


@pytest.mark.parametrize('missing_dates', [('2000-01-03', '2000-01-04'), ('1999-12-30', '2000-01-04')])
def test_refresh_truncation_or_internal_date_loss_does_not_replace_accepted_source(monkeypatch, tmp_path, missing_dates):
    response(monkeypatch, payload())
    source.fetch_snapshot('US_IXIC', tmp_path, full_history=True)
    pointer = tmp_path / 'source' / 'US_IXIC' / 'latest.json'
    old_pointer = pointer.read_bytes()
    response(monkeypatch, payload(missing_dates))
    with pytest.raises(ValueError, match='coverage regressed'):
        source.fetch_snapshot('US_IXIC', tmp_path, refresh=True)
    assert pointer.read_bytes() == old_pointer


def test_revised_close_is_new_vintage_not_retroactive_overwrite(monkeypatch, tmp_path):
    response(monkeypatch, payload())
    _, before = source.fetch_snapshot('US_IXIC', tmp_path, full_history=True)
    response(monkeypatch, payload(close=[102., 101., 101.]))
    _, after = source.fetch_snapshot('US_IXIC', tmp_path, refresh=True)
    assert before['normalized_sha256'] != after['normalized_sha256']
    assert before['metadata_file'] != after['metadata_file']


def test_non_daily_provider_response_is_not_accepted_as_thousands_of_sessions(monkeypatch, tmp_path):
    response(monkeypatch, payload(interval='1mo'))
    with pytest.raises(ValueError, match='non-daily'):
        source.fetch_snapshot('US_IXIC', tmp_path, full_history=True)


@pytest.mark.parametrize('minimum', [0, -1, 2.5, True, '6700'])
def test_invalid_minimum_rejected_without_network(monkeypatch, tmp_path, minimum):
    calls = response(monkeypatch, payload())
    with pytest.raises(ValueError, match='positive integer'):
        source.fetch_snapshot('US_IXIC', tmp_path, minimum_rows=minimum)
    assert calls == []


def test_future_partial_session_still_removed_from_full_history(monkeypatch, tmp_path):
    p = payload(('2026-11-19', '2026-11-20'))
    frame, info = source.normalise(p, 'US_IXIC', datetime(2026, 11, 20, 18, tzinfo=UTC))
    assert frame.date.dt.strftime('%Y-%m-%d').tolist() == ['2026-11-19']
    assert info['dropped_unclosed_bars'] == 1


def naver_payload(dates=('19960702', '19960706', '20011101'), closes=(1000., 1001., 625.5)):
    return [['날짜', '시가', '고가', '저가', '종가', '거래량', '외국인소진율'],
            *[[date, close, close, close, close, 100, 0.] for date, close in zip(dates, closes, strict=True)]]


def test_kosdaq_full_history_selects_whole_naver_source_and_retains_saturdays(monkeypatch, tmp_path):
    calls = response(monkeypatch, naver_payload())
    frame, info = source.fetch_snapshot('KR_KOSDAQ', tmp_path, full_history=True, minimum_rows=3)
    assert calls[0]['symbol'] == 'KOSDAQ' and calls[0]['timeframe'] == 'day'
    assert calls[0]['startTime'] == '19000101'
    assert frame.date.dt.strftime('%Y%m%d').tolist() == ['19960702', '19960706', '20011101']
    assert info['provider'] == 'naver' and info['ticker'] == '^KQ11'
    assert info['normalizer_version'] == source.NAVER_NORMALIZER_VERSION
    assert info['data_quality']['status'] == 'unresolved_cross_source_discrepancy'
    assert info['data_quality']['current_source_close'] == 625.5
    source.fetch_snapshot('KR_KOSDAQ', tmp_path, refresh=True)
    assert calls[-1]['startTime'] == '19000101'


def test_hynix_defaults_to_naver_and_allows_yahoo_primary_for_cross_check(monkeypatch, tmp_path):
    calls = response(monkeypatch, naver_payload())
    frame, info = source.fetch_snapshot('KR_SKHYNIX', tmp_path, full_history=True)

    assert calls[0]['symbol'] == '000660'
    assert info['ticker'] == '000660.KS' and info['kind'] == 'stock'
    assert info['exchange'] == 'KRX KOSPI' and info['currency'] == 'KRW'
    assert info['data_quality']['status'] == 'provider_price_basis'
    assert 'index_level_basis' not in info
    assert frame.close.tolist() == [1000., 1001., 625.5]

    yahoo_payload = payload()
    yahoo_payload['chart']['result'][0]['meta'].update(
        symbol='000660.KS', exchangeTimezoneName='Asia/Seoul', currency='KRW'
    )
    yahoo_payload['chart']['result'][0]['indicators']['adjclose'] = [
        {'adjclose': [100., 101., 102.]}
    ]
    yahoo_calls = response(monkeypatch, yahoo_payload)
    yahoo_frame, yahoo_info = source.fetch_snapshot(
        'KR_SKHYNIX', tmp_path / 'yahoo', full_history=True, provider='yahoo'
    )
    assert len(yahoo_calls) == 1
    assert yahoo_calls[0]['interval'] == '1d'
    assert yahoo_info['provider'] == 'yahoo'
    assert yahoo_info['ticker'] == '000660.KS'
    assert len(yahoo_frame) == 3
    assert len(calls) == 1


def test_kosdaq_provider_transition_preserves_yahoo_vintage_and_material_difference(monkeypatch, tmp_path):
    old_data = payload(('2001-11-01',), close=[636.4000244140625])
    old_data['chart']['result'][0]['meta'].update(symbol='^KQ11', exchangeTimezoneName='Asia/Seoul', currency='KRW')
    response(monkeypatch, old_data)
    _, old = source.fetch_snapshot('KR_KOSDAQ', tmp_path, full_history=True, provider='yahoo')
    response(monkeypatch, naver_payload())
    frame, new = source.fetch_snapshot('KR_KOSDAQ', tmp_path, full_history=True)
    folder = tmp_path / 'source' / 'KR_KOSDAQ'
    assert (folder / old['metadata_file']).is_file() and (folder / old['normalized_file']).is_file()
    assert new['normalized_sha256'] != old['normalized_sha256']
    comparison = new['previous_vintage_comparison']
    assert new['provider_changed'] is True and comparison['previous_provider'] == 'yahoo'
    assert comparison['close_changes_at_two_decimals'] == 1
    assert comparison['material_close_difference_samples'][0]['new_close'] == 625.5
    assert frame.close.iloc[-1] == 625.5  # No vendor mixing or silent correction.


@pytest.mark.parametrize('bad', [
    [['wrong', 'header']],
    naver_payload(('19960702', '19960702', '20011101')),
    naver_payload(('19960706', '19960702', '20011101')),
    naver_payload(closes=(1000., 1001., 0.)),
])
def test_naver_schema_invalid_close_and_date_corruption_rejected(bad):
    with pytest.raises(ValueError):
        source.normalise_naver(json.dumps(bad).encode(), 'KR_KOSDAQ', datetime(2026, 11, 23, tzinfo=UTC))


def test_naver_unfinished_session_removed():
    frame, info = source.normalise_naver(json.dumps(naver_payload(('20261120', '20261121', '20261123'))).encode(),
                                        'KR_KOSDAQ', datetime(2026, 11, 23, 6, 40, tzinfo=UTC))
    assert len(frame) == 2 and info['dropped_unclosed_bars'] == 1


def test_naver_short_refresh_cannot_replace_accepted_vintage(monkeypatch, tmp_path):
    response(monkeypatch, naver_payload())
    _, before = source.fetch_snapshot('KR_KOSDAQ', tmp_path, full_history=True)
    response(monkeypatch, naver_payload(('19960706', '20011101'), (1001., 625.5)))
    with pytest.raises(ValueError, match='coverage regressed'):
        source.fetch_snapshot('KR_KOSDAQ', tmp_path, refresh=True)
    latest = json.loads((tmp_path / 'source' / 'KR_KOSDAQ' / 'latest.json').read_text(encoding='utf-8'))
    assert latest['metadata_file'] == before['metadata_file']


def test_explicit_cache_reader_never_fetches_even_when_missing(monkeypatch, tmp_path):
    calls = response(monkeypatch, naver_payload())
    with pytest.raises(FileNotFoundError):
        source.load_cached_snapshot('KR_KOSDAQ', tmp_path)
    assert calls == []
    _, before = source.fetch_snapshot('KR_KOSDAQ', tmp_path, full_history=True)
    frame, cached = source.load_cached_snapshot('KR_KOSDAQ', tmp_path)
    assert len(calls) == 1 and len(frame) == 3 and before == cached
    source.fetch_snapshot('KR_KOSDAQ', tmp_path, full_history=False)
    assert len(calls) == 1  # Omitted full flag preserves an existing Naver cache.
