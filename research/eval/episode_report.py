"""预警段（Episode）事件级回测。

读已发布的指数历史 `web/mock/data/<sym>_history.json`（周度截止日，严格 as-of）。
每个尺度把连续出现聚类区间（`w[scale]` 非空）的截止日合成一轮预警段（与 frontend/app/alert-ledger.js 相同），
预警段不跨开发/校准/测试段。每轮取首次预警日与当天主簇区间，对照之后第一个确认顶（`tops`）。

- 主簇命中：顶落在首次预警日主簇 [q20, q80] 前后各 BUFFER 个交易日内。
- H 日命中：首次预警日后 H 个交易日内出现顶。
- 覆盖率：段内的顶，之前 H 个交易日内有任一预警截止日的比例。
- 随机基准：同一段内把（是否预警、区间相对截止日的偏移）整体循环平移 k 帧，k 至少 MIN_SHIFT 个交易日，
  N_PERM 次；各指数独立平移后合并。p = (1 + #{基准 ≥ 实际}) / (1 + N_PERM)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ..price_layer.drawdown_table import TURN_WINDOW
from .dataset import price_series

DATA = Path("web/mock/data")
SYMS = ("sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006", "sh000688")
SCALES = ("6-12m", "12-24m")
SPLITS = ("dev", "cal", "test")
H, BUFFER, LOOK = 120, 20, 126
N_PERM, MIN_SHIFT, STEP = 1000, 250, 5
SPLIT_LABEL = {"dev": "开发段", "cal": "校准段", "test": "测试段"}


def _pos(cal: pd.DatetimeIndex, date: str) -> int:
    t = pd.Timestamp(date)
    if t <= cal[-1]:
        return int(cal.searchsorted(t, side="left"))
    extra = int(np.busday_count((cal[-1] + pd.Timedelta(days=1)).date(), (t + pd.Timedelta(days=1)).date()))
    return len(cal) - 1 + extra


def _main_cluster(frame: dict, scale: str) -> dict | None:
    cl = [c for c in (frame.get("clusters") or {}).get(scale) or [] if c.get("q20_date") and c.get("q80_date") and c.get("share") is not None]
    return max(cl, key=lambda c: float(c["share"])) if cl else None


def segment_arrays(frames: list[dict], scale: str, cal: pd.DatetimeIndex) -> dict[str, dict]:
    """每段：截止日位置 p、是否预警 a、主簇 q20/q80 相对截止日的交易日偏移（无主簇为 nan）。"""
    out = {}
    for split in SPLITS:
        fr = [f for f in frames if f.get("split") == split and f.get("close") is not None]
        if not fr:
            continue
        p = np.array([_pos(cal, f["asof"]) for f in fr])
        a = np.array([bool((f.get("w") or {}).get(scale)) for f in fr])
        lo = np.full(len(fr), np.nan)
        hi = np.full(len(fr), np.nan)
        for i, f in enumerate(fr):
            m = _main_cluster(f, scale) if a[i] else None
            if m:
                lo[i] = _pos(cal, m["q20_date"]) - p[i]
                hi[i] = _pos(cal, m["q80_date"]) - p[i]
        out[split] = {"p": p, "a": a, "lo": lo, "hi": hi, "asof": [f["asof"] for f in fr]}
    return out


def _trim(seg: dict, last_ok: float) -> dict:
    keep = seg["p"] + H <= last_ok
    return {
        "p": seg["p"][keep],
        "a": seg["a"][keep],
        "lo": seg["lo"][keep],
        "hi": seg["hi"][keep],
        "asof": [asof for asof, include in zip(seg["asof"], keep, strict=True) if include],
    }


def score(p: np.ndarray, a: np.ndarray, lo: np.ndarray, hi: np.ndarray, tops: np.ndarray,
          last_ok: float = np.inf) -> dict:
    """tops：确认顶的交易日位置（升序）。返回预警段数、两种命中数、覆盖的顶数与段内顶数。"""
    starts = np.flatnonzero(a & ~np.r_[False, a[:-1]])
    n_main = n_h = n_main_ok = 0
    for i in starts:
        k = np.searchsorted(tops, p[i], side="right")
        top = tops[k] if k < len(tops) else None
        if top is not None and top - p[i] <= H:
            n_h += 1
        if np.isfinite(lo[i]) and np.isfinite(hi[i]) and p[i] + hi[i] + BUFFER <= last_ok:
            n_main_ok += 1
            if top is not None and p[i] + lo[i] - BUFFER <= top <= p[i] + hi[i] + BUFFER:
                n_main += 1
    seg_tops = tops[(tops >= p[0]) & (tops <= p[-1]) & (tops <= last_ok)]
    ap = p[a]
    covered = sum(bool(((ap < t) & (ap >= t - H)).any()) for t in seg_tops)
    return {"episodes": len(starts), "with_main": n_main_ok, "hit_main": n_main, "hit_h": n_h,
            "tops": len(seg_tops), "covered": covered}


def episodes(seg: dict, tops: np.ndarray, top_rows: list[dict], cal: pd.DatetimeIndex,
             frames_by_date: dict, scale: str, last_ok: float = np.inf) -> list[dict]:
    p, a = seg["p"], seg["a"]
    rows = []
    for i in np.flatnonzero(a & ~np.r_[False, a[:-1]]):
        j = i
        while j + 1 < len(a) and a[j + 1]:
            j += 1
        k = np.searchsorted(tops, p[i], side="right")
        top = top_rows[k] if k < len(tops) else None
        m = _main_cluster(frames_by_date[seg["asof"][i]], scale)
        lead = int(tops[k] - p[i]) if top else None
        in_main = None
        if top and m:
            in_main = bool(p[i] + seg["lo"][i] - BUFFER <= tops[k] <= p[i] + seg["hi"][i] + BUFFER)
        rows.append({
            "scale": scale, "first_asof": seg["asof"][i], "last_asof": seg["asof"][j], "weeks": int(j - i + 1),
            "main_cluster": [m["q20_date"], m["q80_date"]] if m else None,
            "main_share": float(m["share"]) if m else None,
            "next_top": top["date"] if top else None,
            "days_to_top": lead,
            "max_dd": top.get("max_dd") if top else None,
            "hit_h": bool(top is not None and lead <= H),
            "hit_main": in_main,
            "mature": bool(p[i] + H <= last_ok),
        })
    return rows


def run(syms=SYMS, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    per = {}
    for sym in syms:
        path = DATA / f"{sym}_history.json"
        if not path.exists():
            continue
        h = json.loads(path.read_text(encoding="utf-8"))
        cal = price_series(sym).index
        top_rows = sorted(h["tops"], key=lambda t: t["date"])
        tops = np.array([_pos(cal, t["date"]) for t in top_rows])
        last_ok = len(cal) - 1 - max(LOOK, TURN_WINDOW)
        by_date = {f["asof"]: f for f in h["frames"]}
        per[sym] = {"cal": cal, "tops": tops, "top_rows": top_rows, "last_ok": last_ok,
                    "segs": {s: segment_arrays(h["frames"], s, cal) for s in SCALES}, "by_date": by_date}

    summary, listing = [], {}
    m = MIN_SHIFT // STEP
    for sym, v in per.items():
        listing[sym] = {s: [e for split, seg in v["segs"][s].items()
                            for e in [dict(x, split=split) for x in episodes(
                                seg, v["tops"], v["top_rows"], v["cal"], v["by_date"], s, v["last_ok"])]]
                        for s in SCALES}
    for scale in SCALES:
        for split in SPLITS:
            raw_segs = {sym: v["segs"][scale][split] for sym, v in per.items() if split in v["segs"][scale]}
            if not raw_segs:
                continue
            segs, excluded = {}, []
            for sym, seg in raw_segs.items():
                trimmed = _trim(seg, per[sym]["last_ok"])
                if len(trimmed["a"]) <= 2 * m:
                    excluded.append(sym)
                else:
                    segs[sym] = trimmed
            obs = {k: 0 for k in ("episodes", "with_main", "hit_main", "hit_h", "tops", "covered")}
            for sym, seg in segs.items():
                for k, x in score(seg["p"], seg["a"], seg["lo"], seg["hi"], per[sym]["tops"],
                                  per[sym]["last_ok"]).items():
                    obs[k] += x
            null = np.zeros((N_PERM, 3))
            for b in range(N_PERM):
                tot = np.zeros(5)
                for sym, seg in segs.items():
                    n = len(seg["a"])
                    k = int(rng.integers(m, n - m + 1))
                    s = score(seg["p"], np.roll(seg["a"], k), np.roll(seg["lo"], k), np.roll(seg["hi"], k),
                              per[sym]["tops"], per[sym]["last_ok"])
                    tot += [s["episodes"], s["with_main"], s["hit_main"], s["hit_h"], s["covered"]]
                null[b] = [tot[2] / tot[1] if tot[1] else np.nan, tot[3] / tot[0] if tot[0] else np.nan,
                           tot[4] / obs["tops"] if obs["tops"] else np.nan]
            rate = {"hit_main": obs["hit_main"] / obs["with_main"] if obs["with_main"] else None,
                    "hit_h": obs["hit_h"] / obs["episodes"] if obs["episodes"] else None,
                    "coverage": obs["covered"] / obs["tops"] if obs["tops"] else None}
            row = {"scale": scale, "split": split, "symbols": sorted(segs), "excluded": sorted(excluded),
                   **obs, "hit_main_n": obs["hit_main"], "hit_h_n": obs["hit_h"]}
            for c, key in enumerate(("hit_main", "hit_h", "coverage")):
                col = null[:, c]
                col = col[np.isfinite(col)]
                row[key] = None if rate[key] is None else round(rate[key], 3)
                row[key + "_null"] = round(float(col.mean()), 3) if len(col) else None
                row[key + "_p"] = (round(float((1 + (col >= rate[key] - 1e-12).sum()) / (1 + len(col))), 4)
                                   if rate[key] is not None and len(col) else None)
            summary.append(row)
    return {
        "rule": "连续出现聚类区间的周度截止日合成一轮预警段（不跨开发/校准/测试段）；首次预警日 = 该轮第一个截止日。",
        "params": {"H": H, "buffer": BUFFER, "n_perm": N_PERM, "min_shift": MIN_SHIFT, "seed": seed,
                   "hit_main": f"顶落在首次预警日主簇 q20–q80 前后各 {BUFFER} 个交易日内",
                   "hit_h": f"首次预警日后 {H} 个交易日内出现确认顶",
                   "coverage": f"段内确认顶之前 {H} 个交易日内有预警截止日",
                   "null": f"同段内把预警与区间偏移整体循环平移（≥{MIN_SHIFT} 个交易日），{N_PERM} 次，各指数独立"},
        "summary": summary,
        "episodes": listing,
    }


def _pct(x):
    return "—" if x is None else f"{x:.0%}"


def markdown(rep: dict) -> str:
    md = ["# 预警段事件级回测", "", rep["rule"], ""]
    md += [f"- {k}：{v}" for k, v in rep["params"].items() if isinstance(v, str)]
    md += ["", "| 尺度 | 段 | 预警段 | 主簇命中 | 基准 | p | H 日命中 | 基准 | p | 顶 | 覆盖率 | 基准 | p | 排除 |", "|" + "---|" * 14]
    for r in rep["summary"]:
        excluded = ",".join(r["excluded"]) or "—"
        md.append(f"| {r['scale']} | {SPLIT_LABEL[r['split']]} | {r['episodes']} | {r['hit_main_n']}/{r['with_main']} = {_pct(r['hit_main'])} | "
                  f"{_pct(r['hit_main_null'])} | {r['hit_main_p']} | {r['hit_h_n']}/{r['episodes']} = {_pct(r['hit_h'])} | {_pct(r['hit_h_null'])} | {r['hit_h_p']} | "
                  f"{r['tops']} | {_pct(r['coverage'])} | {_pct(r['coverage_null'])} | {r['coverage_p']} | {excluded} |")
    return "\n".join(md) + "\n"


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    rep = run(seed=seed)
    (DATA / "episode_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    Path("reports").mkdir(exist_ok=True)
    Path("reports/episode_report.md").write_text(markdown(rep), encoding="utf-8")
    print(markdown(rep))


if __name__ == "__main__":
    main()
