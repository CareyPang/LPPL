"""Score frozen long-window replays with the preserved two-level top evaluator.

The same forecast geometry is probed against short and stage labels separately;
window length is not used to claim that the model classified a stage top.
Synthetic replay timestamps exist only inside an explicitly hypothetical
adapter and are never recorded as actual historical publication evidence.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ..eval.top_time.contracts import VERSION, Forecast, Protocol, ScheduledRun
from ..eval.top_time.labels import build_labels
from ..eval.top_time.scoring import evaluate

VERSION_ROLLING = 'long_rolling_two_level_score_v1'
WINDOWS = (900, 925, 950, 6500, 6600, 6700)
ARMS = tuple('window_' + str(n) for n in WINDOWS) + ('ultra_neighbours', 'cross_family')
ORIGINAL_SOURCE = 'LPPL PR50 research/eval/top_time from async-stock-20261106'
ORIGINAL_HASHES = {
    '__init__.py': '1357e981928014b65e79139a635e24776ae82277fd464dff4ca447177d0719fc',
    'contracts.py': '7ec1522c8a34433c6c66c87fad392168fddb1d141e660900a07c8baf8821688b',
    'labels.py': 'a57b69709a18376a7b4bb5a9afba83f9601f878a3987b941b70d79432d64480f',
    'replay.py': 'd4fa78946841f738f50c1062e068f9811ede9c4f8950c3da7f61921622efd073',
    'scoring.py': 'ab4cff21eee0230ce3a8762dd030b9150a12936ab402d1e8379e6c200d1ae0bb',
}


def source_manifest():
    folder = Path(__file__).resolve().parents[1] / 'eval' / 'top_time'
    actual = {name: hashlib.sha256((folder / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for name in ORIGINAL_HASHES}
    if actual != ORIGINAL_HASHES:
        raise ValueError('Preserved two-level evaluator source changed; register a new protocol')
    return {'origin': ORIGINAL_SOURCE, 'version': VERSION, 'sha256_normalized_lf': actual,
            'hash_normalization': 'CRLF to LF only; no content or whitespace normalization',
            'raw_sha256': {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in ORIGINAL_HASHES},
            'original_reports_verified_20261123': {
                'docs/research/2026-11-06-top-time-evaluator-implementation.md':
                    '5856369cc1a938c89f393572ca9f4d7bf5108de7b3b74c92f2c53cd0ae1768de',
                'docs/research/evidence/top-time-evaluator-20261106/v1/protocol.json':
                    'd9d48f1a35a15843bf34c4f81af7e75bcd7a27c554d624644bbc3cafdd286596'},
            'unchanged_copy': True, 'old_label_protocol': Protocol().to_dict()}


def _completed(window):
    seeds = window.get('seeds', [])
    return len(seeds) == 2 and all(s.get('status') == 'complete' for s in seeds)


def select_interval(row, arm, rule='cycles_1_5'):
    """Deterministic past-only arm selection; no labels/prices are accepted."""
    windows = {int(w['n']): w for w in row.get('windows', [])}
    if arm.startswith('window_'):
        required = (int(arm.removeprefix('window_')),)
    elif arm == 'ultra_neighbours':
        required = (6500, 6600, 6700)
    elif arm == 'cross_family':
        required = WINDOWS
    else:
        raise ValueError('Unknown experimental arm')
    if any(n not in windows or not _completed(windows[n]) for n in required):
        return {'status': 'unavailable', 'alarm': False, 'reason': 'required_windows_incomplete', 'members': []}
    good = [windows[n] for n in required if windows[n].get('eligible', {}).get(rule) is True]
    if not good:
        return {'status': 'no_signal', 'alarm': False, 'reason': 'no_qualified_window', 'members': []}
    groups = []
    if arm.startswith('window_'):
        spread = good[0].get('seed_ahead_range')
        if not isinstance(spread, (list, tuple)) or len(spread) != 2:
            raise ValueError('Qualified singleton requires actual two-seed ahead range')
        groups = [(float(spread[0]), float(spread[1]), [good[0]['n']])]
    elif arm == 'ultra_neighbours':
        if len(good) >= 2:
            ahead = [float(w['point_ahead']) for w in good]
            if max(ahead) - min(ahead) <= 5:
                groups = [(min(ahead), max(ahead), sorted(w['n'] for w in good))]
    else:
        import itertools
        for count in range(2, len(good) + 1):
            for group in itertools.combinations(good, count):
                ahead = [float(w['point_ahead']) for w in group]
                if len({w.get('family', 'long_900' if w['n'] < 1000 else 'ultra_6600') for w in group}) == 2 and max(ahead) - min(ahead) <= 5:
                    groups.append((min(ahead), max(ahead), sorted(w['n'] for w in group)))
    if not groups:
        return {'status': 'no_signal', 'alarm': False, 'reason': 'no_registered_cluster', 'members': []}
    # Earliest candidate first; ties prefer the broadest member set, then stable ids.
    lo, hi, members = min(groups, key=lambda value: (value[0], value[1], -len(value[2]), value[2]))
    if not math.isfinite(lo) or not math.isfinite(hi) or lo > hi:
        raise ValueError('Nonfinite/unordered candidate interval')
    return {'status': 'interval', 'alarm': True, 'low': lo, 'high': hi, 'members': members,
            'candidate_groups': len(groups), 'selection': 'earliest_start_then_end_then_most_members',
            'interval_meaning': 'numerical_seed_or_member_envelope_not_probability_interval'}


def _bundle(symbol, sessions, rows, arm, scope, rule):
    forecasts, runs, audit = [], [], []
    episode, expiry, first_id = None, -1, None
    for row in rows:
        i, date = row['asof_index'], row['asof']
        selected = select_interval(row, arm, rule)
        run_id = f'{symbol}:{arm}:{rule}:{scope}:{date}'
        audit_row = {'symbol': symbol, 'asof': date, 'asof_index': i, 'arm': arm, 'scope_probe': scope,
                     'selection': selected, 'actual_published_at': None, 'first_visible_at': None,
                     'evidence': 'HYPOTHETICAL_REPLAY_NOT_ORIGINAL_PUBLICATION'}
        if selected['status'] == 'unavailable':
            # Missing source windows are not model failure or a negative signal.
            runs.append(ScheduledRun(run_id, symbol, i, 'OUT_OF_SCOPE'))
        elif not selected['alarm']:
            runs.append(ScheduledRun(run_id, symbol, i, 'NO_SIGNAL'))
        else:
            left, right = i + math.floor(selected['low']), i + math.ceil(selected['high'])
            action = i + 1 if i + 1 < len(sessions) else None
            change = 'REVISION'
            if episode is None or i > expiry:
                episode, expiry, first_id = run_id, max(i, min(right, i + 90)), run_id
                change = 'FIRST_CLAIM'
            # Calendar-date adapter only, not an assertion about exchange publication.
            timestamp = date + 'T23:59:59+00:00'
            forecasts.append(Forecast(run_id, episode, symbol, scope, left, right, i, i,
                                      timestamp, action, 'theoretical', True, run_id))
            runs.append(ScheduledRun(run_id, symbol, i, 'INTERVAL'))
            audit_row.update(interval_start=left, interval_end=right, width=right - left + 1,
                             hypothetical_action_session=action, hypothetical_adapter_timestamp=timestamp,
                             episode_id=episode, episode_original_expiry=expiry, first_claim_id=first_id,
                             claim_change=change)
        audit.append(audit_row)
    return forecasts, runs, audit


def _raw_timing(book, audit, start, end, scope):
    """Pure first-window event coverage, without discarding short lead times."""
    claims = [a for a in audit if a.get('claim_change') == 'FIRST_CLAIM']
    events = sorted([e for e in book.events if e.scale == scope], key=lambda e: e.peak_session)
    by_anchor = {e.peak_session: e for e in events}
    assigned = {}
    for claim in claims:
        for i in range(claim['asof_index'] + 1, claim['asof_index'] + 91):
            if i >= len(book.sessions) or not book.known[scope][i]:
                break
            if i in by_anchor:
                assigned.setdefault(by_anchor[i].event_id, []).append(claim)
                break
    rows = []
    for event in events:
        if not start <= event.peak_session <= end:
            continue
        opportunities = assigned.get(event.event_id, [])
        first = min(opportunities, key=lambda c: c['asof_index']) if opportunities else None
        cover = bool(first and first['interval_start'] <= event.peak_session <= first['interval_end'])
        lead = event.peak_session - first['asof_index'] if first else None
        action_lead = event.peak_session - first['hypothetical_action_session'] if first and first['hypothetical_action_session'] is not None else None
        rows.append({'event_id': event.event_id, 'scale': scope, 'peak_session': event.peak_session,
                     'peak_date': book.sessions[event.peak_session], 'first_claim_id': first.get('first_claim_id') if first else None,
                     'covered': cover, 'lead_from_cutoff': lead, 'lead_from_next_session_action': action_lead,
                     'full_90_session_opportunity_history': event.peak_session - 90 >= start,
                     'covered_with_5_sessions_action_lead': bool(cover and action_lead is not None and action_lead >= 5)})
    covered = sum(r['covered'] for r in rows)
    return {'E': len(rows), 'covered': covered, 'missed': len(rows) - covered,
            'coverage': covered / len(rows) if rows else None,
            'covered_ge5_action_lead': sum(r['covered_with_5_sessions_action_lead'] for r in rows),
            'covered_cutoff_leads': [r['lead_from_cutoff'] for r in rows if r['covered']],
            'covered_action_leads': [r['lead_from_next_session_action'] for r in rows if r['covered']],
            'events': rows, 'meaning': 'first-claim geometry only; no 5-session rejection, no trading PnL'}


def score_rolling(symbol, frame, ledgers, generated_at, protocol_hash='', source_id=''):
    """Return two-level retrospective scores for one asset's fixed endpoint grid.

    frame: all observed daily date/close rows, including subsequent data used
    only to mature labels. ledgers: asset/asof/asof_index/windows snapshots;
    windows use the existing long_horizon summary contract. The adapter checks
    all identities and source calendars before assigning any hypothetical claim.
    """
    stamp = datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError('generated_at must identify actual timezone-aware replay time')
    provenance = source_manifest()
    data = frame.copy()
    sessions = pd.to_datetime(data.date).dt.strftime('%Y-%m-%d').tolist()
    prices = pd.to_numeric(data.close, errors='raise').tolist()
    if not sessions or sessions != sorted(set(sessions)) or not np.isfinite(prices).all() or min(prices) <= 0:
        raise ValueError('Explicit unique sorted positive source observations required')
    rows, seen = [], set()
    for raw in ledgers:
        row = dict(raw)
        if row.get('symbol') != symbol:
            raise ValueError('Mixed asset forecast ledger')
        i = row.get('asof_index')
        if type(i) is not int or not 0 <= i < len(sessions) or sessions[i] != row.get('asof') or i in seen:
            raise ValueError('Exact unique forecast cutoff required')
        seen.add(i)
        rows.append(row)
    if not rows:
        raise ValueError('No scheduled cutoffs supplied')
    rows.sort(key=lambda r: r['asof_index'])
    old = Protocol()
    book = build_labels(symbol, sessions, prices, config=old,
                        input_status='CURRENT_DOWNLOAD_HISTORICAL_RECONSTRUCTION_NOT_PIT')
    start, end = rows[0]['asof_index'], len(sessions) - 1
    primary = replace(old, horizon=90, minimum_lead=1, maximum_width=90, require_entire_window_lead=False,
                      parameter_status='FROZEN_LONG_ROLLING_DIAGNOSTIC_20261123')
    result = {'schema_version': VERSION_ROLLING, 'symbol': symbol, 'generated_at': generated_at,
              'protocol_hash': protocol_hash, 'source_id': source_id, 'evaluator': provenance,
              'label_protocol': old.to_dict(), 'primary_score_protocol': primary.to_dict(),
              'legacy_score_protocol': old.to_dict(), 'replay_kind': 'historical_reconstruction',
              'first_visible_at': None, 'actual_historical_publications': 0,
              'scope_basis': 'uniform short/stage target probes; not model stage classification',
              'start_session': start, 'end_session': end, 'observed_session_calendar_verified': False,
              'label_events': [asdict(e) for e in book.events if start <= e.peak_session <= end],
              'pending_labels': book.pending, 'arms': {},
              'limits': ['Retrospective reconstruction, not prospective out-of-sample evidence.',
                         'Missing source sessions cannot be excluded without an independently verified exchange calendar.',
                         'No decline-size success threshold; the copied two-level label implementation is unchanged.',
                         'No 5-session admission filter. Lead>=5 is a separate metric and legacy score.',
                         'A short future-data tail leaves unresolved claims pending, never false positives.',
                         'Periods without 6700 observed rows are unavailable, not failed fits or proof of no signal.']}
    for rule in ('cycles_1_5', 'cycles_2_5'):
        by_arm = {}
        for arm in ARMS:
            scales = {}
            for scope in ('short', 'stage'):
                forecasts, runs, audit = _bundle(symbol, sessions, rows, arm, scope, rule)
                new_score = evaluate(book, forecasts, runs, config=primary, mode='diagnostic', start_session=start, end_session=end)
                old_score = evaluate(book, forecasts, runs, config=old, mode='diagnostic', start_session=start, end_session=end)
                available = sum(a['selection']['status'] != 'unavailable' for a in audit)
                scales[scope] = {
                    'availability': {'scheduled': len(rows), 'available': available,
                                     'unavailable': sum(a['selection']['status'] == 'unavailable' for a in audit)},
                    'evaluation_status': 'NOT_ESTABLISHED_NO_AVAILABLE_RUN' if not available else
                                         'CONDITIONAL_PARTIAL_SOURCE_COVERAGE' if available < len(rows) else 'HISTORICAL_REPLAY_DIAGNOSTIC',
                    'timing_without_5d_gate': _raw_timing(book, audit, start, end, scope) if available else None,
                    'primary': new_score.to_dict() if available else None,
                    'legacy_5d_10d': old_score.to_dict() if available else None, 'claim_audit': audit}
            by_arm[arm] = scales
        result['arms'][rule] = by_arm
    return result
