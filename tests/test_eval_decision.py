import numpy as np

from research.eval.decision import execute, max_drawdown, strategy_returns, target_position


def test_target_position_steps_and_restores():
    p = np.array([0.0] * 5 + [0.35] + [0.0] * 25)
    t = target_position(p, 0.15, 0.30, "two")
    assert t[4] == 1.0 and t[5] == 1 / 3 and t[6] == 1 / 3 and t[-1] == 1.0
    assert np.isclose(target_position(np.array([0.2] * 3), 0.15, 0.30, "two")[-1], 2 / 3)
    assert np.isclose(target_position(np.array([0.2] * 3), 0.15, 0.30, "one")[-1], 1 / 3)


def test_execution_lag_and_costs():
    tgt = np.array([1.0, 1 / 3, 1 / 3, 1 / 3])
    r = np.zeros(4)
    pos = execute(tgt, r)
    assert pos[1] == 1.0 and np.isclose(pos[2], 1 / 3)
    s = strategy_returns(pos, r)
    assert s[2] < 0 and s[1] == 0 and s[3] == 0  # 卖出当日付成本


def test_max_drawdown():
    assert np.isclose(max_drawdown(np.array([0.1, -0.5, 0.2])), -0.5)
