"""H3：在 H2（同深度相似事件的首次触及频率）上按 Markov 波动体制分组是否改进。
p_hi 用截至信号日的后复权日线、最近 260 周周收益两状态 MarkovRegression 的滤波概率（与面板 _regime 相同，PIT）。
H3 模型 = 只用与测试事件同体制（p_hi≥0.5 / <0.5）的参考事件；同体制参考 <30 个时退回 H2。Δ = Brier(H2) − Brier(H3)。"""

import argparse
import json
import logging
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from research.dip import events, panel

DEFAULT_LIB_DIR = Path("/home/ubuntu/dd_study/lib_full")
DEFAULT_CACHE_DIR = Path("/home/ubuntu/dd_study/cache_all")
DEFAULT_OUT_DIR = Path("/home/ubuntu/dd_study/oos/h3")
TEST0 = "2019-01-01"
MIN_REF = 30
B = 2000


def phi(args):
    sym, dates, cache_dir = args
    logging.disable(logging.WARNING)
    data = events.load(cache_dir / f"{sym}.parquet")
    data["date"] = pd.to_datetime(data["date"])
    out = []
    for date in dates:
        regime = panel._regime(data[data.date <= date][["date", "close"]])
        out.append((sym, date, regime["p_hi_filtered"]))
    return out


def main():
    parser = argparse.ArgumentParser(description="Run the H3 Markov-regime OOS test")
    parser.add_argument("--lib-dir", type=Path, default=DEFAULT_LIB_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    warnings.filterwarnings("ignore")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    events_frame = pd.read_parquet(args.lib_dir / "events.parquet")
    phi_cache = args.out_dir / "phi.parquet"
    if not phi_cache.exists():
        jobs = [
            (sym, sorted(group.sig_date.unique()), args.cache_dir)
            for sym, group in events_frame.groupby("sym")
        ]
        rows = []
        with ProcessPoolExecutor(8) as executor:
            for index, result in enumerate(executor.map(phi, jobs, chunksize=4)):
                rows += result
                if index % 200 == 0:
                    print(index, len(jobs), flush=True)
        pd.DataFrame(rows, columns=["sym", "sig_date", "p_hi"]).to_parquet(phi_cache)
    probabilities = pd.read_parquet(phi_cache)
    events_frame = events_frame.merge(
        probabilities, on=["sym", "sig_date"], how="left"
    )
    events_frame["hi"] = events_frame.p_hi >= 0.5
    pools = {
        "全市场": pd.Series(True, index=events_frame.index),
        "剔除2015-16": ~events_frame.sig_date.str[:4].isin(["2015", "2016"]),
    }
    results, rng = [], np.random.default_rng(20261104)
    for label, mask in pools.items():
        pool = events_frame[mask]
        rows = []
        for test_event in events_frame[
            (events_frame.entry_date >= TEST0) & events_frame.p_hi.notna()
        ].itertuples():
            references = pool[pool.depth == test_event.depth]
            for key in ("fh60", "fh120"):
                outcome = getattr(test_event, key)
                if outcome is None or pd.isna(outcome):
                    continue
                reference = references[
                    references[key + "_known"] < test_event.entry_date
                ]
                if len(reference) < MIN_REF:
                    continue
                subset = reference[reference.hi == test_event.hi]
                observed = np.array(
                    [outcome == category for category in ("U", "L", "none")],
                    float,
                )
                p2 = np.array(
                    [
                        (reference[key] == category).mean()
                        for category in ("U", "L", "none")
                    ]
                )
                p3 = (
                    np.array(
                        [
                            (subset[key] == category).mean()
                            for category in ("U", "L", "none")
                        ]
                    )
                    if len(subset) >= MIN_REF
                    else p2
                )
                rows.append(
                    {
                        "test": "H3_" + key,
                        "depth": test_event.depth,
                        "entry": test_event.entry_date,
                        "hi": bool(test_event.hi),
                        "n_sub": len(subset),
                        "d": ((p2 - observed) ** 2).sum()
                        - ((p3 - observed) ** 2).sum(),
                    }
                )
        frame = pd.DataFrame(rows)
        frame["month"] = frame.entry.str[:7]
        frame["year"] = frame.entry.str[:4]
        for (test_name, depth), group in frame.groupby(["test", "depth"]):
            months = group.month.unique()
            by_month = {
                month: group.loc[group.month == month, "d"].to_numpy()
                for month in months
            }
            bootstrap = [
                np.concatenate(
                    [by_month[month] for month in rng.choice(months, len(months))]
                ).mean()
                for _ in range(B)
            ]
            years = group[group.year <= "2025"].groupby("year").d.mean()
            low, high = np.quantile(bootstrap, [0.05, 0.95])
            results.append(
                {
                    "pool": label,
                    "test": test_name,
                    "depth": depth,
                    "n": len(group),
                    "share_hi": float(group.hi.mean()),
                    "n_months": len(months),
                    "delta": float(group.d.mean()),
                    "ci90": [float(low), float(high)],
                    "years_pos": int((years > 0).sum()),
                    "years": len(years),
                    "passed": bool(low > 0 and (years > 0).sum() >= 5),
                }
            )
    missing = int(events_frame.p_hi.isna().sum())
    (args.out_dir / "h3.json").write_text(
        json.dumps(
            {
                "definition": __doc__,
                "phi_missing": missing,
                "results": results,
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    frame = pd.DataFrame(results)
    print("p_hi missing", missing)
    print(frame.to_string(index=False))


if __name__ == "__main__":
    main()
