"""§22.1.1：用更正后的偏移集（lppls_scan.q3_shifts）重算已有 `lppls_v2_g3q3` 分片的 q3_p；`_g3` 拟合列不动。
只重算 q3_p 非空（即过 box）的行；旧值另存 <file>.q3_old.csv 供审计。需 LPPLS_BOX=v2 LPPLS_G3=1 LPPLS_Q3=20。
用法：PYTHONPATH=. python scripts/audit_stock_math/exp20_q3_recompute.py <procs> <parquet>..."""
from __future__ import annotations

import os
import sys
from multiprocessing import Pool

os.environ.setdefault("LPPLS_BOX", "v2")
os.environ["LPPLS_G3"] = "1"
os.environ.setdefault("LPPLS_Q3", "20")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from research.features import lppls_scan as L  # noqa: E402
from research.lppls import core  # noqa: E402

_LP: dict[str, np.ndarray] = {}
_POS: dict[str, dict] = {}


def _init():
    core.ALLOW_INSIDE = True


def _series(sym):
    if sym not in _LP:
        s = L.price_series(sym)
        _LP[sym] = s.to_numpy()
        _POS[sym] = {d: i for i, d in enumerate(s.index)}
    return _LP[sym], _POS[sym]


def _one(args):
    sym, date, n, row = args
    lp, pos = _series(sym)
    e = pos[pd.Timestamp(date)]
    y = lp[e + 1 - n : e + 1]
    bx = L.BOXES[L.BOX]
    dt = n - 1
    tc_lo = bx["tc"][0]
    ahead_hi = 0.2 * dt if bx.get("tc_cap") is None else min(0.2 * dt, bx["tc_cap"])
    lo = np.array([dt + (tc_lo if tc_lo >= 0.5 else tc_lo * dt), bx["m"][0], bx["w"][0]])
    hi = np.array([dt + ahead_hi, bx["m"][1], bx["w"][1]])
    n_random = 3 if L.WINDOWS_MODE == "lite" else bx["n_random"]
    return L._q3_p(y, row, lo, hi, n_random)


def main(procs: int, *files: str) -> None:
    for f in files:
        sym = os.path.basename(f).split("__")[0].split(".")[0]
        df = pd.read_parquet(f)
        msk = df.q3_p.notna().to_numpy()
        df.loc[msk, ["date", "n", "q3_p"]].to_csv(f + ".q3_old.csv", index=False)
        fit_cols = L.COLS[1 : L.COLS.index("g3_src")]
        tasks = [(sym, r.date, int(r.n), tuple(float(getattr(r, c)) for c in fit_cols)) for r in df[msk].itertuples(index=False)]
        with Pool(procs, initializer=_init) as p:
            vals = p.map(_one, tasks, chunksize=4)
        df.loc[msk, "q3_p"] = vals
        df.to_parquet(f, index=False)
        print(f"{f}: recomputed {len(vals)}; pass≤0.10 {int((np.array(vals) <= 0.10).sum())}", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]), *sys.argv[2:])
