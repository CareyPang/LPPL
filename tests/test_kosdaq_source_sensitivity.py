from concurrent.futures import Future

import numpy as np
import pandas as pd
import pytest

from scripts import kosdaq_source_sensitivity as sensitivity


def source_frame():
    frame = pd.DataFrame({'date': pd.bdate_range('1996-07-02', periods=7598).strftime('%Y-%m-%d'),
                          'close': np.linspace(500, 800, 7598)})
    frame.loc[frame.date == sensitivity.AFFECTED_DATE, 'close'] = sensitivity.CANONICAL_CLOSE
    return frame


def test_single_point_copy_preserves_source_and_short_window_identity():
    original = source_frame()
    source_hash = sensitivity.input_identity(original)
    alternate = sensitivity.substitute_one_point(original)
    assert sensitivity.input_identity(original) == source_hash
    assert (original.close != alternate.close).sum() == 1
    method = sensitivity.experiment_method()
    for n in sensitivity.WINDOWS:
        for seed in sensitivity.SEEDS:
            a = sensitivity.make_task(original, original.date.iloc[-1], n, seed, 'same-method', method)
            b = sensitivity.make_task(alternate, original.date.iloc[-1], n, seed, 'same-method', method)
            assert (a['key'] == b['key']) == (n < 1000)
            assert (a['input_hash'] == b['input_hash']) == (n < 1000)


@pytest.mark.parametrize('defect', ['missing', 'changed', 'duplicate'])
def test_substitution_refuses_unregistered_source(defect):
    frame = source_frame()
    if defect == 'missing':
        frame = frame[frame.date != sensitivity.AFFECTED_DATE]
    elif defect == 'changed':
        frame.loc[frame.date == sensitivity.AFFECTED_DATE, 'close'] += 1
    else:
        frame = pd.concat([frame, frame.iloc[:1]])
    with pytest.raises(ValueError):
        sensitivity.substitute_one_point(frame)


def test_write_once_never_overwrites_existing_cache(tmp_path):
    path = tmp_path / 'cache.json'
    sensitivity.write_once(path, {'canonical': 'keep'})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        sensitivity.write_once(path, {'noncanonical': 'replacement'})
    assert path.read_bytes() == before


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


def fit_record(task, ahead=10):
    return {**{key: task[key] for key in sensitivity.IDENTITY_FIELDS}, 'status': 'complete',
            'fit': {'x': [task['n'] - 1 + ahead, .5, 9], 'optimizer_success': True,
                    'beta': [10, -1, .01, .01], 'damping': 2, 'r2': .99, 'rank': 4,
                    'condition': 100, 'nosc': 2, 'sse': .5, 'boundary_status': 'INTERIOR'}}


def setup_run(tmp_path, monkeypatch):
    root, source, primary, cache = [tmp_path / name for name in ('result', 'source', 'primary', 'cache')]
    data = source_frame()
    folder = source / 'source' / sensitivity.SYMBOL
    folder.mkdir(parents=True)
    (folder / 'sample.raw.json').write_text('[]', encoding='utf-8')
    data.to_parquet(folder / 'sample.parquet', index=False)
    meta = {'provider': 'naver', 'source': 'Naver', 'normalized_sha256': sensitivity.digest(folder / 'sample.parquet'),
            'normalized_file': 'sample.parquet', 'raw_file': 'sample.raw.json',
            'raw_sha256': sensitivity.digest(folder / 'sample.raw.json')}
    probe = {'canonical_source_meta': {**meta, 'data_quality': {'affected_date': sensitivity.AFFECTED_DATE,
             'observed_naver_close': sensitivity.CANONICAL_CLOSE, 'observed_yahoo_close': sensitivity.ALTERNATE_CLOSE}}}
    method = sensitivity.experiment_method()
    method_hash = sensitivity.signature(method)
    protocol = {'method': method, 'method_hash': method_hash, 'protocol_hash': 'primary-protocol',
                'inputs': {sensitivity.SYMBOL: {'input_hash': sensitivity.input_identity(data)}},
                'endpoint_dates': {sensitivity.SYMBOL: [data.date.iloc[-1]]}}
    sensitivity.write_once(folder / 'latest.json', meta)
    sensitivity.write_once(source / 'source-probes' / 'kosdaq-source-difference.json', probe)
    sensitivity.write_once(primary / 'protocol.json', protocol)
    sensitivity.write_once(primary / 'inputs' / f'{sensitivity.SYMBOL}.json',
                           {'symbol': sensitivity.SYMBOL, 'dates': data.date.tolist(),
                            'close': data.close.tolist(), 'source_meta': meta})
    for n in sensitivity.WINDOWS:
        for seed in sensitivity.SEEDS:
            task = sensitivity.make_task(data, data.date.iloc[-1], n, seed, method_hash, method)
            sensitivity.write_once(cache / (task['key'] + '.json'), fit_record(task))
    monkeypatch.setattr(sensitivity, 'check_fit', lambda *args: {'test_independent_readback': True})
    monkeypatch.setattr(sensitivity, 'ProcessPoolExecutor', InlinePool)
    return root, source, primary, cache


def test_run_uses_only_six_long_fits_and_keeps_originals_immutable(tmp_path, monkeypatch):
    root, source, primary, cache = setup_run(tmp_path, monkeypatch)
    before = sensitivity.inventory(path for folder in (source, primary, cache) for path in folder.rglob('*') if path.is_file())
    calls = []

    def fit(task):
        calls.append((task['n'], task['seed']))
        return fit_record(task, ahead=11)

    monkeypatch.setattr(sensitivity, 'fit_job', fit)
    result = sensitivity.run(root, source, primary, cache)
    assert sorted(calls) == [(n, seed) for n in (6500, 6600, 6700) for seed in (11, 29)]
    assert result['counts']['unchanged_short_reused'] == 6
    assert result['counts']['alternate_long_new'] == 6
    assert result['experiment_status'] == 'NON_CANONICAL'
    assert result['independent_vendor_adjudication'] == 'NOT_ESTABLISHED'
    assert result['source_unchanged']
    assert result['maximum_absolute_tc_shift_sessions'] == 1
    for path, digest in before.items():
        assert sensitivity.digest(path) == digest
    assert len(list(cache.glob('*.json'))) == 18
    for window in result['windows']:
        assert window['input_changed'] == (window['n'] >= 1000)
        assert not window['baseline_eligible']['cycles_2_5']
        assert window['baseline_eligible']['cycles_1_5']
    again = sensitivity.run(root, source, primary, cache)
    assert len(calls) == 6
    assert again['counts']['alternate_long_new'] == 0
    assert again['counts']['alternate_long_cache_reused'] == 6


def test_missing_baseline_does_not_start_sensitivity_or_fill_primary(tmp_path, monkeypatch):
    root, source, primary, cache = setup_run(tmp_path, monkeypatch)
    next(cache.glob('*.json')).unlink()

    def forbidden(task):
        raise AssertionError('No fit may run before all baseline fits exist')

    monkeypatch.setattr(sensitivity, 'fit_job', forbidden)
    with pytest.raises(FileNotFoundError, match='no fits run'):
        sensitivity.run(root, source, primary, cache)
    assert not root.exists()


def test_source_tampering_fails_before_model_work(tmp_path, monkeypatch):
    root, source, primary, cache = setup_run(tmp_path, monkeypatch)
    (source / 'source' / sensitivity.SYMBOL / 'sample.raw.json').write_text('[1]', encoding='utf-8')
    with pytest.raises(ValueError, match='source hash mismatch'):
        sensitivity.run(root, source, primary, cache)
