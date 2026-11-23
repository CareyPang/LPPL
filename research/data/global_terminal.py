"""Small, explicit global daily-data snapshots for local research previews.

Yahoo v8 transport follows global-stock-data's exchange-timezone approach.
This module does not establish redistribution rights. Raw/provider data stays
under the caller's output root; it is never bundled into the source repository.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, time, timedelta
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

NORMALIZER_VERSION = "global_yahoo_v2_nonpositive_ohlc_null"
NAVER_NORMALIZER_VERSION = "global_naver_index_v1_unmodified_close"
FULL_HISTORY_PERIOD1 = -2208988800  # 1900-01-01; range=max may downgrade daily bars.

ASSETS = {
    "US_SPX": dict(ticker="^GSPC", name="标普500", kind="index", market="us", currency="USD", timezone="America/New_York"),
    "US_IXIC": dict(ticker="^IXIC", name="纳斯达克综合指数", kind="index", market="us", currency="USD", timezone="America/New_York"),
    "US_NDX": dict(ticker="^NDX", name="纳斯达克100", kind="index", market="us", currency="USD", timezone="America/New_York"),
    "US_DJI": dict(ticker="^DJI", name="道琼斯工业平均", kind="index", market="us", currency="USD", timezone="America/New_York"),
    "JP_N225": dict(ticker="^N225", name="日经225", kind="index", market="jp", currency="JPY", timezone="Asia/Tokyo"),
    "KR_KOSPI": dict(ticker="^KS11", name="韩国综合指数", kind="index", market="kr", currency="KRW", timezone="Asia/Seoul"),
    "KR_KOSDAQ": dict(ticker="^KQ11", name="韩国科斯达克", kind="index", market="kr", currency="KRW", timezone="Asia/Seoul"),
    "US_MRVL": dict(ticker="MRVL", name="迈威尔科技", kind="stock", market="us", currency="USD", timezone="America/New_York"),
}


def normalise(payload: dict, asset_id: str, fetched_at: datetime) -> tuple[pd.DataFrame, dict]:
    """Use exchange dates; remove incomplete sessions and preserve missing OHLC."""
    asset = ASSETS[asset_id]
    chart = payload.get("chart", {})
    if chart.get("error") or not chart.get("result"):
        raise ValueError("Yahoo did not return a usable chart result")
    result = chart["result"][0]
    meta = result.get("meta", {})
    if str(meta.get("symbol", "")).upper() != asset["ticker"].upper():
        raise ValueError("Yahoo asset identity mismatch")
    if meta.get('dataGranularity') not in (None, '1d'):
        raise ValueError('Provider returned a non-daily interval')
    zone = ZoneInfo(meta.get("exchangeTimezoneName") or asset["timezone"])
    local_now = fetched_at.astimezone(zone)
    quote_data = result["indicators"]["quote"][0]
    timestamps = result.get("timestamp") or []
    adj = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
    if asset["kind"] == "stock" and not adj:
        raise ValueError("Stock adjusted closes unavailable; refusing unlabelled input change")
    close_hour, close_minute = (16, 0) if asset["market"] == "us" else (15, 30)
    latest_close = datetime.combine(local_now.date(), time(close_hour, close_minute), zone)
    regular = meta.get("currentTradingPeriod", {}).get("regular", {})
    if regular.get("end"):
        provider_close = datetime.fromtimestamp(regular["end"], UTC).astimezone(zone)
        if provider_close.date() == local_now.date():
            latest_close = provider_close
    rows, dropped = [], 0
    for i, timestamp in enumerate(timestamps):
        date = datetime.fromtimestamp(timestamp, UTC).astimezone(zone).date()
        if date > local_now.date() or (date == local_now.date() and local_now < latest_close + timedelta(minutes=20)):
            dropped += 1
            continue
        raw_close = quote_data.get("close", [])[i]
        if raw_close is None or not np.isfinite(raw_close) or raw_close <= 0:
            continue
        adjusted = adj[i] if adj and i < len(adj) else raw_close
        if adjusted is None or not np.isfinite(adjusted) or adjusted <= 0:
            continue
        ratio = float(adjusted / raw_close) if asset["kind"] == "stock" else 1.0
        row = {"date": pd.Timestamp(date), "close": float(raw_close) * ratio,
               "raw_close": float(raw_close), "adj_close": float(adjusted)}
        for column in ("open", "high", "low", "volume"):
            values = quote_data.get(column) or []
            value = values[i] if i < len(values) else None
            valid = value is not None and np.isfinite(value) and (column == "volume" or value > 0)
            row[column] = float(value) * (ratio if column != "volume" else 1) if valid else np.nan
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("No completed positive daily bars")
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    return frame, {
        "id": asset_id, **asset, "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "未记录",
        "timezone": str(zone), "fetched_at": fetched_at.isoformat(),
        "provider_symbol": meta.get("symbol"), "provider_currency": meta.get("currency"),
        "dropped_unclosed_bars": dropped, "rows": len(frame),
        "first_date": str(frame.date.iloc[0].date()), "asof": str(frame.date.iloc[-1].date()),
        "source": "Yahoo Finance v8 chart", "adjustment": "provider_adjclose_ratio_OHLC" if asset["kind"] == "stock" else "none",
        "volume_unit": "vendor_native", "public_redistribution": "NOT_ESTABLISHED",
        "history_vintage": "current_download_reconstruction",
        "close_cutoff_policy": "exchange date; regular close plus 20 minutes; previous dates retained",
    }


def _atomic_pointer(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def normalise_naver(raw: bytes, asset_id: str, fetched_at: datetime) -> tuple[pd.DataFrame, dict]:
    """Preserve Naver's entire KOSDAQ series without filling from another vendor.

    The endpoint returns a JavaScript-like literal, not strict JSON. literal_eval
    parses data without executing code. Historical Saturday sessions are retained.
    """
    if asset_id != 'KR_KOSDAQ':
        raise ValueError('Naver full-history adapter is only verified for KR_KOSDAQ')
    data = ast.literal_eval(raw.decode('utf-8-sig').strip())
    expected = ['날짜', '시가', '고가', '저가', '종가', '거래량', '외국인소진율']
    if not isinstance(data, list) or not data or data[0] != expected:
        raise ValueError('Naver daily schema changed')
    asset = ASSETS[asset_id]
    zone = ZoneInfo(asset['timezone'])
    local_now = fetched_at.astimezone(zone)
    cutoff = datetime.combine(local_now.date(), time(15, 50), zone)
    rows, dropped = [], 0
    for values in data[1:]:
        if not isinstance(values, list) or len(values) != len(expected):
            raise ValueError('Naver daily row schema changed')
        date = datetime.strptime(str(values[0]), '%Y%m%d').date()
        if date > local_now.date() or (date == local_now.date() and local_now < cutoff):
            dropped += 1
            continue
        close = float(values[4])
        if not np.isfinite(close) or close <= 0:
            raise ValueError('Naver contains a nonpositive or nonfinite close')
        row = {'date': pd.Timestamp(date), 'close': close, 'raw_close': close, 'adj_close': close}
        for name, value in zip(('open', 'high', 'low', 'volume'), (values[1], values[2], values[3], values[5]), strict=True):
            valid = value is not None and np.isfinite(value) and (value >= 0 if name == 'volume' else value > 0)
            row[name] = float(value) if valid else np.nan
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError('No completed positive daily bars')
    if frame.date.duplicated().any() or not frame.date.is_monotonic_increasing:
        raise ValueError('Naver daily dates must be unique and ascending')
    return frame, {
        'id': asset_id, **asset, 'exchange': 'KOSDAQ', 'provider': 'naver',
        'provider_symbol': 'KOSDAQ', 'provider_currency': 'KRW',
        'identity_validation': 'request_bound_symbol; response has no independent symbol field',
        'fetched_at': fetched_at.isoformat(), 'timezone': str(zone), 'rows': len(frame),
        'first_date': str(frame.date.iloc[0].date()), 'asof': str(frame.date.iloc[-1].date()),
        'source': 'Naver Finance siseJson daily', 'adjustment': 'provider_index_level_unmodified',
        'index_level_basis': 'vendor historical index level; no locally applied rebasing',
        'ohlc_caveat': 'early vendor OHLC can all equal close; historical independent OHLC completeness not established',
        'volume_unit': 'vendor_native', 'public_redistribution': 'NOT_ESTABLISHED',
        'history_vintage': 'current_download_reconstruction',
        'close_cutoff_policy': 'Asia/Seoul date; regular close plus 20 minutes; previous dates retained',
        'dropped_unclosed_bars': dropped, 'normalizer_version': NAVER_NORMALIZER_VERSION,
        'raw_format': 'naver_array_literal',
        'data_quality': {
            'status': 'unresolved_cross_source_discrepancy',
            'observed_at': '2026-11-23', 'affected_date': '2001-11-01',
            'observed_naver_close': 625.5, 'observed_yahoo_close': 636.4000244140625,
            'current_source_close': next((float(r.close) for r in frame.itertuples() if r.date == pd.Timestamp('2001-11-01')), None),
            'policy': 'retain full Naver series unchanged; cross-source sensitivity is a separately labelled noncanonical experiment',
            'independent_exchange_adjudication': 'NOT_ESTABLISHED',
        },
    }


def _vintage_comparison(frame: pd.DataFrame, previous: pd.DataFrame, previous_info: dict) -> dict:
    overlap = frame[['date', 'close']].merge(previous[['date', 'close']], on='date', suffixes=('_new', '_old'))
    changed = overlap.close_new != overlap.close_old
    material = overlap.close_new.round(2) != overlap.close_old.round(2)
    samples = overlap.loc[material].head(20)
    return {
        'previous_provider': previous_info.get('provider', 'yahoo'),
        'previous_metadata_file': previous_info.get('metadata_file'),
        'previous_normalized_sha256': previous_info['normalized_sha256'],
        'overlap_rows': len(overlap), 'exact_close_changes': int(changed.sum()),
        'close_changes_at_two_decimals': int(material.sum()),
        'max_close_absolute_difference': float((overlap.close_new - overlap.close_old).abs().max()) if len(overlap) else None,
        'material_close_difference_samples': [
            {'date': str(row.date.date()), 'new_close': float(row.close_new), 'previous_close': float(row.close_old)}
            for row in samples.itertuples()
        ],
        'comparison_only_no_values_replaced': True,
    }


def save_snapshot(folder: Path, raw: bytes, frame: pd.DataFrame, info: dict) -> dict:
    """Content-address each normalized vintage, even when raw bytes repeat."""
    digest = hashlib.sha256(raw).hexdigest()
    normalized = frame.to_parquet(index=False)
    normalized_digest = hashlib.sha256(normalized).hexdigest()
    raw_file = digest + ".raw.json"
    normalizer_version = info.get('normalizer_version', NORMALIZER_VERSION)
    normalized_file = f"{normalizer_version}-{normalized_digest}.parquet"
    info = {**{k: v for k, v in info.items() if k != "metadata_file"}, "normalizer_version": normalizer_version, "raw_file": raw_file,
            "raw_sha256": digest, "normalized_file": normalized_file,
            "normalized_sha256": normalized_digest}
    metadata_digest = hashlib.sha256(json.dumps(info, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    metadata_file = f"{digest}-{metadata_digest}.metadata.json"
    info["metadata_file"] = metadata_file
    folder.mkdir(parents=True, exist_ok=True)
    for filename, content in ((raw_file, raw), (normalized_file, normalized),
                              (metadata_file, json.dumps(info, ensure_ascii=False, indent=2).encode())):
        path = folder / filename
        if path.exists():
            if path.read_bytes() != content:
                raise ValueError("Immutable source file content mismatch")
        else:
            path.write_bytes(content)
    _atomic_pointer(folder / "latest.json", info)
    return info


def _cached_snapshot(asset_id: str, folder: Path) -> tuple[pd.DataFrame, dict]:
    info = json.loads((folder / 'latest.json').read_text(encoding='utf-8'))
    if info.get('id') != asset_id or info.get('ticker') != ASSETS[asset_id]['ticker']:
        raise ValueError('Cached source identity mismatch')
    for file_key, hash_key in (('normalized_file', 'normalized_sha256'), ('raw_file', 'raw_sha256')):
        path = (folder / info[file_key]).resolve()
        if not path.is_relative_to(folder.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != info[hash_key]:
            raise ValueError('Cached source snapshot checksum mismatch')
    return pd.read_parquet(BytesIO((folder / info['normalized_file']).read_bytes())), info


def load_cached_snapshot(asset_id: str, root: Path) -> tuple[pd.DataFrame, dict]:
    """Strictly local verified cache read; missing/corrupt cache never fetches."""
    return _cached_snapshot(asset_id, Path(root) / 'source' / asset_id)


def _coverage_problem(frame: pd.DataFrame, minimum_rows: int | None, previous: pd.DataFrame | None) -> str | None:
    if minimum_rows is not None and len(frame) < minimum_rows:
        return f'Insufficient daily history: required {minimum_rows}, received {len(frame)}; no padding or proxy substitution'
    if previous is not None:
        missing = sorted(set(previous.date) - set(frame.date))
        if missing:
            return f'Provider history coverage regressed: {len(missing)} previously stored dates absent, first {missing[0].date()}'
    return None


def _save_rejection(folder: Path, raw: bytes, info: dict, reason: str) -> None:
    rejected = folder / 'rejected'
    rejected.mkdir(parents=True, exist_ok=True)
    raw_hash = hashlib.sha256(raw).hexdigest()
    raw_path = rejected / (raw_hash + '.raw.json')
    if not raw_path.exists():
        raw_path.write_bytes(raw)
    evidence = {**info, 'status': 'rejected', 'reason': reason, 'raw_sha256': raw_hash,
                'raw_file': raw_path.name, 'latest_pointer_updated': False}
    evidence_hash = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    evidence_path = rejected / (evidence_hash + '.json')
    if not evidence_path.exists():
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')


def fetch_snapshot(asset_id: str, root: Path, *, refresh: bool = False,
                   full_history: bool = False, minimum_rows: int | None = None,
                   provider: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Fetch explicit daily history and never silently shorten an accepted vintage.

    Full history means the provider's available daily history, not proof of an
    exchange-complete archive. Existing short-history callers keep their default
    start; once this root has a full-history snapshot, refreshes retain that scope.
    A KOSDAQ full-history request selects the independent Naver series because
    Yahoo begins in 2000. provider='yahoo' explicitly selects the shorter source.
    Provider transitions keep all prior vintages and record overlap differences.
    """
    if not isinstance(full_history, bool):
        raise ValueError('full_history must be boolean')
    if minimum_rows is not None and (isinstance(minimum_rows, bool) or not isinstance(minimum_rows, int) or minimum_rows < 1):
        raise ValueError('minimum_rows must be a positive integer')
    asset = ASSETS[asset_id]
    if provider not in (None, 'yahoo', 'naver') or (provider == 'naver' and asset_id != 'KR_KOSDAQ'):
        raise ValueError('Unsupported asset/provider combination')
    folder = Path(root) / "source" / asset_id
    pointer = folder / "latest.json"
    previous, previous_info = _cached_snapshot(asset_id, folder) if pointer.exists() else (None, {})
    effective_full_history = full_history or previous_info.get('full_history_requested', False)
    selected_provider = provider or ('naver' if asset_id == 'KR_KOSDAQ' and full_history else previous_info.get('provider', 'yahoo'))
    same_provider = selected_provider == previous_info.get('provider', 'yahoo')
    if previous is not None and same_provider and not refresh and (not full_history or previous_info.get('full_history_requested')):
        problem = _coverage_problem(previous, minimum_rows, None)
        if problem:
            raise ValueError(problem)
        return previous, previous_info
    if selected_provider == 'naver':
        url = 'https://api.finance.naver.com/siseJson.naver'
        params = {'symbol': 'KOSDAQ', 'requestType': 1, 'startTime': '19000101' if effective_full_history else '20000101',
                  'endTime': datetime.now(ZoneInfo(asset['timezone'])).strftime('%Y%m%d'), 'timeframe': 'day'}
    else:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(asset["ticker"], safe="")
        params = {"period1": FULL_HISTORY_PERIOD1 if effective_full_history else 946684800,
                  "period2": int(datetime.now(UTC).timestamp()), "interval": "1d", "events": "div,split"}
    response = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=(12, 45))
    response.raise_for_status()
    fetched_at = datetime.now(UTC)
    raw = response.content
    frame, info = normalise_naver(raw, asset_id, fetched_at) if selected_provider == 'naver' else normalise(response.json(), asset_id, fetched_at)
    info.update(url=response.url, http_status=response.status_code, provider=selected_provider, full_history_requested=effective_full_history,
                requested_period1=params.get('period1'), requested_start_date=params.get('startTime'), requested_interval='1d', minimum_rows_requested=minimum_rows,
                coverage_scope='provider_available_daily_history' if effective_full_history else 'since_2000_daily_history')
    if previous is not None:
        info['previous_vintage_comparison'] = _vintage_comparison(frame, previous, previous_info)
        info['provider_changed'] = not same_provider
    problem = _coverage_problem(frame, minimum_rows, previous)
    if problem:
        _save_rejection(folder, raw, info, problem)
        raise ValueError(problem)
    return frame, save_snapshot(folder, raw, frame, info)
