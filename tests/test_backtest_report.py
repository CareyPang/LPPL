import json

import pandas as pd

from research.backtest.report import build_strategy_report


def test_report_keeps_primary_contract_and_explains_missing_lppls_history():
    prices = pd.DataFrame(
        {
            "date": ["2014-01-02", "2014-01-03", "2023-01-03", "2023-01-04"],
            "open": [100.0, 101.0, 102.0, 101.0],
            "high": [101.0, 102.0, 103.0, 102.0],
            "low": [99.0, 100.0, 101.0, 100.0],
            "close": [100.0, 101.0, 102.0, 101.0],
            "prev_close": [100.0, 100.0, 101.0, 102.0],
        }
    )
    dates = pd.to_datetime(prices["date"])
    n_on = pd.Series([0, 0, 0, 0], index=dates)

    report = build_strategy_report(
        "sh000852",
        prices,
        n_on,
        [],
        [
            {
                "start": "2023-01-03",
                "end": "2023-01-03",
                "verdict": "顶部区间",
            }
        ],
        asof="2023-01-04",
    )

    assert report["rule_id"] == "R-TR1"
    assert report["selected_variant"]["K"] in (2, 3)
    assert len(report["variants"]) == 4
    assert all(
        {"precision", "recall", "baseline", "n_signals"} <= variant.keys()
        and variant["evidence"] == "dev_only"
        for variant in report["variants"].values()
    )
    assert report["metrics"]["test"]["evidence"] == "descriptive"
    assert report["metrics"]["test"]["baseline"] == 0.5
    assert report["rules"][1]["rule_id"] == "R-LC1"
    assert report["rules"][1]["skipped"] is True
    assert "缺少 LPPLS history 文件" in report["rules"][1]["note"]
    json.dumps(report, allow_nan=False)
