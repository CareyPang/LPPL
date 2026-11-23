"""No model optimization: scoring identity, fixed labels and horizon boundaries."""
from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from research.eval.top_time.contracts import Protocol
from research.pipeline.long_rolling_score import (
    _bundle,
    score_rolling,
    select_interval,
    source_manifest,
)


def frame():
    return pd.DataFrame({'date': pd.bdate_range('2020-01-01', periods=351),
                         'close': np.interp(range(351), [0, 100, 160, 220, 280, 350],
                                            [120, 105, 90, 140, 110, 115])})


def row(i=200, *, ahead=20, eligible=True, symbol='X', unavailable=False):
    data = frame()
    return {'symbol': symbol, 'asof': data.date.iloc[i].date().isoformat(), 'asof_index': i,
            'windows': [{'n': n, 'family': 'long_900' if n < 1000 else 'ultra_6600',
                         'eligible': {'cycles_1_5': eligible, 'cycles_2_5': eligible},
                         'point_ahead': ahead, 'seed_ahead_range': [ahead, ahead],
                         'seeds': [{'status': 'not_available' if unavailable and n > 1000 else 'complete'}] * 2}
                        for n in (900, 925, 950, 6500, 6600, 6700)]}


def score(rows):
    return score_rolling('X', frame(), rows, '2026-11-23T12:00:00+00:00')


def test_imported_two_level_sources_are_exact_frozen_copies():
    actual = source_manifest()
    assert actual['unchanged_copy']
    assert actual['old_label_protocol']['stage_left'] == 63
    assert actual['old_label_protocol']['stage_right'] == 42
    assert actual['old_label_protocol']['rise_min'] == 21
    assert actual['old_label_protocol']['rise_max'] == 126


def test_short_lead_is_admitted_before_outcome_and_old_5d_rule_is_separate():
    value = score([row(217, ahead=3)])
    result = value['arms']['cycles_1_5']['window_6600']['stage']
    assert result['claim_audit'][0]['selection']['alarm'] is True
    assert result['timing_without_5d_gate']['covered'] == 1
    assert result['timing_without_5d_gate']['covered_ge5_action_lead'] == 0
    assert result['primary']['metrics']['stage']['TP'] == 1
    assert result['legacy_5d_10d']['metrics']['stage']['TP'] == 0
    assert value['first_visible_at'] is None
    assert value['actual_historical_publications'] == 0
    assert result['claim_audit'][0]['actual_published_at'] is None


def test_unavailable_long_windows_are_not_no_signal_or_failed_performance():
    value = score([row(unavailable=True)])
    long = value['arms']['cycles_1_5']['window_6600']['stage']
    assert long['availability'] == {'scheduled': 1, 'available': 0, 'unavailable': 1}
    assert long['primary'] is None
    assert long['timing_without_5d_gate'] is None
    assert long['claim_audit'][0]['selection']['status'] == 'unavailable'
    assert value['arms']['cycles_1_5']['window_925']['stage']['primary'] is not None


def test_zero_signal_is_a_computed_result_not_unavailable():
    value = score([row(eligible=False)])
    result = value['arms']['cycles_1_5']['window_6600']['stage']
    assert result['availability']['available'] == 1
    assert result['primary']['metrics']['operational']['on_time_runs'] == 1
    assert result['primary']['metrics']['stage']['P'] == 0


def test_latest_cutoff_has_pending_action_not_fake_next_session():
    value = score([row(350)])
    result = value['arms']['cycles_1_5']['window_6600']['stage']
    assert result['claim_audit'][0]['hypothetical_action_session'] is None
    assert result['primary']['metrics']['diagnostics']['pending_action'] == 1
    assert result['primary']['metrics']['stage']['P'] == 0


def test_revisions_cannot_replace_first_interval_or_extend_episode_expiry():
    dates = frame().date.dt.strftime('%Y-%m-%d').tolist()
    forecasts, _, audit = _bundle('X', dates, [row(200, ahead=30), row(210, ahead=10)],
                                  'window_6600', 'stage', 'cycles_1_5')
    assert forecasts[0].episode_id == forecasts[1].episode_id
    assert audit[1]['claim_change'] == 'REVISION'
    assert audit[1]['episode_original_expiry'] == 230
    assert audit[1]['first_claim_id'] == audit[0]['first_claim_id']
    value = score([row(200, ahead=30), row(210, ahead=10)])
    assert value['arms']['cycles_1_5']['window_6600']['stage']['timing_without_5d_gate']['covered'] == 0


@pytest.mark.parametrize('change', [{'symbol': 'OTHER'}, {'asof_index': 201}, {'asof_index': True}])
def test_wrong_asset_or_calendar_index_is_rejected(change):
    changed = row()
    changed.update(change)
    with pytest.raises(ValueError):
        score([changed])


def test_duplicate_cutoff_is_rejected():
    with pytest.raises(ValueError):
        score([row(), row()])


def test_cross_family_requires_two_different_scales():
    source = row()
    for w in source['windows']:
        if w['n'] > 1000:
            w['eligible'] = {'cycles_1_5': False}
    assert select_interval(source, 'cross_family')['alarm'] is False
    assert select_interval(source, 'window_925')['alarm'] is True


def test_cycle_rules_reuse_same_window_geometry_without_override():
    source = row()
    for w in source['windows']:
        w['eligible']['cycles_2_5'] = False
    assert select_interval(source, 'window_6600')['alarm'] is True
    assert select_interval(source, 'window_6600', 'cycles_2_5')['alarm'] is False
    assert asdict(Protocol())['minimum_lead'] == 5


def test_singleton_interval_requires_real_seed_envelope():
    source = row()
    del source['windows'][4]['seed_ahead_range']
    with pytest.raises(ValueError, match='actual two-seed'):
        select_interval(source, 'window_6600')
