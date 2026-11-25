from research.eval.long_window_pit import classify_verdict


def stat(signal_asofs=10, dd_obs=20, dd_p95=19.9, median_obs=-20.1, median_p5=-20):
    return {
        "signal_asofs": signal_asofs,
        "metrics": {
            "DD120_le_-20": {"obs": dd_obs, "rand_p95": dd_p95},
            "median_DD120": {"obs": median_obs, "rand_p5": median_p5},
        },
    }


def test_passes_at_ten_signals_when_both_strict_metrics_pass():
    assert classify_verdict(stat()) == "pass"


def test_fewer_than_ten_signals_is_insufficient_even_when_metrics_pass():
    assert classify_verdict(stat(signal_asofs=9)) == "insufficient"


def test_metric_thresholds_are_strict():
    assert classify_verdict(stat(dd_obs=19.9, dd_p95=19.9)) == "fail"
    assert classify_verdict(stat(median_obs=-20, median_p5=-20)) == "fail"


def test_either_failed_metric_makes_the_verdict_fail():
    assert classify_verdict(stat(dd_obs=19)) == "fail"
    assert classify_verdict(stat(median_obs=-19)) == "fail"


def test_missing_metrics_at_sufficient_sample_size_is_fail():
    assert classify_verdict({"signal_asofs": 10, "metrics": {}}) == "fail"
