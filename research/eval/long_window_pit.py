"""Score PIT long-window replay signals against realized tops, with random-date baselines.
Rules fixed before looking at outcomes:
 eligibility = Codex long_horizon summarize_windows (both seeds pass, interior, seed gap<=2), rule cycles_1_5 (primary) / cycles_2_5.
 arms: w925, long_900 (any of 900/925/950), w6600, ultra_6600 (any of 6500/6600/6700), cross (long_900 & ultra_6600 points within 5 sessions).
 signal point ahead = mean of eligible member points (sessions after asof).
 outcomes (need i+230 <= last, else live):
   DD120  = min(C[i+1..i+120])/C[i]-1
   peak   = argmax C[i..i+110]; peak_dd = min(C[peak+1..peak+120])/C[peak]-1
   top_hit = peak_dd <= -15% and |peak-(i+ahead)| <= 20
 baseline: same symbol, all scored asofs; 2000 draws of equal size w/o replacement; ahead drawn from the arm's own aheads.
 episodes: signal asofs <=30 sessions apart merge; first asof of each episode is the episode signal.
"""

import argparse
import collections
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.data.global_terminal import load_cached_snapshot  # noqa: E402
from research.lppls import frozen_v2588 as K  # noqa: E402
from research.pipeline.global_terminal import clean  # noqa: E402
from research.pipeline.long_horizon import SEEDS, WINDOWS, summarize_windows  # noqa: E402

DEFAULT_SOURCE_ROOT = Path("/home/ubuntu/work/global-full")
DEFAULT_FITS_DIR = Path("/home/ubuntu/work/long925/roll")
DEFAULT_OUT = REPO_ROOT / "reports" / "long_window_pit.json"
ASSETS = ("US_IXIC", "US_NDX")
RULES = ("cycles_1_5", "cycles_2_5")
SEED = 20261124
STEP = 10
FIT_ROOT = DEFAULT_SOURCE_ROOT
FIT_OUT = DEFAULT_FITS_DIR
FIT_FRAMES = {}


def _fit_worker_init(source_root, fits_dir):
    global FIT_ROOT, FIT_OUT, FIT_FRAMES
    FIT_ROOT = Path(source_root)
    FIT_OUT = Path(fits_dir)
    FIT_FRAMES = {}


def _fit_close(symbol):
    if symbol not in FIT_FRAMES:
        frame, _ = load_cached_snapshot(symbol, FIT_ROOT)
        FIT_FRAMES[symbol] = (
            np.log(frame.close.to_numpy(float)),
            [str(value.date()) for value in frame.date],
        )
    return FIT_FRAMES[symbol]


def _fit_job(task):
    symbol, index, window, seed = task
    values, dates = _fit_close(symbol)
    path = FIT_OUT / f"{symbol}_{dates[index]}_{window}_{seed}.json"
    if path.exists():
        return None
    started = time.time()
    try:
        fit = K.fit_one(values[index - window + 1 : index + 1], seed)
        fit = {
            key: fit[key]
            for key in (
                "x",
                "beta",
                "sse",
                "r2",
                "damping",
                "nosc",
                "rank",
                "condition",
                "optimizer_success",
                "boundary_status",
            )
        }
        result = {
            "symbol": symbol,
            "asof": dates[index],
            "i": index,
            "n": window,
            "seed": seed,
            "status": "complete",
            "fit": fit,
        }
    except Exception as error:
        result = {
            "symbol": symbol,
            "asof": dates[index],
            "i": index,
            "n": window,
            "seed": seed,
            "status": "failed",
            "error": repr(error),
        }
    result["seconds"] = time.time() - started
    path.write_text(json.dumps(clean(result)), encoding="utf-8")
    return None


def fit_replay(source_root, fits_dir, step=STEP, workers=1):
    """PIT rolling replay of the frozen V2588 long-window protocol (Codex long_horizon rules).
    Every `step` sessions, fit each window on the prefix ending at asof (no future data)."""
    source_root = Path(source_root)
    fits_dir = Path(fits_dir)
    fits_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for symbol in ASSETS:
        frame, _ = load_cached_snapshot(symbol, source_root)
        values = frame.close.to_numpy(float)
        last = len(values) - 1
        indices = list(range(last, -1, -step))[::-1]
        for index in indices:
            for window in WINDOWS:
                if index - window + 1 >= 0:
                    for seed in SEEDS:
                        tasks.append((symbol, index, window, seed))
    print("tasks", len(tasks), flush=True)
    done = 0
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_fit_worker_init,
        initargs=(str(source_root), str(fits_dir)),
    ) as executor:
        futures = [executor.submit(_fit_job, task) for task in tasks]
        for future in as_completed(futures):
            future.result()
            done += 1
            if done % 2000 == 0:
                print("done", done, flush=True)
    print("finished", flush=True)


def classify_verdict(stat):
    signal_asofs = stat.get("signal_asofs", 0)
    if not isinstance(signal_asofs, int) or signal_asofs < 10:
        return "insufficient"
    metrics = stat.get("metrics") or {}
    dd = metrics.get("DD120_le_-20") or {}
    median = metrics.get("median_DD120") or {}
    values = (dd.get("obs"), dd.get("rand_p95"), median.get("obs"), median.get("rand_p5"))
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in values):
        return "fail"
    if dd["obs"] > dd["rand_p95"] and median["obs"] < median["rand_p5"]:
        return "pass"
    return "fail"


def _score_rule(rule, records, source_root):
    rng = np.random.default_rng(SEED)
    results = {}
    for symbol in ASSETS:
        frame, _ = load_cached_snapshot(symbol, source_root)
        close = frame.close.to_numpy(float)
        dates = [str(value.date()) for value in frame.date]
        last = len(close) - 1
        rows = []
        for (record_symbol, index), record in sorted(records.items()):
            if record_symbol != symbol:
                continue
            asof = dates[index]
            if any(
                record.get((asof, window, seed), {}).get("status") is None
                for window in WINDOWS
                if index - window + 1 >= 0
                for seed in SEEDS
            ):
                continue
            windows = {item["n"]: item for item in summarize_windows(record, asof)}
            eligible = {
                window: windows[window]["eligible"][rule]
                for window in WINDOWS
                if index - window + 1 >= 0
            }
            points = {
                window: windows[window]["point_ahead"] for window in eligible if eligible[window]
            }

            long_points = [points[window] for window in (900, 925, 950) if window in points]
            ultra_points = [points[window] for window in (6500, 6600, 6700) if window in points]
            cross = [
                left for left in long_points for right in ultra_points if abs(left - right) <= 5
            ]
            arms = {
                "w925": [points[window] for window in (925,) if window in points],
                "long_900": long_points,
                "w6600": [points[window] for window in (6600,) if window in points],
                "ultra_6600": ultra_points,
                "cross": long_points + ultra_points if cross else [],
            }
            row = {
                "i": index,
                "asof": asof,
                "ultra_avail": index - 6700 + 1 >= 0,
            }
            for arm, values in arms.items():
                row[arm] = float(np.mean(values)) if values else None
            if index + 230 <= last:
                row["DD120"] = close[index + 1 : index + 121].min() / close[index] - 1
                peak = index + int(np.argmax(close[index : index + 111]))
                row["peak"] = peak
                row["peak_dd"] = close[peak + 1 : peak + 121].min() / close[peak] - 1
            rows.append(row)

        def hit(row, ahead):
            return row["peak_dd"] <= -0.15 and abs(row["peak"] - (row["i"] + round(ahead))) <= 20

        symbol_results = {}
        for arm in ("w925", "long_900", "w6600", "ultra_6600", "cross"):
            pool = [
                row
                for row in rows
                if "DD120" in row and (row["ultra_avail"] or arm in ("w925", "long_900"))
            ]
            signals = [row for row in pool if row[arm] is not None]
            live = [row for row in rows if "DD120" not in row and row[arm] is not None]
            episodes = []
            previous = None
            for row in (item for item in rows if item[arm] is not None):
                if previous is None or row["i"] - previous > 30:
                    episodes.append([])
                episodes[-1].append(row)
                previous = row["i"]
            episode_rows = []
            for episode in episodes:
                first = episode[0]
                item = {
                    "first": first["asof"],
                    "last": episode[-1]["asof"],
                    "n_asofs": len(episode),
                    "ahead": round(first[arm], 1),
                    "tc_est": (
                        dates[min(last, first["i"] + round(first[arm]))]
                        if first["i"] + round(first[arm]) <= last
                        else "beyond_data"
                    ),
                }
                if "DD120" in first:
                    item.update(
                        DD120=round(first["DD120"] * 100, 1),
                        peak=dates[first["peak"]],
                        peak_dd=round(first["peak_dd"] * 100, 1),
                        top_hit=bool(hit(first, first[arm])),
                    )
                episode_rows.append(item)
            count = len(signals)
            stat = {
                "pool_asofs": len(pool),
                "signal_asofs": count,
                "live_signal_asofs": len(live),
                "episodes": episode_rows,
            }
            if count:
                aheads = [row[arm] for row in signals]
                observed = {
                    "top_hit": np.mean([hit(row, row[arm]) for row in signals]),
                    "DD120_le_-10": np.mean([row["DD120"] <= -0.10 for row in signals]),
                    "DD120_le_-20": np.mean([row["DD120"] <= -0.20 for row in signals]),
                    "median_DD120": np.median([row["DD120"] for row in signals]),
                }
                draws = collections.defaultdict(list)
                for _ in range(2000):
                    indices = rng.choice(len(pool), size=count, replace=False)
                    ahead = rng.choice(aheads, size=count)
                    sample = [pool[index] for index in indices]
                    draws["top_hit"].append(
                        np.mean([hit(row, value) for row, value in zip(sample, ahead, strict=True)])
                    )
                    draws["DD120_le_-10"].append(np.mean([row["DD120"] <= -0.10 for row in sample]))
                    draws["DD120_le_-20"].append(np.mean([row["DD120"] <= -0.20 for row in sample]))
                    draws["median_DD120"].append(np.median([row["DD120"] for row in sample]))
                stat["metrics"] = {
                    metric: {
                        "obs": round(float(observed[metric]) * 100, 1),
                        "rand_p50": round(float(np.percentile(values, 50)) * 100, 1),
                        "rand_p95": round(float(np.percentile(values, 95)) * 100, 1),
                        "rand_p5": round(float(np.percentile(values, 5)) * 100, 1),
                    }
                    for metric, values in draws.items()
                }
                scored_episodes = [item for item in episode_rows if "top_hit" in item]
                stat["episode_top_hit"] = (
                    f"{sum(item['top_hit'] for item in scored_episodes)}/{len(scored_episodes)}"
                )
            symbol_results[arm] = stat
        results[symbol] = symbol_results
    return results


def score_replay(source_root, fits_dir, out):
    source_root = Path(source_root)
    fits_dir = Path(fits_dir)
    fit_files = sorted(fits_dir.glob("*.json"))
    records = collections.defaultdict(dict)
    for path in fit_files:
        with path.open(encoding="utf-8") as stream:
            record = json.load(stream)
        records[(record["symbol"], record["i"])][(record["asof"], record["n"], record["seed"])] = (
            record
        )

    source_rows = {}
    for symbol in ASSETS:
        frame, _ = load_cached_snapshot(symbol, source_root)
        dates = [str(value.date()) for value in frame.date]
        source_rows[symbol] = {
            "first_date": dates[0],
            "last_date": dates[-1],
            "rows": len(frame),
        }

    rules = {rule: _score_rule(rule, records, source_root) for rule in RULES}
    verdicts = {
        rule: {
            symbol: {arm: classify_verdict(stat) for arm, stat in arms.items()}
            for symbol, arms in symbol_results.items()
        }
        for rule, symbol_results in rules.items()
    }
    report = {
        "schema_version": "long_window_pit_v1",
        "generated_from": {
            "source_root_rows": source_rows,
            "fits": len(fit_files),
            "step": STEP,
            "windows": list(WINDOWS),
            "seeds": list(SEEDS),
        },
        "protocol": __doc__,
        "rules": rules,
        "verdicts": verdicts,
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    fit_parser = commands.add_parser("fit")
    fit_parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    fit_parser.add_argument("--fits-dir", type=Path, default=DEFAULT_FITS_DIR)
    fit_parser.add_argument("--step", type=int, default=STEP)
    fit_parser.add_argument("--workers", type=int, default=1)
    score_parser = commands.add_parser("score")
    score_parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    score_parser.add_argument("--fits-dir", type=Path, default=DEFAULT_FITS_DIR)
    score_parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if args.command == "fit":
        if args.step <= 0 or args.workers <= 0:
            parser.error("--step and --workers must be positive")
        fit_replay(args.source_root, args.fits_dir, args.step, args.workers)
        return
    report = score_replay(args.source_root, args.fits_dir, args.out)
    print(
        f"wrote {args.out} with {report['generated_from']['fits']} fits "
        f"and rules {', '.join(report['rules'])}"
    )


if __name__ == "__main__":
    main()
