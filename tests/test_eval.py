import numpy as np
import pandas as pd

from research.eval.metrics import brier, ece, pr_auc, reliability
from research.eval.splits import cpcv_paths, time_blocks


def test_cpcv_paths_count_and_purge():
    td = pd.bdate_range("2010-01-01", periods=1200)
    dates = pd.Series(np.repeat(td, 2))
    paths = cpcv_paths(dates, td, n_blocks=6, k=2, gap=80)
    assert len(paths) == 15
    pos = pd.Series(np.arange(len(td)), index=td)
    for tr, te, _ in paths:
        assert not (tr & te).any()
        tp = pos.reindex(dates[te]).to_numpy()
        trp = pos.reindex(dates[tr]).to_numpy()
        assert np.min(np.abs(trp[:, None] - tp[None, ::50])) > 80
    assert len(time_blocks(td, 6)) == 6


def test_metrics_basic():
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.8, 0.9])
    assert brier(y, p) < 0.05
    assert pr_auc(y, p) == 1.0
    assert 0 <= ece(y, p, 2) <= 1
    assert len(reliability(y, p, 2)) == 2
