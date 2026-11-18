import datetime as dt

import numpy as np
import pandas as pd
import pytest

from research.data import breadth


def _market_rows(day_index):
    codes = [
        ("sh", "600001"),
        ("sh", "680001"),
        ("sz", "000001"),
        ("sz", "300001"),
        ("bj", "430001"),
    ]
    close_by_day = (
        [10.0, 20.0, 30.0, 10.0, 50.0],
        [12.0, 20.0, 30.0, 12.0, 50.0],
        [15.0, 18.0, 33.0, 15.0, 55.0],
    )
    rows = []
    for index, (market, code) in enumerate(codes):
        previous = 10.0
        close = close_by_day[day_index][index]
        if day_index == 2:
            previous = 10.0
            close = 10.5 if index < 3 else 9.5
        rows.append(
            {
                "market": market,
                "code": code,
                "prev_close": previous,
                "close": close,
                "low": min(previous, close),
                "volume": [10, 20, 30, 40, 50][index],
                "amount": [100, 100, 300, 100, 100][index],
            }
        )
    for code, close in (
        ("000001", 3210.0),
        ("000300", 4000.0),
        ("000016", 5000.0),
        ("000905", 6000.0),
        ("000852", 7000.0),
    ):
        rows.append(
            {
                "market": "sh",
                "code": code,
                "prev_close": close - 1,
                "close": close,
                "low": close - 1,
                "volume": 0,
                "amount": 0,
            }
        )
    return rows


def test_daily_red_and_amount_trin_use_filtered_all_a_rows():
    metrics, spots = breadth.compute_daily_metrics(
        "2026-11-18", _market_rows(day_index=2)
    )

    assert metrics["n"] == 5
    assert metrics["adv"] == 3
    assert metrics["dec"] == 2
    assert metrics["red"] == pytest.approx(0.6)
    assert metrics["amt_up"] == pytest.approx(500 / 700)
    assert metrics["trin_amt"] == pytest.approx(0.6)
    assert metrics["trin_vol"] == pytest.approx(2.25)
    assert metrics["sh"] == pytest.approx(3210)
    assert spots["hs300"] == pytest.approx(4000)


def test_p20_with_short_window_counts_only_stocks_with_full_history():
    dates = pd.date_range("2026-11-16", periods=3, freq="D")
    closes = pd.DataFrame(
        [
            [10, 20, 30, 10, 50],
            [12, 20, 30, 12, np.nan],
            [15, 18, 33, 15, 55],
        ],
        index=dates,
        columns=["sh600001", "sh680001", "sz000001", "sz300001", "bj430001"],
    )

    result = breadth.compute_price_breadth(closes, windows=(2,))

    assert result.loc[dates[2], "P2"] == pytest.approx(0.75)


def test_mcl_matches_adjust_false_ema_recursion():
    adv = pd.Series([3, 2, 5], dtype=float)
    dec = pd.Series([2, 3, 1], dtype=float)

    result = breadth.compute_mcl(adv, dec)
    difference = [1.0, -1.0, 4.0]

    def recurse(alpha):
        values = [difference[0]]
        for value in difference[1:]:
            values.append(alpha * value + (1 - alpha) * values[-1])
        return np.asarray(values)

    expected = recurse(0.10) - recurse(0.05)
    np.testing.assert_allclose(result.to_numpy(), expected)
    assert breadth._trend_days(pd.Series([0.0, 1.0, 2.0])) == 2


def test_basis_selects_highest_volume_unexpired_contract_and_annualizes():
    spot = {"hs300": 4000, "sz50": 5000, "zz500": 6000, "zz1000": 7000}
    futures = [
        {"product": "IF", "symbol": "IF2610", "close": 4300, "volume": 9000},
        {"product": "IF", "symbol": "IF2611", "close": 4200, "volume": 700},
        {"product": "IF", "symbol": "IF2612", "close": 4100, "volume": 600},
    ]

    result, mean = breadth.compute_basis("2026-11-18", spot, futures)

    assert result["IF"]["symbol"] == "IF2611"
    assert result["IF"]["days"] == 2
    assert result["IF"]["pct"] == pytest.approx(5)
    assert result["IF"]["ann"] == pytest.approx(5 * 365 / 5)
    assert mean == pytest.approx(result["IF"]["ann"])


def test_tdx_package_404_raises_value_error():
    class NotFound:
        status_code = 404
        content = b""

    class Session:
        def get(self, *_args, **_kwargs):
            return NotFound()

    with pytest.raises(ValueError, match="TDX daily package not found"):
        breadth.tdx_daily_package("2026-11-18", session=Session())


def test_pipeline_failure_copies_previous_json_then_raises(tmp_path, monkeypatch):
    previous = tmp_path / "previous.json"
    output = tmp_path / "out" / "breadth_latest.json"
    previous_content = b'{\n  "schema": "breadth.v1",\n  "asof": "2026-11-17"\n}\n'
    previous.write_bytes(previous_content)

    def fail(*_args, **_kwargs):
        raise ValueError("source not available")

    monkeypatch.setattr(breadth, "collect_breadth", fail)

    with pytest.raises(ValueError, match="source not available"):
        breadth.run_pipeline(
            output,
            asof=dt.date(2026, 11, 18).isoformat(),
            cache_dir=tmp_path / "cache",
            previous_path=previous,
        )

    assert output.read_bytes() == previous_content
