"""Fixed-tc loss diagnostics for the latest 6600-day fits; not probabilities."""
from __future__ import annotations
import argparse
import ast
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from research.pipeline.global_terminal import atomic_json, clean
from research.pipeline.long_horizon import kernel, signature, digest


def run_cell(task):
    started = time.perf_counter()
    namespace = kernel(task['kernel'], task['kernel_sha256'])
    tree = ast.parse(Path(task['kernel']).read_text(encoding='utf-8-sig'))
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'profile_fit']
    if len(definitions) != 1:
        raise ValueError('Frozen profile_fit absent')
    exec(compile(ast.Module(body=definitions, type_ignores=[]), task['kernel'], 'exec'), namespace)
    try:
        fit = namespace['profile_fit'](np.log(task['close']), 6599 + task['ahead'], task['seed'])
        result = {'status': 'complete', 'fit': fit}
    except Exception as error:
        result = {'status': 'failed', 'error': str(error)}
    return clean({**{k: task[k] for k in ('symbol', 'asof', 'ahead', 'seed', 'key')}, **result,
                  'seconds': time.perf_counter() - started, 'completed_at': datetime.now(UTC).isoformat()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    output = args.root / 'profile-diagnostic'
    (output / 'cells').mkdir(parents=True, exist_ok=True)
    main_manifest = json.loads((args.root / 'manifest.json').read_text(encoding='utf-8'))
    study = json.loads((args.root / 'summary.json').read_text(encoding='utf-8'))
    grid = list(range(1, 89, 3)) + [90]
    protocol = {'asof': '2026-11-20', 'n': 6600, 'ahead_grid': grid, 'seeds': [11, 29],
                'method': main_manifest['method'], 'input_hashes': {},
                'scope': 'Ordinary profiled SSE diagnostics only; not modified profile likelihood or confidence intervals',
                'selection': 'Exploratory followup to the inspected free fits; grid frozen before profile runs'}
    tasks = []
    for symbol in ('US_IXIC', 'US_NDX'):
        raw = json.loads((args.root / 'inputs' / (symbol + '.json')).read_text(encoding='utf-8'))
        close = raw['close'][-6600:]
        dates = raw['date'][-6600:]
        if len(close) != 6600 or dates[-1] != protocol['asof']:
            raise ValueError('Profile input length/asof mismatch')
        protocol['input_hashes'][symbol] = signature({'dates': dates, 'close': close})
        free_window = next(w for w in study['assets'][symbol]['windows'] if w['n'] == 6600)
        if study['assets'][symbol]['asof'] != protocol['asof'] or any(
                seed.get('input_hash') != protocol['input_hashes'][symbol] for seed in free_window['seeds']):
            raise ValueError('Profile input differs from free-fit input; cannot share its minimum')
        for ahead in grid:
            for seed in (11, 29):
                identity = {'symbol': symbol, 'asof': protocol['asof'], 'ahead': ahead, 'seed': seed,
                            'input_hash': protocol['input_hashes'][symbol], 'kernel_sha256': main_manifest['method']['kernel_sha256']}
                tasks.append({**identity, 'key': signature(identity), 'close': close, 'kernel': str(args.root / 'kernel.py')})
    protocol['protocol_hash'] = signature(protocol)
    protocol_path = output / 'protocol.json'
    if protocol_path.exists():
        if json.loads(protocol_path.read_text())['protocol_hash'] != protocol['protocol_hash']:
            raise ValueError('Profile protocol changed; use a separate directory')
    else:
        atomic_json(protocol_path, {**protocol, 'registered_at': datetime.now(UTC).isoformat(), 'runner_sha256': digest(__file__)})
    cells, pending = [], []
    funcs = kernel(str(args.root / 'kernel.py'), main_manifest['method']['kernel_sha256'])
    for task in tasks:
        path = output / 'cells' / (task['key'] + '.json')
        if path.exists():
            saved = json.loads(path.read_text())
            if any(saved.get(k) != task[k] for k in ('key', 'symbol', 'asof', 'ahead', 'seed')):
                raise ValueError('Profile cache mismatch')
            if saved['status'] == 'complete':
                fit = saved['fit']
                check = funcs['lin'](np.arange(6600, dtype=float), np.log(task['close']),
                                     6599 + task['ahead'], fit['m'], fit['omega'])
                if not np.isclose(check['sse'], fit['sse'], rtol=1e-10, atol=1e-12):
                    raise ValueError('Profile cached SSE does not reproduce on its input')
            cells.append(saved)
        else:
            pending.append(task)
    def progress():
        value = {'expected': len(tasks), 'completed': sum(c['status'] == 'complete' for c in cells),
                 'failed': sum(c['status'] != 'complete' for c in cells), 'pending': len(tasks) - len(cells)}
        atomic_json(output / 'progress.json', value)
        return value
    progress()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_cell, task) for task in pending]
        for future in as_completed(futures):
            cell = future.result()
            atomic_json(output / 'cells' / (cell['key'] + '.json'), cell)
            cells.append(cell)
            progress()
            if len(cells) % 20 == 0:
                print(f'{len(cells)}/{len(tasks)} fixed-tc fits saved', flush=True)
    summary = {'schema_version': 'long_profile_diagnostic_v1', 'counts': progress(), 'protocol_hash': protocol['protocol_hash'],
               'runner_sha256': digest(__file__), 'assets': {}}
    for symbol in ('US_IXIC', 'US_NDX'):
        rows = []
        asset_cells = [c for c in cells if c['symbol'] == symbol]
        asset_counts = {'expected': len(grid) * 2,
                        'completed': sum(c['status'] == 'complete' for c in asset_cells),
                        'failed': sum(c['status'] != 'complete' for c in asset_cells),
                        'pending': len(grid) * 2 - len(asset_cells),
                        'converged_seeds': sum(c['status'] == 'complete' and c['fit']['de_success'] and c['fit']['lbfgs_success'] for c in asset_cells)}
        for ahead in grid:
            pair = [c for c in cells if c['symbol'] == symbol and c['ahead'] == ahead and c['status'] == 'complete']
            converged = [c for c in pair if c['fit']['de_success'] and c['fit']['lbfgs_success']]
            rows.append({'ahead': ahead, 'sse': min((c['fit']['sse'] for c in converged), default=None),
                         'completed_seeds': len(pair), 'converged_seeds': len(converged)})
        free = next(w for w in study['assets'][symbol]['windows'] if w['n'] == 6600)
        free_seed = min(free['seeds'], key=lambda seed: seed['sse'])
        best = min([{'ahead': free_seed['tc_ahead'], 'sse': free_seed['sse'], 'kind': 'free_fit'}] +
                   [dict(row, kind='profile_grid') for row in rows if row['sse'] is not None], key=lambda r: r['sse'])
        for row in rows:
            row['delta_sse_pct'] = 100 * (row['sse'] / best['sse'] - 1) if row['sse'] is not None else None
        summary['assets'][symbol] = {'asof': protocol['asof'], 'n': 6600,
             'status': 'complete' if asset_counts['completed'] == asset_counts['expected'] else 'incomplete',
             'data_version': study['assets'][symbol]['source']['data_version'], 'points': rows,
             'counts': asset_counts,
             'minimum': best, 'note': 'Fixed tc, independently refit m/omega and linear coefficients. Relative SSE change is not a probability or calibrated interval. A coarse grid cannot exclude missed narrow modes.'}
    archive = output / 'exports' / (signature(summary) + '.json')
    archive.parent.mkdir(exist_ok=True)
    if not archive.exists():
        atomic_json(archive, clean(summary))
    atomic_json(output / 'summary.json', clean(summary))
    print(str(output / 'summary.json'), flush=True)


if __name__ == '__main__':
    main()
