"""Aftershock evidence, archive identity and point-in-time boundaries."""
import hashlib
import json
import math

import numpy as np
import pandas as pd
import pytest

from research.features.aftershock import (
    ARCHIVE_VERSION,
    DAILY_VERSION,
    _daily_omori,
    _daily_productivity,
    _daily_table,
    _episodes,
    analyze_aftershock,
)


def market(n=800):
    rng = np.random.default_rng(7)
    returns = rng.normal(.0003, .006, n)
    for index in range(100, n, 70):
        returns[index] = -.09
    return pd.DataFrame({"date": pd.bdate_range(end="2026-11-20", periods=n).strftime("%Y-%m-%d"),
                         "close": 100*np.exp(np.cumsum(returns))})


def analyze(frame, asof=None, symbol="US_IXIC", archive=None):
    return analyze_aftershock(symbol, frame, asof or frame.date.iloc[-1],
                              {"symbol": symbol, "data_version": "fixture", "source": "synthetic test data"}, archive)


def test_future_append_does_not_change_historical_output():
    data = market()
    prefix = data.iloc[:500]
    asof = prefix.date.iloc[-1]
    before = analyze(prefix, asof)
    future = data.copy()
    future.loc[500:, "close"] *= 1e6
    after = analyze(future, asof)
    assert before == after
    assert all(event["date"] <= asof for event in after["episode_ledger"])


@pytest.mark.parametrize("identity", [{}, {"symbol": "US_NDX"}, {"asset_id": "KR_KOSPI"}])
def test_wrong_or_missing_asset_identity_rejected(identity):
    with pytest.raises(ValueError, match="identity"):
        analyze_aftershock("US_IXIC", market(), "2026-11-20", identity)


def test_mixed_symbol_rows_rejected():
    frame = market()
    frame["symbol"] = "US_NDX"
    with pytest.raises(ValueError, match="different asset"):
        analyze(frame)


@pytest.mark.parametrize("bad", [0., -1., float("nan"), float("inf")])
def test_invalid_prices_are_not_zero_signal(bad):
    frame = market()
    frame.loc[100, "close"] = bad
    with pytest.raises(ValueError, match="positive and finite"):
        analyze(frame)


def test_no_input_and_short_history_do_not_fabricate_parameters():
    for frame in (market(10), pd.DataFrame({"date": [], "close": []})):
        result = analyze(frame, "2026-11-20")
        assert all(m["status"] == "insufficient_data" and m["parameters"] is None for m in result["modules"].values())


def test_constant_prices_are_no_shock_not_infinite_z():
    frame = market()
    frame["close"] = 100.
    result = analyze(frame)
    assert result["current_episode"] is None
    assert result["modules"]["omori"]["status"] == "not_available"
    assert result["modules"]["productivity"]["parameters"] is None


def test_sigma_excludes_current_return():
    frame = market(100)
    data = _daily_table(frame)
    expected = np.log(frame.close).diff().iloc[36:99].std(ddof=1)
    assert data.sigma.iloc[99] == pytest.approx(expected)
    changed = frame.copy()
    changed.loc[99, "close"] *= .1
    assert _daily_table(changed).sigma.iloc[99] == data.sigma.iloc[99]


def test_latest_shock_has_zero_after_days_not_zero_risk():
    frame = market(200)
    frame.loc[199, "close"] = frame.close.iloc[198]*.5
    result = analyze(frame)
    assert result["current_episode"]["observed_after_days"] == 0
    assert result["current_episode"]["mature"] is False
    for name in ("omori", "bath"):
        module = result["modules"][name]
        assert module["status"] == "insufficient_data"
        assert module["parameters"] is None


def test_historical_cooldown_and_pending_events_are_separate():
    data = pd.DataFrame({"date": pd.bdate_range("2025-01-01", periods=100).strftime("%Y-%m-%d"),
                         "close": np.ones(100), "return": np.zeros(100), "sigma": np.ones(100), "z": np.zeros(100)})
    for index in (64, 65, 85, 99):
        data.loc[index, ["return", "z"]] = -4.
    events, current = _episodes(data)
    assert [event["index"] for event in events] == [64, 85]
    assert [event["mature"] for event in events] == [True, False]
    assert current["index"] == 99  # Current risk is not hidden by historical deduplication.
    assert current["observed_after_days"] == 0


def current_episode(counts):
    return {"date": "2026-10-20", "counts": counts, "dates": [str(i) for i in range(len(counts))],
            "observed_after_days": len(counts), "aftershock_count": sum(counts), "mature": len(counts) == 20}


def test_omori_runs_real_bernoulli_fit_when_sample_is_sufficient():
    result = _daily_omori(current_episode([1]*7+[0]*13))
    assert result["status"] == "available"
    assert 0 <= result["parameters"]["p"] <= 3
    assert len(result["parameters"]["predicted_rates"]) == 20
    assert result["parameters"]["optimizer_success"]


def test_no_events_cannot_be_interpreted_as_p_zero_success():
    result = _daily_omori(current_episode([0]*20))
    assert result["status"] == "insufficient_data"
    assert result["parameters"] is None


def productivity_events(n=40):
    rng = np.random.default_rng(32)
    events = []
    for i in range(n):
        magnitude = 3.+(i % 10)/2
        events.append({"date": f"{2015+i//4}-01-01", "year": 2015+i//4, "mature": True,
                       "magnitude_sigma": magnitude, "aftershock_count": int(rng.poisson(1.5*magnitude**.6))})
    return events


def test_productivity_real_fit_with_clustered_interval_and_no_probability():
    result = _daily_productivity(productivity_events(), {"date": "2026-11-20", "magnitude_sigma": 4.})
    assert result["status"] == "available"
    params = result["parameters"]
    assert np.isfinite(params["alpha"])
    assert len(params["alpha_ci95"]) == 2
    assert params["calibrated_probability"] is False
    assert params["expected_20d_events"] > 0


def test_productivity_does_not_train_on_immature_zero_counts():
    events = productivity_events(12)
    events[-1]["mature"] = False
    result = _daily_productivity(events, None)
    assert result["samples"]["mature_events"] == 11
    assert result["samples"]["pending_events"] == 1
    assert result["status"] == "insufficient_data"
    assert result["parameters"] is None


def test_extreme_shock_count_stays_within_the_20_day_horizon():
    result = _daily_productivity(productivity_events(), {"date": "2026-11-20", "magnitude_sigma": 1e15})
    params = result["parameters"]
    assert 0 < params["expected_20d_events"] <= 20
    assert params["current_prediction_status"] == "extrapolation"


def test_productivity_recovers_alpha_from_binomial_counts():
    rng = np.random.default_rng(7)
    events = []
    for i in range(400):
        magnitude = 3.+(i % 20)/4
        prob = 1-np.exp(-0.03*magnitude**1.2)
        events.append({"date": f"{1990+i//12}-01-01", "year": 1990+i//12, "mature": True,
                       "magnitude_sigma": magnitude, "aftershock_count": int(rng.binomial(20, prob))})
    params = _daily_productivity(events, {"date": "2026-11-20", "magnitude_sigma": 4.})["parameters"]
    assert abs(params["alpha"]-1.2) < 0.2
    assert params["alpha_ci95"][0] < 1.2 < params["alpha_ci95"][1]
    assert abs(params["expected_20d_events"]-20*(1-np.exp(-0.03*4**1.2))) < 0.5


def test_binomial_loss_matches_scipy_and_is_finite_at_extreme_rates():
    from scipy.stats import binom

    from research.features.aftershock import _binomial_loss
    y, rate = np.array([0., 3., 20.]), np.array([0.05, 0.2, 1.5])
    expected = -binom.logpmf(y, 20, 1-np.exp(-rate)).sum()
    assert abs(_binomial_loss(y, rate, 20)-expected) < 1e-9
    assert np.isfinite(_binomial_loss(np.array([0., 1.]), np.array([1e-300, 1e3])))
    assert _binomial_loss(np.array([1.]), np.array([0.])) == float("inf")


def test_omori_finds_decay_when_the_first_day_after_the_shock_is_quiet():
    # 上证 2015-06-26 冲击后截至 2015-07-24 的逐日序列
    params = _daily_omori(current_episode([0, 1, 1, 0, 1, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]))["parameters"]
    assert params["amplitude"] > 0.01
    assert params["aic_omori"] < params["aic_constant"]+2


def test_omori_probabilities_stay_between_zero_and_one():
    params = _daily_omori(current_episode([1]*10+[0]*10))["parameters"]
    probabilities = np.asarray(params["predicted_probabilities"])
    assert ((probabilities > 0) & (probabilities < 1)).all()
    assert np.allclose(probabilities, 1-np.exp(-np.asarray(params["predicted_rates"])))


def archive_fixture(tmp_path, frame):
    """Synthetic small protocol fixture, never a scientific result."""
    root = tmp_path/"quake"
    (root/"inputs").mkdir(parents=True)
    latest = {"day": "2026-11-20", "is_negative_mainshock": True, "observed_after_days": 0,
              "expected_20d_events_from_productivity": 4.}
    historical = {"historical_start": "1990-01-01", "historical_end": "2025-12-31", "n_episodes": 52,
                  "n_years": 28, "alpha": .6, "alpha_normal95": [-.1, 1.3], "alpha_cluster_year_se": .35,
                  "intercept": .5, "optimizer_success": True, "mean_aftershock_count": 4.,
                  "larger_aftershock_fraction": .4, "bath_gap_quantiles": [-.2, 0, .1, .2, .3],
                  "prediction_examples": {"latest": latest, "peak": {"is_negative_mainshock": False}}}
    intraday = {"0.95": {"threshold": 3.9, "n_after_days": 33, "latest5_events": 52, "previous5_events": 20,
                         "latest_day_events": 16, "omori": {"p": 0., "c": 1, "decay_identified": False, "optimizer_success": True},
                         "alternative_anchor": "2026-11-05", "alternative_anchor_selection": "retrospective", "alternative_omori": {}, "c_sensitivity": []},
                "normalization": {"current_cutoff": "2026-11-20", "baseline_sessions": 27, "baseline_bars": 702, "bars_per_session": 26}}
    result = {"historical": historical, "intraday": intraday}
    files = {"results.json": json.dumps({"IXIC": result, "NDX": result}),
             "protocol.json": json.dumps({"current_peak": "2026-10-06", "event_quantiles": [.9, .95, .975]}),
             "analyse.py": "# synthetic test fixture, not executed\n", "omori_fit_comparison.csv": "asset,p\nIXIC,0\n"}
    for asset in ("IXIC", "NDX"):
        files[f"{asset}_daily_summary.json"] = json.dumps({"asset": asset, "latest": "2026-11-20", "worst_day": "2026-11-05",
            "worst_return_percent": -5., "bath_observation_tail": 11, "bath_gap_since_largest_decline_so_far": .02,
            "latest_relative_to_previous_largest": .95})
        files[f"inputs/{asset}_daily.csv"] = frame.to_csv(index=False, float_format="%.17g")
        files[f"inputs/{asset}_15m.csv"] = "date,close\n2026-11-20,1\n"
    hashes = {}
    for name, content in files.items():
        (root/name).write_text(content, encoding="utf-8")
        hashes[name] = hashlib.sha256((root/name).read_bytes()).hexdigest()
    (root/"manifest.json").write_text(json.dumps({"completed": True, "latest": "2026-11-20", "files": hashes}), encoding="utf-8")
    return root


def test_archive_real_fields_do_not_confuse_peak_with_negative_shock(tmp_path):
    frame = market(300)
    root = archive_fixture(tmp_path, frame)
    result = analyze(frame, archive=root)
    assert result["method_version"] == ARCHIVE_VERSION
    assert result["archive_reuse"]["matching_close_rows"] == 300
    omori = result["modules"]["omori"]
    assert omori["anchor_date"] == "2026-10-06"
    assert omori["mainshock_date"] == "2026-11-20"
    assert omori["anchor_is_negative_mainshock"] is False
    assert omori["samples"]["latest_mainshock_after_days"] == 0
    assert omori["parameters"]["p"] == 0
    assert omori["current_mainshock"]["status"] == "insufficient_data"
    assert result["modules"]["productivity"]["parameters"]["alpha_interval_includes_zero"]
    json.dumps(result, allow_nan=False)


def test_archive_hash_tamper_falls_back_to_daily(tmp_path):
    frame = market(300)
    root = archive_fixture(tmp_path, frame)
    (root/"analyse.py").write_text("changed", encoding="utf-8")
    result = analyze(frame, archive=root)
    assert result["method_version"] == DAILY_VERSION
    assert result["archive_reuse"]["status"] == "rejected"
    assert "hash verification failed" in result["archive_reuse"]["reason"]


def test_archive_different_asset_cannot_fallback_to_nasdaq(tmp_path):
    frame = market(300)
    root = archive_fixture(tmp_path, frame)
    result = analyze(frame, symbol="US_MRVL", archive=root)
    assert result["symbol"] == "US_MRVL"
    assert result["method_version"] == DAILY_VERSION
    assert result["archive_reuse"]["status"] == "rejected"


def test_current_archive_never_fills_historical_cutoff(tmp_path):
    frame = market(300)
    root = archive_fixture(tmp_path, frame)
    result = analyze(frame, asof="2026-11-19", archive=root)
    assert result["method_version"] == DAILY_VERSION
    assert result["asof"] == "2026-11-19"
    assert result["data_asof"] == "2026-11-19"
    assert result["archive_reuse"]["status"] == "rejected"


def test_archive_source_revision_not_silently_reused(tmp_path):
    frame = market(300)
    root = archive_fixture(tmp_path, frame)
    frame.loc[100, "close"] = math.nextafter(frame.close.iloc[100], math.inf)
    result = analyze(frame, archive=root)
    assert result["method_version"] == DAILY_VERSION
    assert "input mismatch" in result["archive_reuse"]["reason"]


def test_archive_future_training_is_rejected_even_with_valid_file_hash(tmp_path):
    frame = market(300)
    root = archive_fixture(tmp_path, frame)
    payload = json.loads((root/"results.json").read_text())
    payload["IXIC"]["historical"]["historical_end"] = "2027-12-31"
    (root/"results.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest = json.loads((root/"manifest.json").read_text())
    manifest["files"]["results.json"] = hashlib.sha256((root/"results.json").read_bytes()).hexdigest()
    (root/"manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = analyze(frame, archive=root)
    assert result["method_version"] == DAILY_VERSION
    assert "beyond requested cutoff" in result["archive_reuse"]["reason"]
