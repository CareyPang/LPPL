"""Data/meaning boundaries for the local long-window research adapter."""
import copy
import json

import numpy as np
import pandas as pd
import pytest

from research.pipeline import long_horizon as lh


def record(n=925, seed=11, ahead=30, cycles=3.0, **changes):
    fit = {"x": [n-1+ahead, .5, 9.0], "beta": [10.0, -.1, .001, .002],
           "sse": .1, "r2": .99, "damping": 2., "nosc": cycles, "rank": 4,
           "condition": 100., "strict_pass": cycles >= 2.5, "optimizer_success": True,
           "boundary_status": "INTERIOR"}
    fit.update(changes)
    return {"n": n, "seed": seed, "asof": lh.ASOF, "symbol": "US_NDX",
            "status": "complete", "fit": fit, "input_hash": "frozen", "origin": "test"}


def records_for(n=925, ahead=(30, 30.1), cycles=3., **changes):
    return {(lh.ASOF, n, seed): record(n=n, seed=seed, ahead=distance, cycles=cycles, **changes)
            for seed, distance in zip(lh.SEEDS, ahead, strict=True)}


def window(records, n=925):
    return next(w for w in lh.summarize_windows(records, lh.ASOF) if w["n"] == n)


def test_exact_asof_prefix_never_reads_later_prices():
    frame = pd.DataFrame({"date": ["2026-11-18", "2026-11-19", "2026-11-20"], "close": [1., 2., 1000.]})
    selected = lh.prefix(frame, "2026-11-19", 2)
    assert selected.close.tolist() == [1., 2.]
    with pytest.raises(ValueError, match="Exact input"):
        lh.prefix(frame, "2026-11-17", 1)


def test_one_ulp_source_revision_changes_input_identity():
    a = pd.DataFrame({"date": ["2026-11-11"], "close": [28374.25]})
    b = a.copy()
    b.loc[0, "close"] = np.nextafter(b.close[0], np.inf)
    assert lh.input_identity(a) != lh.input_identity(b)


def test_1_5_and_2_5_rules_share_fits_but_are_separate():
    result = window(records_for(cycles=2.0))
    assert result["eligible"] == {"cycles_2_5": False, "cycles_1_5": True}
    assert len(result["seeds"]) == 2


@pytest.mark.parametrize("changes", [{"damping": .9}, {"r2": .89}, {"optimizer_success": False},
                                     {"rank": 3}, {"condition": 1e10}, {"boundary_status": "m_LOW"}])
def test_oscillation_threshold_does_not_bypass_other_gates(changes):
    result = window(records_for(**changes))
    assert not any(result["eligible"].values())
    assert result["point_date"] is None
    assert result["point_ahead"] is None


def test_two_optimizer_modes_are_not_averaged_into_candidate():
    result = window(records_for(n=6500, ahead=(43., 87.)), 6500)
    assert result["seed_gap_days"] == 44.
    assert result["seed_ahead_range"] == [43., 87.]
    assert not any(result["eligible"].values())
    assert result["point_date"] is None


def test_missing_seed_cannot_be_a_stable_window():
    records = records_for()
    del records[(lh.ASOF, 925, 29)]
    result = window(records)
    assert result["point_date"] is None
    assert not any(result["eligible"].values())


def test_neighbours_are_one_family_not_cross_scale_evidence():
    records = {}
    for n in (900, 925, 950):
        records.update(records_for(n=n))
    rules = lh.summarize_rules(lh.summarize_windows(records, lh.ASOF))
    for rule in rules.values():
        assert rule["families"][0]["qualified_windows"] == [900, 925, 950]
        assert rule["cross_family_clusters"] == []


def test_cross_family_cluster_does_not_join_long_chains():
    records = {}
    for n, ahead in ((900, 10), (925, 14), (6600, 18)):
        records.update(records_for(n=n, ahead=(ahead, ahead)))
    rules = lh.summarize_rules(lh.summarize_windows(records, lh.ASOF))
    groups = rules["cycles_1_5"]["cross_family_clusters"]
    assert len(groups) == 1
    assert groups[0]["members"] == [925, 6600]
    assert groups[0]["span_trading_days"] == 4


def test_single_qualified_window_is_not_a_cluster():
    rules = lh.summarize_rules(lh.summarize_windows(records_for(), lh.ASOF))
    assert rules["cycles_1_5"]["cross_family_clusters"] == []
    assert rules["cycles_1_5"]["families"][0]["member_date_range"][0] == rules["cycles_1_5"]["families"][0]["member_date_range"][1]


def test_calendar_avoids_known_holidays_without_changing_ahead():
    assert lh.weekday_date("2026-12-24", 1) == "2026-12-25"
    assert lh.date_for("2026-12-24", 1) == "2026-12-28"
    assert lh.date_for("2026-12-31", 1) == "2027-01-04"
    assert lh.CALENDAR["verified"] is False
    result = lh.seed_summary(record(ahead=25))
    assert result["tc_ahead"] == 25
    assert result["weekday_estimate_date"] != result["tc_date"]


def manifest():
    return {"method_hash": "method", "method": {}, "inputs": {
        s: {"input_hash": "prices", "data_version": "v1"} for s in lh.ASSETS}}


def test_unavailable_archive_is_not_running_or_a_zero_signal():
    records = {(lh.HISTORY[0], n, seed): {"seed": seed, "status": "not_available", "error": "source revision"}
               for n in lh.WINDOWS for seed in lh.SEEDS}
    result = lh.snapshot("US_NDX", lh.HISTORY[0], records, manifest())
    assert result["status"] == "not_available"
    assert result["counts"]["not_available"] == 12
    assert result["counts"]["pending"] == 0
    assert result["windows"][0]["seeds"][0]["error"] == "source revision"


def test_final_export_preserves_separate_content_version(tmp_path):
    records = {s: {} for s in lh.ASSETS}
    result = lh.publish_summary(tmp_path, records, manifest(), running=False)
    assert result["status"] == "incomplete"
    assert result["counts"]["completed"] == 0
    assert (tmp_path/"exports"/f"{result['report_version']}.json").exists()
    before = copy.deepcopy(result)
    again = lh.publish_summary(tmp_path, records, manifest(), running=False)
    assert before["report_version"] == again["report_version"]
    assert len(list((tmp_path/"exports").glob("*.json"))) == 1
    assert json.loads((tmp_path/"summary.json").read_text())["report_version"] == again["report_version"]


def test_kernel_hash_rejects_unregistered_code(tmp_path):
    path = tmp_path/"kernel.py"
    path.write_text("raise RuntimeError('must not execute')")
    with pytest.raises(ValueError, match="hash mismatch"):
        lh.kernel(path, "not-the-file-hash")


def test_kernel_does_not_execute_unselected_archive_pipeline(tmp_path):
    path = tmp_path/"kernel.py"
    path.write_text("raise RuntimeError('pipeline must not execute')\n"
                    "def Xmat(t,tc,m,w): return t\n"
                    "def lin(t,y,tc,m,w): return {'sse': 0}\n"
                    "def fit_one(y,seed): return {'seed':seed}\n")
    funcs = lh.kernel(path, lh.digest(path))
    assert funcs["fit_one"]([1, 2], 11) == {"seed": 11}
