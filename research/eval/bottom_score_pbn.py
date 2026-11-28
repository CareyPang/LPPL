"""底分候选“破净率单项”预登记检验（docs/preregistration_bottom_pbn.md）。"""

from __future__ import annotations

import argparse
import json

import numpy as np

from research.eval.bottom_score_v2 import CONFIGS as V2_CONFIGS
from research.eval.bottom_score_v2 import INDEX_LIST, ROOT, SEED, evaluate, load_index
from research.eval.bottom_score_v2 import is_green as v2_is_green

REPORT_DIR = ROOT / "reports" / "bottom_score_pbn"
BASELINE = "C1_v0.3_t60"

CONFIGS: dict[str, dict] = {"B0": {"kind": "B0"}}
for _kind in ("P1", "P2"):
    for _v in (0.3, 0.7):
        for _t in (50, 60):
            CONFIGS[f"{_kind}_v{_v}_t{_t}"] = {"kind": _kind, "v_min": _v, "tau": _t}
for _t in (70, 90):
    CONFIGS[f"P3_t{_t}"] = {"kind": "P3", "tau": _t}
SIMPLICITY = {"P3": 0, "P1": 1, "P2": 2, "B0": 3}


def _val(pct: float | None) -> float | None:
    return None if pct is None else float(np.clip((float(pct) - 0.60) / 0.30, 0.0, 1.0))


def is_green(frame: dict, cfg: dict) -> bool:
    if cfg["kind"] == "B0":
        return v2_is_green(frame, V2_CONFIGS[BASELINE])
    det = frame.get("bottom_detail") or {}
    erp, pbn, dd = det.get("erp_pct"), det.get("pbn_pct"), det.get("dd_52w")
    if cfg["kind"] == "P2":
        both = [x for x in (erp, pbn) if x is not None]
        v = _val(max(both)) if both else None
    else:
        v = _val(pbn)
    if v is None:
        return False
    if cfg["kind"] == "P3":
        return round(100 * v, 6) >= cfg["tau"]
    if dd is None:
        return False
    d20 = float(np.clip((-dd - 0.20) / 0.20, 0.0, 1.0))
    score = 100 * (0.6 * v + 0.4 * d20) if round(v, 6) >= cfg["v_min"] else 0.0
    return round(score, 6) >= cfg["tau"]


def select_dev(results: dict) -> dict:
    b0 = results["B0"]["L50"]
    ok = []
    for name, r in results.items():
        if name == "B0" or r["L50"] is None:
            continue
        r["eligible"] = 0.10 <= r["coverage"] <= 0.40 and r["events"] >= 30
        r["robust"] = all(v is not None and v > 0 for v in r["loo_L50"].values())
        if r["eligible"] and r["robust"]:
            ok.append(name)
    if not ok:
        return {"selected": None, "reason": "没有配置同时满足合格条件与留一指数稳健性"}
    best = max(results[n]["L50"] for n in ok)
    near = [n for n in ok if best - results[n]["L50"] < 0.02]
    pick = min(near, key=lambda n: (SIMPLICITY[CONFIGS[n]["kind"]], -results[n]["L50"]))
    if b0 is not None and results[pick]["L50"] <= b0 + 0.03:
        return {"selected": None, "reason": f"最优配置 {pick} 的 L50 未比 B0 高出 0.03", "best": pick}
    return {"selected": pick, "reason": "开发段 L50 最大（差距 <0.02 时取更简单的结构）"}


def gate(segment: str, results: dict, pick: str) -> dict:
    c, b = results[pick], results["B0"]
    if c["L50"] is None or b["L50"] is None:
        return {"passed": False, "reason": "L50 无法计算"}
    checks = {
        "L50_not_worse": c["L50"] >= b["L50"] - 0.05,
        "R24_not_worse": c["R24"] is not None and b["R24"] is not None and c["R24"] <= b["R24"] + 0.05,
    }
    if segment == "cal":
        checks["events_ge_5"] = c["events"] >= 5
    else:
        checks["L50_positive_p_le_0.10"] = c["L50"] > 0 and c.get("null_p") is not None and c["null_p"] <= 0.10
    return {"passed": all(checks.values()), "checks": checks}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segment", choices=("dev", "cal", "test"), default="dev")
    ap.add_argument("--config", help="cal/test 只评估开发段选出的这一个配置（另加 B0 作对照）")
    args = ap.parse_args()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"{args.segment}.json"
    if out.exists():
        raise SystemExit(f"{out} 已存在：每段只跑一次")
    if args.segment != "dev":
        dev = json.loads((REPORT_DIR / "dev.json").read_text(encoding="utf-8"))
        if args.config is None or args.config != dev["selection"].get("selected"):
            raise SystemExit("cal/test 必须用 --config 指定开发段选出的配置")
        if args.segment == "test":
            cal = json.loads((REPORT_DIR / "cal.json").read_text(encoding="utf-8"))
            if not cal["gate"]["passed"]:
                raise SystemExit("校准段未通过，测试段不打开")
    indices = [ix for ix in (load_index(item[0], args.segment) for item in INDEX_LIST) if ix]
    names = list(CONFIGS) if args.segment == "dev" else ["B0", args.config]
    rng = np.random.default_rng(SEED)
    results = {n: evaluate(indices, CONFIGS[n], rng, green_fn=is_green) for n in names}
    report = {"segment": args.segment, "seed": SEED, "indices": [ix["sym"] for ix in indices],
              "pullback_weeks": int(sum(len(ix["pos"]) for ix in indices)), "results": results}
    if args.segment == "dev":
        report["selection"] = select_dev(results)
    else:
        report["gate"] = gate(args.segment, results, args.config)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for n, r in results.items():
        loo = [v for v in r["loo_L50"].values() if v is not None]
        print(n, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items() if k not in ("per_index", "loo_L50", "null_q", "null_indices")},
              "loo_min", round(min(loo), 3) if loo else None)
    print(report.get("selection") or report.get("gate"))


if __name__ == "__main__":
    main()
