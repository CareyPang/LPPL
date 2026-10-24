import shutil

import pytest

from research.lppls.js_compat import JS_DS, JS_STRICT, fit_window
from research.lppls.parity import derived_check, fixed_theta_check, run_harness
from research.synth.lppls_synth import sample

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not on PATH")


def test_fixed_theta_parity_on_small_synthetic_cases():
    cases = (
        sample(n=60, sigma=0.01, noise="iid", seed=3)[1],
        sample(n=125, sigma=0.02, noise="ar1", seed=5)[1],
        sample(n=250, sigma=0.03, noise="iid", seed=7)[1],
    )
    for index, y in enumerate(cases):
        result = fixed_theta_check(y, case_seed=900 + index, n_random=200)
        assert result["max_relative_sse"] < 1e-8
        assert result["infeasible_agreement"] == 1


def test_derived_and_filter_parity_at_js_optimum():
    y = sample(n=60, sigma=0.01, noise="iid", seed=13)[1]
    js_fit = run_harness(
        {"type": "fitwindow", "cases": [{"y": y.tolist(), "seed": 0}]}
    )["results"][0]
    result = derived_check(y, js_fit)
    assert result["max_relative_error"] < 1e-8
    assert result["ds_agreement"]
    assert result["strict_agreement"]


def test_js_strict_filter_uses_strict_bounds():
    base = {
        "B": -1,
        "m": 0.1,
        "w": 7,
        "ahead": 90,
        "O": 2.5,
        "D": 1,
        "R2": 0.9,
        "n": 100,
    }
    assert not JS_STRICT(base)
    assert JS_STRICT({**base, "m": 0.5})
    assert not JS_STRICT({**base, "m": 0.5, "w": 6})
    assert not JS_STRICT({**base, "m": 0.5, "w": 13})


def test_js_ds_filter_includes_configured_boundaries():
    base = {
        "B": -1,
        "m": 0.01,
        "w": 2,
        "ahead": 5,
        "O": 2.5,
        "D": 0.5,
        "R2": 0.5,
        "n": 50,
    }
    assert JS_DS(base)
    assert not JS_DS({**base, "ahead": 5.01})


@pytest.mark.parametrize(
    ("method", "budget"),
    [
        ("de_lbfgsb", {"popsize": 3, "maxiter": 3}),
        ("ms_lm", {"starts": 1}),
        ("tcgrid_lm", {"n_tc": 4, "n_m": 4, "n_w": 4, "topk": 1}),
        ("cmaes", {"maxfevals": 60, "restarts": 0}),
    ],
)
def test_python_nested_power_fit_uses_two_parameter_optimizer(method, budget):
    y = sample(n=60, sigma=0.01, noise="iid", seed=17)[1]
    fit = fit_window(y, {"power": True}, method=method, seed=0, budget=budget)
    assert fit["ssePow"] >= fit["sse"]
