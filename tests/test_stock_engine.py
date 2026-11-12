import hashlib
import json
import subprocess
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from research.data import sources, tencent_sina
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
        stock,
        "_trading_days_stale",
        lambda last_bar, asof=None, cutoff=None: (0, None),
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

    monkeypatch.setattr(stock, "tencent_raw", fake_tencent)
    stock._reference_calendar.cache_clear()
    try:
        cutoff = today - pd.Timedelta(days=1)
        first = stock._reference_calendar(cutoff)
        second = stock._reference_calendar(cutoff)
        assert first.equals(second)
        assert first.tolist() == [today - pd.Timedelta(days=1)]
        assert calls == [("sh000001", stock.DEFAULT_START)]
    finally:
        stock._reference_calendar.cache_clear()


@pytest.mark.network
def test_load_beijing_stock_network():
    prices, data_version, meta = stock.load_stock("920002")
    assert len(prices) >= 500
    assert meta["n_bars"] == len(prices)
    assert meta["source"] == "sina"
    assert meta["history_truncated"] is False
    assert meta["history_earliest_date"] == "2024-05-30"
    assert data_version.startswith("vintage_")
    print(
        "920002 load_stock:",
        f"symbol={stock.universe._sym('920002')}",
        f"rows={len(prices)}",
        f"asof={prices.date.iloc[-1].date()}",
        f"source={meta['source']}",
    )


@pytest.mark.network
def test_sina_hfq_matches_tencent_raw_factors_network():
    symbol = "sh600519"
    sina_raw = sources.sina_raw_daily(symbol)
    factors = tencent_sina.sina_factors(symbol, "hfq")
    sina_hfq = tencent_sina.apply_factors(sina_raw, factors, "hfq")
    start = pd.Timestamp(sina_hfq["date"].iloc[max(0, len(sina_hfq) - 640)]).date()
    end = pd.Timestamp(sina_hfq["date"].iloc[-1]).date()
    tencent_raw = tencent_sina.tencent_raw(
        symbol, start=str(start), end=str(end)
    )
    tencent_hfq = tencent_sina.apply_factors(tencent_raw, factors, "hfq")
    sina_raw["date"] = pd.to_datetime(sina_raw["date"])
    tencent_raw["date"] = pd.to_datetime(tencent_raw["date"])
    sina_hfq["date"] = pd.to_datetime(sina_hfq["date"])
    tencent_hfq["date"] = pd.to_datetime(tencent_hfq["date"])
    overlap = sina_hfq.merge(
        tencent_hfq, on="date", suffixes=("_sina", "_tencent")
    )
    assert not overlap.empty
    raw_overlap = sina_raw.merge(
        tencent_raw, on="date", suffixes=("_sina", "_tencent")
    )
    assert not raw_overlap.empty
    raw_relative_errors = []
    relative_errors = []
    for column in ("open", "high", "low", "close"):
        raw_relative_errors.append(
            (
                raw_overlap[f"{column}_sina"] - raw_overlap[f"{column}_tencent"]
            ).abs()
            / raw_overlap[f"{column}_tencent"].abs()
        )
        relative_errors.append(
            (
                overlap[f"{column}_sina"] - overlap[f"{column}_tencent"]
            ).abs()
            / overlap[f"{column}_tencent"].abs()
        )
    max_raw_relative_error = float(
        pd.concat(raw_relative_errors, axis=1).max().max()
    )
    max_relative_error = float(pd.concat(relative_errors, axis=1).max().max())
    assert max_raw_relative_error <= 1e-4
    assert max_relative_error <= 1e-4
    assert np.isfinite(max_relative_error)
    print(
        "sh600519 Sina raw × HFQ vs Tencent raw × HFQ:",
        f"overlap={len(overlap)}",
        f"max_raw_relative_error={max_raw_relative_error:.12g}",
        f"max_relative_error={max_relative_error:.12g}",
    )


def test_sina_raw_daily_parses_wrapped_json_and_marks_limit(monkeypatch):
    class Response:
        text = (
            "/*<script>blocked</script>*/\n"
            'var=([{"day":"2024-05-30","open":"57.000","high":"75.000",'
            '"low":"56.660","close":"67.980","volume":"4621401"},'
            '{"day":"2024-05-31","open":"68.000","high":"72.000",'
            '"low":"60.000","close":"65.000","volume":"3000000"}]);'
        )

        def raise_for_status(self):
            return None

    request = {}

    def fake_get(url, params, headers, timeout):
        request.update(url=url, params=params, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr(sources, "rate_limit", lambda: None)
    monkeypatch.setattr(sources.requests, "get", fake_get)

    frame = sources.sina_raw_daily("bj920002", datalen=2)

    assert request["url"] == sources.SINA_DAILY_URL
    assert request["params"] == {
        "symbol": "bj920002",
        "scale": 240,
        "ma": "no",
        "datalen": 2,
    }
    assert request["headers"]["Referer"] == "https://finance.sina.com.cn/"
    assert request["timeout"] == 15
    assert frame.date.iloc[0] == pd.Timestamp("2024-05-30")
    assert frame.close.tolist() == [67.98, 65.0]
    assert frame.volume.tolist() == [4621401, 3000000]
    assert frame.amount.isna().all()
    assert frame.attrs["source"] == "sina"
    assert frame.attrs["history_truncated"] is True
    assert frame.attrs["history_earliest_date"] == "2024-05-30"


@pytest.mark.parametrize(
    ("code", "symbol"),
    (("920002", "bj920002"), ("600519", "sh600519")),
)
def test_load_stock_uses_sina_raw_after_tencent_failures(monkeypatch, code, symbol):
    raw = _ohlc(600, start="2024-05-30")
    raw.attrs.update(
        source="sina",
        history_truncated=True,
        history_earliest_date="2024-05-30",
    )
    factors = pd.DataFrame({"date": ["1900-01-01"], "factor": [1.0]})
    calls = []

    def fail_tencent(sym, start):
        calls.append(("tencent", sym, start))
        raise RuntimeError("Tencent history unavailable")

    def fail_cache(sym, **kwargs):
        calls.append(("cache", sym, kwargs))
        raise RuntimeError("Tencent cache history unavailable")

    def fake_sina(sym):
        calls.append(("sina", sym))
        return raw.copy()

    monkeypatch.setattr(stock, "sina_factors", lambda *_args, **_kwargs: factors)
    monkeypatch.setattr(stock, "tencent_raw", fail_tencent)
    monkeypatch.setattr(stock.cache, "download", fail_cache)
    monkeypatch.setattr(stock, "sina_raw_daily", fake_sina)

    prices, data_version, meta = stock.load_stock(code)

    assert calls[0][0] == "tencent" and calls[0][1] == symbol
    assert calls[1][0] == "cache" and calls[1][1] == symbol
    assert calls[2] == ("sina", symbol)
    assert len(prices) >= 500
    assert meta["source"] == "sina"
    assert meta["history_truncated"] is True
    assert meta["history_earliest_date"] == "2024-05-30"
    assert data_version.startswith("vintage_") and "_sina_hfq_" in data_version


def test_load_stock_uses_sina_when_tencent_returns_only_latest_bar(monkeypatch):
    latest_bar = _ohlc(1, start="2026-11-02")
    sina_history = _ohlc(600, start="2024-05-30")
    sina_history.attrs.update(
        source="sina",
        history_truncated=False,
        history_earliest_date="2024-05-30",
    )
    factors = pd.DataFrame({"date": ["1900-01-01"], "factor": [1.0]})
    calls = []

    def fake_tencent(sym, start):
        calls.append(("tencent", sym, start))
        return latest_bar.copy()

    def fail_cache(sym, **kwargs):
        calls.append(("cache", sym, kwargs))
        raise RuntimeError("Tencent history unavailable")

    def fake_sina(sym):
        calls.append(("sina", sym))
        return sina_history.copy()

    monkeypatch.setattr(
        stock, "_now", lambda: pd.Timestamp("2026-11-03 16:00", tz="Asia/Shanghai")
    )
    monkeypatch.setattr(stock, "sina_factors", lambda *_args, **_kwargs: factors)
    monkeypatch.setattr(stock, "tencent_raw", fake_tencent)
    monkeypatch.setattr(stock.cache, "download", fail_cache)
    monkeypatch.setattr(stock, "sina_raw_daily", fake_sina)

    prices, _, meta = stock.load_stock("920002")

    assert [call[0] for call in calls] == ["tencent", "cache", "sina"]
    assert len(prices) >= 500
    assert meta["source"] == "sina"


def test_beijing_history_failure_has_clear_error(monkeypatch):
    factors = pd.DataFrame({"date": ["1900-01-01"], "factor": [1.0]})

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("no historical data")

    monkeypatch.setattr(stock, "sina_factors", lambda *_args, **_kwargs: factors)
    monkeypatch.setattr(stock, "tencent_raw", unavailable)
    monkeypatch.setattr(stock.cache, "download", unavailable)
    monkeypatch.setattr(stock, "sina_raw_daily", unavailable)

    with pytest.raises(RuntimeError, match="北交所历史日线暂不可得: bj920002"):
        stock.load_stock("920002")


def test_load_stock_and_calendar_share_close_cutoff(monkeypatch):
    today = pd.Timestamp("2026-11-02")
    raw = _ohlc(600)
    raw["date"] = pd.bdate_range(end=today + pd.Timedelta(days=1), periods=len(raw))
    factors = pd.DataFrame({"date": ["1900-01-01"], "factor": [1.0]})
    now_values = iter(
        (
            pd.Timestamp("2026-11-02 15:29", tz="Asia/Shanghai"),
            pd.Timestamp("2026-11-02 15:31", tz="Asia/Shanghai"),
        )
    )
    now_calls = []
    fetches = []

    def fake_now():
        now_calls.append(True)
        return next(now_values)

    def fake_tencent(sym, start):
        fetches.append(sym)
        return raw.copy()

    monkeypatch.setattr(stock, "_now", fake_now)
    monkeypatch.setattr(stock, "tencent_raw", fake_tencent)
    monkeypatch.setattr(stock, "sina_factors", lambda sym, kind: factors)
    stock._reference_calendar.cache_clear()
    try:
        prices, _, meta = stock.load_stock("600570", start="2020-01-01")
        status = stock._stock_status_meta(prices, False, meta)

        assert prices.date.iloc[-1] == today - pd.Timedelta(days=3)
        assert meta["dropped_unclosed_bar"] is True
        assert meta["reference_cutoff"] == today - pd.Timedelta(days=1)
        assert status["trading_days_stale"] == 0
        assert status["status"] == "eligible"
        assert status["in_stats"] is True
        assert now_calls == [True]
        assert fetches == ["sh600570", "sh000001"]
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
    monkeypatch.setattr(stock, "_reference_calendar", lambda cutoff: calendar)

    meta = stock._stock_status_meta(prices, False, {"dropped_unclosed_bar": False})
    assert meta["trading_days_stale"] == gap
    assert meta["status"] == expected_status
    assert meta["in_stats"] is expected_in_stats


def test_reference_calendar_gap_is_clipped_at_asof(monkeypatch):
    prices = _ohlc(600)
    last_bar = pd.Timestamp(prices.date.iloc[-1])
    calendar = pd.DatetimeIndex(pd.bdate_range(last_bar, periods=10))
    asof = calendar[5]
    monkeypatch.setattr(stock, "_reference_calendar", lambda cutoff: calendar)

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
    monkeypatch.setattr(stock, "_reference_calendar", lambda cutoff: calendar)

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
    raw.attrs["source"] = "tencent_kline"
    monkeypatch.setattr(stock, "tencent_raw", lambda sym, start: raw)
    monkeypatch.setattr(stock, "sina_factors", lambda sym, kind: factors)

    result, version, meta = stock.load_stock("600519", start="2020-01-01")

    assert result.close.tolist() == [10.0, 20.0, 20.0]
    assert version == (
        "vintage_20200103_tencent_sina_hfq_"
        + hashlib.sha1(factors.to_csv(index=False).encode("utf-8")).hexdigest()[:8]
    )
    assert meta["ipo_in_range"] is False
    assert meta["source"] == "tencent_kline"


def test_history_is_point_in_time_and_matches_predict(monkeypatch, tmp_path):
    _install_fake_model(monkeypatch)
    prices = _ohlc(610)
    version = ["v1"]
    monkeypatch.setattr(
        stock,
        "load_stock",
        lambda code, start=None: (
            prices.copy(),
            version[0],
            {"ipo_in_range": False, "source": "tencent_kline"},
        ),
    )
    monkeypatch.setattr(stock, "_name_and_st", lambda code: ("sample", False))
    asof = stock._weekly_asofs(stock._fit_logp(prices), 10)[-3]

    record = stock.predict("600519", asof=str(asof.date()), procs=1)
    historical = stock.history(
        "600519", weeks=10, procs=1, cache_dir=tmp_path / "cache"
    )
    assert record["stock_meta"]["trading_days_stale"] == 0
    assert record["stock_meta"]["dropped_unclosed_bar"] is False
    assert record["stock_meta"]["source"] == "tencent_kline"
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


def test_history_reuses_sealed_price_snapshot_and_fit_cache(monkeypatch, tmp_path):
    _install_fake_model(monkeypatch)
    prices = _ohlc(610)
    monkeypatch.setattr(
        stock, "load_stock", lambda *_args, **_kwargs: pytest.fail("unexpected reload")
    )
    monkeypatch.setattr(stock, "_name_and_st", lambda _code: ("sample", False))
    calls = []

    def counted_fit(logp, asof, windows):
        calls.append((pd.Timestamp(asof), tuple(windows)))
        return _fake_fit_asof(logp, asof, windows)

    monkeypatch.setattr(stock, "fit_asof", counted_fit)
    snapshot = (
        prices,
        "fixture-v1",
        {"ipo_in_range": False, "source": "sealed_fixture"},
    )
    first = stock.history(
        "600519",
        weeks=2,
        procs=1,
        cache_dir=tmp_path,
        price_snapshot=snapshot,
    )
    assert calls
    calls.clear()
    second = stock.history(
        "600519",
        weeks=2,
        procs=1,
        cache_dir=tmp_path,
        price_snapshot=snapshot,
    )

    assert not calls
    assert first["data_version"] == second["data_version"] == "fixture-v1"


def test_history_only_does_not_predict_or_replace_current_on_failure(
    monkeypatch, tmp_path
):
    output = tmp_path / "output"
    output.mkdir()
    code = "600519"
    current_path = output / f"{code}.json"
    prices = _ohlc(600)
    asof = str(prices.date.iloc[-2].date())
    current = {
        "symbol": "sh600519",
        "asof": asof,
        "model_version": f"{stock.MODEL_VERSION}+stk_lite",
        "data_version": "fixture-v1",
        "stock_meta": {
            "price_snapshot": {
                "path": str(tmp_path / "cache" / code / "prices" / "fixture-v1.parquet"),
                "sha256": "sealed-hash",
                "data_version": "fixture-v1",
            }
        },
    }
    current_path.write_text(json.dumps(current), encoding="utf-8")
    before = current_path.read_bytes()
    snapshot = (prices, "fixture-v1", {"ipo_in_range": False})
    requested = {}

    monkeypatch.setattr(
        stock,
        "predict",
        lambda *_args, **_kwargs: pytest.fail("history-only called predict"),
    )
    monkeypatch.setattr(
        stock,
        "_load_price_snapshot",
        lambda *args: requested.update(snapshot_args=args) or snapshot,
    )
    monkeypatch.setattr(
        stock,
        "load_stock",
        lambda *_args, **_kwargs: pytest.fail("history-only reloaded prices"),
    )

    def fail_history(_code, **kwargs):
        requested["history_kwargs"] = kwargs
        raise RuntimeError("history fit failed")

    monkeypatch.setattr(stock, "history", fail_history)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stock",
            code,
            "--history-only",
            "--out",
            str(output),
            "--cache-dir",
            str(tmp_path / "cache"),
        ],
    )

    with pytest.raises(RuntimeError, match="history fit failed"):
        stock.main()

    assert requested["snapshot_args"][1:3] == (
        "fixture-v1",
        tmp_path / "cache",
    )
    assert requested["history_kwargs"]["weeks"] == 104
    assert requested["history_kwargs"]["price_snapshot"][1] == "fixture-v1"
    assert str(
        requested["history_kwargs"]["price_snapshot"][0].date.iloc[-1].date()
    ) == asof
    assert current_path.read_bytes() == before
    assert not (output / f"{code}_history.json").exists()


def test_price_snapshot_is_write_once_and_checksum_verified(tmp_path):
    prices = _ohlc(10)
    meta = {"source": "fixture"}
    reference = stock._seal_price_snapshot(
        "600519", prices, "fixture-v1", meta, tmp_path
    )

    loaded, version, loaded_meta = stock._load_price_snapshot(
        "600519", "fixture-v1", tmp_path, reference
    )

    assert version == "fixture-v1"
    assert loaded.equals(prices)
    assert loaded_meta == meta
    changed = prices.copy()
    changed.loc[changed.index[-1], "close"] += 1
    with pytest.raises(RuntimeError, match="sealed price snapshot changed"):
        stock._seal_price_snapshot("600519", changed, "fixture-v1", meta, tmp_path)


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


def test_stock_fit_version_changes_with_optimizer_bytes(monkeypatch, tmp_path):
    dependencies = (
        "research/lppls/core.py",
        "research/optim/optimizers.py",
        "research/features/lppls_scan.py",
        "research/pipeline/daily.py",
        "research/pipeline/universe.py",
    )
    for relative in dependencies:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((stock.ROOT / relative).read_bytes())
    monkeypatch.setattr(stock, "ROOT", tmp_path)
    original = stock._version()

    optimizer = tmp_path / "research/optim/optimizers.py"
    optimizer.write_bytes(optimizer.read_bytes() + b"\n")

    assert stock._version() != original


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
    raw_hfq = tencent_sina.apply_factors(raw, factors, "hfq")
    assert raw_hfq.close.tolist() == [20.0, 20.0]
    assert tencent_sina.apply_factors(raw, factors, "qfq").close.tolist() == [5.0, 5.0]
    datetime_raw = raw.assign(date=pd.to_datetime(raw.date))
    datetime_factors = factors.assign(date=pd.to_datetime(factors.date))
    assert tencent_sina.apply_factors(
        datetime_raw, datetime_factors, "hfq"
    ).close.tolist() == raw_hfq.close.tolist()


def test_display_calendar_appends_known_future_trading_days(monkeypatch):
    bars = pd.DatetimeIndex(["2025-06-24", "2025-06-25", "2025-06-26", "2025-06-27", "2025-06-30", "2025-07-01"])
    asof = pd.Timestamp("2025-06-30")
    ref = pd.DatetimeIndex(["2025-06-30", "2025-07-01", "2025-07-02", "2025-07-03", "2025-07-04"])
    monkeypatch.setattr(stock, "_reference_calendar", lambda cutoff: ref)
    cal = stock._display_calendar(bars, asof)
    assert list(cal) == list(bars[bars <= asof]) + list(pd.to_datetime(["2025-07-01", "2025-07-02", "2025-07-03", "2025-07-04"]))
    assert cal.is_monotonic_increasing and cal.is_unique
    assert export_contract._to_cal(cal, asof, 2.0) == "2025-07-02"

    def boom(cutoff):
        raise RuntimeError("offline")

    monkeypatch.setattr(stock, "_reference_calendar", boom)
    assert list(stock._display_calendar(bars, asof)) == list(bars[bars <= asof])


def test_main_adds_generated_at_to_current_and_history_records(tmp_path, monkeypatch):
    monkeypatch.setattr(stock, "predict", lambda *_args, **_kwargs: {"symbol": "sh600519"})
    monkeypatch.setattr(
        stock,
        "history",
        lambda *_args, **_kwargs: {"symbol": "sh600519", "frames": []},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["stock", "600519", "--history-weeks", "1", "--out", str(tmp_path)],
    )

    stock.main()

    for name in ("600519.json", "600519_history.json"):
        record = json.loads((tmp_path / name).read_text(encoding="utf-8"))
        assert datetime.fromisoformat(record["generated_at"]).utcoffset().total_seconds() == 0


def test_name_and_st_uses_stock_names_without_http(monkeypatch, tmp_path):
    stock._tencent_stock_name.cache_clear()
    names_path = tmp_path / "stock_names.json"
    names_path.write_text(json.dumps({"600000": "浦发银行"}), encoding="utf-8")
    monkeypatch.setattr(stock, "NAMES_PATH", names_path)

    def fail_http(*_args, **_kwargs):
        raise AssertionError("unexpected HTTP request")

    monkeypatch.setattr(stock.requests, "get", fail_http)
    assert stock._name_and_st("600000") == ("浦发银行", False)


def test_name_and_st_falls_back_to_tencent_gbk_response(monkeypatch, tmp_path):
    stock._tencent_stock_name.cache_clear()
    monkeypatch.setattr(stock, "NAMES_PATH", tmp_path / "missing.json")
    content = 'v_sz301196="51~唯科科技~301196~66.20~..."'.encode("gbk")

    class Response:
        def __init__(self):
            self.content = content

        def raise_for_status(self):
            return None

    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(stock.requests, "get", get)
    assert stock._name_and_st("301196") == ("唯科科技", False)
    assert calls[0][0] == "https://qt.gtimg.cn/q=sz301196"
    assert calls[0][1]["timeout"] == 5


def test_name_and_st_marks_tencent_st_name(monkeypatch, tmp_path):
    stock._tencent_stock_name.cache_clear()
    monkeypatch.setattr(stock, "NAMES_PATH", tmp_path / "missing.json")
    content = 'v_sh600000="51~*ST测试~600000~66.20~..."'.encode("gbk")

    class Response:
        def __init__(self):
            self.content = content

        def raise_for_status(self):
            return None

    monkeypatch.setattr(stock.requests, "get", lambda *_args, **_kwargs: Response())
    assert stock._name_and_st("600000") == ("*ST测试", True)


def test_name_and_st_returns_none_on_tencent_http_failure(monkeypatch, tmp_path):
    stock._tencent_stock_name.cache_clear()
    monkeypatch.setattr(stock, "NAMES_PATH", tmp_path / "missing.json")

    def fail_http(*_args, **_kwargs):
        raise stock.requests.HTTPError("HTTP 403")

    monkeypatch.setattr(stock.requests, "get", fail_http)
    assert stock._name_and_st("301196") == (None, None)
