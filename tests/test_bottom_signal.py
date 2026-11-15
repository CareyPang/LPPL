import json
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from research.data import bottom_signal
from research.data.bottom_signal import (
    compute_bottom_signal,
    compute_series,
    write_snapshot,
)


def _frames(length=800):
    dates = pd.bdate_range("2007-01-02", periods=length)
    ebs = pd.DataFrame(
        {
            "日期": dates,
            "沪深300指数": [100.0 + index / 10 for index in range(length)],
            "股债利差": [0.0] * length,
        }
    )
    pbn = pd.DataFrame(
        {
            "date": dates,
            "below_net_asset_ratio": [0.0] * length,
        }
    )
    return ebs, pbn, dates


def test_rolling_percentile_uses_past_and_today_without_lookahead():
    ebs, pbn, dates = _frames(850)
    ebs["股债利差"] = [float(index) for index in range(len(ebs))]
    pbn["below_net_asset_ratio"] = [float(index) for index in range(len(pbn))]
    changed_ebs, changed_pbn = ebs.copy(), pbn.copy()
    changed_ebs.loc[651:, "股债利差"] = -1_000_000
    changed_pbn.loc[651:, "below_net_asset_ratio"] = -1_000_000

    original = compute_series(ebs, pbn)
    changed = compute_series(changed_ebs, changed_pbn)

    assert pd.isna(original.loc[dates[498], "erp_pct"])
    assert original.loc[dates[499], "erp_pct"] == pytest.approx(1.0)
    assert bool(original.loc[dates[650], "signal"])
    pd.testing.assert_frame_equal(
        original.loc[: dates[650]],
        changed.loc[: dates[650]],
    )


def test_events_require_twenty_signal_free_trading_days():
    ebs, pbn, dates = _frames()
    for index in (600, 620, 621, 642):
        ebs.loc[index, "股债利差"] = 5.0
        pbn.loc[index, "below_net_asset_ratio"] = 5.0

    result = compute_bottom_signal(ebs, pbn)

    assert [event["date"] for event in result["events"]] == [
        dates[600].date().isoformat(),
        dates[642].date().isoformat(),
    ]


def test_snapshot_serializes_nan_as_null_and_rounds_floats(tmp_path):
    ebs, pbn, dates = _frames(600)
    ebs.loc[590, "股债利差"] = 5.0
    pbn.loc[590, "below_net_asset_ratio"] = 5.0
    ebs.loc[599, "股债利差"] = float("nan")
    pbn.loc[599, "below_net_asset_ratio"] = 12.345678

    result = compute_bottom_signal(ebs, pbn)
    path = write_snapshot(result, tmp_path)
    serialized = path.read_text(encoding="utf-8")
    saved = json.loads(serialized)

    assert saved["current"]["date"] == dates[-1].date().isoformat()
    assert saved["current"]["erp"] is None
    assert saved["current"]["erp_pct"] is None
    assert saved["current"]["pbn_ratio"] == 12.3457
    assert saved["events"][0]["ret_120"] is None
    assert saved["events"][0]["ret_250"] is None
    assert "NaN" not in serialized


def test_empty_pbn_source_fails_instead_of_returning_unlit_signal():
    ebs, _, _ = _frames()
    pbn = pd.DataFrame(columns=["date", "below_net_asset_ratio"])

    with pytest.raises(ValueError, match="stock_a_below_net_asset_statistics"):
        compute_series(ebs, pbn)


def test_partial_event_window_is_excluded_from_median_post_min():
    ebs, pbn, dates = _frames(1000)
    for index in (600, 900):
        ebs.loc[index, "股债利差"] = 5.0
        pbn.loc[index, "below_net_asset_ratio"] = 5.0
    ebs.loc[901:, "沪深300指数"] = 180.0

    result = compute_bottom_signal(ebs, pbn)
    full_event, partial_event = result["events"]

    assert full_event["date"] == dates[600].date().isoformat()
    assert full_event["post_min_complete"] is True
    assert partial_event["date"] == dates[900].date().isoformat()
    assert partial_event["post_min_complete"] is False
    assert full_event["post_min"] != partial_event["post_min"]
    assert result["summary"]["median_post_min"] == pytest.approx(full_event["post_min"])
    assert result["summary"]["n_up_250"] == 1


def test_a500_failure_does_not_change_hs300_result(monkeypatch, tmp_path):
    ebs, pbn, _ = _frames()
    fake_ak = SimpleNamespace(
        stock_a_below_net_asset_statistics=lambda symbol: pbn,
        stock_ebs_lg=lambda: ebs,
    )
    history = pd.DataFrame(
        {"n": [1], "mcap": [100.0], "earn": [10.0], "pe_ttm": [10.0]},
        index=pd.DatetimeIndex(["2026-11-13"], name="date"),
    )

    def fail_a500(*args, **kwargs):
        raise RuntimeError("A500 source unavailable")

    monkeypatch.setitem(sys.modules, "akshare", fake_ak)
    monkeypatch.setattr(bottom_signal.a500_pe, "load_history", lambda path: history)
    monkeypatch.setattr(bottom_signal.a500_pe, "constituents", lambda: ["000001"])
    monkeypatch.setattr(
        bottom_signal.a500_pe, "fetch_recent_many", lambda codes: pd.DataFrame()
    )
    monkeypatch.setattr(
        bottom_signal.a500_pe, "update", lambda hist, n_constituents, rows: history
    )
    monkeypatch.setattr(bottom_signal, "_a500_payload", fail_a500)

    history_path = tmp_path / "a500_pe_hist.csv"
    result = bottom_signal.fetch_live(a500_out=history_path)
    expected = compute_bottom_signal(ebs, pbn)

    for key, value in expected.items():
        assert result[key] == value
    assert result["a500"] is None
    assert result["a500_error"] == "RuntimeError: A500 source unavailable"
    assert pd.read_csv(history_path)["date"].tolist() == ["2026-11-13"]


def test_a500_uses_renamed_akshare_functions_when_needed(monkeypatch):
    dates = pd.to_datetime(["2026-11-12", "2026-11-13"])
    captured = {}
    calls = []
    fake_ak = SimpleNamespace(
        bond_zh_us_yield_em=lambda start_date: (
            calls.append(start_date)
            or pd.DataFrame(
                {
                    "日期": dates,
                    "中国国债收益率10年": [3.0, 3.1],
                }
            )
        ),
        index_zh_daily_sina=lambda symbol: pd.DataFrame(
            {"date": dates, "close": [100.0, 101.0]}
        ),
    )
    history = pd.DataFrame(
        {"pe_ttm": [20.0, 20.0]},
        index=pd.DatetimeIndex(dates, name="date"),
    )

    def capture_frame(frame, pbn):
        captured["frame"] = frame.copy()
        return {"rule": bottom_signal.RULE, "notes": []}

    monkeypatch.setattr(bottom_signal, "compute_bottom_signal", capture_frame)

    result = bottom_signal._a500_payload(fake_ak, pd.DataFrame(), history)

    assert calls == ["20050101"]
    assert result["sources"]["close"] == "ak.stock_zh_index_daily(sh000510)"
    assert captured["frame"]["股债利差"].tolist() == pytest.approx([0.02, 0.019])
    assert captured["frame"]["沪深300指数"].tolist() == [100.0, 101.0]


def test_cli_passes_a500_history_and_skip_flags(monkeypatch, tmp_path):
    calls = {}

    def fake_fetch_live(a500_hist=None, a500_out=None, no_a500=False):
        calls.update(
            a500_hist=a500_hist,
            a500_out=a500_out,
            no_a500=no_a500,
        )
        return {
            "asof": "2026-11-13",
            "events": [],
            "summary": {},
            "a500": None,
        }

    monkeypatch.setattr(bottom_signal, "fetch_live", fake_fetch_live)
    hist = tmp_path / "prior.csv"
    output = tmp_path / "out"

    assert bottom_signal.main(
        [
            "--out",
            str(output),
            "--a500-hist",
            str(hist),
            "--no-a500",
        ]
    ) == 0

    assert calls == {
        "a500_hist": hist,
        "a500_out": output / "a500_pe_hist.csv",
        "no_a500": True,
    }
