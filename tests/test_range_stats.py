import json
from pathlib import Path

import pytest

from research.data.range_stats import compute_range_stats

FIXTURE = Path(__file__).parent / "fixtures" / "range" / "market_history.json"


def history():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_range_returns_compound_and_flow_sums():
    result = compute_range_stats(history())
    row = next(row for row in result["windows"]["5"]["industry"] if row["name"] == "A行业")

    assert row["return_pct"] == pytest.approx((1.01**5 - 1) * 100)
    assert row["net_flow"] == 60
    assert row["provider"] == "eastmoney"
    assert row["skip_reason"] is None


def test_provider_mismatch_skips_range():
    snapshots = history()
    snapshots[-1]["board_flow"]["provider"]["industry"] = "sina"

    result = compute_range_stats(snapshots)
    row = next(row for row in result["windows"]["5"]["industry"] if row["name"] == "A行业")

    assert row["return_pct"] is None
    assert row["net_flow"] is None
    assert row["skip_reason"] == "provider_mismatch"


def test_short_history_returns_null_metrics():
    result = compute_range_stats(history()[:3])
    row = next(row for row in result["windows"]["5"]["industry"] if row["name"] == "A行业")

    assert result["n_days"] == 3
    assert row["return_pct"] is None
    assert row["net_flow"] is None
    assert row["skip_reason"] == "short_history"
