from concurrent.futures import Future
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from research.lppls import frozen_v2588
from research.pipeline import long_rolling as rolling
from research.pipeline.long_horizon import math_ast_hash


def frame(n=1000):
    return pd.DataFrame({'date': pd.bdate_range('2020-01-01', periods=n), 'close': np.linspace(100, 200, n)})


def test_registered_grid_uses_only_actual_completed_sessions():
    data = frame()
    data['date'] = data.date.dt.strftime('%Y-%m-%d')
    grid = rolling.endpoint_dates(data)
    assert len(grid) == 52
    assert grid[-1] == data.date.iloc[-1]
    assert [data.date.tolist().index(day) for day in grid] == list(range(744, 1000, 5))
    with pytest.raises(ValueError):
        rolling.endpoint_dates(data, 300)


def test_calendar_never_applies_us_holidays_to_korean_observed_sessions():
    dates = ['1996-07-05', '1996-07-06', '1996-07-08']  # Historical Korean Saturday session.
    assert rolling.market_date(dates, dates[0], 1) == (dates[1], 'observed_session_calendar_for_retrospective_scoring')
    future, state = rolling.market_date(dates, dates[-1], 1)
    assert future == '1996-07-09'
    assert state == 'weekday_estimate_holidays_not_removed'


def record(n, ahead, seed):
    return {'seed': seed, 'n': n, 'asof': '2026-11-20', 'status': 'complete',
            'fit': {'x': [n - 1 + ahead, .5, 9], 'optimizer_success': True,
                    'beta': [10, -1, .01, .01], 'damping': 2, 'r2': .99, 'rank': 4,
                    'condition': 100, 'nosc': 2, 'sse': .5, 'boundary_status': 'INTERIOR'}}


def test_snapshot_preserves_one_day_lead_and_two_families_not_six_votes():
    data = frame(7200)
    data['date'] = pd.bdate_range(end='2026-11-20', periods=len(data)).strftime('%Y-%m-%d')
    records = {('2026-11-20', n, seed): record(n, 1, seed) for n in rolling.WINDOWS for seed in rolling.SEEDS}
    view = rolling.make_snapshot('KR_KOSPI', '2026-11-20', data, {'normalized_sha256': 'input-a'}, records, 'method-a', {})
    assert view['counts']['completed'] == 12
    assert all(w['eligible']['cycles_1_5'] for w in view['windows'])
    assert all(not w['eligible']['cycles_2_5'] for w in view['windows'])
    assert view['rules']['cycles_1_5']['cross_family_clusters']
    assert all(cluster['families'] == 2 for cluster in view['rules']['cycles_1_5']['cross_family_clusters'])
    assert view['first_visible_at'] is None


def test_boundary_or_unstable_seed_pair_does_not_form_candidate():
    data = frame(7200)
    data['date'] = pd.bdate_range(end='2026-11-20', periods=len(data)).strftime('%Y-%m-%d')
    records = {('2026-11-20', n, seed): record(n, 10, seed) for n in rolling.WINDOWS for seed in rolling.SEEDS}
    records[('2026-11-20', 6600, 11)]['fit']['boundary_status'] = 'm_HIGH'
    records[('2026-11-20', 6700, 29)]['fit']['x'][0] += 10
    view = rolling.make_snapshot('KR_KOSPI', '2026-11-20', data, {'normalized_sha256': 'input-a'}, records, 'method-a', {})
    assert not next(w for w in view['windows'] if w['n'] == 6600)['eligible']['cycles_1_5']
    assert not next(w for w in view['windows'] if w['n'] == 6700)['eligible']['cycles_1_5']


class InlinePool:
    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def submit(self, fn, task):
        future = Future()
        future.set_result(fn(task))
        return future


def test_run_finishes_all_registered_work_and_counts_data_gaps(tmp_path, monkeypatch):
    data = frame()
    seen = []
    monkeypatch.setattr(rolling, 'fetch_snapshot', lambda *args, **kwargs: (data, {'normalized_sha256': 'input-a'}))
    monkeypatch.setattr(rolling, 'ProcessPoolExecutor', InlinePool)
    monkeypatch.setattr(rolling, 'check_fit', lambda *args: {'verified': True})

    def fake_fit(task):
        seen.append(deepcopy(task))
        value = record(task['n'], 10, task['seed'])
        value.update({k: task[k] for k in ('symbol', 'asof', 'n', 'seed', 'input_hash', 'method_hash')})
        return value

    monkeypatch.setattr(rolling, 'fit_job', fake_fit)
    result = rolling.run(tmp_path / 'run', tmp_path / 'source', assets=('US_IXIC',), endpoints=2, profiles=False)
    assert result['counts']['expected'] == 24
    assert result['counts']['completed'] == 12
    assert result['counts']['not_available'] == 12
    assert result['counts']['pending'] == result['counts']['failed'] == 0
    assert result['status'] == 'complete_with_data_gaps'
    assert all(len(task['close']) == task['n'] for task in seen)
    assert (tmp_path / 'run' / 'protocol.json').exists()
    seen.clear()
    repeated = rolling.run(tmp_path / 'run', tmp_path / 'source', assets=('US_IXIC',), endpoints=2, profiles=False)
    assert repeated['counts']['cache_reused'] == 12
    assert seen == []
    monkeypatch.setattr(rolling, 'fetch_snapshot', lambda *args, **kwargs: (data, {'normalized_sha256': 'input-b'}))
    with pytest.raises(ValueError, match='Frozen protocol/input changed'):
        rolling.run(tmp_path / 'run', tmp_path / 'source', assets=('US_IXIC',), endpoints=2, profiles=False)


def test_extracted_numerical_kernel_matches_audited_ast_and_budget():
    assert math_ast_hash(frozen_v2588.__file__) == 'ac00580978ed58cc57a5a1a5c07b69846d5516ec7499722ea46f6d49fc715c01'
    method = rolling.experiment_method()
    assert method['de']['popsize'] == 25
    assert method['de']['maxiter'] == 1500
    assert method['seeds'] == [11, 29]
    assert method['windows'][-2:] == [6600, 6700]
