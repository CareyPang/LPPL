import datetime as dt
import json
from pathlib import Path

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
    assert metrics["top50_share"] == pytest.approx(1)
    assert metrics["top100_share"] == pytest.approx(1)
    assert metrics["sh"] == pytest.approx(3210)
    assert spots["hs300"] == pytest.approx(4000)


def test_concentration_shares_use_top_50_and_top_100_amounts():
    rows = [
        {
            "market": "sz",
            "code": f"{index + 1:06d}",
            "prev_close": 10,
            "close": 10,
            "low": 10,
            "volume": 1,
            "amount": index + 1,
        }
        for index in range(105)
    ]

    metrics, _ = breadth.compute_daily_metrics("2026-11-18", rows)

    total = sum(range(1, 106))
    assert metrics["top50_share"] == pytest.approx(sum(range(56, 106)) / total)
    assert metrics["top100_share"] == pytest.approx(sum(range(6, 106)) / total)


def test_limit_prices_round_half_up_for_up_and_down_limits():
    rows = [
        {
            "market": "sh",
            "code": f"60000{index}",
            "name": "样本",
            "prev_close": 4.75,
            "close": close,
            "low": min(4.75, close),
            "volume": 100,
            "amount": 1000,
        }
        for index, close in enumerate((5.23, 5.22, 4.28, 4.52), start=1)
    ]

    metrics, _ = breadth.compute_daily_metrics("2026-11-18", rows)
    up_price = breadth._rounded_limit_prices(
        np.array([4.75]), np.array([0.1]), up=True
    )[0]
    down_price = breadth._rounded_limit_prices(
        np.array([4.75]), np.array([0.1]), up=False
    )[0]

    assert up_price == pytest.approx(5.23)
    assert 5.23 >= up_price - 0.001
    assert not 5.22 >= up_price - 0.001
    assert down_price == pytest.approx(4.28)
    assert 4.28 <= down_price + 0.001
    assert not 4.29 <= down_price + 0.001
    assert metrics["lu"] == 1
    assert metrics["ld"] == 1


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
    assert result["IF"]["spread"] == pytest.approx(200)
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


def _state_frame(n: int = 90) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=n).strftime("%Y-%m-%d")
    return pd.DataFrame(
        {
            "date": dates,
            "sh": [3000.0 + i for i in range(n)],
            "red": [0.5] * n,
            "lu": [50] * n,
            "ld": [10] * n,
            "amount_yi": [10000.0] * n,
            "P20": [0.5] * n,
        }
    )


def test_state_keys_follow_registered_thresholds():
    key = breadth._state_key
    assert key(0.10, 1.2, 20, 150) == "panic"
    assert key(0.10, 0.95, 20, 150) == "down"  # 缩量不算恐慌出清
    assert key(0.10, 1.2, 20, 99) == "down_heavy"
    assert key(0.30, 0.85, 20, 10) == "down_light"
    assert key(0.80, 1.10, 20, 10) == "up_heavy"
    assert key(0.70, 1.10, 20, 10) == "up"
    assert key(0.70, 0.80, 20, 10) == "up_light"
    assert key(0.50, 1.50, 20, 10) == "mixed"
    assert key(0.50, float("nan"), 20, 10) is None


def test_classify_states_uses_only_past_data_and_marks_divergence():
    frame = _state_frame()
    frame.loc[frame.index[-1], ["red", "P20"]] = [0.4, 0.3]
    frame.loc[frame.index[-10], "P20"] = 0.7
    states = breadth.classify_states(frame)
    assert states["state"].iloc[:20].isna().all()
    assert bool(states["top_div"].iloc[-1])
    assert not states["bottom_div"].any()
    truncated = breadth.classify_states(frame.iloc[:-5])
    pd.testing.assert_frame_equal(
        states.iloc[:-5].reset_index(drop=True), truncated.reset_index(drop=True)
    )


def test_build_state_splices_seed_before_first_live_row(tmp_path):
    frame = _state_frame()
    seed = tmp_path / "seed.csv"
    frame.iloc[:60].to_csv(seed, index=False)
    live = frame.iloc[40:].copy()
    live.loc[live.index[:5], "P20"] = None
    state = breadth._build_state(live, seed)
    expected = breadth.classify_states(frame)
    expected = expected.loc[expected["state"].notna()]
    assert state["history"]["date"] == expected["date"].tolist()
    assert state["history"]["state"] == expected["state"].tolist()
    assert state["latest"]["date"] == frame["date"].iloc[-1]
    assert state["latest"]["streak"] == len(expected)
    assert sum(state["counts"].values()) == state["n_days"]


def test_state_seed_has_every_shanghai_session():
    seed = pd.read_csv(breadth.STATE_SEED)
    dates = list(seed["date"])
    assert dates == sorted(set(dates))
    root = Path(breadth.__file__).resolve().parents[2]
    bars = json.loads((root / "web/mock/data/sh000001_bars.json").read_text(encoding="utf-8"))
    expected = [day for day in bars["dates"] if dates[0] <= day <= dates[-1]]
    assert len(expected) > 1000
    assert [day for day in expected if day not in set(dates)] == []
