"""底分 V2 候选评估，规则见 docs/preregistration_bottom_score_v2.md。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from research.eval.bottom_calibration import independent_positions
from research.pipeline.overview_export import INDEX_LIST

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "web" / "mock" / "data"
REPORT_DIR = ROOT / "reports" / "bottom_score_v2"
SEED = 20261126
SHIFTS = 2000
MIN_SHIFT = 26

CONFIGS: dict[str, dict] = {"C0": {"kind": "C0"}}
for _v in (0.3, 0.5, 0.7):
    for _t in (50, 60):
        CONFIGS[f"C1_v{_v}_t{_t}"] = {"kind": "C1", "v_min": _v, "tau": _t}
for _t in (50, 60):
    CONFIGS[f"C2_t{_t}"] = {"kind": "C2", "tau": _t}
for _t in (50, 70):
    CONFIGS[f"C3_t{_t}"] = {"kind": "C3", "tau": _t}
SIMPLICITY = {"C3": 0, "C2": 1, "C1": 2, "C0": 3}


def is_green(frame: dict, cfg: dict) -> bool:
    if cfg["kind"] == "C0":
        return float(frame.get("fco_neg_intensity") or 0.0) >= 0.50
    det = frame.get("bottom_detail") or {}
    v, dd = det.get("valuation"), det.get("dd_52w")
    if v is None or dd is None:
        return False
    d20 = float(np.clip((-dd - 0.20) / 0.20, 0.0, 1.0))
    if cfg["kind"] == "C1":
        score = 100 * (0.6 * v + 0.4 * d20) if v >= cfg["v_min"] else 0.0
    elif cfg["kind"] == "C2":
        score = 100 * (0.5 * v + 0.5 * d20)
    else:
        score = 100 * v
    return score >= cfg["tau"]


def load_index(sym: str, segment: str) -> dict | None:
    frames = sorted(json.loads((DATA_DIR / f"{sym}_history.json").read_text(encoding="utf-8"))["frames"], key=lambda f: f["asof"])
    closes = np.array([float(f.get("close") or np.nan) for f in frames])
    splits = [f.get("split") for f in frames]
    pos = [i for i, f in enumerate(frames) if splits[i] == segment and f.get("phase") == "pullback"]
    if not pos:
        return None

    def fwd(i: int, h: int):
        j = i + h
        if j >= len(frames) or splits[j] != segment or not np.isfinite(closes[j]) or not np.isfinite(closes[i]):
            return None
        return closes[i + 1 : j + 1] / closes[i] - 1.0

    up50, dn24 = [], []
    for i in pos:
        a, b = fwd(i, 50), fwd(i, 24)
        up50.append(np.nan if a is None else float(a[-1] > 0))
        dn24.append(np.nan if b is None else float(np.nanmin(b) <= -0.10))
    return {"sym": sym, "pos": np.array(pos), "up50": np.array(up50), "dn24": np.array(dn24), "frames": [frames[i] for i in pos]}


def _lift(ix: dict, green: np.ndarray, key: str) -> tuple[float | None, int]:
    out = ix[key]
    ok = np.isfinite(out)
    cand = [int(p) for p, g, o in zip(ix["pos"], green, ok, strict=True) if g and o]
    ev = set(independent_positions(cand))
    sel = np.array([p in ev for p in ix["pos"]])
    if not sel.any() or not ok.any():
        return None, 0
    return float(out[sel].mean() - out[ok].mean()), int(sel.sum())


def evaluate(indices: list[dict], cfg: dict, rng: np.random.Generator | None = None) -> dict:
    greens = [np.array([is_green(f, cfg) for f in ix["frames"]]) for ix in indices]
    per = {}
    for ix, g in zip(indices, greens, strict=True):
        l50, n50 = _lift(ix, g, "up50")
        r24, _ = _lift(ix, g, "dn24")
        per[ix["sym"]] = {"L50": l50, "R24": r24, "events": n50}

    def mean(key, skip=None):
        vals = [v[key] for s, v in per.items() if v[key] is not None and s != skip]
        return float(np.mean(vals)) if vals else None

    res = {
        "L50": mean("L50"),
        "R24": mean("R24"),
        "events": sum(v["events"] for v in per.values()),
        "coverage": float(sum(g.sum() for g in greens) / sum(len(g) for g in greens)),
        "loo_L50": {s: mean("L50", skip=s) for s in per},
        "per_index": per,
    }
    if rng is not None and res["L50"] is not None:
        null = []
        usable = [(ix, g) for ix, g in zip(indices, greens, strict=True) if len(g) >= 52]
        for _ in range(SHIFTS):
            vals = []
            for ix, g in usable:
                k = int(rng.integers(MIN_SHIFT, len(g) - MIN_SHIFT + 1))
                v, _n = _lift(ix, np.roll(g, k), "up50")
                if v is not None:
                    vals.append(v)
            if vals:
                null.append(float(np.mean(vals)))
        res["null_p"] = float((np.array(null) >= res["L50"]).mean()) if null else None
        res["null_q"] = [float(x) for x in np.quantile(null, [0.05, 0.5, 0.95])] if null else None
    return res


def select_dev(results: dict) -> dict:
    c0 = results["C0"]["L50"]
    ok = []
    for name, r in results.items():
        if name == "C0" or r["L50"] is None:
            continue
        eligible = 0.10 <= r["coverage"] <= 0.40 and r["events"] >= 30
        robust = all(v is not None and v > 0 for v in r["loo_L50"].values())
        r["eligible"], r["robust"] = eligible, robust
        if eligible and robust:
            ok.append(name)
    if not ok:
        return {"selected": None, "reason": "没有配置同时满足合格条件与留一指数稳健性"}
    best = max(results[n]["L50"] for n in ok)
    near = [n for n in ok if best - results[n]["L50"] < 0.02]
    pick = min(near, key=lambda n: (SIMPLICITY[CONFIGS[n]["kind"]], -results[n]["L50"]))
    if c0 is not None and results[pick]["L50"] <= c0 + 0.03:
        return {"selected": None, "reason": f"最优配置 {pick} 的 L50 未比 C0 高出 0.03", "best": pick}
    return {"selected": pick, "reason": "开发段 L50 最大（差距 <0.02 时取更简单的结构）"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segment", choices=("dev", "cal", "test"), default="dev")
    ap.add_argument("--config", help="cal/test 只评估开发段选出的这一个配置（另加 C0 作对照）")
    args = ap.parse_args()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"{args.segment}.json"
    if args.segment != "dev":
        if out.exists():
            raise SystemExit(f"{out} 已存在：{args.segment} 段只跑一次")
        if args.config not in CONFIGS or args.config == "C0":
            raise SystemExit("cal/test 必须用 --config 指定开发段选出的配置")
    indices = [ix for ix in (load_index(item[0], args.segment) for item in INDEX_LIST) if ix]
    names = list(CONFIGS) if args.segment == "dev" else ["C0", args.config]
    rng = np.random.default_rng(SEED)
    results = {n: evaluate(indices, CONFIGS[n], rng) for n in names}
    report = {"segment": args.segment, "seed": SEED, "indices": [ix["sym"] for ix in indices],
              "pullback_weeks": int(sum(len(ix["pos"]) for ix in indices)), "results": results}
    if args.segment == "dev":
        report["selection"] = select_dev(results)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for n, r in results.items():
        print(n, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items() if k not in ("per_index", "loo_L50")},
              "loo_min", None if r["L50"] is None else round(min(v for v in r["loo_L50"].values() if v is not None), 3))
    print(report.get("selection"))


if __name__ == "__main__":
    main()
