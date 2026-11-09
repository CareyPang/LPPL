"""Window selection and cross-scale research must not create information or votes."""
import copy

import numpy as np
import pandas as pd
import pytest

from research.lppls.window_clusters import (
    MAX_CLUSTER_WIDTH,
    MINIMUM_CYCLES,
    SCALE_WINDOWS,
    analyze_asof,
    selected_windows,
)


def source(accepted=None, expected=None):
    accepted = {} if accepted is None else accepted
    expected = list(n for grid in SCALE_WINDOWS.values() for n in grid) if expected is None else expected
    return pd.DataFrame([
        dict(date=pd.Timestamp("2015-06-01"), n=n, tc=n - 1 + accepted.get(n, 10.),
             m=.5, w=8., B=-1. if n in accepted else 1.) for n in expected
    ], columns=["date", "n", "tc", "m", "w", "B"]), expected


def test_full_and_thin_selection_are_frozen_before_seeing_fits():
    full, thin = selected_windows(), selected_windows("thin")
    assert {k: len(v) for k, v in full.items()} == {"short": 7, "mid": 13, "medium": 25, "long": 50}
    assert sum(map(len, thin.values())) == 28
    assert thin["short"] == full["short"]
    for scale in full:
        assert thin[scale][0] == full[scale][0] and thin[scale][-1] == full[scale][-1]
        assert len(set(thin[scale])) == 7
    with pytest.raises(ValueError, match="mode"):
        selected_windows("adaptive_after_filter")


def test_complete_zero_pass_asof_is_evaluable_with_fixed_denominators():
    fits, expected = source()
    result = analyze_asof(fits, expected)
    assert result["evaluable"] and result["minimum_cycles"] == 1.5 == MINIMUM_CYCLES
    assert sum(s["denominator"] for s in result["scales"].values()) == 95
    assert all(s["fraction"] == 0 and not s["alarm"] for s in result["scales"].values())
    assert result["clusters"]["cross"]["primary"] is None
    assert sum(r["weight"] for r in result["fits"]) == pytest.approx(1)


def test_missing_source_window_does_not_shrink_denominator_or_fake_cluster():
    fits, expected = source({35: 10, 45: 10, 135: 10})
    complete = analyze_asof(fits, expected)
    assert complete["clusters"]["cross"]["primary"] is None  # only 1/25 medium support, below .05
    missing = analyze_asof(fits[fits.n != 130], expected)
    assert not missing["evaluable"]
    assert missing["scales"]["medium"]["denominator"] == 25
    assert missing["scales"]["medium"]["missing_windows"] == [130]
    assert missing["scales"]["medium"]["status"] == "incomplete_window_grid"
    assert missing["clusters"]["any"]["primary"] is None


def test_history_shortage_and_missing_scan_are_different_and_never_renormalize():
    fits, expected = source({30: 5, 35: 5}, expected=[30, 35])
    result = analyze_asof(fits, expected)
    assert result["scales"]["short"]["status"] == "insufficient_window_history"
    assert sum(r["weight"] for r in result["fits"]) == pytest.approx(.25)
    assert result["scales"]["long"]["fraction"] is None
    all_fits, full_expected = source()
    missing = analyze_asof(all_fits.iloc[:0], full_expected)
    assert {s["status"] for s in missing["scales"].values()} == {"missing_scan"}


def test_original_best_window_cannot_be_duplicated_as_extra_seed_vote():
    fits, expected = source({35: 10})
    with pytest.raises(ValueError, match="duplicate window"):
        analyze_asof(pd.concat([fits, fits[fits.n == 35]]), expected)
    changed = fits.copy()
    changed.loc[0, "date"] = pd.Timestamp("2015-06-02")
    with pytest.raises(ValueError, match="one nonmissing"):
        analyze_asof(changed, expected)


def test_invalid_and_past_fit_rows_stay_in_denominator_and_fail_qualification():
    fits, expected = source({35: 10, 45: 10, 135: 10, 140: 10})
    fits.loc[fits.n == 35, "tc"] = 34
    fits.loc[fits.n == 45, "w"] = np.nan
    result = analyze_asof(fits, expected)
    assert result["evaluable"]
    records = {r["n"]: r for r in result["fits"]}
    assert not records[35]["qualified"] and records[35]["osc_cycles"] is None
    assert not records[45]["qualified"] and records[45]["osc_cycles"] is None
    assert result["scales"]["short"]["denominator"] == 7


def test_cycle_gate_uses_complete_cycles_and_does_not_assume_five_bar_lead():
    fits, expected = source({30: 20, 35: 3, 40: 4, 45: 5})
    result = analyze_asof(fits, expected)
    records = {r["n"]: r for r in result["fits"]}
    assert records[30]["osc_cycles"] < 1.5 and not records[30]["qualified"]
    assert all(records[n]["qualified"] for n in (35, 40, 45))
    assert result["clusters"]["any"]["primary"]["hi"] == 5
    # No h>=6 hard gate: actual actionable warning lead belongs to event evaluation.


def test_cross_scale_support_uses_original_scale_denominators():
    fits, expected = source({35: 10, 45: 10, 135: 10, 140: 10})
    result = analyze_asof(fits, expected)
    cluster = result["clusters"]["cross"]["primary"]
    assert cluster["members"] == [35, 45, 135, 140]
    assert cluster["supported_scales"] == ["short", "medium"]
    assert cluster["scale_fractions"]["short"] == pytest.approx(2 / 7)
    assert cluster["scale_fractions"]["medium"] == pytest.approx(2 / 25)
    assert cluster["mass"] == pytest.approx(2 / (4 * 7) + 2 / (4 * 25))
    assert cluster["lo"] == cluster["hi"] == 10


def test_density_never_chains_neighbors_into_interval_wider_than_ten():
    fits, expected = source({130: 1, 135: 9, 140: 17})
    result = analyze_asof(fits, expected)
    assert result["clusters"]["any"]["primary"] is None
    fits, expected = source({130: 1, 135: 2, 140: 9, 145: 17})
    result = analyze_asof(fits, expected)
    primary = result["clusters"]["any"]["primary"]
    assert primary["members"] == [130, 135, 140]
    assert primary["lo"] == 1 and primary["hi"] == 9
    assert all(c["width"] <= MAX_CLUSTER_WIDTH for c in result["clusters"]["any"]["candidates"])


def test_equal_scale_mass_prevents_dense_long_band_dominating_by_count():
    accepted = {35: 10, 40: 10, 45: 10}
    accepted.update({n: 30 for n in range(255, 305, 5)})
    fits, expected = source(accepted)
    result = analyze_asof(fits, expected)
    primary = result["clusters"]["any"]["primary"]
    assert primary["members"] == [35, 40, 45]
    assert primary["n_members"] == 3  # beats ten long windows through scale balance


def test_membership_ties_and_output_are_deterministic_under_row_permutation():
    fits, expected = source({130: 10, 135: 10, 140: 10, 145: 30, 150: 30, 155: 30})
    before = fits.copy(deep=True)
    first = analyze_asof(fits, expected)
    second = analyze_asof(fits.sample(frac=1, random_state=7), list(reversed(expected)))
    assert first == second
    assert first["clusters"]["any"]["primary"]["lo"] == 10
    pd.testing.assert_frame_equal(before, fits)


def test_thinning_is_intersected_with_history_without_replacing_missing_selected_windows():
    fits, expected = source()
    thin = selected_windows("thin")
    long_choice = thin["long"][2]
    result = analyze_asof(fits[fits.n != long_choice], expected, mode="thin")
    assert result["scales"]["long"]["expected_windows"] == list(thin["long"])
    assert result["scales"]["long"]["denominator"] == 7
    assert result["scales"]["long"]["missing_windows"] == [long_choice]
    assert not result["evaluable"]
    partial = [n for n in expected if n <= 320]
    result = analyze_asof(fits[fits.n.isin(partial)], partial, mode="thin")
    assert result["scales"]["long"]["expected_windows"] == [n for n in thin["long"] if n <= 320]


def test_singleton_or_two_windows_cannot_become_zero_width_cluster():
    fits, expected = source({35: 10, 135: 10})
    result = analyze_asof(fits, expected)
    assert result["clusters"]["any"]["primary"] is None


def test_unexpected_grid_and_invalid_expected_configuration_are_explicit():
    fits, expected = source()
    result = analyze_asof(fits, [n for n in expected if n != 130])
    assert result["scales"]["medium"]["unexpected_windows"] == [130]
    assert not result["evaluable"]
    with pytest.raises(ValueError, match="unique"):
        analyze_asof(fits, expected + [130])
    with pytest.raises(ValueError, match="step-5"):
        analyze_asof(fits, expected + [131])
    # Mutating a returned list cannot alter the frozen window specification.
    result_copy = copy.deepcopy(result)
    result_copy["scales"]["medium"]["expected_windows"].clear()
    assert len(SCALE_WINDOWS["medium"]) == 25
