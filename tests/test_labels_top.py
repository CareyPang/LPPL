import numpy as np
import pandas as pd

from research.labels.top import consensus_tops, epsilon_tops, event_segments, label_top


def _bubble(n=600, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    trend = np.where(t < 400, 0.004 * t, 0.004 * 400 - 0.006 * (t - 400))
    return np.log(100) + trend + 0.01 * rng.standard_normal(n).cumsum() * 0.3


def test_detects_clear_peak_and_labels_before_it():
    logp = _bubble()
    dates = pd.bdate_range("2010-01-01", periods=len(logp))
    tops = consensus_tops(logp, epsilon_tops(logp))
    assert any(abs(k - 400) <= 5 for k in tops)
    lab = label_top(dates, logp, tops, quant=None)  # 固定 10% 门槛
    assert lab.y.iloc[385] == 1 and lab.y.iloc[100] == 0
    assert np.isnan(lab.y.iloc[-1])  # 成熟期未满


def test_label_is_point_in_time_given_maturity():
    logp = _bubble(700)
    dates = pd.bdate_range("2010-01-01", periods=len(logp))
    full = label_top(dates, logp, consensus_tops(logp, epsilon_tops(logp)))
    cut = 500
    part = label_top(dates[:cut], logp[:cut], consensus_tops(logp[:cut], epsilon_tops(logp[:cut])))
    # t + 80 < cut 的标签不应随后续数据改变（顶的定位在 t+20 内，跌幅看 60 日，都在成熟期内）
    a, b = full.y.iloc[: cut - 85], part.y.iloc[: cut - 85]
    assert (a.fillna(-1) == b.fillna(-1)).mean() > 0.98


def test_event_segments_merge_consecutive_days():
    y = pd.Series([0, 1, 1, 0, 0, 1, np.nan, 1], index=pd.bdate_range("2020-01-01", periods=8))
    assert len(event_segments(y)) == 3
