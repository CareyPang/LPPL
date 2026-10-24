import numpy as np
import pandas as pd

from research.eval.interval import evaluate, interval, interval_score, intervals_by_date, wquantile


def test_wquantile_matches_numpy_when_equal_weights():
    x = np.random.default_rng(0).normal(size=200)
    w = np.ones(200)
    got = wquantile(x, w, [0.1, 0.9])
    assert np.allclose(got, np.quantile(x, [0.1, 0.9]), atol=0.05)


def test_interval_requires_min_windows():
    assert np.isnan(interval(np.arange(4.0), None, "eq", 0.1, 0.9)[0])
    a, b = interval(np.arange(100.0), None, "eq", 0.1, 0.9)
    assert 5 < a < 15 and 85 < b < 95


def test_interval_score_penalises_misses():
    inside = interval_score(5, 15, 10)
    below = interval_score(5, 15, 2)
    assert inside == 10 and below == 10 + 10 * 3


def test_evaluate_prefers_sharp_covering_interval():
    dates = pd.date_range("2020-01-01", periods=10)
    rows = []
    for dt in dates:
        for _ in range(20):
            rows.append(dict(date=dt, ahead=np.random.default_rng(1).normal(8, 1), sse=1.0))
    d = pd.DataFrame(rows)
    d["ahead"] = np.random.default_rng(2).normal(8, 1, len(d))
    iv = intervals_by_date(d, pd.Series(True, index=d.index))
    ev = pd.DataFrame(dict(date=dates, t_star=8.0))
    tab = evaluate(iv, ev)
    base = tab[tab.config == "baseline_1-20"].IS.iloc[0]
    assert (tab[tab.config != "baseline_1-20"].IS < base).all()
