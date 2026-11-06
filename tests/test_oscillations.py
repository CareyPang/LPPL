"""Unit migration checks on stored parameter rows, without fitting a model."""
import hashlib

import numpy as np
import pandas as pd
import pytest

from research.features.lppls_rules import _derived, grid_rules, rules, rules_ab
from research.lppls.core import Fit
from research.lppls.oscillations import (
    LEGACY_EQUIVALENT_CYCLE_THRESHOLD,
    LEGACY_OSC_VERSION,
    OSC_UNITS_VERSION,
    compare_cycle_thresholds,
    future_cycle_gate,
    future_oscillations,
    legacy_half_phase_gate,
)


def test_complete_cycles_match_phase_difference_and_time_coordinate_invariance():
    tc, omega, t1, t2 = 210.0, 8.0, 0.0, 199.0
    cycles, status = future_oscillations(tc, omega, t1, t2=t2)
    phase_difference = omega * (np.log(tc - t1) - np.log(tc - t2))
    assert status == "ok"
    assert cycles == pytest.approx(phase_difference / (2 * np.pi), rel=1e-14)
    moved, _ = future_oscillations(3 * tc + 500, omega, 3 * t1 + 500, t2=3 * t2 + 500)
    assert moved == pytest.approx(cycles, rel=1e-14)


def test_future_only_domain_and_nonfinite_inputs_never_pass_new_gates():
    tc = np.array([10., 9., 5., -2., np.nan, np.inf, 10., 10., 10., 10., 10.])
    omega = np.array([8., 8., 8., 8., 8., 8., 0., -1., np.nan, 8., 8.])
    t1 = np.array([0.] * 9 + [9., 10.])
    with np.errstate(all="raise"):
        cycles, status = future_oscillations(tc, omega, t1, t2=9.)
        gate = future_cycle_gate(tc, omega, t1, t2=9., minimum_cycles=0)
    assert status.tolist() == [
        "ok", "not_future", "not_future", "not_future", "nonfinite_input",
        "nonfinite_input", "nonpositive_frequency", "nonpositive_frequency",
        "nonfinite_input", "invalid_window", "invalid_window",
    ]
    assert np.isfinite(cycles[0]) and np.isnan(cycles[1:]).all()
    assert gate.tolist() == [True] + [False] * 10


def test_numerical_failure_is_reported_instead_of_passing_infinite_count():
    cycles, status = future_oscillations(1e308, 8, -1e308, t2=0)
    # The span itself is representable for this case; the count is finite.
    assert status == "ok" and np.isfinite(cycles)
    cycles, status = future_oscillations(1e308, 8, -1e308, t2=9e307)
    assert status == "numerical_failure" and np.isnan(cycles)
    assert not future_cycle_gate(1e308, 8, -1e308, t2=9e307, minimum_cycles=0)


def test_log1p_retains_distant_future_phase_and_no_critical_point_floor():
    count, status = future_oscillations(1e20, 2 * np.pi, t2=1.)
    assert status == "ok" and count == pytest.approx(1e-20, rel=1e-14, abs=0)
    count, status = future_oscillations(199.00001, 8., t2=199.)
    expected = 8. / (2 * np.pi) * np.log(199.00001 / .00001)
    assert status == "ok" and count == pytest.approx(expected, rel=1e-9)
    legacy_clipped = 8. / (2 * np.pi) * np.log(199.00001 / .001)
    assert count > legacy_clipped


def test_inclusive_thresholds_do_not_add_an_epsilon():
    count, _ = future_oscillations(210., 8., t2=199.)
    assert future_cycle_gate(210., 8., t2=199., minimum_cycles=float(count))
    assert future_cycle_gate(210., 8., t2=199., minimum_cycles=np.nextafter(count, -np.inf))
    assert not future_cycle_gate(210., 8., t2=199., minimum_cycles=np.nextafter(count, np.inf))
    values = [np.nextafter(2.5, -np.inf), 2.5, np.nextafter(2.5, np.inf), np.nan, np.inf]
    assert legacy_half_phase_gate(values).tolist() == [False, True, True, False, True]


@pytest.mark.parametrize("threshold", [np.nan, np.inf, -1.])
def test_invalid_thresholds_are_errors(threshold):
    with pytest.raises(ValueError, match="finite and nonnegative"):
        future_cycle_gate(210., 8., t2=199., minimum_cycles=threshold)


def test_same_fit_comparison_separates_unit_conversion_from_stricter_policies():
    # log((2-0)/(2-1)) = log(2); choose frequencies for known cycle counts.
    target = np.array([1., 2., 3.])
    omega = target * (2 * np.pi) / np.log(2)
    old_half_phase = target * np.pi
    result = compare_cycle_thresholds(2., omega, t2=1., legacy_half_phase=old_half_phase)
    np.testing.assert_allclose(result["osc_cycles"], target, rtol=1e-14)
    assert result["legacy"].tolist() == [True, True, True]
    assert result["cycles_1_5"].tolist() == [False, True, True]
    assert result["cycles_2_5"].tolist() == [False, False, True]
    np.testing.assert_array_equal(result["legacy"], result["legacy_future"])
    assert LEGACY_EQUIVALENT_CYCLE_THRESHOLD == 2.5 / np.pi
    assert not result["conversion_disagreement"].any()


def test_comparison_keeps_past_legacy_acceptance_but_excludes_it_from_forecasts():
    result = compare_cycle_thresholds(
        [210., 190., 199., np.nan], 8., t2=199., legacy_half_phase=[20., 20., 20., 20.]
    )
    assert result["legacy"].all()
    assert result["legacy_future"].tolist() == [True, False, False, False]
    assert result["cycles_1_5"].tolist() == [True, False, False, False]
    assert result["cycles_2_5"].tolist() == [True, False, False, False]
    # Preserve the exact original threshold even where a conversion rounds.
    values = np.array([np.nextafter(2.5, -np.inf), 2.5, np.nextafter(2.5, np.inf), np.nan])
    result = compare_cycle_thresholds(210., 8., t2=199., legacy_half_phase=values)
    np.testing.assert_array_equal(result["legacy"], values >= 2.5)
    np.testing.assert_array_equal(
        result["conversion_disagreement"],
        (values >= 2.5) != (values / np.pi >= 2.5 / np.pi),
    )


def _legacy_fixture():
    # Deliberately cover before/inside/at/after-window tc, shape, error,
    # damping, and frequency variants, including Jiang and antibubble gates.
    spec = [
        (210, 8, .5, -1, 2, .02), (240, 8, .5, -1, 2, .02),
        (300, 8, .5, -1, 2, .02), (1000, 8, .5, -1, 2, .02),
        (190, 8, .5, -1, 2, .02), (199, 8, .5, -1, 2, .02),
        (-10, 8, .5, -1, 2, .02), (210, 8, .5, 1, 2, .02),
        (210, 3, .5, -1, 2, .02), (210, 8, .5, -1, .6, .02),
        (210, 8, 1.1, -1, 2, .02), (210, 8, .5, -1, 2, .10),
        (210, 8, .5, -1, 2, .20), (210, 20, .5, -1, 2, .02),
    ]
    return pd.DataFrame([
        dict(date=pd.Timestamp("2015-06-01"), n=200, tc=tc, m=m, w=w, A=5., B=B,
             C1=m * abs(B) / (w * damping), C2=0., sse=200 * (.3 * error)**2,
             r2=.95, pow_B=-1., pow_m=.5, pow_sse=1., y_std=.3, lomb_w=w, df_t=-4.)
        for tc, w, m, B, damping, error in spec
    ])


def test_derived_preserves_old_numeric_fields_and_explicitly_names_both_units():
    scan = _legacy_fixture()
    d = _derived(scan)
    old_half_phase = scan.w / 2 * np.log(np.abs(scan.tc) / np.maximum(np.abs(scan.tc - 199), 1e-3))
    np.testing.assert_array_equal(d.osc, old_half_phase)
    np.testing.assert_array_equal(d.n_osc, old_half_phase / np.pi)
    np.testing.assert_array_equal(d.osc, d.osc_legacy_half_phase)
    np.testing.assert_array_equal(d.n_osc, d.osc_legacy_cycles)
    assert set(d.osc_units_version) == {OSC_UNITS_VERSION}
    assert set(d.osc_legacy_version) == {LEGACY_OSC_VERSION}
    assert d.loc[[4, 5, 6], "osc_cycles"].isna().all()
    assert set(d.loc[[4, 5, 6], "osc_cycles_status"]) == {"not_future"}
    assert "osc_cycles" not in scan  # Caller input is not mutated.


def test_all_existing_rules_keep_their_pre_migration_masks():
    # Frozen before this change at b8f584e, using the fixture above. The CSV
    # fingerprints include every named gate and row (LF), not just pass counts.
    expected = {
        rules: "a59564e2611c1aae36bfe8e36b9aaeb7b5859e16175b17dd6127c2b631f02db6",
        grid_rules: "84d7b9a380f68085efaf6a97d6f68ff686918bc8a91592755d146e1e6a0ddc3f",
        rules_ab: "b74a2572ec650a2abda99e2e4a8d6dcf4e54a457913b3cf2e953c45455b8b622",
    }
    d = _derived(_legacy_fixture())
    for rule, digest in expected.items():
        encoded = rule(d).to_csv(index=False, lineterminator="\n").encode()
        assert hashlib.sha256(encoded).hexdigest() == digest, rule.__name__
    assert rules(d).box.iloc[5]  # Legacy box accepts tc=t2; keep this visible.
    assert rules(d).lit1.iloc[4]  # Legacy abs extension accepts inside-window tc.


def test_fit_exposes_validated_cycles_without_replacing_legacy_calculation():
    f = Fit(tc=210., m=.5, w=8., A=5., B=-1., C1=.01, C2=0., sse=.1, r2=.95, n=200)
    original = 8. / (2 * np.pi) * np.log(210. / 11.)
    assert f.n_osc() == original
    assert f.osc_cycles() == pytest.approx(original, rel=1e-14)
    f.tc = 190.
    assert np.isnan(f.osc_cycles())
