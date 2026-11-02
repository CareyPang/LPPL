"""tencent_sina：复权因子套用的离线测试 + 可选联网对账（CP_NET=1）。"""
import os

import pandas as pd
import pytest

from research.data import tencent_sina as T
from research.data.sources import COLS


def test_apply_factors_qfq_hfq():
    raw = pd.DataFrame({"date": ["2020-01-02", "2020-06-30", "2021-01-04"], "open": [10.0, 20.0, 30.0], "high": [10, 20, 30],
                        "low": [10, 20, 30], "close": [10.0, 20.0, 30.0], "volume": [1, 1, 1], "amount": [None] * 3})
    f = pd.DataFrame({"date": ["2020-06-20", "2020-12-20"], "factor": [2.0, 1.0]})
    q = T.apply_factors(raw, f, "qfq")
    assert list(q.close.round(3)) == [5.0, 10.0, 30.0]  # 首行无更早因子 → 回填 2.0；6-30 用 2.0；2021 用 1.0
    h = T.apply_factors(raw, f, "hfq")
    assert list(h.close.round(3)) == [20.0, 40.0, 30.0]


def test_tencent_raw_falls_back_to_kline_and_pages(monkeypatch):
    monkeypatch.setattr(T, "rate_limit", lambda: None)
    monkeypatch.setattr(T, "_cooldown", {})
    symbol = "sh600000"
    first_dates = pd.bdate_range("2024-01-02", periods=T.SEG).strftime("%Y-%m-%d")

    def row(date):
        return [date, "10.000", "20.000", "30.000", "5.000", "1000.000"]

    segments = [
        [row(date) for date in first_dates],
        [row("2020-01-02"), row("2020-01-03")],
    ]
    calls = []

    class Response:
        def __init__(self, status, rows=None):
            self.status = status
            self.rows = rows

        def raise_for_status(self):
            if self.status >= 400:
                raise RuntimeError(f"HTTP {self.status}")

        def json(self):
            return {"data": {symbol: {"day": self.rows}}}

    def get(url, params, **kwargs):
        calls.append((url, params["param"]))
        if url.endswith("/appstock/app/fqkline/get"):
            return Response(501)
        if url.endswith("/appstock/app/kline/kline"):
            return Response(200, segments.pop(0))
        raise AssertionError(f"unexpected endpoint: {url}")

    monkeypatch.setattr(T.requests, "get", get)
    result = T.tencent_raw(
        symbol, start="2020-01-01", end="2026-10-30"
    )

    assert list(result.columns) == COLS
    assert result.attrs["source"] == "tencent_kline"
    assert len(result) == T.SEG + 2
    parsed = result.iloc[0]
    assert parsed[["open", "high", "low", "close", "volume"]].tolist() == [
        10.0,
        30.0,
        5.0,
        20.0,
        1000.0,
    ]
    assert len(calls) == 4
    assert calls[0][1] == "sh600000,day,2020-01-01,2026-10-30,640,"
    assert calls[1][1] == "sh600000,day,2020-01-01,2026-10-30,640"
    second_end = (
        pd.Timestamp(first_dates[0]) - pd.Timedelta(days=1)
    ).strftime("%Y-%m-%d")
    assert calls[2][1] == f"sh600000,day,2020-01-01,{second_end},640,"
    assert calls[3][1] == f"sh600000,day,2020-01-01,{second_end},640"


@pytest.mark.skipif(os.environ.get("CP_NET") != "1", reason="需要联网")
def test_live_index_matches_frozen():
    fz = pd.read_parquet("data/frozen/v20261024/sh000001_qfq.parquet")
    df = T.fetch_tencent_sina("sh", "000001", True)
    m = fz.assign(date=pd.to_datetime(fz.date)).merge(df.assign(date=pd.to_datetime(df.date)), on="date", suffixes=("_fz", "_tx"))
    assert len(m) > 6000 and ((m.close_fz - m.close_tx).abs() / m.close_fz).max() < 1e-6


@pytest.mark.network
@pytest.mark.skipif(os.environ.get("CP_NET") != "1", reason="需要联网")
def test_live_kline_hfq_matches_fqkline_and_has_long_range():
    raw_long = T.tencent_raw(
        "sh600000",
        start="2005-01-01",
        end="2026-10-30",
        endpoint="kline",
    )
    long_dates = pd.to_datetime(raw_long.date)
    assert (long_dates.dt.year == 2005).any()
    assert (raw_long.close > 0).all()

    raw_kline = T.tencent_raw(
        "sh600000",
        start="2024-01-01",
        end="2026-10-30",
        endpoint="kline",
    )
    factors = T.sina_factors("sh600000", "hfq")
    adjusted_kline = T.apply_factors(raw_kline, factors, "hfq")
    try:
        raw_fqkline = T.tencent_raw(
            "sh600000",
            start="2024-01-01",
            end="2026-10-30",
            endpoint="fqkline",
        )
    except T.SourceError as exc:
        pytest.skip(f"fqkline endpoint unavailable: {exc}")

    adjusted_fqkline = T.apply_factors(raw_fqkline, factors, "hfq")
    joined = adjusted_kline.merge(
        adjusted_fqkline, on="date", suffixes=("_kline", "_fqkline")
    )
    assert len(joined) >= 600
    relative_difference = (
        (joined.close_kline - joined.close_fqkline).abs()
        / joined.close_fqkline
    )
    assert relative_difference.max() < 1e-5
