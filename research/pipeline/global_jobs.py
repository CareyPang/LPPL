"""Local asynchronous, single-cutoff international analysis jobs.

Only registered assets are admitted. Raw data and checkpoints stay outside the
checkout. Existing static archives are read, never overwritten by this service.
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from ..data.global_terminal import ASSETS, fetch_snapshot, load_cached_snapshot
from .global_terminal import (
    WINDOWS,
    atomic_json,
    clean,
    fit_job,
    fit_key,
    make_record,
    merge_history,
    method_identity,
)


def now():
    return datetime.now(UTC).isoformat()


def identity(value):
    return hashlib.sha256(json.dumps(clean(value), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class GlobalJobs:
    def __init__(self, root, source_root, archive_root=None, long_root=None):
        self.root, self.source_root = Path(root).resolve(), Path(source_root).resolve()
        checkout = Path(__file__).resolve().parents[2]
        if self.root.is_relative_to(checkout) or self.source_root.is_relative_to(checkout):
            raise ValueError('Job/cache roots must be outside source checkout')
        self.root.mkdir(parents=True, exist_ok=True)
        self.archive_root = Path(archive_root) if archive_root else None
        self.long_root = Path(long_root) if long_root else None
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='global-analysis')
        self.jobs, self.active = {}, {}

    def capabilities(self):
        return {'available': True, 'symbols': list(ASSETS), 'methods': ['lppls_sparse27', 'aftershock'],
                'local_only': True, 'asof_mode': 'one_exact_endpoint', 'history_auto_run': False}

    def start(self, body):
        if not isinstance(body, dict):
            raise ValueError('JSON object required')
        symbol = str(body.get('symbol', '')).upper()
        if symbol not in ASSETS:
            raise ValueError('资产尚未登记；不会替换成其他指数')
        asof = body.get('asof') or None
        if asof is not None:
            if not isinstance(asof, str) or len(asof) != 10:
                raise ValueError('截止日必须为YYYY-MM-DD')
            date = pd.Timestamp(asof)
            if date.strftime('%Y-%m-%d') != asof or date.tz is not None:
                raise ValueError('无效截止日')
        refresh = body.get('refresh', True)
        if not isinstance(refresh, bool):
            raise ValueError('refresh must be boolean')
        key = (symbol, asof)
        with self.lock:
            if key in self.active:
                return dict(self.jobs[self.active[key]])
            if len(self.active) >= 8:
                raise RuntimeError('任务队列已满，请稍后重试')
            job_id = uuid.uuid4().hex
            job = {'job_id': job_id, 'symbol': symbol, 'requested_asof': asof, 'status': 'queued',
                   'progress': {'completed': 0, 'expected': 27}, 'created_at': now(), 'updated_at': now(),
                   'result_url': f'/api/global-analysis/{job_id}/result', 'asof': None, 'error': None}
            self.jobs[job_id] = job
            self.active[key] = job_id
            self._save(job)
            self.executor.submit(self._run, job_id, refresh)
            return dict(job)

    def _save(self, job):
        atomic_json(self.root / 'jobs' / (job['job_id'] + '.json'), job)

    def _update(self, job_id, **changes):
        with self.lock:
            self.jobs[job_id].update(changes, updated_at=now())
            self._save(self.jobs[job_id])

    def get(self, job_id):
        if not isinstance(job_id, str) or len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
            raise KeyError('任务不存在')
        with self.lock:
            if job_id in self.jobs:
                return dict(self.jobs[job_id])
        path = self.root / 'jobs' / (job_id + '.json')
        if not path.is_file():
            raise KeyError('任务不存在')
        value = json.loads(path.read_text(encoding='utf-8'))
        if value['status'] not in ('complete', 'failed'):
            value.update(status='failed', error='本机服务重启中断了旧任务，请重试；旧结果未删除')
        return value

    def result(self, job_id):
        job = self.get(job_id)
        path = self.root / 'results' / (job_id + '.json')
        if not path.is_file():
            raise FileNotFoundError('分析仍在进行' if job['status'] != 'failed' else job['error'])
        value = json.loads(path.read_text(encoding='utf-8'))
        if value.get('symbol') != job['symbol'] or value.get('asof') != job['asof']:
            raise ValueError('Result identity mismatch')
        if value.get('record_version') and value['record_version'] != identity({k: v for k, v in value.items() if k != 'record_version'}):
            raise ValueError('Result content hash mismatch')
        return value

    def selected_result(self, symbol, asof=None):
        """New exact dates are available; existing dated static archives win."""
        if symbol not in ASSETS:
            return None
        path = self.root / 'pointers' / (symbol + ('_' + asof if asof else '_latest') + '.json')
        if not path.is_file():
            return None
        pointer = json.loads(path.read_text(encoding='utf-8'))
        result = self.result(pointer['job_id'])
        if (result.get('symbol') != symbol or result.get('asof') != pointer.get('asof')
                or (asof and result.get('asof') != asof)
                or result.get('record_version') != pointer.get('record_version')):
            raise ValueError('Selected result pointer identity mismatch')
        return result

    def history(self, symbol, existing=None):
        """Append new dates for display, retaining every original selected frame."""
        if symbol not in ASSETS:
            raise ValueError('Unsupported asset')
        value = existing or {}
        dates = {item['asof'] for item in value.get('frames', [])}
        for path in sorted((self.root / 'pointers').glob(symbol + '_????-??-??.json')):
            pointer = json.loads(path.read_text(encoding='utf-8'))
            if pointer['asof'] not in dates:
                record = self.enrich(self.selected_result(symbol, pointer['asof']), historical=True)
                previous = value
                value = merge_history(previous, record)
                if previous.get('asof', '') > record['asof']:
                    # Adding an older replay must not replace the latest header's provenance.
                    value.update({k: v for k, v in previous.items() if k not in ('frames', 'revisions')})
                dates.add(pointer['asof'])
        return value

    def enrich(self, record, historical=True):
        """Supplement failures never make an already fitted LPPL result disappear."""
        result = {**record, 'research': {**record.get('research', {})}}
        try:
            result = self._aftershock(result)
        except Exception as error:
            result['research']['aftershock'] = {
                'schema_version': 'aftershock_v1', 'symbol': record.get('symbol'), 'asof': record.get('asof'),
                'data_version': record.get('data_version'), 'status': 'failed', 'modules': {},
                'reason': f'{type(error).__name__}: {error}'}
        from ..data.global_events import collect_market_events
        events = result['research'].get('market_events')
        if not historical or not events or events.get('mode') != 'historical':
            try:
                result['research']['market_events'] = collect_market_events(
                    record['symbol'], self.source_root, record['asof'], mode='historical' if historical else 'current')
            except Exception as error:
                result['research']['market_events'] = {
                    'symbol': record.get('symbol'), 'asof': record.get('asof'), 'mode': 'historical' if historical else 'current',
                    'status': 'failed', 'items': [], 'stale_reason': str(error), 'model_input': False}
        return result

    def _aftershock(self, record):
        """Add matched research to a response without rewriting its original file."""
        symbol, asof = record.get('symbol'), record.get('asof')
        price = record.get('price_history') or {}
        if symbol not in ASSETS or not asof or not price.get('dates'):
            return record
        from ..features.aftershock import analyze_aftershock
        module_path = Path(__file__).resolve().parents[1] / 'features' / 'aftershock.py'
        archive_hashes = {}
        if self.archive_root and self.archive_root.is_dir():
            # Cache reuse must notice modified evidence, not just its directory name.
            for file in sorted(self.archive_root.rglob('*')):
                if file.is_file() and file.suffix in ('.json', '.csv', '.py'):
                    archive_hashes[str(file.relative_to(self.archive_root))] = hashlib.sha256(file.read_bytes()).hexdigest()
        key = identity({'symbol': symbol, 'asof': asof, 'version': record.get('data_version'),
                        'dates': price['dates'], 'close': price['close'],
                        'code': hashlib.sha256(module_path.read_bytes()).hexdigest(), 'archive': archive_hashes})
        path = self.root / 'supplements' / (key + '.json')
        if path.exists():
            analysis = json.loads(path.read_text(encoding='utf-8'))
        else:
            frame = pd.DataFrame({'date': pd.to_datetime(price['dates']), 'close': price['close']})
            analysis = analyze_aftershock(symbol, frame, asof,
                {'symbol': symbol, 'asset_id': symbol, 'data_version': record.get('data_version'),
                 'source': record.get('source'), 'timezone': record.get('timezone')}, self.archive_root)
            atomic_json(path, clean(analysis))
        if analysis.get('symbol') != symbol or analysis.get('asof') != asof or analysis.get('data_version') != record.get('data_version'):
            raise ValueError('Aftershock source identity mismatch')
        return {**record, 'research': {**record.get('research', {}), 'aftershock': analysis}}

    def _run(self, job_id, refresh):
        job = self.get(job_id)
        symbol, requested = job['symbol'], job['requested_asof']
        try:
            self._update(job_id, status='fetching')
            source_note = None
            try:
                frame, metadata = fetch_snapshot(symbol, self.source_root, refresh=refresh, full_history=True)
            except Exception as error:
                frame, metadata = load_cached_snapshot(symbol, self.source_root)
                source_note = f'刷新失败，使用有来源的缓存：{type(error).__name__}: {error}'
            actual = requested or str(frame.date.iloc[-1].date())
            asof = pd.Timestamp(actual)
            prefix = frame[frame.date <= asof].copy()
            if prefix.empty or prefix.date.iloc[-1] != asof:
                raise ValueError('该截止日没有完整交易日线；不会用邻近日期替代')
            expected = [n for n in WINDOWS if n <= len(prefix)]
            if not expected:
                raise ValueError('可用日线不足10根，无法执行已登记窗口')
            self._update(job_id, asof=actual, status='fitting', source_status='stale' if source_note else 'ready',
                         source_note=source_note, progress={'completed': 0, 'expected': len(expected)})
            method = method_identity()
            optimizer = 'de' if symbol == 'US_MRVL' else 'g3'
            cells, tasks = [], []
            for n in expected:
                key = fit_key(prefix, asof, n, optimizer, method)
                path = self.root / 'fits' / (key + '.json')
                original = self.source_root / 'fits' / symbol / actual / f'{n}-{key}.json'
                candidate = path if path.exists() else original
                if candidate.exists():
                    cached = json.loads(candidate.read_text(encoding='utf-8'))
                    if (cached.get('fit_input_hash') == key and cached.get('status') == 'complete'
                            and cached.get('asset_id') == symbol and cached.get('asof') == actual and cached.get('n') == n):
                        cells.append(cached)
                        continue
                tail = prefix.tail(n)
                tasks.append(({'asset_id': symbol, 'asof': actual, 'n': n, 'optimizer': optimizer, 'key': key,
                               'dates': tail.date.dt.strftime('%Y-%m-%d').tolist(), 'close': tail.close.tolist()}, path))
            reused = len(cells)
            self._update(job_id, cache_reused=reused, progress={'completed': len(cells), 'expected': len(expected)})
            with ProcessPoolExecutor(max_workers=2) as pool:
                futures = {pool.submit(fit_job, task): (task, path) for task, path in tasks}
                for future in as_completed(futures):
                    task, path = futures[future]
                    value = future.result()
                    atomic_json(path, value)
                    if value['status'] != 'complete':
                        raise RuntimeError(f"{task['n']}日窗口计算失败：{value.get('error')}")
                    cells.append(value)
                    self._update(job_id, progress={'completed': len(cells), 'expected': len(expected)})
            record = make_record(symbol, frame, metadata, asof, cells, method)
            record['source_status'] = 'stale' if source_note else 'ready'
            record['stale_reason'] = source_note
            record['job_id'] = job_id
            record['research']['job_scope'] = 'one exact endpoint; cached windows reused; no automatic 104-week replay'
            record = self.enrich(record)
            atomic_json(self.root / 'results' / (job_id + '.json'), record)
            aftershock_status = record['research']['aftershock'].get('status', 'complete')
            self._update(job_id, status='current_ready', modules={'lppls': 'complete', 'aftershock': aftershock_status, 'events': 'running'})
            from ..data.global_events import collect_market_events
            try:
                events = collect_market_events(symbol, self.source_root, actual, refresh=not bool(requested),
                                                mode='historical' if requested else 'current')
            except Exception as error:
                events = {'symbol': symbol, 'asof': actual, 'status': 'failed', 'items': [], 'stale_reason': str(error)}
            record['research']['market_events'] = events
            # Content-address the finished result. Exact archived date pointers are not overwritten.
            record['record_version'] = identity(record)
            immutable = self.root / 'archive' / (record['record_version'] + '.json')
            if not immutable.exists():
                atomic_json(immutable, record)
            atomic_json(self.root / 'results' / (job_id + '.json'), record)
            dated = self.root / 'pointers' / (symbol + '_' + actual + '.json')
            if not dated.exists():
                atomic_json(dated, {'job_id': job_id, 'asof': actual, 'record_version': record['record_version']})
            if not requested:
                atomic_json(self.root / 'pointers' / (symbol + '_latest.json'), {'job_id': job_id, 'asof': actual, 'record_version': record['record_version']})
            self._update(job_id, status='complete', completed_at=now(), modules={'lppls': 'complete', 'aftershock': aftershock_status, 'events': events['status']})
        except Exception as error:
            self._update(job_id, status='failed', error=f'{type(error).__name__}: {error}', completed_at=now())
        finally:
            with self.lock:
                self.active.pop((symbol, requested), None)
