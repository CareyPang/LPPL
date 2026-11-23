"""Independent regression cases from the long-replay implementation review."""
import json
from concurrent.futures import Future

import numpy as np
import pandas as pd
import pytest

from research.pipeline import long_rolling as rolling


class InlinePool:
    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def submit(self, function, task):
        future = Future()
        future.set_result(function(task))
        return future


def frame(n):
    return pd.DataFrame({'date': pd.bdate_range(end='2026-11-20', periods=n),
                         'close': np.linspace(100, 200, n)})


def test_existing_input_evidence_is_verified_not_silently_ignored(tmp_path, monkeypatch):
    data = frame(100)
    monkeypatch.setattr(rolling, 'fetch_snapshot', lambda *a, **kw: (data, {'normalized_sha256': 'input-a'}))
    monkeypatch.setattr(rolling, 'ProcessPoolExecutor', InlinePool)
    rolling.run(tmp_path/'run', tmp_path/'source', assets=('US_IXIC',), endpoints=1, profiles=False)
    path = tmp_path/'run'/'inputs'/'US_IXIC.json'
    evidence = json.loads(path.read_text(encoding='utf-8'))
    evidence['close'][0] += 1
    path.write_text(json.dumps(evidence), encoding='utf-8')
    with pytest.raises(ValueError, match='[Ii]nput|[Ee]vidence|[Ss]napshot'):
        rolling.run(tmp_path/'run', tmp_path/'source', assets=('US_IXIC',), endpoints=1, profiles=False)


def test_profile_numerical_completion_is_not_optimizer_convergence(tmp_path, monkeypatch):
    data = frame(6800)
    monkeypatch.setattr(rolling, 'fetch_snapshot', lambda *a, **kw: (data, {'normalized_sha256': 'input-a', 'source': 'Naver real source'}))
    monkeypatch.setattr(rolling, 'ProcessPoolExecutor', InlinePool)
    monkeypatch.setattr(rolling, 'check_fit', lambda *a: {'verified': True})
    monkeypatch.setattr(rolling, 'PROFILE_GRID', (1, 2))

    def fake_fit(task):
        fit = {'x': [task['n'] - 1 + 20, .5, 9], 'optimizer_success': True,
               'beta': [10, -1, .01, .01], 'damping': 2, 'r2': .99, 'rank': 4,
               'condition': 100, 'nosc': 2, 'sse': 50, 'boundary_status': 'INTERIOR'}
        return {**{k: task[k] for k in ('symbol', 'asof', 'n', 'seed', 'input_hash', 'method_hash')},
                'status': 'complete', 'fit': fit}

    def fake_profile(task):
        fit = {'sse': 1 if task['seed'] == 11 else 2, 'de_success': True,
               'lbfgs_success': task['seed'] == 29, 'm': .5, 'omega': 9}
        return {**{k: task[k] for k in ('symbol', 'asof', 'ahead', 'seed', 'input_hash', 'method_hash', 'key')},
                'status': 'complete', 'fit': fit}

    monkeypatch.setattr(rolling, 'fit_job', fake_fit)
    monkeypatch.setattr(rolling, 'profile_job', fake_profile)
    result = rolling.run(tmp_path/'run', tmp_path/'source', assets=('KR_KOSDAQ',), endpoints=1)
    snapshot = result['assets']['KR_KOSDAQ']
    assert 'Naver' in snapshot['source']['label']
    points = snapshot['profile_diagnostic']['points']
    assert all(p['completed_seeds'] == 2 for p in points)
    assert all(p['converged_seeds'] == 1 for p in points)
    assert all(p['sse'] == 2 for p in points)
