import hashlib
import subprocess

import numpy as np
import pandas as pd
import pytest

from research.data import tencent_sina
from research.eval import export_contract
from research.features import lppls_scan
from research.pipeline import stock


def _ohlc(n: int, start: str = "2020-01-01") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=n)
    close = 100 * np.exp(np.cumsum(np.sin(np.arange(n) / 13) * 0.002 + 0.0002))
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.999,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(n, 1000.0),
            "amount": np.full(n, 100000.0),
        }
    )


def _fake_fit_asof(logp, asof, windows):
    pos = logp.index.get_loc(pd.Timestamp(asof))
    rows = []
    for n in windows:
        last = float(logp.iloc[pos])
        ahead = round(last - float(logp.iloc[pos - 1]), 4)
        rows.append(
            {
                "date": pd.Timestamp(asof),
                "n": n,
                "tc": n - 1 + ahead,
                "m": 0.5,
                "w": 8.0,
                "A": 1.0,
                "B": -0.1,
                "C1": 0.01,
                "C2": 0.01,
                "sse": 0.1,
                "r2": 0.9,
                "pow_tc": n - 1 + ahead,
                "pow_m": 0.5,
                "pow_B": -0.1,
                "pow_sse": 0.2,
                "lomb_w": 8.0,
                "lomb_pn": 0.2,
                "df_t": -2.0,
                "y_std": float(logp.iloc[pos + 1 - n : pos + 1].std()),
            }
        )
    return pd.DataFrame(rows, columns=[*lppls_scan.COLS, "y_std"])


def _fake_derived(fits):
    out = fits.copy()
    out["ahead"] = out.tc - (out.n - 1)
    return out


def _fake_rules(fits):
    return pd.DataFrame({"box": np.ones(len(fits), dtype=bool)}, index=fits.index)


def _fake_history_frame(d, r, date, cal, close, split, include_scenarios=False):
    rows = d[d.date == date]
    scenarios = [
        {"n": int(row.n), "ahead": round(float(row.ahead), 4)}
        for row in rows.itertuples()
    ]
    conf = round(float(rows.ahead.mean()), 4) if len(rows) else None
    return {
        "asof": str(date.date()),
        "split": split,
        "close": round(float(close), 2),
        "conf": {"6-12m": conf, "12-24m": conf},
        "w": {"6-12m": None, "12-24m": None},
        "scenarios": scenarios if include_scenarios else [],
    }


def _fake_record(sym, asof, d, r, cal, ohlc, data_version):
    frame = _fake_history_frame(
        d, r, pd.Timestamp(asof), cal, float(ohlc.close.iloc[-1]), "stock", True
    )
    return {
        "symbol": sym,
        "asof": asof,
        "model_version": "prereg_v1.7_v2",
        "top": {
            "scenarios": frame["scenarios"],
            "lppls_confidence": {
                "6-12m": frame["conf"]["6-12m"],
                "12-24m": frame["conf"]["12-24m"],
            },
        },
        "validation": [],
    }


def _install_fake_model(monkeypatch):
    monkeypatch.setattr(stock, "fit_asof", _fake_fit_asof)
    monkeypatch.setattr(stock, "_derived", _fake_derived)
    monkeypatch.setattr(stock, "rules", _fake_rules)
    monkeypatch.setattr(stock, "_history_frame", _fake_history_frame)
    monkeypatch.setattr(stock, "build_record", _fake_record)
    monkeypatch.setattr(stock, "_variant_windows", lambda variant, n: (127, 152))
    monkeypatch.setattr(
        stock, "_trading_days_stale", lambda last_bar, asof=None: (0, None)
    )


def test_load_stock_drops_unclosed_same_day_and_future_bars(monkeypatch):
    today = pd.Timestamp("2026-11-02")
    raw = _ohlc(3)
    raw["date"] = [
        today - pd.Timedelta(days=1),
        today,
        today + pd.Timedelta(days=1),
    ]
    factors = pd.DataFrame({"date": ["1900-01-01"], "factor": [1.0]})
    monkeypatch.setattr(stock, "tencent_raw", lambda sym, start: raw.copy())
    monkeypatch.setattr(stock, "sina_factors", lambda sym, kind: factors)

    monkeypatch.setattr(
        stock, "_now", lambda: pd.Timestamp("2026-11-02 10:00", tz="Asia/Shanghai")
    )
    before_close, _, before_meta = stock.load_stock("600519", start="2026-11-01")
    assert before_close.date.tolist() == [today - pd.Timedelta(days=1)]
    assert before_meta["dropped_unclosed_bar"] is True

    monkeypatch.setattr(
        stock, "_now", lambda: pd.Timestamp("2026-11-02 15:31", tz="Asia/Shanghai")
    )
    after_close, _, after_meta = stock.load_stock("600519", start="2026-11-01")
    assert after_close.date.tolist() == [
        today - pd.Timedelta(days=1),
        today,
    ]
    assert after_meta["dropped_unclosed_bar"] is True

    raw = raw.iloc[:2].copy()
    after_close_without_future, _, final_meta = stock.load_stock(
        "600519", start="2026-11-01"
    )
    assert after_close_without_future.date.tolist() == [
        today - pd.Timedelta(days=1),
        today,
    ]
    assert final_meta["dropped_unclosed_bar"] is False


def test_reference_calendar_is_cached_and_drops_unclosed_bars(monkeypatch):
    today = pd.Timestamp("2026-11-02")
    raw = _ohlc(3)
    raw["date"] = [
        today - pd.Timedelta(days=1),
        today,
        today + pd.Timedelta(days=1),
    ]
    calls = []

    def fake_tencent(sym, start):
        calls.append((sym, start))
        return raw.copy()

    monkeypatch.setattr(
        stock,
        "_now",
        lambda: pd.Timestamp("2026-11-02 10:00", tz="Asia/Shanghai"),
    )
    monkeypatch.setattr(stock, "tencent_raw", fake_tencent)
    stock._reference_calendar.cache_clear()
    try:
        first = stock._reference_calendar()
        second = stock._reference_calendar()
        assert first.equals(second)
        assert first.tolist() == [today - pd.Timedelta(days=1)]
        assert calls == [("sh000001", stock.DEFAULT_START)]
    finally:
        stock._reference_calendar.cache_clear()


@pytest.mark.parametrize(
    ("gap", "expected_status", "expected_in_stats"),
    (
        (0, "eligible", True),
        (5, "suspended", False),
        (60, "delisted_or_long_suspended", False),
    ),
)
def test_reference_calendar_gap_controls_stock_status(
    monkeypatch, gap, expected_status, expected_in_stats
):
    prices = _ohlc(600)
    last_bar = pd.Timestamp(prices.date.iloc[-1])
    calendar = pd.DatetimeIndex(pd.bdate_range(last_bar, periods=gap + 1))
    monkeypatch.setattr(stock, "_reference_calendar", lambda: calendar)

    meta = stock._stock_status_meta(prices, False, {"dropped_unclosed_bar": False})
    assert meta["trading_days_stale"] == gap
    assert meta["status"] == expected_status
    assert meta["in_stats"] is expected_in_stats


def test_reference_calendar_gap_is_clipped_at_asof(monkeypatch):
    prices = _ohlc(600)
    last_bar = pd.Timestamp(prices.date.iloc[-1])
    calendar = pd.DatetimeIndex(pd.bdate_range(last_bar, periods=10))
    asof = calendar[5]
    monkeypatch.setattr(stock, "_reference_calendar", lambda: calendar)

    meta = stock._stock_status_meta(
        prices, False, {"dropped_unclosed_bar": False}, asof
    )
    assert meta["trading_days_stale"] == 5
    assert meta["status"] == "suspended"
    assert meta["in_stats"] is False


def test_stale_calendar_does_not_override_ineligible_status(monkeypatch):
    prices = _ohlc(600)
    last_bar = pd.Timestamp(prices.date.iloc[-1])
    calendar = pd.DatetimeIndex(pd.bdate_range(last_bar, periods=61))
    monkeypatch.setattr(stock, "_reference_calendar", lambda: calendar)

    insufficient = stock._stock_status_meta(
        _ohlc(499), False, {"dropped_unclosed_bar": False}
    )
    assert insufficient["status"] == "insufficient_history"
    assert insufficient["in_stats"] is False

    degenerate = _ohlc(505)
    close = degenerate.close.to_numpy(copy=True)
    jump_indices = np.arange(2, 112)
    for index in jump_indices:
        close[index] = close[index - 1] * 1.10
    degenerate["close"] = close
    degenerate["high"] = close
    degenerate["low"] = close
    flagged = stock._stock_status_meta(
        degenerate, False, {"dropped_unclosed_bar": False}
    )
    assert flagged["status"] == "degenerate"
    assert flagged["in_stats"] is False


def test_reference_calendar_failure_keeps_eligibility_and_records_null(monkeypatch):
    prices = _ohlc(600)

    def unavailable(sym, start):
        raise ConnectionError("reference endpoint unavailable")

    stock._reference_calendar.cache_clear()
    monkeypatch.setattr(stock, "tencent_raw", unavailable)
    try:
        meta = stock._stock_status_meta(
            prices, False, {"dropped_unclosed_bar": False}
        )
    finally:
        stock._reference_calendar.cache_clear()

    assert meta["trading_days_stale"] is None
    assert meta["status"] == "eligible"
    assert meta["in_stats"] is True
    assert "参考指数交易日历获取失败" in meta["eligibility_note"]


def test_load_stock_hfq_factor_direction_and_date_boundary(monkeypatch):
    raw = pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-02", "2020-01-03"],
            "open": [10.0, 10.0, 10.0],
            "high": [10.0, 10.0, 10.0],
            "low": [10.0, 10.0, 10.0],
            "close": [10.0, 10.0, 10.0],
            "volume": [1, 1, 1],
        }
    )
    factors = pd.DataFrame(
        {"date": ["2020-01-01", "2020-01-02"], "factor": [1.0, 2.0]}
    )
    monkeypatch.setattr(stock, "tencent_raw", lambda sym, start: raw)
    monkeypatch.setattr(stock, "sina_factors", lambda sym, kind: factors)

    result, version, meta = stock.load_stock("600519", start="2020-01-01")

    assert result.close.tolist() == [10.0, 20.0, 20.0]
    assert version == (
        "vintage_20200103_tencent_sina_hfq_"
        + hashlib.sha1(factors.to_csv(index=False).encode("utf-8")).hexdigest()[:8]
    )
    assert meta["ipo_in_range"] is False


def test_history_is_point_in_time_and_matches_predict(monkeypatch, tmp_path):
    _install_fake_model(monkeypatch)
    prices = _ohlc(610)
    version = ["v1"]
    monkeypatch.setattr(
        stock,
        "load_stock",
        lambda code, start=None: (prices.copy(), version[0], {"ipo_in_range": False}),
    )
    monkeypatch.setattr(stock, "_name_and_st", lambda code: ("sample", False))
    asof = stock._weekly_asofs(stock._fit_logp(prices), 10)[-3]

    record = stock.predict("600519", asof=str(asof.date()), procs=1)
    historical = stock.history(
        "600519", weeks=10, procs=1, cache_dir=tmp_path / "cache"
    )
    assert record["stock_meta"]["trading_days_stale"] == 0
    assert record["stock_meta"]["dropped_unclosed_bar"] is False
    assert historical["stock_meta"]["trading_days_stale"] == 0
    frame = next(item for item in historical["frames"] if item["asof"] == str(asof.date()))
    assert frame["scenarios"] == record["top"]["scenarios"]
    assert frame["conf"] == {
        scale: record["top"]["lppls_confidence"][scale]
        for scale in ("6-12m", "12-24m")
    }

    appended = _ohlc(625)
    monkeypatch.setattr(
        stock,
        "load_stock",
        lambda code, start=None: (appended.copy(), "v2", {"ipo_in_range": False}),
    )
    extended = stock.history(
        "600519", weeks=10, procs=1, cache_dir=tmp_path / "cache"
    )
    extended_frame = next(
        item for item in extended["frames"] if item["asof"] == str(asof.date())
    )
    assert extended_frame["scenarios"] == frame["scenarios"]
    assert extended_frame["conf"] == frame["conf"]


def test_history_cache_reuses_asofs_after_appending_one_bar(monkeypatch, tmp_path):
    _install_fake_model(monkeypatch)
    prices = [_ohlc(600)]
    monkeypatch.setattr(
        stock,
        "load_stock",
        lambda code, start=None: (prices[0].copy(), "v1", {"ipo_in_range": False}),
    )
    monkeypatch.setattr(stock, "_name_and_st", lambda code: ("sample", False))
    calls = []

    def counted_fit(logp, asof, windows):
        calls.append((pd.Timestamp(asof), tuple(windows)))
        return _fake_fit_asof(logp, asof, windows)

    monkeypatch.setattr(stock, "fit_asof", counted_fit)
    stock.history("600519", weeks=3, procs=1, cache_dir=tmp_path)
    cached_asofs = {asof for asof, _ in calls}

    prices[0] = _ohlc(601)
    calls.clear()
    stock.history("600519", weeks=3, procs=1, cache_dir=tmp_path)
    assert calls
    assert cached_asofs.isdisjoint(asof for asof, _ in calls)


def test_history_cache_invalidates_restatement(monkeypatch, tmp_path):
    _install_fake_model(monkeypatch)
    prices = [_ohlc(600)]
    monkeypatch.setattr(
        stock,
        "load_stock",
        lambda code, start=None: (prices[0].copy(), "same-vintage", {"ipo_in_range": False}),
    )
    monkeypatch.setattr(stock, "_name_and_st", lambda code: ("sample", False))
    calls = []

    def counted_fit(logp, asof, windows):
        calls.append((pd.Timestamp(asof), tuple(windows)))
        return _fake_fit_asof(logp, asof, windows)

    monkeypatch.setattr(stock, "fit_asof", counted_fit)
    stock.history("600519", weeks=3, procs=1, cache_dir=tmp_path)
    calls.clear()

    prices[0].loc[prices[0].index[-1], "close"] *= 1.01
    stock.history("600519", weeks=3, procs=1, cache_dir=tmp_path)
    assert calls
    assert {asof for asof, _ in calls} == {pd.Timestamp(prices[0].date.iloc[-1])}


def test_model_code_version_does_not_call_git(monkeypatch):
    expected = stock._version()

    def unexpected_git_call(*args, **kwargs):
        raise AssertionError("model code version must not invoke git")

    monkeypatch.setattr(subprocess, "run", unexpected_git_call)
    assert stock._version() == expected


def test_predict_rejects_non_v2_box(monkeypatch):
    monkeypatch.setattr(stock.lppls_scan, "BOX", "v1")
    with pytest.raises(RuntimeError, match="requires LPPLS_BOX=v2"):
        stock.predict("600519")


def test_history_scenarios_use_full_fit_rows(monkeypatch):
    date = pd.Timestamp("2024-01-05")
    fit = pd.DataFrame(
        {
            "date": [date],
            "n": [127],
            "ahead": [1.0],
            "tc": [127.0],
            "m": [0.5],
            "w": [8.0],
            "D": [1.0],
            "osc": [3.0],
            "n_osc": [1.0],
            "sse": [0.1],
        },
        index=[4],
    )
    scenario = pd.DataFrame(
        [
            {
                "share": 1.0,
                "dt_min": 127,
                "dt_max": 127,
                "ahead_mean": 1.0,
                "ahead_std": 0.0,
                "q20": 1.0,
                "q80": 1.0,
                "q025": 1.0,
                "q975": 1.0,
                "tc_mode": 1.0,
                "rep_idx": 4,
            }
        ]
    )
    monkeypatch.setattr(export_contract, "grid_rules", lambda rows: pd.DataFrame(
        {
            "g_fco_standard": [False],
            "g_fco_early": [False],
            "g_fco_end": [False],
            "g_fco_pure": [False],
        },
        index=rows.index,
    ))
    monkeypatch.setattr(export_contract, "scenarios", lambda rows: scenario)
    monkeypatch.setattr(export_contract, "_curve", lambda *args: {})
    frame = export_contract._history_frame(
        fit,
        pd.DataFrame({"box": [True]}, index=fit.index),
        date,
        pd.date_range("2024-01-01", periods=10),
        100.0,
        "stock",
        include_scenarios=True,
    )
    assert frame["scenarios"][0]["representative"]["m"] == 0.5


def test_parallel_and_serial_window_fits_match():
    dates = pd.bdate_range("2024-01-01", periods=160)
    logp = pd.Series(
        np.log(100 * np.exp(np.cumsum(np.sin(np.arange(160) / 9) * 0.01))),
        index=dates,
    )
    date = dates[-1]
    serial = stock._fit_pairs(logp, [(date, 127), (date, 130)], procs=1)
    parallel = stock._fit_pairs(logp, [(date, 127), (date, 130)], procs=2)
    pd.testing.assert_frame_equal(serial, parallel)


def test_eligibility_history_boundary_ipo_drop_and_degenerate_flag(monkeypatch):
    short = _ohlc(499)
    enough = _ohlc(500)
    assert stock._eligibility(short, False)["status"] == "insufficient_history"
    assert stock._eligibility(enough, False)["in_stats"] is True

    raw = _ohlc(100, start="2021-01-01")
    factors = pd.DataFrame({"date": ["1900-01-01"], "factor": [1.0]})
    monkeypatch.setattr(stock, "tencent_raw", lambda sym, start: raw)
    monkeypatch.setattr(stock, "sina_factors", lambda sym, kind: factors)
    loaded, _, meta = stock.load_stock("600519", start="2020-01-01")
    assert meta["ipo_in_range"] is True
    assert len(loaded) == 40
    assert meta["n_bars"] == 40

    one_price = _ohlc(505)
    jumps = np.linspace(2, 504, 102, dtype=int)
    close = one_price.close.to_numpy(copy=True)
    for i in jumps:
        close[i] = close[i - 1] * 1.10
    one_price["close"] = close
    one_price["high"] = close * 1.01
    one_price["low"] = close * 0.99
    one_price.loc[jumps, "high"] = close[jumps]
    one_price.loc[jumps, "low"] = close[jumps]
    result = stock._eligibility(one_price, False)
    assert result["degenerate"] is True
    assert result["in_stats"] is False

    st_prices = _ohlc(505)
    st_close = st_prices.close.to_numpy(copy=True)
    for i in jumps:
        st_close[i] = st_close[i - 1] * 1.06
    st_prices["close"] = st_close
    st_prices["high"] = st_close * 1.01
    st_prices["low"] = st_close * 0.99
    st_prices.loc[jumps, "high"] = st_close[jumps]
    st_prices.loc[jumps, "low"] = st_close[jumps]
    assert stock._eligibility(st_prices, True)["degenerate"] is True
    assert stock._eligibility(st_prices, False)["degenerate"] is False


def test_hfq_apply_factors_remains_explicit():
    raw = pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-02"],
            "open": [10.0, 10.0],
            "high": [10.0, 10.0],
            "low": [10.0, 10.0],
            "close": [10.0, 10.0],
        }
    )
    factors = pd.DataFrame({"date": ["2020-01-01"], "factor": [2.0]})
    assert tencent_sina.apply_factors(raw, factors, "hfq").close.tolist() == [20.0, 20.0]
    assert tencent_sina.apply_factors(raw, factors, "qfq").close.tolist() == [5.0, 5.0]
