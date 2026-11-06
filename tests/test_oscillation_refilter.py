"""Saved-fit re-filtering must preserve optimization choices and missing evidence."""
import json

import numpy as np
import pandas as pd
import pytest

from tools.lppl_oscillation_refilter import analyze, run


def inputs():
    metadata = {"asof_endpoint_positions": [100, 101], "windows": [32, 80], "seeds": [101, 202]}
    records = []
    for endpoint in metadata["asof_endpoint_positions"]:
        for window in metadata["windows"]:
            for seed in metadata["seeds"]:
                # The worse-objective seed passes stricter thresholds even when
                # the true objective-best seed does not. It must never replace it.
                cycles = (1.4 if window == 32 else 2.8) if seed == 101 else 3.0
                offset = (window - 1) / np.expm1(2 * np.pi * cycles / 8)
                b = -1.0 if endpoint == 100 else 1.0
                records.append(dict(
                    endpoint_pos=endpoint, endpoint_time_iso=f"2020-01-{endpoint - 98:02d}",
                    created_at_utc="2020-02-01T00:00:00Z", window=window, seed=seed,
                    ok=True, objective=0.1 if seed == 101 else 0.2, tc_offset=offset,
                    m=0.5, omega=8.0, B=b, damping=1.0, r2=0.9, osc=cycles,
                    boundary=False, right_censored=False, b_sign_ok=b < 0,
                    raw_clean=b < 0 and cycles >= 1.25,
                    series_kind="daily_top", transform="top_log",
                    window_family="short" if window <= 75 else "mid",
                ))
    all_fits = pd.DataFrame(records)
    return all_fits, all_fits[all_fits.seed == 101].copy(), metadata


def test_fixed_best_seed_not_reselected_and_zero_asof_kept():
    all_fits, best, metadata = inputs()
    summary, asof, detail = analyze(all_fits, best, metadata)
    assert len(asof) == 2 * 7
    assert asof.n_windows.eq(2).all()
    assert detail.seed.eq(101).all()
    source = asof[asof.rule == "source_cycles_2_5"].set_index("endpoint_pos")
    assert source.loc[100, "n_pass"] == 1
    assert source.loc[100, "n_lost"] == 1
    assert source.loc[101, "n_pass"] == 0
    assert source.loc[101, "empty_after_filter"]
    assert np.isnan(source.loc[101, "q50_tc_offset"])
    assert source.loc[101, "n_common_retained_previous"] == 0
    assert not source.descriptive_interval_width_le_10.any()  # a singleton is not a cluster
    assert summary["event_recall"] is None
    assert summary["actual_warning_lead"] is None
    assert summary["event_metrics_status"] == "NOT_ESTABLISHED"


def test_actual_best_is_validated_before_any_rule_can_choose_seed():
    all_fits, best, metadata = inputs()
    wrong = all_fits[all_fits.seed == 202].copy()
    with pytest.raises(ValueError, match="objective minimum"):
        analyze(all_fits, wrong, metadata)


@pytest.mark.parametrize("which", ["all", "best"])
def test_missing_grid_rows_fail_instead_of_shrinking_denominator(which):
    all_fits, best, metadata = inputs()
    if which == "all":
        all_fits = all_fits.iloc[1:]
    else:
        best = best.iloc[1:]
    with pytest.raises(ValueError, match="grid"):
        analyze(all_fits, best, metadata)


def test_duplicate_seed_row_rejected():
    all_fits, best, metadata = inputs()
    with pytest.raises(ValueError, match="duplicate"):
        analyze(pd.concat([all_fits, all_fits.iloc[:1]]), best, metadata)


def test_units_are_checked_in_all_seeds_not_just_best():
    all_fits, best, metadata = inputs()
    all_fits.loc[all_fits.seed == 202, "osc"] *= np.pi
    with pytest.raises(ValueError, match="full cycles"):
        analyze(all_fits, best, metadata)


def test_source_raw_clean_must_be_reproduced():
    all_fits, best, metadata = inputs()
    all_fits.loc[0, "raw_clean"] = False
    with pytest.raises(ValueError, match="raw_clean cannot be reproduced"):
        analyze(all_fits, best, metadata)


def test_source_baseline_preserves_saved_ulp_threshold_decision(tmp_path):
    all_fits, best, metadata = inputs()
    # Source log and canonical log1p land on opposite sides of 1.25.
    offset = 33 / np.expm1(2 * np.pi * 1.25 / 8)
    source_cycles = 8 / (2 * np.pi) * np.log((33 + offset) / offset)
    assert source_cycles >= 1.25
    metadata["windows"] = [34, 80]
    for frame in (all_fits, best):
        changed = (frame.window == 32) & (frame.endpoint_pos == 100)
        frame.loc[frame.window == 32, "window"] = 34
        frame.loc[changed, "tc_offset"] = offset
        frame.loc[changed, "osc"] = source_cycles
        # The other endpoint's window changed too, so keep its original source
        # count consistent with the new length (its positive B still rejects it).
        other = (frame.window == 34) & (frame.endpoint_pos == 101)
        frame.loc[other, "osc"] = frame.loc[other, "omega"] / (2 * np.pi) * np.log1p(33 / frame.loc[other, "tc_offset"])
    summary, _, detail = analyze(all_fits, best, metadata)
    row = detail[(detail.rule == "source_cycles_1_25") & (detail.endpoint_pos == 100) & (detail.window == 34)].iloc[0]
    assert row.osc >= 1.25
    assert row.osc_cycles < 1.25
    assert row.passed and row.baseline_passed
    assert row.source_cycle_conversion_gate_disagreement
    assert summary["source_conversion_disagreements"]["all_seed_after_nonosc_mask"] == 2
    assert summary["source_conversion_disagreements"]["best_after_nonosc_mask"] == 1
    all_path, best_path, meta_path = tmp_path / "all.csv", tmp_path / "best.csv", tmp_path / "meta.json"
    all_fits.to_csv(all_path, index=False)
    best.to_csv(best_path, index=False)
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    persisted = run(all_path, best_path, meta_path, tmp_path / "boundary-evidence")
    assert persisted["source_conversion_disagreements"]["best_after_nonosc_mask"] == 1
    original = next(r for r in persisted["rules"] if r["rule"] == "source_cycles_1_25")
    assert original["n_pass"] == 2
    assert original["n_lost"] == 0


def test_original_source_rejects_infinite_damping():
    all_fits, best, metadata = inputs()
    for frame in (all_fits, best):
        frame.loc[:, "damping"] = np.inf
        frame.loc[:, "raw_clean"] = False
    _, asof, _ = analyze(all_fits, best, metadata)
    assert asof[asof.family == "source_raw_clean"].n_pass.eq(0).all()
    # The independent box family intentionally has no damping predicate.
    assert asof[(asof.rule == "box_future_no_N") & (asof.endpoint_pos == 100)].n_pass.iloc[0] == 2


def test_best_fit_cannot_mix_parameters_from_other_row():
    all_fits, best, metadata = inputs()
    best.iloc[0, best.columns.get_loc("r2")] = 0.95
    with pytest.raises(ValueError, match="selected seed row differs"):
        analyze(all_fits, best, metadata)


def test_missing_values_and_nonfuture_tc_are_not_silently_dropped():
    all_fits, best, metadata = inputs()
    bad = all_fits.copy()
    bad.loc[0, "osc"] = np.nan
    with pytest.raises(ValueError, match="missing numeric"):
        analyze(bad, best, metadata)
    bad = all_fits.copy()
    bad.loc[0, "tc_offset"] = -1.0
    with pytest.raises(ValueError, match="nonfuture"):
        analyze(bad, best, metadata)


def test_five_bar_distance_is_not_next_bar_action_distance():
    all_fits, best, metadata = inputs()
    for frame in (all_fits, best):
        frame.loc[:, "tc_offset"] = 5.5
        frame.loc[:, "osc"] = frame.omega / (2 * np.pi) * np.log1p((frame.window - 1) / 5.5)
    _, asof, _ = analyze(all_fits, best, metadata)
    row = asof[(asof.rule == "box_future_no_N") & (asof.endpoint_pos == 100)].iloc[0]
    assert row.n_pass_tc_forward_ge_5 == 2
    assert row.n_pass_action_forward_ge_5 == 0


def test_box_gate_experiment_uses_same_denominator_and_preserves_source_baseline():
    all_fits, best, metadata = inputs()
    summary, asof, _ = analyze(all_fits, best, metadata)
    assert summary["source_original_threshold_cycles"] == 1.25
    assert summary["source_osc_unit"] == "full_cycles"
    box = asof[(asof.family == "box_future_added_gate") & (asof.endpoint_pos == 100)]
    assert box.n_windows.eq(2).all()
    assert box.n_baseline_pass.eq(2).all()
    assert box.n_gained.eq(0).all()
    assert box.set_index("rule").loc["box_future_cycles_2_5", "n_pass"] == 1


def test_output_manifest_hashes_and_refusal_to_overwrite(tmp_path):
    all_fits, best, metadata = inputs()
    all_path, best_path, meta_path = tmp_path / "all.csv", tmp_path / "best.csv", tmp_path / "meta.json"
    all_fits.to_csv(all_path, index=False)
    best.to_csv(best_path, index=False)
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    output = tmp_path / "evidence"
    run(all_path, best_path, meta_path, output)
    assert {p.name for p in output.iterdir()} == {"summary.json", "input_manifest.json", "per_asof.csv", "per_fit.csv"}
    manifest = json.loads((output / "input_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["inputs"]["all_seed_fits"]["sha256"]) == 64
    assert len(manifest["inputs"]["refilter_tool"]["sha256"]) == 64
    assert len(manifest["inputs"]["oscillation_unit_api"]["sha256"]) == 64
    assert manifest["implementation_versions"]["input_float_parsing"] == "pandas float_precision=round_trip"
    assert manifest["sample_boundaries"]["endpoint_positions"] == [100, 101]
    prior = (output / "summary.json").read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        run(all_path, best_path, meta_path, output)
    assert (output / "summary.json").read_bytes() == prior
