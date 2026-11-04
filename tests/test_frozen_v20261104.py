"""Offline integrity checks for the corrected frozen index vintage."""

import hashlib
import json
from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

from research.data.cache import quality_check

ROOT = Path(__file__).resolve().parents[1]
FROZEN_ROOT = ROOT / "data" / "frozen"
OUTPUT = FROZEN_ROOT / "v20261104"
BASE = FROZEN_ROOT / "v20261024"
A90S = FROZEN_ROOT / "a90s_v20261104"
SPLICE_SYMBOLS = ("sh000001", "sz399001")
FIRST_DATES = {"sh000001": "1990-12-19", "sz399001": "1991-04-03"}
SPLICE_END = pd.Timestamp("2000-12-29")
SPLICE_START = pd.Timestamp("2001-01-02")


def _manifest(path: Path) -> list[dict]:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))


def _record_map(path: Path) -> dict[str, dict]:
    return {record["symbol"]: record for record in _manifest(path)}


def test_manifest_hashes_and_metadata_match_files():
    records = _manifest(OUTPUT)
    assert len(records) == 8

    for record in records:
        path = OUTPUT / f"{record['symbol']}_qfq.parquet"
        frame = pd.read_parquet(path)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
        assert record["vintage"] == "20261104"
        assert record["rows"] == len(frame)
        assert record["first_date"] == frame["date"].iloc[0].strftime("%Y-%m-%d")
        assert record["last_date"] == frame["date"].iloc[-1].strftime("%Y-%m-%d")
        assert record["quality_check"] == quality_check(frame)
        assert list(frame.columns) == [
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
        ]
        assert frame["date"].dtype == "datetime64[ns]"
        assert all(frame[column].dtype == "float64" for column in frame.columns[1:])


def test_six_unchanged_files_are_byte_identical():
    base_files = sorted(BASE.glob("*_qfq.parquet"))
    unchanged = [
        path for path in base_files if path.stem.removesuffix("_qfq") not in SPLICE_SYMBOLS
    ]
    assert len(unchanged) == 6
    for source in unchanged:
        assert (OUTPUT / source.name).read_bytes() == source.read_bytes()


def test_splice_boundaries_match_sources():
    for symbol in SPLICE_SYMBOLS:
        result = pd.read_parquet(OUTPUT / f"{symbol}_qfq.parquet")
        original = pd.read_parquet(BASE / f"{symbol}_qfq.parquet")
        a90s = pd.read_parquet(A90S / f"{symbol}.parquet")

        result_old = result.loc[result["date"] <= SPLICE_END].reset_index(drop=True)
        source_old = a90s.loc[a90s["date"] <= SPLICE_END].reset_index(drop=True)
        assert result_old["date"].equals(source_old["date"])
        assert result_old["close"].equals(source_old["close"])
        for column in ("open", "high", "low", "close"):
            assert result_old[column].equals(source_old[column])
        assert result_old["volume"].equals((source_old["volume"] / 100).astype("float64"))
        assert result_old["amount"].equals(source_old["amount"].astype("float64"))

        result_new = result.loc[result["date"] >= SPLICE_START].reset_index(drop=True)
        source_new = original.loc[original["date"] >= SPLICE_START].reset_index(drop=True)
        assert_frame_equal(result_new, source_new, check_exact=True)

    records = _record_map(OUTPUT)
    expected_source = (
        "a90s_v20261104(<=2000-12-29)+v20261024(>=2001-01-02)"
    )
    assert all(records[symbol]["source"] == expected_source for symbol in SPLICE_SYMBOLS)


def test_dates_prices_and_registered_start_dates():
    for symbol, first_date in FIRST_DATES.items():
        frame = pd.read_parquet(OUTPUT / f"{symbol}_qfq.parquet")
        assert frame["date"].iloc[0] == pd.Timestamp(first_date)

    for record in _manifest(OUTPUT):
        frame = pd.read_parquet(OUTPUT / f"{record['symbol']}_qfq.parquet")
        assert frame["date"].is_monotonic_increasing
        assert not frame["date"].duplicated().any()
        assert (frame["date"].dt.day_of_week < 5).all()
        assert (frame[["open", "high", "low", "close"]] > 0).all().all()
