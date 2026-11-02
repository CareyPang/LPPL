# ruff: noqa: E402, E702, B905, B007
"""3-5 real stocks: load (rate-limited), stk_lite vs stk_full at same asof; per-scale box/standard shares; bound shares;
stock chain (_fit_pairs) vs index chain (daily.fit_asof) on identical windows; PIT check (future bars present vs truncated)."""
import json
import os
import sys
import time

OUT = os.environ.get("AUDIT_OUT", "/home/ubuntu/audit"); os.makedirs(OUT, exist_ok=True)
os.environ.setdefault("LPPLS_BOX", "v2")
import pandas as pd

from research.features.lppls_rules import SCALES_FCO6, _derived, grid_rules, rules
from research.pipeline import daily, stock

codes = sys.argv[1].split(",") if len(sys.argv) > 1 else ["000858", "300750", "601318", "002594"]
asof = pd.Timestamp(sys.argv[2] if len(sys.argv) > 2 else "2025-06-30")
procs = int(sys.argv[3]) if len(sys.argv) > 3 else 3
rows = []
for code in codes:
    t0 = time.time()
    pq = f"{OUT}/{code}_hfq.parquet"
    if os.path.exists(pq):
        ohlc = pd.read_parquet(pq); meta = json.load(open(pq + ".meta.json"))
    else:
        ohlc, dv, meta = stock.load_stock(code)
        ohlc.to_parquet(pq); json.dump({k: str(v) for k, v in meta.items()}, open(pq + ".meta.json", "w")); time.sleep(3)
    full = stock._fit_logp(ohlc)
    avail = full[full.index <= asof]; date = avail.index[-1]
    elig = stock._eligibility(ohlc[ohlc.date <= date].reset_index(drop=True), None)
    print(f"[{code}] n={len(ohlc)} {ohlc.date.min().date()}..{ohlc.date.max().date()} src={meta.get('source')} load {time.time()-t0:.1f}s elig={elig}", flush=True)
    for variant in ("stk_lite", "stk_full"):
        t1 = time.time()
        windows = [n for n in stock._variant_windows(variant, len(avail)) if n <= len(avail)]
        fits = stock._fit_pairs(avail, [(date, n) for n in windows], procs)
        fits = stock._add_y_std(fits, avail)
        d = _derived(fits); r = rules(d); g = grid_rules(d)
        # index-chain consistency on identical windows (serial, same fit_one)
        chk = [daily.fit_asof(avail, date, (n,)) for n in windows[:: max(1, len(windows) // 8)]]
        idx = pd.concat(chk); mg = fits.merge(idx, on="n", suffixes=("", "_idx"))
        cons = max(float((mg[c] - mg[c + "_idx"]).abs().max()) for c in ("tc", "m", "w", "sse"))
        # PIT: fit on the full series (future bars present) at the same as-of
        pit = stock._fit_pairs(full, [(date, n) for n in windows[:: max(1, len(windows) // 8)]], procs)
        mp = fits.merge(pit, on="n", suffixes=("", "_pit"))
        leak = max(float((mp[c] - mp[c + "_pit"]).abs().max()) for c in ("tc", "m", "w", "sse"))
        dt = d.n - 1
        edge = ((d.ahead - (-0.2 * dt)).abs() < 1.0) | ((d.ahead - 0.2 * dt).abs() < 1.0)
        rec = dict(code=code, variant=variant, n_windows=len(windows), secs=round(time.time() - t1, 1), consistency_maxdiff=cons, pit_maxdiff=leak,
                   m_lo=float((d.m <= 0.011).mean()), m_hi=float((d.m >= 1.99).mean()), w_lo=float((d.w <= 1.01).mean()), w_hi=float((d.w >= 49.9).mean()),
                   tc_edge=float(edge.mean()), inside=float((d.ahead <= 0).mean()), r2_med=float(d.r2.median()), relerr_med=float(d.rel_err.median()))
        for sc, (lo, hi) in SCALES_FCO6.items():
            msk = (d.n >= lo) & (d.n <= hi)
            if msk.any():
                rec[f"{sc}:n"] = int(msk.sum()); rec[f"{sc}:box"] = round(float(r.box[msk].mean()), 3); rec[f"{sc}:std"] = round(float(g.g_fco_standard[msk].mean()), 3); rec[f"{sc}:end"] = round(float(g.g_fco_end[msk].mean()), 3)
        rows.append(rec); print("  ", {k: v for k, v in rec.items() if ":" not in k}, flush=True)
        fits.assign(code=code, variant=variant).to_parquet(f"{OUT}/exp6_{code}_{variant}.parquet")
df = pd.DataFrame(rows); df.to_csv(f"{OUT}/exp6_summary.csv", index=False)
pd.set_option("display.width", 250); print(df[[c for c in df.columns if ":" in c or c in ("code", "variant")]].to_string())
