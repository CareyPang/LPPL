# ruff: noqa: E402, E702, B905, B007
"""Does tcgrid_lm's grid stage ever evaluate t_c inside the window when ALLOW_INSIDE=True?"""
import os
import time

OUT = os.environ.get("AUDIT_OUT", "/home/ubuntu/audit"); os.makedirs(OUT, exist_ok=True)
os.environ.setdefault("LPPLS_BOX", "v2")
import numpy as np

from research.lppls import core
from research.optim.optimizers import grid_profile, tcgrid_lm

core.ALLOW_INSIDE = True
n = 250; t = np.arange(n, dtype=float); dt = n - 1
rng = np.random.default_rng(1)
# true tc inside window (tc = t2 - 0.1 dt), m=0.5, w=8, B<0
tc0, m0, w0 = dt - 0.1 * dt, 0.5, 8.0
X = core.design(t, tc0, m0, w0, allow_inside=True)
y = X @ np.array([5.0, -0.03, 0.003, 0.002]) + rng.normal(0, 0.003, n)
lo = np.array([dt - 0.2 * dt, 0.01, 1.0]); hi = np.array([dt + 0.2 * dt, 2.0, 50.0])
tcs = np.linspace(lo[0], hi[0], 40)
g = grid_profile(t, y, tcs, np.linspace(0.01, 2, 12), np.linspace(1, 50, 16))
prof = g.reshape(40, -1).min(axis=1)
print("grid tcs <= t2:", int((tcs <= dt).sum()), " of which finite profile:", int(np.isfinite(prof[tcs <= dt]).sum()))
print("grid tcs > t2:", int((tcs > dt).sum()), " finite:", int(np.isfinite(prof[tcs > dt]).sum()))
for nr in (0, 10):
    t0 = time.time(); r = tcgrid_lm(t, y, lo, hi, seed=0, n_random=nr)
    print(f"n_random={nr}: theta={np.round(r.theta,3)} sse={r.sse:.5f} true tc={tc0:.1f} time={time.time()-t0:.2f}s nfev={r.nfev}")
s_true, _ = core.lin_fit(t, y, tc0, m0, w0)
print("sse at truth:", round(s_true, 5))
