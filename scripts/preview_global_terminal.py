"""Loopback-only preview of local international research exports; no publication.

Usage: python scripts/preview_global_terminal.py --results D:/.../global-terminal
Local global JSON wins. Existing A-share JSON is read from the public Pages site.
Only the optional loopback analysis API accepts POST. Do not expose this
development server to the Internet. Existing Worker writes remain disabled.
"""
import hashlib
import json
import math
import re
import sys
from argparse import ArgumentParser
from bisect import bisect_right
from copy import deepcopy
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def record_input_hash(record):
    """Match the complete exact-cutoff prefix used by the rolling study."""
    price = record.get('price_history')
    if not isinstance(price, dict):
        return None
    dates, close = price.get('dates'), price.get('close')
    if (not isinstance(dates, list) or not isinstance(close, list) or not dates or len(dates) != len(close)
            or dates[-1] != record.get('asof')
            or any(not isinstance(d, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', d) for d in dates)
            or len(set(dates)) != len(dates)
            or dates != sorted(dates) or any(d > record['asof'] for d in dates)
            or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v <= 0 for v in close)):
        return None
    return hashlib.sha256(json.dumps({'dates': dates, 'close': close}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def matching_long_input(record, source):
    if not isinstance(source, dict):
        return False
    if source.get('input_hash'):
        return source['input_hash'] == record_input_hash(record)
    return bool(source.get('data_version') and source['data_version'] == record.get('data_version'))


def restrict_long_history(record, study):
    """Every replay row must use this selected record's exact price vintage."""
    stability = study.get('stability') if isinstance(study.get('stability'), dict) else {}
    rows = stability.get('history', study.get('history'))
    if not isinstance(rows, list):
        return
    accepted, excluded = [], 0
    valid_input = record_input_hash(record) is not None
    price = record.get('price_history', {})
    for row in rows:
        asof = row.get('asof') if isinstance(row, dict) else None
        if (not valid_input or not isinstance(asof, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', asof)
                or asof >= record['asof'] or row.get('symbol', record['symbol']) != record['symbol']):
            excluded += 1
            continue
        end = bisect_right(price['dates'], asof)
        prefix = {**record, 'asof': asof, 'price_history': {
            'dates': price['dates'][:end], 'close': price['close'][:end]}}
        # Require an observed exact cutoff even for legacy rows without input_hash.
        if record_input_hash(prefix) is None or not matching_long_input(prefix, row.get('source')):
            excluded += 1
            continue
        accepted.append(row)
    study['history'] = accepted
    study['stability'] = {**stability, 'history': accepted, 'excluded_history_rows': excluded}
    if excluded:
        study['stability']['note'] = (str(stability.get('note') or '') +
            f' 已排除 {excluded} 期资产、截止日或输入版本无法与所选行情原档核对的历史，不用修订后的行情替代旧版。').strip()


def verify_long_version(value, key):
    """Legacy study JSON lacks these fields; versioned new files must reproduce."""
    if not isinstance(value, dict) or key not in value:
        return
    omitted = {'history', 'stability', 'snapshot_path', 'snapshot_version'} if key == 'snapshot_version' else {key}
    payload = {k: v for k, v in value.items() if k not in omitted}
    actual = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if value[key] != actual:
        raise ValueError(f'Long-window {key} content hash mismatch')


def with_long_horizon(record, summary, comparison=None, profile=None):
    """Attach only the exact asset/as-of research snapshot, without file writes.

    Original sparse27 results and history remain unchanged. In particular, a
    current long-window study must never fill a missing historical result.
    """
    if not isinstance(record, dict) or not isinstance(summary, dict):
        return record
    assets = summary.get('assets')
    if not isinstance(assets, dict):
        return record
    asset = assets.get(record.get('symbol'))
    if not isinstance(asset, dict):
        return record
    if isinstance(asset.get('latest'), dict):
        asset = asset['latest']
    if asset.get('asof') != record.get('asof'):
        return record
    if asset.get('symbol') is not None and asset['symbol'] != record.get('symbol'):
        return record
    source = asset.get('source')
    if not matching_long_input(record, source):
        return record
    result = deepcopy(record)
    study = deepcopy(asset)
    restrict_long_history(record, study)
    study['first_visible_at'] = None
    study['preview_delivery'] = 'local_read_only_exact_asof_overlay'
    if isinstance(comparison, dict) and isinstance(comparison.get('assets'), dict):
        comp = comparison['assets'].get(record.get('symbol'))
        if (isinstance(comp, dict) and comp.get('asof') == record.get('asof')
                and comp.get('data_version') == record.get('data_version')):
            study['g3_comparison'] = deepcopy(comp)
    if isinstance(profile, dict) and isinstance(profile.get('assets'), dict):
        diagnostic = profile['assets'].get(record.get('symbol'))
        if (isinstance(diagnostic, dict) and diagnostic.get('asof') == record.get('asof')
                and diagnostic.get('data_version') == record.get('data_version')):
            study['profile_diagnostic'] = deepcopy(diagnostic)
            study['limits'] = [note for note in study.get('limits', [])
                               if note != 'No fixed-tc profile, bootstrap or price forecast was run.']
            study['limits'].append('已附独立固定 tc 误差检验；未运行 bootstrap，未校准顶部概率或价格预测。')
    result.setdefault('research', {})['long_horizon'] = study
    return result


def decorate_long_horizon(record, directory):
    """Optional research corruption cannot hide a completed primary result."""
    if not directory:
        return record
    directory = Path(directory)
    try:
        study_file = directory / 'summary.json'
        if not study_file.is_file():
            return record
        study = json.loads(study_file.read_text(encoding='utf-8'))
        verify_long_version(study, 'report_version')
        symbol, asof = record.get('symbol'), record.get('asof')
        if (isinstance(study, dict) and isinstance(study.get('assets'), dict)
                and isinstance(symbol, str) and re.fullmatch(r'[A-Z0-9_]+', symbol)
                and isinstance(asof, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', asof)):
            asset = study['assets'].get(symbol)
            snapshot = (directory / 'snapshots' / symbol / (asof + '.json')).resolve()
            latest = asset.get('latest') if isinstance(asset, dict) and isinstance(asset.get('latest'), dict) else asset
            if (isinstance(latest, dict) and latest.get('symbol') == symbol and latest.get('asof') == asof
                    and matching_long_input(record, latest.get('source')) and latest.get('snapshot_path')):
                snapshot = (directory / latest['snapshot_path']).resolve()
                if not snapshot.is_relative_to(directory.resolve()) or not snapshot.is_file():
                    raise ValueError('Invalid versioned long-window snapshot pointer')
            if snapshot.is_relative_to(directory.resolve()) and snapshot.is_file():
                exact = json.loads(snapshot.read_text(encoding='utf-8'))
                if not isinstance(exact, dict) or exact.get('symbol') != symbol or exact.get('asof') != asof:
                    raise ValueError('Long-window snapshot identity mismatch')
                verify_long_version(exact, 'snapshot_version')
                if (isinstance(latest, dict) and latest.get('snapshot_path')
                        and (directory / latest['snapshot_path']).resolve() == snapshot
                        and latest.get('snapshot_version') != exact.get('snapshot_version')):
                    raise ValueError('Long-window snapshot version pointer mismatch')
                if isinstance(asset, dict):
                    # Profile and history are added after snapshot creation; never import another cutoff's profile.
                    if (latest.get('symbol') == symbol and latest.get('asof') == asof
                            and latest.get('source') == exact.get('source')):
                        for key in ('profile_diagnostic', 'stability', 'history'):
                            if key in latest:
                                exact[key] = deepcopy(latest[key])
                    stability = asset.get('stability') if isinstance(asset.get('stability'), dict) else {}
                    rows = asset.get('history', stability.get('history', []))
                    if isinstance(rows, list):
                        earlier = [r for r in rows if isinstance(r, dict) and r.get('symbol', symbol) == symbol
                                   and isinstance(r.get('asof'), str) and r['asof'] < asof]
                        exact['stability'] = {**exact.get('stability', {}), 'history': earlier,
                            'note': '各期使用其截止日的历史重建，不代表当时已公开发布。'}
                study = {**study, 'assets': {**study['assets'], symbol: exact}}
        comparison_file = directory / 'g3-comparison' / 'summary.json'
        comparison = json.loads(comparison_file.read_text(encoding='utf-8')) if comparison_file.is_file() else None
        profile_file = directory / 'profile-diagnostic' / 'summary.json'
        profile = json.loads(profile_file.read_text(encoding='utf-8')) if profile_file.is_file() else None
        return with_long_horizon(record, study, comparison, profile)
    except (ValueError, OSError, TypeError) as error:
        return {**record, 'research': {**record.get('research', {}), 'long_horizon_load_error': {
            'status': 'failed', 'reason': f'{type(error).__name__}: {error}'}}}


def main():
    parser = ArgumentParser()
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8796)
    parser.add_argument('--long-results', type=Path, action='append', default=[],
                        help='Local long-horizon summary directory; repeat for independent batches')
    parser.add_argument('--jobs-root', type=Path, help='Enable local queued analysis; store jobs outside checkout')
    parser.add_argument('--aftershock-archive', type=Path, help='Verified source research archive, read only')
    args = parser.parse_args()
    front = Path(__file__).resolve().parents[1] / 'frontend'
    global_root = (args.results / 'global').resolve()
    service = None
    if args.jobs_root:
        from research.pipeline.global_jobs import GlobalJobs
        service = GlobalJobs(args.jobs_root, args.results, args.aftershock_archive)

    class Handler(SimpleHTTPRequestHandler):
        def translate_path(self, path):
            route = urlsplit(path).path
            base, relative = ((global_root, route[len('/lab/mock/data/global/'):])
                              if route.startswith('/lab/mock/data/global/') else (front, route.lstrip('/')))
            resolved = (base / relative).resolve()
            return str(resolved if resolved.is_relative_to(base) else base / '__invalid__')

        def send_data(self, data, content_type):
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, value, status=200):
            data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def local_request(self):
            host = urlsplit('//' + self.headers.get('Host', '')).hostname
            origin = self.headers.get('Origin')
            return host in ('localhost', '127.0.0.1', '::1') and (not origin or (
                urlsplit(origin).hostname in ('localhost', '127.0.0.1', '::1') and urlsplit(origin).port == args.port))

        def decorate(self, record, historical=True):
            if service and record.get('price_history'):
                try:
                    record = service.enrich(record, historical=historical)
                except Exception as error:
                    record = {**record, 'research': {**record.get('research', {}), 'aftershock': {
                        'schema_version': 'aftershock_v1', 'symbol': record.get('symbol'), 'asof': record.get('asof'),
                        'data_version': record.get('data_version'), 'status': 'failed', 'modules': {},
                        'reason': f'{type(error).__name__}: {error}'}}}
            for directory in args.long_results:
                enriched = decorate_long_horizon(record, directory)
                if enriched.get('research', {}).get('long_horizon'):
                    return enriched
                record = enriched
            return record

        def do_GET(self):
            if not self.local_request():
                return self.send_json({'error': '仅接受同源本机请求'}, 403)
            route = urlsplit(self.path).path
            if route.startswith('/api/global-analysis'):
                if not self.local_request():
                    return self.send_json({'error': '仅接受同源本机请求'}, 403)
                if not service:
                    return self.send_json({'available': False, 'reason': '本机计算服务未启用'}, 503)
                if route == '/api/global-analysis':
                    return self.send_json(service.capabilities())
                match = re.fullmatch(r'/api/global-analysis/([0-9a-f]{32})(/result)?', route)
                if not match:
                    return self.send_json({'error': '任务不存在'}, 404)
                try:
                    value = self.decorate(service.result(match[1]), historical=bool(service.get(match[1])['requested_asof'])) if match[2] else service.get(match[1])
                    return self.send_json(value)
                except KeyError:
                    return self.send_json({'error': '任务不存在'}, 404)
                except FileNotFoundError as error:
                    return self.send_json({'error': str(error)}, 409)
                except (ValueError, OSError) as error:
                    return self.send_json({'error': str(error)}, 422)
            if route.startswith('/lab/mock/data/global/'):
                if (args.long_results or service) and route.endswith('.json'):
                    file = Path(self.translate_path(self.path))
                    if file.is_file() or service:
                        try:
                            record = json.loads(file.read_text(encoding='utf-8')) if file.is_file() else None
                            name = route.rsplit('/', 1)[-1]
                            history = re.fullmatch(r'([A-Z0-9_]+)_history\.json', name)
                            if service and history:
                                return self.send_json(service.history(history[1], record))
                            match = re.fullmatch(r'([A-Z0-9_]+)_(latest|\d{4}-\d{2}-\d{2})\.json', name)
                            if service and match:
                                # Existing dated archives win; current pointers may update independently.
                                if match[2] == 'latest' or record is None:
                                    selected = service.selected_result(match[1], None if match[2] == 'latest' else match[2])
                                    if selected and (record is None or selected['asof'] >= record.get('asof', '')):
                                        record = selected
                            if record is None:
                                return self.send_json({'error': '该日期尚未封存；可提交独立回测'}, 404)
                            merged = self.decorate(record, historical=not (match and match[2] == 'latest'))
                            return self.send_data(json.dumps(merged, ensure_ascii=False, allow_nan=False).encode('utf-8'),
                                                  'application/json; charset=utf-8')
                        except (ValueError, OSError, TypeError):
                            # A pending or invalid study cannot interrupt existing prices.
                            pass
                return super().do_GET()
            if route == '/app/lppl-data.js':
                return self.send_data(b"window.LPPL_QUERY_API='/api';\n" +
                                      (front / 'app/lppl-data.js').read_bytes(), 'text/javascript; charset=utf-8')
            if route.startswith('/lab/mock/data/') or route.startswith('/api/'):
                url = ('https://careypang.github.io/LPPL' + self.path if route.startswith('/lab/')
                       else 'https://lppl-stock-query.careypang.workers.dev' + self.path[4:])
                try:
                    with urlopen(url, timeout=20) as response:
                        self.send_data(response.read(), 'application/json; charset=utf-8')
                except HTTPError as error:
                    self.send_error(error.code)
                except (URLError, TimeoutError):
                    self.send_error(502)
                return
            return super().do_GET()

        def do_POST(self):
            if urlsplit(self.path).path != '/api/global-analysis' or not service:
                return self.send_json({'error': '该写入入口未启用'}, 405)
            if not self.local_request():
                return self.send_json({'error': '仅接受同源本机请求'}, 403)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 1 or length > 16384 or 'application/json' not in self.headers.get('Content-Type', ''):
                    return self.send_json({'error': '需要受限JSON请求'}, 400)
                value = json.loads(self.rfile.read(length))
                return self.send_json(service.start(value), 202)
            except (ValueError, TypeError) as error:
                return self.send_json({'error': str(error)}, 400)
            except RuntimeError as error:
                return self.send_json({'error': str(error)}, 429)

    print(f'Local research preview: http://127.0.0.1:{args.port}/home.html', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
