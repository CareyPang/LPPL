"""Kronos rolling zero-shot backtest. Usage: run.py PHASE SHARD NSHARDS OUTDIR   (PHASE in dev|final)"""
import sys, os, json, hashlib, time
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
HS = (12, 20, 60)
DEV_END, CAL_END, START = pd.Timestamp("2017-12-31"), pd.Timestamp("2021-12-31"), pd.Timestamp("2000-01-01")
MAX_LB, MAX_H = 128, 60

def split_of(d):
    return "dev" if d <= DEV_END else "cal" if d <= CAL_END else "test"

def load(asset):
    """asset row -> DataFrame date, open, high, low, close, volume(, amount); stocks back-adjusted by hfq_factor."""
    p = pd.read_parquet(os.path.join(DATA, asset["file"]))
    p["date"] = pd.to_datetime(p["date"])
    if asset["kind"] == "stock":
        for c in ("open", "high", "low", "close"):
            p[c] = p[c] * p["hfq_factor"]
        p = p[(p.volume > 0) & p[["open", "high", "low", "close"]].notna().all(axis=1)]
    return p.sort_values("date").reset_index(drop=True)

def cutoffs(asset, p):
    """Indices of cutoff bars (last bar used as input). Stepping is on the asset's own trading rows."""
    lo = max(START, pd.Timestamp(asset["period_lo"])); hi = pd.Timestamp(asset["period_hi"])
    out, i = [], MAX_LB
    while i + MAX_H < len(p):
        d = p.date[i - 1]
        if lo <= d <= hi:
            step = asset["step_dev"] if split_of(d) == "dev" else asset["step_final"]
            out.append(i - 1); i += step
        else:
            i += 1
    return out

def tasks(phase):
    assets = pd.read_csv(os.path.join(HERE, "assets.csv")).to_dict("records")
    for a in assets:
        p = load(a)
        for c in cutoffs(a, p):
            s = split_of(p.date[c])
            if (phase == "dev") != (s == "dev"):
                continue
            if phase == "final" and a["group"] == "stock_current" and s != "test":
                continue
            yield a, p, c, s

def configs(phase, kind):
    if phase == "dev":
        cs = [(m, lb, 30, 20) for m in ("Kronos-small", "Kronos-base") for lb in (40, 128)]
        if kind == "index":
            cs.append(("Kronos-small", 128, 100, 20))
        return cs
    sel = json.load(open(os.path.join(HERE, "selected.json")))
    cs = [(sel["model"], sel["lookback"], sel["samples"], 60)]
    if cs[0][:3] != ("Kronos-small", 128, 30):
        cs.append(("Kronos-small", 128, 30, 60))
    return cs

def main():
    phase, shard, nsh, outdir = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    from kronos_paths import Sampler
    samplers = {}
    os.makedirs(outdir, exist_ok=True)
    out = open(os.path.join(outdir, f"{phase}_{shard:03d}.jsonl"), "w")
    for a, p, c, s in tasks(phase):
        key = f"{a['asset']}|{p.date[c].date()}"
        if int(hashlib.md5(key.encode()).hexdigest(), 16) % nsh != shard:
            continue
        last = float(p.close[c])
        for model, lb, ns, plen in configs(phase, a["kind"]):
            if model not in samplers:
                samplers[model] = Sampler(model)
            hist, fut = p.iloc[c - lb + 1: c + 1], p.iloc[c + 1: c + 1 + plen]
            assert hist.date.max() < fut.date.min() and len(hist) == lb and len(fut) == plen
            seed = int(hashlib.md5((key + model).encode()).hexdigest(), 16) % 2**31
            t = time.time()
            z = Sampler.paths(samplers[model], hist, hist.date, fut.date, ns, seed=seed)
            rec = {"asset": a["asset"], "group": a["group"], "kind": a["kind"], "cutoff": str(p.date[c].date()),
                   "split": s, "model": model, "lookback": lb, "samples": ns, "secs": round(time.time() - t, 2), "last": last}
            for h in HS:
                if h <= plen:
                    rec[f"r{h}"] = float(np.log(p.close[c + h] / last))
                    rec[f"k{h}"] = np.round(np.log(np.maximum(z[:, h - 1, 3], 1e-9) / last), 6).tolist()
            out.write(json.dumps(rec) + "\n"); out.flush()
    out.close()

if __name__ == "__main__":
    main()
