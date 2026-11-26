import numpy as np
import pandas as pd
import pytest

from research.data import a90s
from research.eval import calibration_lppls


def test_permutation_statistics_ignore_nonfinite_values():
    assert calibration_lppls._perm_pvalue([0.1, 0.6, np.nan], 0.5) == 0.5
    assert np.isnan(calibration_lppls._perm_pvalue([0.1, np.nan], np.nan))
    assert np.isnan(calibration_lppls._perm_pvalue([np.nan], 0.5))
    assert np.isnan(calibration_lppls._nanmean([]))
    assert calibration_lppls._nanmean([1.0, np.nan, 3.0]) == 2.0


def test_null_returns_empty_array_for_short_series():
    result = calibration_lppls._null(
        np.array([True, False, True]),
        np.array([1]),
        np.array([0, 1, 2]),
        120,
        np.random.default_rng(0),
    )

    assert result.shape == (0, 2)


def test_conf_table_returns_early_for_empty_scan(monkeypatch, tmp_path):
    scan = pd.DataFrame(
        {
            "date": pd.Series(dtype="datetime64[ns]"),
            "n": pd.Series(dtype="int64"),
        }
    )
    monkeypatch.setattr(calibration_lppls, "SCAN", tmp_path)
    monkeypatch.setattr(
        calibration_lppls.pd, "read_parquet", lambda _path: scan.copy()
    )
    monkeypatch.setattr(
        calibration_lppls,
        "price_series",
        lambda _sym: pytest.fail("empty scan should not read prices"),
    )

    assert calibration_lppls.conf_table("test").empty


@pytest.mark.parametrize(
    ("scan_date", "window", "price_dates", "message"),
    [
        ("2019-01-02", 1, ["2019-01-01"], "scan dates missing"),
        ("2019-01-01", 2, ["2019-01-01"], "exceed available price history"),
    ],
)
def test_conf_table_rejects_missing_dates_and_negative_windows(
    monkeypatch, tmp_path, scan_date, window, price_dates, message
):
    scan = pd.DataFrame(
        {"date": pd.to_datetime([scan_date]), "n": [window]}
    )
    prices = pd.Series(
        [np.log(100.0 + i) for i in range(len(price_dates))],
        index=pd.to_datetime(price_dates),
    )
    monkeypatch.setattr(calibration_lppls, "SCAN", tmp_path)
    monkeypatch.setattr(
        calibration_lppls.pd, "read_parquet", lambda _path: scan.copy()
    )
    monkeypatch.setattr(calibration_lppls, "price_series", lambda _sym: prices)

    with pytest.raises(ValueError, match=message):
        calibration_lppls.conf_table("test")


def _patch_a90s(monkeypatch, tmp_path, frame):
    monkeypatch.setattr(a90s, "ROOT", tmp_path)
    monkeypatch.setattr(
        a90s, "SYMBOLS", {"sh000001": ("sh", "000001", "1990-12-19")}
    )
    monkeypatch.setattr(a90s, "fetch", lambda *_args: frame.copy())


def test_a90s_rejects_empty_fetch(monkeypatch, tmp_path):
    _patch_a90s(
        monkeypatch,
        tmp_path,
        pd.DataFrame(columns=["date", "close"]),
    )

    with pytest.raises(RuntimeError, match="为空表"):
        a90s.main("guard_test")

    assert not (tmp_path / "data/frozen/a90s_guard_test/sh000001.parquet").exists()


@pytest.mark.parametrize(
    ("dates", "closes", "message"),
    [
        (["1990-12-19", "1990-12-22"], [100.0, 101.0], "weekend_rows=1"),
        (["1990-12-19", "1990-12-20"], [100.0, 0.0], "nonpositive=1"),
    ],
)
def test_a90s_rejects_quality_errors_before_parquet_write(
    monkeypatch, tmp_path, dates, closes, message
):
    frame = pd.DataFrame(
        {"date": pd.to_datetime(dates), "close": closes}
    )
    _patch_a90s(monkeypatch, tmp_path, frame)

    with pytest.raises(RuntimeError, match=message):
        a90s.main("guard_test")

    assert not (tmp_path / "data/frozen/a90s_guard_test/sh000001.parquet").exists()
