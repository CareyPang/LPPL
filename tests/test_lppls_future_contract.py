import hashlib
import json
import math
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pytest

from research.lppls import core
from research.lppls import future_contract
from research.lppls.future_contract import (
    CONTRACT_VERSION,
    DEFAULT_FILTER_BOUNDS,
    DEFAULT_SEARCH_BOUNDS,
    FilterOutcome,
    LogPrice,
    cache_key,
    canonical_json,
    cycles_full,
    evaluate_filter,
    fit_window,
    inclusive_width_sessions,
    legacy_osc_to_full_cycles,
    log_price_from_price,
    session_indices_for_bars,
)
from research.optim.optimizers import grid_profile, tcgrid_lm

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lppls_v2_allow_inside_golden.json"
FAST_SEARCH = replace(DEFAULT_SEARCH_BOUNDS, budget=(8, 4, 4, 2), n_random=2)


@pytest.fixture
def golden():
    return json.loads(FIXTURE_PATH.read_text())


def _window_input(series, *, search_bounds=FAST_SEARCH, seed_retries=((0, 0),), execute=True):
    log_price = LogPrice.from_log_price(series, source_field="synthetic_log_price")
    data_hash = hashlib.sha256(canonical_json(log_price.values).encode("utf-8")).hexdigest()
    result = fit_window(
        log_price,
        data_hash=data_hash,
        asof="2024-02-22",
        window_start="2023-11-01",
        window_end="2024-02-22",
        lookback_L=len(series),
        bar_to_session_index=tuple(range(len(series))),
        search_bounds=search_bounds,
        seed_retries=seed_retries,
        execute=execute,
    )
    return log_price, data_hash, result


def test_pre_change_tcgrid_lm_global_behavior_matches_pinned_golden(golden, monkeypatch):
    series = np.asarray(golden["series"], dtype=float)
    time_grid = golden["time_grid"]
    t = time_grid["start"] + time_grid["step"] * np.arange(time_grid["count"], dtype=float)
    spec = golden["tcgrid_lm"]
    for enabled, name in ((True, "allow_inside_true"), (False, "allow_inside_false")):
        monkeypatch.setattr(core, "ALLOW_INSIDE", enabled)
        result = tcgrid_lm(
            t,
            series,
            np.asarray(spec["lo"], dtype=float),
            np.asarray(spec["hi"], dtype=float),
            seed=spec["seed"],
            n_random=spec["n_random"],
        )
        expected = spec["legacy_global_results"][name]
        assert np.array_equal(result.theta, np.asarray(expected["theta"], dtype=float))
        assert result.sse == expected["sse"]


def test_cycles_full_hand_values_and_legacy_oscillation_conversion():
    cycles = cycles_full(2 * math.pi, 30, 0, 10)
    assert cycles == pytest.approx(math.log(1.5), abs=1e-15)
    legacy_osc = math.pi * math.log(1.5)
    assert legacy_osc_to_full_cycles(legacy_osc) == pytest.approx(cycles, abs=1e-15)
    assert legacy_osc_to_full_cycles(2.5) == pytest.approx(2.5 / math.pi)
    with pytest.raises(ValueError, match="t1"):
        cycles_full(8.0, 20.0, 10.0, 10.0)


def test_exact_full_cycle_boundary_passes_and_direction_is_separate():
    t1, t2, tc = 0.0, 10.0, 20.0
    omega = 3 * math.pi / math.log(2)
    assert cycles_full(omega, tc, t1, t2) == pytest.approx(1.5, abs=1e-15)
    accepted = evaluate_filter(
        np.asarray([tc, 0.5, omega]),
        np.asarray([5.0, -1.0, 0.01, 0.0]),
        1.0,
        t1,
        t2,
        DEFAULT_FILTER_BOUNDS,
    )
    assert accepted == FilterOutcome("pass", ())
    wrong_direction = evaluate_filter(
        np.asarray([tc, 0.5, omega]),
        np.asarray([5.0, 1.0, 0.01, 0.0]),
        1.0,
        t1,
        t2,
        DEFAULT_FILTER_BOUNDS,
    )
    assert wrong_direction.status == "reject"
    assert "direction" in wrong_direction.reasons


def test_zero_amplitude_damping_preserves_legacy_positive_infinity_rule():
    omega = 3 * math.pi / math.log(2)
    outcome = evaluate_filter(
        np.asarray([20.0, 0.5, omega]),
        np.asarray([5.0, -1.0, 0.0, 0.0]),
        1.0,
        0.0,
        10.0,
        DEFAULT_FILTER_BOUNDS,
    )
    assert outcome == FilterOutcome("pass", ())


@pytest.mark.parametrize("tc", [10.0, 9.0])
def test_tc_at_or_inside_window_is_rejected(tc):
    assert math.isnan(cycles_full(8.0, tc, 0.0, 10.0))
    outcome = evaluate_filter(
        np.asarray([tc, 0.5, 8.0]),
        np.asarray([5.0, -1.0, 0.01, 0.0]),
        1.0,
        0.0,
        10.0,
        DEFAULT_FILTER_BOUNDS,
    )
    assert outcome.status == "reject"
    assert "tc_not_future" in outcome.reasons
    assert "non_finite" in outcome.reasons


@pytest.mark.parametrize("price", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_nonpositive_or_nonfinite_prices_are_rejected(price):
    with pytest.raises(ValueError, match="finite positive"):
        log_price_from_price([100.0, price])


def test_log_price_constructors_record_input_kind_and_provenance():
    from_price = LogPrice.from_price([1.0, math.e], source_field="close_qfq", adjustment_type="qfq")
    from_log = LogPrice.from_log_price([0.0, 1.0], source_field="log_close_qfq", adjustment_type="qfq")
    np.testing.assert_array_equal(from_price.as_array(), np.asarray([0.0, 1.0]))
    assert from_price.constructed_from == "price"
    assert from_log.constructed_from == "log_price"
    assert from_price.source_field == "close_qfq"
    assert from_price.adjustment_type == "qfq"
    assert from_log.to_dict()["constructed_from"] == "log_price"
    with pytest.raises(TypeError, match="requires LogPrice"):
        fit_window(
            np.asarray([0.0, 1.0]),
            data_hash="a" * 64,
            asof="2024-02-22",
            window_start="2024-02-21",
            window_end="2024-02-22",
            lookback_L=2,
            bar_to_session_index=(0, 1),
        )


def test_same_unconstrained_design_has_equal_sse_for_y_and_minus_y():
    t = np.arange(30, dtype=float)
    y = np.sin(t / 4) + 0.01 * t
    sse_y, beta_y = core.lin_fit(t, y, 40.0, 0.5, 8.0, allow_inside=False)
    sse_neg, beta_neg = core.lin_fit(t, -y, 40.0, 0.5, 8.0, allow_inside=False)
    assert sse_y == pytest.approx(sse_neg, rel=1e-13, abs=1e-13)
    np.testing.assert_allclose(beta_neg, -beta_y, rtol=1e-12, atol=1e-12)


def test_grid_profile_fixed_tc_matches_brute_force_over_m_omega():
    t = np.arange(30, dtype=float)
    y = np.cos(t / 5) + 0.03 * t
    tc = np.asarray([38.0])
    ms = np.asarray([0.2, 0.5, 0.8])
    omegas = np.asarray([4.0, 8.0, 12.0])
    profile = grid_profile(t, y, tc, ms, omegas, allow_inside=False)
    brute = np.asarray(
        [[core.lin_fit(t, y, tc[0], m, omega, allow_inside=False)[0] for omega in omegas] for m in ms]
    )
    np.testing.assert_allclose(profile[0], brute, rtol=1e-12, atol=1e-12)
    assert float(profile[0].min()) == pytest.approx(float(brute.min()), rel=1e-12, abs=1e-12)


def test_future_fits_ignore_global_inside_flag_in_both_run_orders(golden, monkeypatch):
    series = np.asarray(golden["series"], dtype=float)
    observed = []
    for order in ((True, False), (False, True)):
        run = {}
        for enabled in order:
            monkeypatch.setattr(core, "ALLOW_INSIDE", enabled)
            _, _, result = _window_input(series)
            assert result.status == "fit_ok"
            assert len(result.attempts) == 1
            assert result.attempts[0].status == "success"
            assert result.attempts[0].design_rank == 4
            assert result.attempts[0].condition_number is not None
            run[enabled] = result
            t = np.arange(20, dtype=float)
            inside_tc = 10.5
            legacy_design = core.design(t, inside_tc, 0.5, 8.0)
            assert (legacy_design is not None) is enabled
            if enabled:
                np.testing.assert_array_equal(
                    legacy_design,
                    core.design(t, inside_tc, 0.5, 8.0, allow_inside=True),
                )
                assert math.isfinite(core.sse([inside_tc, 0.5, 8.0], t, np.ones_like(t)))
                assert math.isinf(core.sse([inside_tc, 0.5, 8.0], t, np.ones_like(t), allow_inside=False))
            explicit_future_design = core.design(t, inside_tc, 0.5, 8.0, allow_inside=False)
            assert explicit_future_design is None
        assert run[True].attempts[0].theta == run[False].attempts[0].theta
        assert run[True].attempts[0].sse == run[False].attempts[0].sse
        observed.append(run[True].to_dict())
    assert observed[0] == observed[1]


def test_same_window_seed_budget_has_identical_attempts_and_cache_key(golden):
    series = np.asarray(golden["series"], dtype=float)
    _, _, first = _window_input(series, seed_retries=((0, 0), (1, 0)))
    _, _, second = _window_input(series, seed_retries=((0, 0), (1, 0)))
    assert first.status == "fit_ok"
    assert len(first.attempts) == 2
    assert first.to_dict() == second.to_dict()
    assert first.attempts[0].cache_key == second.attempts[0].cache_key
    assert first.attempts[0].attempt_id == second.attempts[0].attempt_id
    assert first.attempts[0].cache_key != first.attempts[1].cache_key
    assert first.eval_H == 63
    assert first.label_confirmation_E is None
    assert first.fit_clock == "effective_bars"
    assert first.contract_version == CONTRACT_VERSION
    assert first.domain == "future_only"
    assert first.units == "full_cycles"
    assert first.t1 == 0.0
    assert first.t2 == len(series) - 1
    assert first.fit_horizon == pytest.approx(0.2 * (len(series) - 1))
    assert first.bar_to_session_index == tuple(range(len(series)))
    assert first.tc_offset_bars is not None and first.tc_offset_bars > 0


def test_pending_window_keeps_one_pending_attempt_and_no_filter(golden):
    result = _window_input(np.asarray(golden["series"], dtype=float), execute=False)[2]
    assert result.status == "pending"
    assert [attempt.status for attempt in result.attempts] == ["pending"]
    assert result.filter_outcome.status == "not_evaluated"
    json.dumps(result.to_dict(), allow_nan=False)


def test_numerical_failure_is_an_attempt_failure_not_a_filter_rejection(golden, monkeypatch):
    def fail(*_args, **_kwargs):
        raise np.linalg.LinAlgError("synthetic failure")

    monkeypatch.setattr(future_contract, "tcgrid_lm", fail)
    result = _window_input(np.asarray(golden["series"], dtype=float))[2]
    assert result.status == "all_attempts_failed"
    assert len(result.attempts) == 1
    assert result.attempts[0].status == "numerical_failure"
    assert result.filter_outcome.status == "not_evaluated"


def test_nonfinite_optimizer_output_is_not_serialized_as_a_success(golden, monkeypatch):
    class NonfiniteResult:
        theta = np.asarray([85.0, 0.5, 8.0])
        sse = math.nan

    monkeypatch.setattr(future_contract, "tcgrid_lm", lambda *_args, **_kwargs: NonfiniteResult())
    result = _window_input(np.asarray(golden["series"], dtype=float))[2]
    assert result.status == "all_attempts_failed"
    assert result.attempts[0].status == "numerical_failure"
    assert result.attempts[0].sse is None
    assert not result.attempts[0].finite
    json.dumps(result.to_dict(), allow_nan=False)


def test_future_tc_violation_is_an_invalid_attempt_not_clamped(golden, monkeypatch):
    class BadResult:
        theta = np.asarray([78.0, 0.5, 8.0])
        sse = 1.0

    monkeypatch.setattr(future_contract, "tcgrid_lm", lambda *_args, **_kwargs: BadResult())
    result = _window_input(np.asarray(golden["series"], dtype=float))[2]
    assert result.status == "all_attempts_failed"
    assert result.attempts[0].status == "invalid"
    assert result.attempts[0].theta[0] == 78.0
    assert result.filter_outcome.status == "not_evaluated"


def test_nan_fit_metrics_reject_instead_of_passing():
    outcome = evaluate_filter(
        np.asarray([20.0, 0.5, 8.0]),
        np.asarray([5.0, -1.0, 0.01, math.nan]),
        1.0,
        0.0,
        10.0,
        DEFAULT_FILTER_BOUNDS,
    )
    assert outcome.status == "reject"
    assert "non_finite" in outcome.reasons


def test_calendar_mapping_keeps_holiday_weekend_and_suspension_positions():
    calendar = ["2024-02-08", "2024-02-19", "2024-02-20", "2024-02-21", "2024-02-22"]
    assert session_indices_for_bars(["2024-02-08", "2024-02-19"], calendar) == (0, 1)
    weekend_calendar = ["2024-02-16", "2024-02-19"]
    assert session_indices_for_bars(["2024-02-16", "2024-02-19"], weekend_calendar) == (0, 1)
    assert session_indices_for_bars(["2024-02-19", "2024-02-21"], calendar) == (1, 3)


def test_inclusive_width_counts_ten_and_eleven_sessions():
    assert inclusive_width_sessions(4, 13) == 10
    assert inclusive_width_sessions(4, 14) == 11


def test_contract_bounds_are_json_serializable_and_separate():
    from research.lppls.future_contract import DEFAULT_FILTER_BOUNDS, DEFAULT_SEARCH_BOUNDS

    payload = {"search_bounds": DEFAULT_SEARCH_BOUNDS.to_dict(), "filter_bounds": DEFAULT_FILTER_BOUNDS.to_dict()}
    serialized = json.dumps(payload, sort_keys=True, allow_nan=False)
    json.dumps(asdict(DEFAULT_SEARCH_BOUNDS), allow_nan=False)
    json.dumps(asdict(DEFAULT_FILTER_BOUNDS), allow_nan=False)
    assert CONTRACT_VERSION == "future_fullcycles_1p5_v1"
    assert '"allow_inside": false' in serialized
    assert DEFAULT_FILTER_BOUNDS.primary_column == "g_fco_standard"
    assert DEFAULT_FILTER_BOUNDS.m_min == 0.0 and not DEFAULT_FILTER_BOUNDS.m_min_inclusive
    assert DEFAULT_FILTER_BOUNDS.m_max == 1.0 and DEFAULT_FILTER_BOUNDS.m_max_inclusive
    assert DEFAULT_FILTER_BOUNDS.omega == (2.0, 25.0)
    assert DEFAULT_FILTER_BOUNDS.damping_min == 0.5
    assert DEFAULT_FILTER_BOUNDS.r2_min is None
    assert DEFAULT_FILTER_BOUNDS.rel_err_max is None
    assert DEFAULT_FILTER_BOUNDS.horizon is None
    assert DEFAULT_SEARCH_BOUNDS.solver == "tcgrid_lm"
    assert DEFAULT_SEARCH_BOUNDS.seed == 0
    assert DEFAULT_SEARCH_BOUNDS.n_random == 10
    assert DEFAULT_SEARCH_BOUNDS.budget_dict == {"n_tc": 40, "n_m": 12, "n_w": 16, "topk": 5}
    lo, hi = DEFAULT_SEARCH_BOUNDS.numeric_bounds(0.0, 10.0)
    np.testing.assert_array_equal(lo, np.asarray([10.001, 0.01, 1.0]))
    np.testing.assert_array_equal(hi, np.asarray([12.0, 2.0, 50.0]))


def test_cache_key_covers_clock_mapping_and_contract_fields():
    args = dict(
        data_hash="a" * 64,
        asof="2024-02-22",
        window_start="2023-11-01",
        window_end="2024-02-22",
        lookback_L=80,
        clock_map=tuple(range(80)),
    )
    key = cache_key(**args)
    assert key == cache_key(**args)
    assert key != cache_key(**{**args, "clock_map": tuple(range(1, 81))})
    altered_search = replace(DEFAULT_SEARCH_BOUNDS, n_random=9)
    assert key != cache_key(**args, search_bounds=altered_search)
