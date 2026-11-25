"""One-point, NON_CANONICAL KOSDAQ source-discrepancy sensitivity.

Reads the frozen primary study and its existing latest-endpoint fits. Only the
long-window inputs containing 2001-11-01 receive a new fit. This experiment does
not decide which vendor is correct and never edits source data or pointers.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from research.lppls import frozen_v2588 as numerical
from research.pipeline.global_terminal import atomic_json, clean
from research.pipeline.long_horizon import (
    SEEDS,
    WINDOWS,
    check_fit,
    digest,
    fit_job,
    input_identity,
    prefix,
    signature,
)
from research.pipeline.long_rolling import experiment_method, make_snapshot

SYMBOL = 'KR_KOSDAQ'
AFFECTED_DATE = '2001-11-01'
CANONICAL_CLOSE = 625.5
ALTERNATE_CLOSE = 636.4000244140625
VERSION = 'kosdaq_one_point_source_sensitivity_v1'
IDENTITY_FIELDS = ('symbol', 'asof', 'n', 'seed', 'input_hash', 'method_hash')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def substitute_one_point(frame):
    """Return a separate experimental copy; reject any unexpected baseline."""
    if frame.date.duplicated().any() or not frame.date.is_monotonic_increasing:
        raise ValueError('Input dates must be unique and increasing')
    if not np.isfinite(frame.close).all() or (frame.close <= 0).any():
        raise ValueError('Finite positive close required')
    selected = frame.date == AFFECTED_DATE
    if selected.sum() != 1 or frame.loc[selected, 'close'].item() != CANONICAL_CLOSE:
        raise ValueError('The registered Naver point is absent or has changed')
    alternate = frame.copy(deep=True)
    alternate.loc[selected, 'close'] = ALTERNATE_CLOSE
    if (alternate.close != frame.close).sum() != 1:
        raise ValueError('Sensitivity must change exactly one close')
    return alternate


def make_task(frame, asof, n, seed, method_hash, method):
    part = prefix(frame, asof, n)
    task = {'symbol': SYMBOL, 'asof': asof, 'n': n, 'seed': seed,
            'input_hash': input_identity(part), 'method_hash': method_hash,
            'kernel_path': numerical.__file__, 'kernel_sha256': method['kernel_sha256'],
            'close': part.close.tolist()}
    task['key'] = signature({key: task[key] for key in IDENTITY_FIELDS})
    return task


def checked_cache(path, task):
    saved = read_json(path)
    if any(saved.get(key) != task[key] for key in IDENTITY_FIELDS):
        raise ValueError('Fit cache identity mismatch')
    if saved.get('status') != 'complete':
        raise ValueError('A complete baseline/cached fit is required; no implicit rerun')
    saved['independent_readback'] = check_fit(
        saved['fit'], task['close'], {'lin': numerical.lin, 'Xmat': numerical.Xmat})
    return saved


def write_once(path, value):
    """Never replace a canonical or pre-existing cache record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(clean(value), stream, ensure_ascii=False, indent=1, allow_nan=False)
        stream.write('\n')


def inventory(paths):
    return {str(path.resolve()): digest(path) for path in sorted(set(paths))}


def compare_snapshots(baseline, alternate):
    comparisons = []
    fields = ('tc_ahead', 'm', 'omega', 'sse', 'r2', 'damping', 'full_cycles')
    for before, after in zip(baseline['windows'], alternate['windows'], strict=True):
        seeds = []
        for a, b in zip(before['seeds'], after['seeds'], strict=True):
            seeds.append({'seed': a['seed'], 'baseline': {key: a.get(key) for key in fields},
                          'alternate': {key: b.get(key) for key in fields},
                          'delta_alternate_minus_baseline': {key: b[key] - a[key] for key in fields},
                          'baseline_optimizer_success': a['optimizer_success'],
                          'alternate_optimizer_success': b['optimizer_success'],
                          'baseline_boundary_status': a['boundary_status'],
                          'alternate_boundary_status': b['boundary_status'],
                          'baseline_passes': a['passes'], 'alternate_passes': b['passes']})
        comparisons.append({'n': before['n'], 'family': before['family'], 'seeds': seeds,
                            'input_changed': before['seeds'][0]['input_hash'] != after['seeds'][0]['input_hash'],
                            'baseline_seed_gap_sessions': before['seed_gap_days'],
                            'alternate_seed_gap_sessions': after['seed_gap_days'],
                            'baseline_eligible': before['eligible'], 'alternate_eligible': after['eligible'],
                            'eligibility_changed': before['eligible'] != after['eligible'],
                            'baseline_point_ahead': before['point_ahead'], 'alternate_point_ahead': after['point_ahead']})
    return {'windows': comparisons,
            'cluster_comparison': {rule: {'baseline': baseline['rules'][rule], 'alternate': alternate['rules'][rule],
                                         'changed': baseline['rules'][rule] != alternate['rules'][rule]}
                                   for rule in ('cycles_1_5', 'cycles_2_5')},
            'maximum_absolute_tc_shift_sessions': max(abs(seed['delta_alternate_minus_baseline']['tc_ahead'])
                                                      for window in comparisons for seed in window['seeds'])}


def report_markdown(summary):
    def number(value):
        return '—' if value is None else f'{value:.6f}'

    rows = [
        '# KOSDAQ 单点数据源差异敏感性', '',
        f"截止日：{summary['asof']}。状态：NON_CANONICAL / source_discrepancy_sensitivity。", '',
        '仅把独立实验副本的 2001-11-01 收盘从 625.5 改为 636.4000244140625；其他数据、优化器、随机种子和筛选规则不变。',
        '这不是对源数据的订正，不裁定 Naver 或 Yahoo 哪一个正确，也不是新增提前发布预测。', '',
        f"VERIFIED：12 个原拟合复用；其中 6 个短窗直接复用。长窗新算 {summary['counts']['alternate_long_new']} 个，"
        f"本敏感性缓存复用 {summary['counts']['alternate_long_cache_reused']} 个。源文件及原拟合 {summary['protected_files']} 个 hash 未变。", '',
        f"全部 12 个 seed 拟合的最大绝对 tc 变化：{number(summary['maximum_absolute_tc_shift_sessions'])} 个交易日。", '',
        '| 窗口 | 原/副本 1.5 合格 | 原/副本 2.5 合格 | 原 seed 间距 | 副本 seed 间距 | 最大 tc 变化 |',
        '|---|---|---|---:|---:|---:|',
    ]
    for row in summary['windows']:
        primary = f"{row['baseline_eligible']['cycles_1_5']} / {row['alternate_eligible']['cycles_1_5']}"
        stricter = f"{row['baseline_eligible']['cycles_2_5']} / {row['alternate_eligible']['cycles_2_5']}"
        shift = max(abs(seed['delta_alternate_minus_baseline']['tc_ahead']) for seed in row['seeds'])
        rows.append(f"| {row['n']} | {primary} | {stricter} | {number(row['baseline_seed_gap_sessions'])} | "
                    f"{number(row['alternate_seed_gap_sessions'])} | {number(shift)} |")
    boundary_pairs = sum(seed['baseline_boundary_status'] != 'INTERIOR'
                         or seed['alternate_boundary_status'] != 'INTERIOR'
                         for window in summary['windows'] for seed in window['seeds'])
    if boundary_pairs:
        rows += ['', f'{boundary_pairs} 对 seed 拟合至少一版落在参数边界。相同的 tc 可能来自共同边界约束；'
                 '不能把“tc 未变化”解释成日期准确或预测可靠。']
    rows += ['', '相邻窗口视为同一尺度；seed 一致不代表预测概率。完整周期 1.5 为主规则，2.5 为同拟合对照。', '']
    for rule, value in summary['cluster_comparison'].items():
        rows.append(f"- {rule}：跨尺度聚类数量 {len(value['baseline']['cross_family_clusters'])} → "
                    f"{len(value['alternate']['cross_family_clusters'])}；窗口族及聚类摘要变化：{value['changed']}。")
    rows += ['', 'NOT_ESTABLISHED：任一供应商正确性、此结果的预警准确率、其他日期或其他源差异的稳定性。',
             '未运行额外历史重放或 profile；逐 seed 的 tc、m、omega、SSE、R²、阻尼、完整周期和合格状态见 summary.json。', '',
             f"主实验 protocol：`{summary['primary_protocol_hash']}`",
             f"敏感性 protocol：`{summary['protocol_hash']}`",
             f"数值方法：`{summary['method_hash']}`", '']
    return '\n'.join(rows)


def run(root, source_root, baseline_root, fit_cache, *, workers=2):
    started = time.perf_counter()
    root, source_root, baseline_root, fit_cache = map(lambda value: Path(value).resolve(),
                                                     (root, source_root, baseline_root, fit_cache))
    checkout = Path(__file__).resolve().parents[1]
    if any(path.is_relative_to(checkout) for path in (root, source_root, baseline_root, fit_cache)):
        raise ValueError('Research outputs, sources and caches must stay outside checkout')
    if any(root.is_relative_to(path) or path.is_relative_to(root)
           for path in (baseline_root, source_root, fit_cache)):
        raise ValueError('Use an independent sensitivity output directory')
    if workers < 1:
        raise ValueError('At least one worker required')
    input_path = baseline_root / 'inputs' / f'{SYMBOL}.json'
    baseline_protocol_path = baseline_root / 'protocol.json'
    probe_path = source_root / 'source-probes' / 'kosdaq-source-difference.json'
    folder = source_root / 'source' / SYMBOL
    pointer_path = folder / 'latest.json'
    protocol, raw, probe, pointer = map(read_json, (baseline_protocol_path, input_path, probe_path, pointer_path))
    method = experiment_method()
    if protocol['method'] != method or protocol['method_hash'] != signature(method):
        raise ValueError('Primary and sensitivity numerical methods must be identical')
    metadata = raw['source_meta']
    if (raw['symbol'] != SYMBOL or metadata.get('provider') != 'naver'
            or metadata['normalized_sha256'] != probe['canonical_source_meta']['normalized_sha256']
            or metadata['normalized_sha256'] != pointer['normalized_sha256']):
        raise ValueError('Primary input is not the frozen single-source Naver series')
    quality = probe['canonical_source_meta']['data_quality']
    if (quality.get('affected_date') != AFFECTED_DATE or quality.get('observed_naver_close') != CANONICAL_CLOSE
            or quality.get('observed_yahoo_close') != ALTERNATE_CLOSE):
        raise ValueError('Source discrepancy differs from the registered substitution')
    for file_key, hash_key in (('raw_file', 'raw_sha256'), ('normalized_file', 'normalized_sha256')):
        if digest(folder / metadata[file_key]) != metadata[hash_key]:
            raise ValueError('Canonical source hash mismatch')
    frame = pd.DataFrame({'date': raw['dates'], 'close': raw['close']})
    normalized = pd.read_parquet(folder / metadata['normalized_file'])
    if (pd.to_datetime(normalized.date).dt.strftime('%Y-%m-%d').tolist() != raw['dates']
            or normalized.close.tolist() != raw['close']
            or input_identity(frame) != protocol['inputs'][SYMBOL]['input_hash']):
        raise ValueError('Frozen primary input differs from canonical source')
    alternate = substitute_one_point(frame)
    asof = frame.date.iloc[-1]
    if asof != protocol['endpoint_dates'][SYMBOL][-1]:
        raise ValueError('Sensitivity must use the registered latest primary endpoint')
    baseline_records, alternate_records, mapping, tasks, missing, cache_files = {}, {}, [], [], [], []
    for n in WINDOWS:
        for seed in SEEDS:
            original = make_task(frame, asof, n, seed, protocol['method_hash'], method)
            changed = make_task(alternate, asof, n, seed, protocol['method_hash'], method)
            same = original['input_hash'] == changed['input_hash']
            if same != (n < 1000):
                raise ValueError('Unexpected affected-window membership')
            path = fit_cache / (original['key'] + '.json')
            mapping.append({'n': n, 'seed': seed, 'baseline_key': original['key'],
                            'alternate_key': changed['key'], 'baseline_input_hash': original['input_hash'],
                            'alternate_input_hash': changed['input_hash'], 'reused_unchanged_input': same})
            if not path.exists():
                missing.append({'n': n, 'seed': seed, 'key': original['key']})
                continue
            saved = checked_cache(path, original)
            cache_files.append(path)
            baseline_records[(asof, n, seed)] = saved
            if same:
                alternate_records[(asof, n, seed)] = saved
            else:
                tasks.append(changed)
    if missing:
        raise FileNotFoundError(f'Primary latest endpoint incomplete: {len(missing)}/12 fits absent; no fits run')
    protected_paths = [input_path, baseline_protocol_path, probe_path, *folder.rglob('*'), *cache_files]
    protected = inventory(path for path in protected_paths if path.is_file())
    sensitivity = {'schema_version': VERSION, 'status': 'NON_CANONICAL', 'experiment': 'source_discrepancy_sensitivity',
                   'symbol': SYMBOL, 'asof': asof, 'primary_protocol_hash': protocol['protocol_hash'],
                   'method': method, 'method_hash': protocol['method_hash'],
                   'original_input_hash': input_identity(frame), 'alternate_input_hash': input_identity(alternate),
                   'canonical_source_sha256': metadata['normalized_sha256'], 'probe_sha256': digest(probe_path),
                   'substitution': {'date': AFFECTED_DATE, 'original_close': CANONICAL_CLOSE,
                                    'alternate_close': ALTERNATE_CLOSE, 'changed_close_count': 1},
                   'expected_original_fits_reused': 12, 'expected_unchanged_short_fits_reused': 6,
                   'expected_alternate_long_fits': 6, 'mapping': mapping,
                   'independent_vendor_adjudication': 'NOT_ESTABLISHED',
                   'interpretation': 'Local input sensitivity only; does not validate either vendor or establish forecast accuracy.'}
    sensitivity['protocol_hash'] = signature(sensitivity)
    protocol_path = root / 'protocol.json'
    if protocol_path.exists():
        if read_json(protocol_path).get('protocol_hash') != sensitivity['protocol_hash']:
            raise ValueError('Frozen sensitivity changed; use a new output directory')
    else:
        write_once(protocol_path, {**sensitivity, 'registered_at': datetime.now(UTC).isoformat()})
    reused_alternate = 0
    pending = []
    for task in tasks:
        path = fit_cache / (task['key'] + '.json')
        if path.exists():
            saved = checked_cache(path, task)
            if saved.get('origin') != 'source_discrepancy_sensitivity_noncanonical':
                raise ValueError('Alternate cache provenance is not the sensitivity experiment')
            if saved.get('sensitivity_protocol_hash') != sensitivity['protocol_hash']:
                raise ValueError('Alternate cache sensitivity protocol mismatch')
            alternate_records[(asof, task['n'], task['seed'])] = saved
            reused_alternate += 1
        else:
            pending.append(task)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fit_job, task): task for task in pending}
        for future in as_completed(futures):
            task = futures[future]
            result = future.result()
            result.update(origin='source_discrepancy_sensitivity_noncanonical',
                          sensitivity_protocol_hash=sensitivity['protocol_hash'], key=task['key'])
            if result.get('status') == 'complete':
                result['independent_readback'] = check_fit(
                    result['fit'], task['close'], {'lin': numerical.lin, 'Xmat': numerical.Xmat})
            write_once(fit_cache / (task['key'] + '.json'), result)
            alternate_records[(asof, task['n'], task['seed'])] = result
    unchanged = protected == inventory(Path(path) for path in protected)
    if not unchanged:
        raise ValueError('Protected source/primary files changed during experiment')
    protection = {'unchanged': True, 'files': protected}
    atomic_json(root / 'protected-file-hashes.json', protection)
    failed = sum(row['status'] != 'complete' for row in alternate_records.values())
    if failed:
        atomic_json(root / 'summary.json', {'status': 'incomplete', 'experiment': sensitivity['experiment'],
                                          'noncanonical': True, 'failed': failed, 'expected': 12,
                                          'source_unchanged': True, 'protocol_hash': sensitivity['protocol_hash']})
        raise RuntimeError(f'{failed} alternate fits failed; no comparison claimed')
    canonical_view = make_snapshot(SYMBOL, asof, frame, metadata, baseline_records, protocol['method_hash'], method)
    alternative_meta = deepcopy(metadata)
    alternative_meta.update(source='NON_CANONICAL one-point source-discrepancy sensitivity',
                            normalized_sha256='NON_CANONICAL:' + input_identity(alternate),
                            provider='experimental_copy', data_quality={'status': 'NON_CANONICAL',
                            'source_discrepancy_unresolved': True, 'canonical_parent': metadata['normalized_sha256']})
    alternate_view = make_snapshot(SYMBOL, asof, alternate, alternative_meta, alternate_records, protocol['method_hash'], method)
    alternate_view['experiment_status'] = 'NON_CANONICAL'
    summary = {'schema_version': VERSION, 'status': 'complete', 'experiment_status': 'NON_CANONICAL',
               'experiment': sensitivity['experiment'], 'symbol': SYMBOL, 'asof': asof,
               'protocol_hash': sensitivity['protocol_hash'], 'primary_protocol_hash': protocol['protocol_hash'],
               'method_hash': protocol['method_hash'], 'substitution': sensitivity['substitution'],
               'original_input_hash': sensitivity['original_input_hash'],
               'alternate_input_hash': sensitivity['alternate_input_hash'],
               'canonical_source_sha256': sensitivity['canonical_source_sha256'],
               'probe_sha256': sensitivity['probe_sha256'],
               'source_unchanged': True, 'protected_files': len(protected),
               'counts': {'baseline_reused': 12, 'unchanged_short_reused': 6, 'alternate_long_expected': 6,
                          'alternate_long_new': len(pending), 'alternate_long_cache_reused': reused_alternate,
                          'complete_alternate_total': len(alternate_records), 'failed': 0},
               'seconds': time.perf_counter() - started, 'completed_at': datetime.now(UTC).isoformat(),
               'first_visible_at': None, 'independent_vendor_adjudication': 'NOT_ESTABLISHED',
               'limits': ['One latest endpoint and one substituted source point only.',
                          'No canonical source or fit was overwritten; no vendor correctness is inferred.',
                          'Cluster/seed agreement is numerical structure, not probability or forecast accuracy.',
                          'All full-cycle 1.5/2.5 gates and optimizer settings are identical to the frozen primary study.',
                          'Future calendar dates are weekday estimates; tc shifts use trading-session units.'],
               **compare_snapshots(canonical_view, alternate_view)}
    atomic_json(root / 'baseline-snapshot.json', canonical_view)
    atomic_json(root / 'alternate-snapshot.json', alternate_view)
    atomic_json(root / 'summary.json', summary)
    (root / 'REPORT.md').write_text(report_markdown(summary), encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'source-root', 'baseline-root', 'fit-cache'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    summary = run(args.root, args.source_root, args.baseline_root, args.fit_cache, workers=args.workers)
    print(json.dumps({key: summary[key] for key in ('status', 'experiment_status', 'counts',
                                                  'source_unchanged', 'maximum_absolute_tc_shift_sessions', 'seconds')}, indent=2))


if __name__ == '__main__':
    main()
