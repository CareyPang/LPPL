import numpy as np
import pandas as pd

from research.data.top_risk_episodes import (
    DEFINITION,
    JUDGE_DEFINITION,
    build_episode_report,
)


def test_episode_report_matches_hand_calculated_fixture():
    dates = pd.bdate_range("2020-01-01", periods=400).strftime("%Y-%m-%d")
    close = np.full(len(dates), 100.0)
    close[130:146] = 200.0
    close[146:266] = 200.0
    close[160] = 170.0
    close[280] = 120.0
    history = [
        {
            "date": date,
            "n_on": 3 if index in (130, 145, 280) else 0,
            "index_on": index in (10, 20, 30, 40),
        }
        for index, date in enumerate(dates)
    ]
    prices = [
        {"date": date, "close": float(value)}
        for date, value in zip(dates, close, strict=True)
    ]

    result = build_episode_report(
        {"sh000001": history},
        {"sh000001": prices},
    )

    assert result == {
        "definition": DEFINITION,
        "judge": JUDGE_DEFINITION,
        "episodes": [
            {
                "index": "上证指数",
                "start": dates[130],
                "end": dates[145],
                "days": 2,
                "peak": 200.0,
                "after120_max_pct": 0.0,
                "after120_min_pct": -0.15,
                "verdict": "顶部区间",
            },
            {
                "index": "上证指数",
                "start": dates[280],
                "end": dates[280],
                "days": 1,
                "peak": 120.0,
                "after120_max_pct": -0.1667,
                "after120_min_pct": -0.1667,
                "verdict": None,
            },
        ],
        "stats": [
            {"index": "上证指数", "n": 1, "hit": 1.0, "base": 0.0}
        ],
    }


def test_episode_cluster_merges_signals_within_twenty_sessions():
    dates = pd.bdate_range("2020-01-01", periods=400).strftime("%Y-%m-%d")
    states = [
        {
            "date": date,
            "n_on": 3 if index in (100, 120) else 0,
            "index_on": index in (10, 20),
        }
        for index, date in enumerate(dates)
    ]
    prices = [
        {"date": date, "close": 100.0}
        for date in dates
    ]

    report = build_episode_report(
        {"sh000001": states},
        {"sh000001": prices},
    )

    assert len(report["episodes"]) == 1
    assert report["episodes"][0]["start"] == dates[100]
    assert report["episodes"][0]["end"] == dates[120]
