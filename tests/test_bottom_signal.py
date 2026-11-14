import json

import pandas as pd
import pytest

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
