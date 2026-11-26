"""优化器一致性审计（research/eval/optimizer_parity.py）的快速测试。

真实数据上的等价性由审计脚本按预登记判据裁决，不放进 CI：这里只测统计口径、日期选择、spawn 进程设置和端到端管线。
"""
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd
import pytest

from research.eval import optimizer_parity as P


def _windows(arm, box, sse, n=(130, 140, 260, 270), date="2020-01-03", anchor=False, sym="sh000001"):
    return pd.DataFrame({
        "symbol": sym, "date": pd.Timestamp(date), "arm": arm, "is_anchor": anchor, "n": list(n),
        "scale": P.scale_of(list(n)).to_numpy(), "tc": 0.0, "ahead": [10.0] * len(n), "m": 0.5, "w": 8.0,
        "B": -1.0, "D": 1.0, "osc": 3.0, "rel_err": 0.1, "r2": 0.9, "sse": sse, "box": box,
        "standard": box, "seconds": 0.0,
    })


def test_scale_of_matches_fco6_boundaries():
    got = P.scale_of([10, 20, 21, 126, 127, 252, 253, 504, 505, 1500, 9]).tolist()
    assert got == ["2-4w", "2-4w", "1-3m", "3-6m", "6-12m", "6-12m", "12-24m", "12-24m", "2-6y", "2-6y", None]


def test_primary_windows_keeps_only_evaluated_scales():
    assert P.primary_windows((120, 125, 130, 250, 255, 500, 525)) == (130, 250, 255, 500)


def test_pick_dates_grid_and_anchor_flags():
    idx = pd.bdate_range("2007-01-01", "2007-12-31")
    d = P.pick_dates(idx, "2007-01-01", None, 60, anchors=("2007-10-16", "2030-01-01"))
    assert d.date.iloc[-1] == idx[-1] and not d.is_anchor.iloc[-1]
    anchors = d[d.is_anchor]
    assert list(anchors.date) == [pd.Timestamp("2007-10-16")]
    assert d.date.is_monotonic_increasing and not d.date.duplicated().any()


def test_cohen_kappa_edge_cases():
    assert P.cohen_kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert P.cohen_kappa([True, True], [True, True]) == 1.0
    assert np.isnan(P.cohen_kappa([], []))
    assert P.cohen_kappa([True, False], [False, True]) < 0


def test_identical_arms_pass_all_criteria():
    ref = _windows("tcgrid", [True, False, True, True], [1.0, 1.0, 1.0, 1.0])
    alt = _windows("de_trf", [True, False, True, True], [1.0, 1.0, 1.0, 1.0])
    res = P.compare(pd.concat([ref, alt]), "de_trf")
    assert res["window"]["sse_worse_share"] == 0.0
    assert res["scales"]["6-12m"]["conf_mae"] == 0.0
    assert res["scales"]["6-12m"]["alarm_jaccard"] == 1.0
    assert P.verdict(res)["overall"] == "pass"


def test_alarm_flip_and_worse_sse_fail():
    ref = _windows("tcgrid", [False, False, True, True], [1.0, 1.0, 1.0, 1.0])
    alt = _windows("de_trf", [True, False, True, True], [1.2, 1.0, 1.0, 1.0])
    res = P.compare(pd.concat([ref, alt]), "de_trf")
    s = res["scales"]["6-12m"]
    assert s["conf_mae"] == pytest.approx(0.5)
    assert s["alarm_only_alt"] == 1 and s["alarm_only_ref"] == 0
    assert res["window"]["sse_worse_share"] == pytest.approx(0.25)
    v = P.verdict(res)
    assert v["overall"] == "fail"
    failed = {c["check"] for c in v["checks"] if c["status"] == "fail"}
    assert {"sse_worse_share", "6-12m.conf_mae", "6-12m.alarm_jaccard"} <= failed


def test_no_alarms_in_either_arm_is_not_evaluable():
    ref = _windows("tcgrid", [False] * 4, [1.0] * 4)
    alt = _windows("de_trf", [False] * 4, [1.0] * 4)
    v = P.verdict(P.compare(pd.concat([ref, alt]), "de_trf"))
    assert v["overall"] == "not_evaluable"


def test_anchor_dates_excluded_from_verdict():
    ref = _windows("tcgrid", [True] * 4, [1.0] * 4)
    alt = _windows("de_trf", [True] * 4, [1.0] * 4)
    bad_ref = _windows("tcgrid", [True] * 4, [1.0] * 4, date="2007-10-16", anchor=True)
    bad_alt = _windows("de_trf", [False] * 4, [2.0] * 4, date="2007-10-16", anchor=True)
    w = pd.concat([ref, alt, bad_ref, bad_alt])
    assert P.verdict(P.compare(w, "de_trf"))["overall"] == "pass"
    assert P.compare(w, "de_trf", anchors=True)["scales"]["6-12m"]["alarms_alt"] == 0


def test_criteria_hash_is_stable_and_sensitive():
    h = P.criteria_sha256()
    assert h == P.criteria_sha256(dict(P.CRITERIA))
    assert h != P.criteria_sha256({**P.CRITERIA, "conf_mae_max": 0.03})


def test_spawn_worker_without_initializer_loses_allow_inside(monkeypatch):
    """记录审查 P1-9：父进程改 core.ALLOW_INSIDE，spawn 子进程看不到。"""
    from research.lppls import core

    monkeypatch.setattr(core, "ALLOW_INSIDE", True)
    with ProcessPoolExecutor(1, mp_context=mp.get_context("spawn")) as ex:
        assert ex.submit(P._worker_state).result()["allow_inside"] is False


def test_spawn_worker_initializer_sets_v2_and_inside():
    with ProcessPoolExecutor(1, mp_context=mp.get_context("spawn"), initializer=P._init_worker) as ex:
        assert ex.submit(P._worker_state).result() == {"box": "v2", "allow_inside": True}


def test_run_pipeline_end_to_end_on_synthetic_series(monkeypatch):
    """管线冒烟：两臂都能在同一 as-of、同一窗口上产出生产口径的 box/standard 列。不检验等价性。"""
    from research.lppls import core
    from research.synth.lppls_synth import sample

    monkeypatch.setattr(core, "ALLOW_INSIDE", True)
    _, y, _ = sample(n=300, sigma=0.005, seed=3)
    logp = pd.Series(y, index=pd.bdate_range("2019-01-01", periods=len(y)))
    asof = logp.index[-1]
    frames = []
    for arm in ("tcgrid", "g3", "de_trf", "de_trf_cold"):
        d = P.evaluate_fits(P.fit_arm(logp, asof, (130, 140), arm))
        d.insert(0, "symbol", "synth")
        d.insert(2, "arm", arm)
        d.insert(3, "is_anchor", False)
        frames.append(d)
        assert list(d.n) == [130, 140]
        assert set(d.scale) == {"6-12m"}
        assert d.box.dtype == bool and d.standard.dtype == bool
    res = P.compare(pd.concat(frames), "de_trf")
    assert res["n_windows_paired"] == 2


def test_fit_arm_refuses_when_inside_disabled(monkeypatch):
    from research.lppls import core

    monkeypatch.setattr(core, "ALLOW_INSIDE", False)
    logp = pd.Series(np.linspace(1, 2, 200), index=pd.bdate_range("2019-01-01", periods=200))
    with pytest.raises(RuntimeError, match="ALLOW_INSIDE"):
        P.fit_arm(logp, logp.index[-1], (130,), "tcgrid")


def test_summarize_pairs_each_alt_with_each_ref_once():
    w = pd.concat([_windows(a, [True, False, True, True], [1.0] * 4) for a in ("tcgrid", "g3", "de_trf")])
    s = P.summarize(w, ("tcgrid", "g3", "de_trf"), {}, refs=("tcgrid", "g3"))
    pairs = [(c["ref"], c["alt"]) for c in s["comparisons"]]
    assert pairs == [("tcgrid", "g3"), ("tcgrid", "de_trf"), ("g3", "de_trf")]
    assert all(c["verdict"]["overall"] == "pass" for c in s["comparisons"])


def test_anchors_and_default_end_stay_in_dev_split():
    assert all(pd.Timestamp(a) <= pd.Timestamp(P.DEV_END) for a in P.ANCHORS)
    assert P.DEV_END == "2018-12-31"


def test_main_refuses_post_dev_end_without_flag():
    with pytest.raises(SystemExit, match="开发段"):
        P.main(["--end", "2019-01-02", "--dry-run"])


def test_pick_dates_requires_full_window_history():
    idx = pd.bdate_range("2010-01-04", periods=800)
    d = P.pick_dates(idx, "2010-01-01", None, 50, anchors=(), min_bars=500)
    assert d.date.min() >= idx[499]
    assert P.pick_dates(idx[:100], "2010-01-01", None, 50, anchors=(), min_bars=500).empty
