"""Phase 0 精度尺子：首报抽取与事件指标（合成）。"""
import numpy as np
import pandas as pd

from research.eval import precision_baseline as pb


def test_first_alarms_respects_gap():
    gpos = np.arange(0, 100, 5)
    alarm = np.zeros(20, bool)
    alarm[[2, 3, 4, 10, 15, 16]] = True  # 10,15,20 | 50 | 75,80
    fa = pb.first_alarms(alarm, gpos, gap=20)
    assert gpos[fa].tolist() == [10, 50, 75]


def test_episodes_top_metrics_on_synthetic_path():
    n = 400
    close = np.ones(n) * 100.0
    close[100:150] = np.linspace(100, 130, 50)  # 涨到 150 日的顶 130
    close[150:260] = np.linspace(130, 90, 110)  # 顶后下跌到 90
    close[260:] = 95.0
    cal = pd.bdate_range("2010-01-01", periods=n)
    gpos = np.arange(0, n, 5)
    alarm = np.zeros(len(gpos), bool)
    alarm[gpos == 120] = True  # 报警在 120 日，价 112
    e = pb.episodes("x", "top", close, cal, gpos, alarm, np.array([149]))
    assert len(e) == 1
    r = e.iloc[0]
    assert r.hit and r.lead == 29
    assert abs(r.miss_up - (close[149] / close[120] - 1)) < 1e-9
    assert abs(r.avoid - (close[149:276].min() / close[120] - 1)) < 1e-9
    assert abs(r.fwd120 - (close[240] / close[120] - 1)) < 1e-9


def test_null_hit_returns_rates_in_unit_interval():
    gpos = np.arange(0, 3000, 5)
    rng = np.random.default_rng(0)
    alarm = rng.random(len(gpos)) < 0.1
    epos = np.array([500, 1500, 2500])
    nul = pb.null_hit(alarm, gpos, epos, rng)
    v = nul[~np.isnan(nul)]
    assert len(v) > 0 and ((v >= 0) & (v <= 1)).all()
