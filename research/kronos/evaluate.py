"""Score run.py outputs vs RW/HB baselines. Usage: evaluate.py OUTDIR [h]"""
import sys, os, glob, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run

def crps(samples, y):
    s = np.sort(np.asarray(samples, float)); n = len(s)
    return np.mean(np.abs(s - y)) - np.sum((2 * np.arange(1, n + 1) - n - 1) * s) / n**2

def crps_normal(sig, y):
    from math import erf, sqrt, pi, exp
    z = y / sig; Phi = 0.5 * (1 + erf(z / sqrt(2))); phi = exp(-z * z / 2) / sqrt(2 * pi)
    return sig * (z * (2 * Phi - 1) + 2 * phi - 1 / sqrt(pi))

def baselines(p, c, h):
    lr = np.log(p.close.values[: c + 1])
    d1 = np.diff(lr[-251:]); sig = d1.std(ddof=1) * np.sqrt(h)
    w = lr[max(0, c - 750): c + 1]; hb = w[h:] - w[:-h]
    return sig, hb

def score(outdir, h):
    recs = [json.loads(l) for f in sorted(glob.glob(f"{outdir}/*.jsonl")) for l in open(f)]
    assets = {a["asset"]: a for a in pd.read_csv(os.path.join(run.HERE, "assets.csv")).to_dict("records")}
    cache, rows = {}, []
    for r in recs:
        if f"k{h}" not in r: continue
        a = assets[r["asset"]]
        if r["asset"] not in cache: cache[r["asset"]] = run.load(a)
        p = cache[r["asset"]]; c = int(np.flatnonzero(p.date.dt.strftime("%Y-%m-%d").values == r["cutoff"])[0])
        y = r[f"r{h}"]; k = np.asarray(r[f"k{h}"])
        sig, hb = baselines(p, c, h)
        q = lambda x, a: np.quantile(x, a)
        rows.append(dict(asset=r["asset"], group=r["group"], kind=r["kind"], split=r["split"], cutoff=r["cutoff"],
            cfg=f'{r["model"].split("-")[1]}-{r["lookback"]}-{r["samples"]}', y=y,
            crps_k=crps(k, y), crps_rw=crps_normal(sig, y), crps_hb=crps(hb, y),
            cov60_k=q(k, .2) <= y <= q(k, .8), cov90_k=q(k, .05) <= y <= q(k, .95),
            cov60_rw=-0.8416 * sig <= y <= 0.8416 * sig, cov60_hb=q(hb, .2) <= y <= q(hb, .8),
            dir_k=np.sign(np.median(k)) == np.sign(y), up=y > 0,
            q20_k=q(k, .2), q20_rw=-0.8416 * sig, width_k=q(k, .8) - q(k, .2), width_rw=2 * 0.8416 * sig))
    return pd.DataFrame(rows)

def block_ci(df, col, n=2000, seed=0):
    m = df.assign(month=df.cutoff.str[:7]).groupby("month")[col].agg(["sum", "count"])
    rng = np.random.default_rng(seed); idx = rng.integers(0, len(m), (n, len(m)))
    s, c = m["sum"].values[idx].sum(1), m["count"].values[idx].sum(1)
    return np.quantile(s / c, [0.025, 0.975])

if __name__ == "__main__":
    outdir = sys.argv[1]; h = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    df = score(outdir, h)
    df["d_rw"], df["d_hb"] = df.crps_k - df.crps_rw, df.crps_k - df.crps_hb
    g = df.groupby(["cfg", "kind", "split"])
    print(g.agg(n=("y", "size"), crps_k=("crps_k", "mean"), crps_rw=("crps_rw", "mean"), crps_hb=("crps_hb", "mean"),
                cov60_k=("cov60_k", "mean"), cov60_rw=("cov60_rw", "mean"), cov60_hb=("cov60_hb", "mean"),
                cov90_k=("cov90_k", "mean"), dir_k=("dir_k", "mean"), up=("up", "mean")).round(4).to_string())
    for key, sub in g:
        print(key, "d_rw CI", block_ci(sub, "d_rw").round(5), "d_hb CI", block_ci(sub, "d_hb").round(5))
    df.to_csv(os.path.join(outdir, f"scored_h{h}.csv"), index=False)
