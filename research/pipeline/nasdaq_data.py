"""Fetch Nasdaq daily data into the website's existing source cache; never fit."""
from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..data.global_terminal import ASSETS, fetch_snapshot, load_cached_snapshot

NASDAQ = ('US_IXIC', 'US_NDX')
ALIASES = {'IXIC': 'US_IXIC', '^IXIC': 'US_IXIC', 'NDX': 'US_NDX', '^NDX': 'US_NDX'}
ROOT = Path(__file__).resolve().parents[2]


def _atomic_report(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def run(root: Path, assets: list[str], *, cache_only: bool = False,
        minimum_rows: int = 6600) -> tuple[dict, int]:
    root = root.resolve()
    if root.is_relative_to(ROOT):
        raise ValueError('Data root must stay outside the source checkout')
    if not assets or len(assets) != len(set(assets)) or any(s not in NASDAQ for s in assets):
        raise ValueError('Only unique US_IXIC / US_NDX assets are accepted')
    if isinstance(minimum_rows, bool) or not isinstance(minimum_rows, int) or minimum_rows < 1:
        raise ValueError('minimum_rows must be a positive integer')
    report = {'schema_version': 'nasdaq_data_refresh_v1',
              'started_at': datetime.now(UTC).isoformat(), 'assets': [],
              'model_execution': False, 'publication': 'none'}
    failures = 0
    for symbol in assets:
        try:
            if cache_only:
                frame, metadata = load_cached_snapshot(symbol, root)
            else:
                frame, metadata = fetch_snapshot(symbol, root, refresh=True,
                    full_history=True, minimum_rows=minimum_rows, provider='yfinance')
            if len(frame) < minimum_rows:
                raise ValueError(f'Need {minimum_rows} actual daily rows; received {len(frame)}')
            report['assets'].append({'id': symbol, 'ticker': ASSETS[symbol]['ticker'],
                'market': 'us', 'kind': 'index', 'status': 'cached' if cache_only else 'updated',
                'asof': metadata['asof'], 'rows': len(frame),
                'source': metadata['source'], 'data_hash': metadata['normalized_sha256'],
                'fetched_at': metadata['fetched_at'], 'metadata_file': metadata['metadata_file'],
                'fetch_mode': metadata.get('download_mode'), 'source_cache': str(root / 'source' / symbol)})
        except Exception as error:
            failures += 1
            row = {'id': symbol, 'status': 'failed', 'error': f'{type(error).__name__}: {error}',
                   'last_attempt_at': datetime.now(UTC).isoformat(),
                   'stale_reason': 'refresh_failed_existing_snapshot_not_replaced'}
            try:
                frame, metadata = load_cached_snapshot(symbol, root)
                row.update(status='failed_cached_available', cached_asof=metadata['asof'],
                           cached_rows=len(frame), cached_hash=metadata['normalized_sha256'])
            except Exception:
                row['cache_available'] = False
            report['assets'].append(row)
    report.update(completed_at=datetime.now(UTC).isoformat(),
                  status='partial_failure' if failures else 'complete')
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    _atomic_report(root / 'fetch-audit' / (stamp + '-' + uuid.uuid4().hex[:8] + '.json'), report)
    _atomic_report(root / 'nasdaq_fetch_latest.json', report)
    return report, 1 if failures else 0


def main(argv: list[str] | None = None, *, default_asset: str | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path,
                        help='Persistent backend data root outside checkout (Windows: use D:)')
    parser.add_argument('--assets', '--symbol', dest='assets', default=default_asset or ','.join(NASDAQ))
    parser.add_argument('--minimum-rows', type=int, default=6600)
    parser.add_argument('--cache-only', action='store_true', help='Verify existing cache without HTTP')
    args = parser.parse_args(argv)
    assets = [ALIASES.get(s.strip().upper(), s.strip().upper()) for s in args.assets.split(',')]
    report, code = run(args.root, assets, cache_only=args.cache_only, minimum_rows=args.minimum_rows)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
