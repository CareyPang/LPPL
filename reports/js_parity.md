# JavaScript / Python LPPLS numerical parity

- Cases: 100 total (60 synthetic, 40 frozen-index windows).
- Analyze fit options: `{"gens": 45, "keepWS": false, "nm": 120, "pop": 24}`; because `power` is not false, the browser also fits the nested power model.
- Critical top-scan options: `{"aheadHi": 120, "aheadLo": 1, "gens": 28, "mHi": 0.99, "mLo": 0.05, "nm": 50, "pop": 18, "power": false, "wHi": 16, "wLo": 3}` (the top rule is declared at `web/app/critical.js:90`, with executable comparisons at lines 91–92; Python `TOP_RULE` is `research/lppls/core.py:91`, and the same criteria are documented at `web/review.html:237`).
- `TOP_RULE` mirrors the critical top scan; it is intentionally distinct from the browser engine's `OD.FILTERS.ds` / `OD.FILTERS.strict` gates.
- Real data: `sh000001`, frozen vintage `v20261024`, log-close windows.
- JavaScript bounds follow `fitWindow`; random fixed-parameter checks use 200 feasible points and four infeasible `tc <= n-1` points per case.

## A. Fixed-parameter linear fit

| Case type | Cases | θ points | Max relative SSE Δ | Max relative β Δ | Infeasible agreement |
| --- | --- | --- | --- | --- | --- |
| synthetic | 60 | 12240 | 4.19e-14 | 9.214e-14 | 1 |
| real | 40 | 8160 | 3.764e-14 | 1.333e-13 | 1 |

Per-case fixed-θ maxima:

| Case | n | θ points | Max relative SSE Δ | Max relative β Δ | Infeasible agreement |
| --- | --- | --- | --- | --- | --- |
| synth_n60_iid_s0.01_seed0 | 60 | 204 | 3.35e-14 | 2.08e-14 | 1 |
| synth_n60_iid_s0.01_seed1 | 60 | 204 | 4.19e-14 | 2.87e-14 | 1 |
| synth_n60_iid_s0.01_seed2 | 60 | 204 | 2.55e-14 | 1.71e-14 | 1 |
| synth_n60_iid_s0.03_seed0 | 60 | 204 | 2.72e-14 | 3.09e-14 | 1 |
| synth_n60_iid_s0.03_seed1 | 60 | 204 | 1.5e-14 | 2.48e-14 | 1 |
| synth_n60_iid_s0.03_seed2 | 60 | 204 | 2.69e-14 | 3.24e-14 | 1 |
| synth_n60_ar1_s0.01_seed0 | 60 | 204 | 1.55e-14 | 1.84e-14 | 1 |
| synth_n60_ar1_s0.01_seed1 | 60 | 204 | 2.88e-14 | 2.68e-14 | 1 |
| synth_n60_ar1_s0.01_seed2 | 60 | 204 | 2.2e-14 | 2.9e-14 | 1 |
| synth_n60_ar1_s0.03_seed0 | 60 | 204 | 9.78e-15 | 2.18e-14 | 1 |
| synth_n60_ar1_s0.03_seed1 | 60 | 204 | 1.63e-14 | 2.8e-14 | 1 |
| synth_n60_ar1_s0.03_seed2 | 60 | 204 | 1.34e-14 | 3.18e-14 | 1 |
| synth_n125_iid_s0.01_seed0 | 125 | 204 | 1.14e-14 | 2.09e-14 | 1 |
| synth_n125_iid_s0.01_seed1 | 125 | 204 | 2.88e-14 | 4.19e-14 | 1 |
| synth_n125_iid_s0.01_seed2 | 125 | 204 | 1.61e-14 | 3.35e-14 | 1 |
| synth_n125_iid_s0.03_seed0 | 125 | 204 | 1.26e-14 | 2.83e-14 | 1 |
| synth_n125_iid_s0.03_seed1 | 125 | 204 | 1.06e-14 | 3.38e-14 | 1 |
| synth_n125_iid_s0.03_seed2 | 125 | 204 | 1.92e-14 | 1.64e-14 | 1 |
| synth_n125_ar1_s0.01_seed0 | 125 | 204 | 1.12e-14 | 2.8e-14 | 1 |
| synth_n125_ar1_s0.01_seed1 | 125 | 204 | 1.62e-14 | 2.16e-14 | 1 |
| synth_n125_ar1_s0.01_seed2 | 125 | 204 | 3.73e-14 | 4.27e-14 | 1 |
| synth_n125_ar1_s0.03_seed0 | 125 | 204 | 9.02e-15 | 3.81e-14 | 1 |
| synth_n125_ar1_s0.03_seed1 | 125 | 204 | 9.86e-15 | 9.21e-14 | 1 |
| synth_n125_ar1_s0.03_seed2 | 125 | 204 | 8.59e-15 | 2.72e-14 | 1 |
| synth_n250_iid_s0.01_seed0 | 250 | 204 | 1.17e-14 | 2.8e-14 | 1 |
| synth_n250_iid_s0.01_seed1 | 250 | 204 | 1.48e-14 | 4.78e-14 | 1 |
| synth_n250_iid_s0.01_seed2 | 250 | 204 | 1e-14 | 3.44e-14 | 1 |
| synth_n250_iid_s0.03_seed0 | 250 | 204 | 3.6e-15 | 1.48e-14 | 1 |
| synth_n250_iid_s0.03_seed1 | 250 | 204 | 8.71e-15 | 2.54e-14 | 1 |
| synth_n250_iid_s0.03_seed2 | 250 | 204 | 9.53e-15 | 3.93e-14 | 1 |
| synth_n250_ar1_s0.01_seed0 | 250 | 204 | 8.78e-15 | 2.08e-14 | 1 |
| synth_n250_ar1_s0.01_seed1 | 250 | 204 | 1.53e-14 | 2.03e-14 | 1 |
| synth_n250_ar1_s0.01_seed2 | 250 | 204 | 2.06e-14 | 1.89e-14 | 1 |
| synth_n250_ar1_s0.03_seed0 | 250 | 204 | 5.38e-15 | 2.99e-14 | 1 |
| synth_n250_ar1_s0.03_seed1 | 250 | 204 | 8.68e-15 | 5.81e-14 | 1 |
| synth_n250_ar1_s0.03_seed2 | 250 | 204 | 7.54e-15 | 2.54e-14 | 1 |
| synth_n500_iid_s0.01_seed0 | 500 | 204 | 1.62e-14 | 3.76e-14 | 1 |
| synth_n500_iid_s0.01_seed1 | 500 | 204 | 1.23e-14 | 4.19e-14 | 1 |
| synth_n500_iid_s0.01_seed2 | 500 | 204 | 1.39e-14 | 1.24e-14 | 1 |
| synth_n500_iid_s0.03_seed0 | 500 | 204 | 6.79e-15 | 3.61e-14 | 1 |
| synth_n500_iid_s0.03_seed1 | 500 | 204 | 4.31e-15 | 3.7e-14 | 1 |
| synth_n500_iid_s0.03_seed2 | 500 | 204 | 6.41e-15 | 2.33e-14 | 1 |
| synth_n500_ar1_s0.01_seed0 | 500 | 204 | 1.06e-14 | 2.38e-14 | 1 |
| synth_n500_ar1_s0.01_seed1 | 500 | 204 | 1.32e-14 | 2.8e-14 | 1 |
| synth_n500_ar1_s0.01_seed2 | 500 | 204 | 1.8e-14 | 5.66e-14 | 1 |
| synth_n500_ar1_s0.03_seed0 | 500 | 204 | 4.35e-15 | 4.04e-14 | 1 |
| synth_n500_ar1_s0.03_seed1 | 500 | 204 | 6.47e-15 | 6.98e-14 | 1 |
| synth_n500_ar1_s0.03_seed2 | 500 | 204 | 1.08e-14 | 3.05e-14 | 1 |
| synth_n700_iid_s0.01_seed0 | 700 | 204 | 8.19e-15 | 4.99e-14 | 1 |
| synth_n700_iid_s0.01_seed1 | 700 | 204 | 9.74e-15 | 4.7e-14 | 1 |
| synth_n700_iid_s0.01_seed2 | 700 | 204 | 1.04e-14 | 2.76e-14 | 1 |
| synth_n700_iid_s0.03_seed0 | 700 | 204 | 3.75e-15 | 3.59e-14 | 1 |
| synth_n700_iid_s0.03_seed1 | 700 | 204 | 4.5e-15 | 3.34e-14 | 1 |
| synth_n700_iid_s0.03_seed2 | 700 | 204 | 6.93e-15 | 1.68e-14 | 1 |
| synth_n700_ar1_s0.01_seed0 | 700 | 204 | 7.72e-15 | 3.17e-14 | 1 |
| synth_n700_ar1_s0.01_seed1 | 700 | 204 | 8e-15 | 1.89e-14 | 1 |
| synth_n700_ar1_s0.01_seed2 | 700 | 204 | 1.05e-14 | 3.2e-14 | 1 |
| synth_n700_ar1_s0.03_seed0 | 700 | 204 | 7.19e-15 | 2.07e-14 | 1 |
| synth_n700_ar1_s0.03_seed1 | 700 | 204 | 3.39e-15 | 2.81e-14 | 1 |
| synth_n700_ar1_s0.03_seed2 | 700 | 204 | 5.69e-15 | 4.75e-14 | 1 |
| real_2007-12-28_n125 | 125 | 204 | 7.43e-15 | 4.99e-14 | 1 |
| real_2007-12-28_n250 | 250 | 204 | 8.25e-15 | 3.16e-14 | 1 |
| real_2007-12-28_n500 | 500 | 204 | 4.22e-15 | 2.23e-14 | 1 |
| real_2007-12-28_n700 | 700 | 204 | 7.71e-15 | 3.73e-14 | 1 |
| real_2009-10-30_n125 | 125 | 204 | 6.7e-15 | 3.36e-14 | 1 |
| real_2009-10-30_n250 | 250 | 204 | 3.71e-15 | 3.41e-14 | 1 |
| real_2009-10-30_n500 | 500 | 204 | 2.06e-15 | 5.74e-14 | 1 |
| real_2009-10-30_n700 | 700 | 204 | 2.08e-15 | 6.89e-14 | 1 |
| real_2011-10-28_n125 | 125 | 204 | 8.47e-15 | 2.65e-14 | 1 |
| real_2011-10-28_n250 | 250 | 204 | 4.77e-15 | 4.99e-14 | 1 |
| real_2011-10-28_n500 | 500 | 204 | 2.4e-15 | 3.99e-14 | 1 |
| real_2011-10-28_n700 | 700 | 204 | 3.05e-15 | 4.14e-14 | 1 |
| real_2013-12-31_n125 | 125 | 204 | 9.36e-15 | 3.12e-14 | 1 |
| real_2013-12-31_n250 | 250 | 204 | 3.92e-15 | 5.18e-14 | 1 |
| real_2013-12-31_n500 | 500 | 204 | 2.99e-15 | 3.09e-14 | 1 |
| real_2013-12-31_n700 | 700 | 204 | 2.66e-15 | 6.96e-14 | 1 |
| real_2015-06-12_n125 | 125 | 204 | 1.13e-14 | 3.55e-14 | 1 |
| real_2015-06-12_n250 | 250 | 204 | 1e-14 | 3.78e-14 | 1 |
| real_2015-06-12_n500 | 500 | 204 | 2.98e-15 | 3.39e-14 | 1 |
| real_2015-06-12_n700 | 700 | 204 | 5.32e-15 | 5.74e-14 | 1 |
| real_2017-12-29_n125 | 125 | 204 | 3.76e-14 | 5.86e-14 | 1 |
| real_2017-12-29_n250 | 250 | 204 | 1.26e-14 | 6.95e-14 | 1 |
| real_2017-12-29_n500 | 500 | 204 | 5.98e-15 | 4.63e-14 | 1 |
| real_2017-12-29_n700 | 700 | 204 | 3.01e-15 | 5.03e-14 | 1 |
| real_2019-12-31_n125 | 125 | 204 | 1.97e-14 | 1.33e-13 | 1 |
| real_2019-12-31_n250 | 250 | 204 | 4.53e-15 | 4.4e-14 | 1 |
| real_2019-12-31_n500 | 500 | 204 | 3.29e-15 | 2.22e-14 | 1 |
| real_2019-12-31_n700 | 700 | 204 | 2.82e-15 | 5.32e-14 | 1 |
| real_2021-12-31_n125 | 125 | 204 | 2.86e-14 | 3.33e-14 | 1 |
| real_2021-12-31_n250 | 250 | 204 | 1.44e-14 | 3.56e-14 | 1 |
| real_2021-12-31_n500 | 500 | 204 | 5.05e-15 | 3.73e-14 | 1 |
| real_2021-12-31_n700 | 700 | 204 | 4.38e-15 | 4.84e-14 | 1 |
| real_2023-12-29_n125 | 125 | 204 | 2.71e-14 | 1.09e-14 | 1 |
| real_2023-12-29_n250 | 250 | 204 | 1.16e-14 | 2.44e-14 | 1 |
| real_2023-12-29_n500 | 500 | 204 | 6.09e-15 | 4.25e-14 | 1 |
| real_2023-12-29_n700 | 700 | 204 | 3.8e-15 | 8.75e-14 | 1 |
| real_2025-10-24_n125 | 125 | 204 | 3.13e-14 | 3.23e-14 | 1 |
| real_2025-10-24_n250 | 250 | 204 | 1.23e-14 | 4.59e-14 | 1 |
| real_2025-10-24_n500 | 500 | 204 | 4.75e-15 | 5.24e-14 | 1 |
| real_2025-10-24_n700 | 700 | 204 | 4.77e-15 | 3.66e-14 | 1 |

Overall pass: **True** (SSE relative error < 1e-8 when non-tiny; infeasible / `None` agreement 100%).

## B. Derived values and browser filters at the JavaScript optimum

| Cases | Max relative Δ across D/O/R² | DS agreement | Strict agreement | Pass |
| --- | --- | --- | --- | --- |
| 100 | 4.475e-12 | 1 | 1 | True |

Relative differences compare Python `lin_fit` plus the JavaScript formulas for D, O, and R² against the browser fit result.

## C. Full optimization comparison

| Python optimizer | Comparisons | Median SSE ratio−1 | P10 ratio−1 | P90 ratio−1 | Median |Δtc| | Median |Δm| | Median |Δw| | DS agreement | Strict agreement | Median JS sec | Median Python sec |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| de_lbfgsb | 300 | 6.251e-12 | -1.019e-14 | 3.695e-09 | 9.928e-05 | 6.713e-07 | 1.098e-05 | 0.9767 | 0.9967 | 0.1224 | 0.09387 |
| ms_lm | 300 | 2.776e-14 | -1.051e-12 | 0.00782 | 4.777e-06 | 7.561e-08 | 1.098e-06 | 0.9333 | 0.9733 | 0.1224 | 0.05295 |
| tcgrid_lm | 300 | 1.876e-14 | -2.621e-12 | 3.686e-13 | 3.472e-06 | 5.506e-08 | 7.189e-07 | 0.9833 | 1 | 0.1224 | 0.1258 |
| cmaes | 300 | 3.177e-11 | 1.665e-16 | 0.0004374 | 0.0002396 | 1.835e-06 | 2.791e-05 | 0.9567 | 0.9833 | 0.1224 | 0.115 |

Best Python method per JS fit: median SSE ratio `1.0000000000000075` over 300 fits; required ≤ 1 + 1e-6: **True**.

JavaScript Nelder–Mead candidate worse than the DE candidate in 0 fits.

A negative `sse_py/sse_js − 1` means the Python optimizer found a lower SSE. Python optimizer budgets are listed in the JSON report; the browser uses the unmodified analyze options above.
