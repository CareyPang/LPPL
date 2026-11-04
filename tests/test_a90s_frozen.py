"""§21.3 (c) 1990 年代 A 股冻结版本：哈希、登记首日、截止日、无周末/非正价（离线）。"""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from research.data import a90s

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v20261104"
OUT = ROOT / "data/frozen" / f"a90s_{VERSION}"


@pytest.fixture(scope="module")
def manifest():
    if not (OUT / "MANIFEST.json").exists():
        pytest.skip("冻结目录不存在")
    return json.loads((OUT / "MANIFEST.json").read_text())


def test_manifest_hashes_match_files(manifest):
    assert a90s.verify(OUT)
    for sym, m in manifest["symbols"].items():
        assert hashlib.sha256((OUT / f"{sym}.parquet").read_bytes()).hexdigest() == m["sha256"]


def test_registered_start_end_and_quality(manifest):
    for sym, (_, _, start) in a90s.SYMBOLS.items():
        df = pd.read_parquet(OUT / f"{sym}.parquet")
        assert df.date.iloc[0] == pd.Timestamp(start)
        assert df.date.iloc[-1] <= pd.Timestamp(a90s.END)
        assert df.date.is_monotonic_increasing and not df.date.duplicated().any()
        assert (df.date.dt.weekday < 5).all()
        assert (df.close > 0).all()
        assert manifest["symbols"][sym]["rows"] == len(df)


def test_fetch_filters_window_and_today(monkeypatch):
    dates = pd.to_datetime(["1990-12-18", "1990-12-19", "2000-12-29", "2001-01-02"])
    fake = pd.DataFrame(dict(date=dates, open=1.0, high=1.0, low=1.0, close=[1.0, 2.0, 3.0, 4.0], volume=1, amount=1))
    monkeypatch.setattr(a90s.S, "fetch_ak_sina_index", lambda *a, **k: fake)
    out = a90s.fetch("sh", "000001", "1990-12-19")
    assert out.date.tolist() == list(pd.to_datetime(["1990-12-19", "2000-12-29"]))
