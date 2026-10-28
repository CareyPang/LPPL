import numpy as np
import pandas as pd

from research.features.lppls_rules import scores


def _row(date, n, tc, m, w, B, C1, sse, r2, pow_B=-1.0, pow_m=0.5):
    return dict(date=pd.Timestamp(date), n=n, tc=tc, m=m, w=w, A=5.0, B=B, C1=C1, C2=0.0, sse=sse, r2=r2,
                pow_tc=tc, pow_m=pow_m, pow_B=pow_B, pow_sse=sse * 1.5, y_std=0.3)


def test_scores_shares_and_tc_cluster():
    good = _row("2015-06-01", 200, 199 + 10, 0.5, 8.0, -1.0, 0.01, 250 * (0.3 * 0.03) ** 2, 0.95)
    bad = _row("2015-06-01", 500, 499 + 300, 1.5, 30.0, 0.2, 0.5, 500 * 0.1**2, 0.5, pow_B=0.1)
    s = scores(pd.DataFrame([good, bad]))
    assert s.loc["2015-06-01", "n_windows"] == 2
    assert s.loc["2015-06-01", "s_power"] == 0.5
    assert s.loc["2015-06-01", "s_lit1"] == 0.5
    assert s.loc["2015-06-01", "s_p_top"] == 0.5
    assert np.isclose(s.loc["2015-06-01", "top_tc_med"], 10.0)
    assert s.loc["2015-06-01", "s_lit1_s"] == 1.0 and s.loc["2015-06-01", "s_lit1_l"] == 0.0
