import numpy as np, pandas as pd, os, json
U = "/home/ubuntu/repos/LPPL/data/universe"; S = "/home/ubuntu/repos/LPPL/data/cache/stocks"
PERIODS = {"20100104": ("2010-01-04", "2018-12-27"), "20181228": ("2018-12-28", "2021-12-30"), "20211231": ("2021-12-31", "2099-12-31")}
rows = []
for snap, (lo, hi) in PERIODS.items():
    u = pd.read_csv(f"{U}/csi300_{snap}.csv", dtype=str)
    codes = sorted((u.market.str.lower() + u.code.str.zfill(6)).unique())
    perm = np.random.default_rng(20261117 + int(snap[:4])).permutation(len(codes))
    picked = []
    for r, i in enumerate(perm):
        c = codes[i]; f = f"{S}/{c}.parquet"
        if not os.path.exists(f) or c in [p["code"] for p in rows]:
            continue
        d = pd.read_parquet(f, columns=["date"]).date
        n_in = ((d >= lo) & (d <= hi)).sum()
        if (d < lo).sum() + n_in < 128 + 60 + 63 or n_in < 63 + 60:
            continue
        rows.append({"snapshot": snap, "code": c, "perm_rank": r, "period_lo": lo, "period_hi": hi, "last_date": str(d.max())[:10]})
        picked.append(c)
        if len(picked) == 10: break
pd.DataFrame(rows).to_csv("data/sample_csi300.csv", index=False)
print(pd.DataFrame(rows).to_string())
