# ruff: noqa: E402, E702, B905, B007
"""Real-stock checks on cached 600519 HFQ: (a) predict() == fit_asof on PIT series; (b) no look-ahead: truncating future bars leaves fits identical;
(c) stk_lite vs stk_full window grids; (d) stock chain vs index chain (daily.fit_asof) same windows -> identical rows; (e) boundary-hitting shares."""
import os
import sys
import time

OUT = os.environ.get("AUDIT_OUT", "/home/ubuntu/audit"); os.makedirs(OUT, exist_ok=True)
os.environ.setdefault("LPPLS_BOX", "v2")
import numpy as np
import pandas as pd

from research.features.lppls_rules import SCALES_FCO6, _derived, grid_rules, rules
from research.lppls import core
from research.pipeline import daily, stock, universe

ohlc = pd.read_parquet(f"{OUT}/600519_hfq.parquet")
meta = {"ipo_in_range": True, "source": "tencent_fqkline", "dropped_unclosed_bar": False, "reference_cutoff": pd.Timestamp("2026-11-02")}
stock.load_stock = lambda code, start=None: (ohlc.copy(), "vintage_test", dict(meta))
stock._trading_days_stale = lambda *a, **k: (0, None)
asof = sys.argv[1] if len(sys.argv) > 1 else "2025-06-30"
procs = 4
t0 = time.time()
rec = stock.predict("600519", "stk_lite", asof=asof, procs=procs)
print("predict stk_lite", round(time.time() - t0, 1), "s; asof", rec["asof"], "conf", rec["top"]["lppls_confidence"]["6-12m"], rec["top"]["lppls_confidence"]["12-24m"], "status", rec["stock_meta"]["status"])
# (a)/(d) same windows via daily.fit_asof on PIT logp
logp = stock._fit_logp(ohlc); date = logp.index[logp.index <= pd.Timestamp(asof)][-1]
core.ALLOW_INSIDE = True
d_idx = daily.fit_asof(logp[logp.index <= date], date, tuple(universe.WINDOWS))
fits_stock = stock._fit_pairs(logp[logp.index <= date], [(date, n) for n in universe.WINDOWS], procs)
diff = (d_idx[["tc", "m", "w", "sse"]].to_numpy() - fits_stock[["tc", "m", "w", "sse"]].to_numpy())
print("(d) stock _fit_pairs vs daily.fit_asof max abs diff:", np.abs(diff).max())
# (b) look-ahead: full series (future bars present) vs truncated series
fits_full = stock._fit_pairs(logp, [(date, n) for n in universe.WINDOWS], procs)
print("(b) PIT: fits with future bars present vs truncated max abs diff:", np.abs(fits_full[["tc","m","w","sse"]].to_numpy() - fits_stock[["tc","m","w","sse"]].to_numpy()).max())
# (c) window grids
lite = set(stock._variant_windows("stk_lite", len(logp))); full = set(stock._variant_windows("stk_full", len(logp)))
print("(c) stk_lite windows", sorted(lite)); print("    overlap with stk_full:", sorted(lite & full), "| stk_full count", len(full))
for sc, (lo, hi) in SCALES_FCO6.items():
    print(f"    {sc}: lite {sum(lo<=n<=hi for n in lite)} windows, full {sum(lo<=n<=hi for n in full)} windows")
# (e) boundaries on stk_full at this asof
t0 = time.time()
fits_f = stock._fit_pairs(logp[logp.index <= date], [(date, n) for n in sorted(full)], procs)
print("stk_full fits", len(fits_f), round(time.time() - t0, 1), "s")
d = _derived(fits_f); r = rules(d); g = grid_rules(d)
print("(e) m<=0.011:", (d.m <= 0.011).mean().round(3), " m>=1.99:", (d.m >= 1.99).mean().round(3), " w<=1.01:", (d.w <= 1.01).mean().round(3), " w>=49.9:", (d.w >= 49.9).mean().round(3),
      " |ahead|>=0.2dt-1:", (d.ahead.abs() >= 0.2 * d.dt - 1).mean().round(3), " m>1:", (d.m > 1).mean().round(3))
d["standard"] = g.g_fco_standard; d["box"] = r.box
for sc, (lo, hi) in SCALES_FCO6.items():
    m = d.n.between(lo, hi)
    if m.any():
        print(f"    {sc}: n={m.sum()} box={d.box[m].mean():.3f} standard={d.standard[m].mean():.3f} r2_med={d.r2[m].median():.3f} m_med={d.m[m].median():.2f} w_med={d.w[m].median():.1f} rel_err_med={d.rel_err[m].median():.3f}")
fits_f.to_parquet(f"{OUT}/600519_full_{asof}.parquet")
# rel_err check on tiny windows: n=10..20
tiny = d[d.n <= 20]
print("tiny windows (10-20): r2 med", tiny.r2.median().round(3), "standard share", tiny.standard.mean().round(3), "osc med", tiny.osc.median().round(2))
