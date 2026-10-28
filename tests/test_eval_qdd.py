import numpy as np
import pandas as pd

from research.eval.qdd import fit_quantile, fit_unconditional, pinball


def test_pinball_asymmetry():
    y = np.array([1.0, 1.0])
    q = np.array([0.0, 2.0])
    assert np.allclose(pinball(y, q), [0.9, 0.1])


def test_quantile_fit_recovers_conditional_quantile():
    rng = np.random.default_rng(0)
    x = rng.normal(size=4000)
    y = 0.5 * x + rng.normal(size=4000)
    df = pd.DataFrame(dict(x=x, y=y))
    q = fit_quantile(["x"], 1.0)(df, df)
    assert abs(np.mean(y <= q) - 0.9) < 0.03
    assert np.allclose(fit_unconditional(df, df.iloc[:3]), np.quantile(y, 0.9))
