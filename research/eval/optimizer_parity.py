"""优化器一致性审计：线上 de_trf 与评测用 tcgrid 在同一批 as-of、同一组窗口上是否给出相同结论。

背景（审查 P0-1，2026-11-26）：dev/cal/test 评测由 lppls_scan 默认的 tcgrid_lm 产出；线上 index_daily.yml 与
history_extend_weekly.yml 默认用 de_trf（且 daily.fit_asof 对 de_trf 做邻窗热启动）。此前只有“de_trf 可复现”的测试，
没有任何“与 tcgrid 等价”的证据。本模块只改变一个变量——优化器——其余（数据、窗口、搜索域、规则）全部复用生产代码。

四条臂：
  tcgrid       daily.fit_asof(opt="tcgrid")：预登记评测口径（lppls_v2 扫描，alarm_grid / by_year 报告）
  g3           daily.fit_asof(opt="g3")：history.json 冻结帧口径（HISTORY_SCANS=lppls_v2_g3*，MODEL_VERSION v2.2）
  de_trf       daily.fit_asof(opt="de_trf")：线上口径（index_daily / history_extend，含邻窗热启动）
  de_trf_cold  逐窗 fit_one(opt="de_trf", warm_starts=None)：用于把“优化器差异”和“热启动差异”分开（可选）
两个问题用两个参照：--ref tcgrid 问“线上数字是否仍受开发段评测覆盖”；--ref g3 问“live 帧能否与冻结帧拼成一条序列”。

判据（CRITERIA）在看到结果之前写定；改动判据必须在 summary 里留痕（criteria_sha256 会变）。
裁决只用常规网格日期（is_anchor=False），锚点日期（泡沫年附近）单独报告，避免按评测臂结果挑日期带来的偏差。
只用开发段（as-of ≤ DEV_END）：校准段与测试段不参与本审计，超出会直接报错（--allow-post-dev 仅供事后复核）。
每个日期都要求全部窗口可拟合（≥ 最长窗口的历史），保证各臂、各日期的置信度分母相同（6–12m 25 窗、12–24m 50 窗）。

用法（需 scipy；Windows 可直接跑，进程池固定 spawn）：
  python -m research.eval.optimizer_parity --dry-run
  python -m research.eval.optimizer_parity --symbols sh000001 --step 480 --out reports/optimizer_parity/pilot
  python -m research.eval.optimizer_parity --out reports/optimizer_parity/v1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from ..features.lppls_rules import SCALES_FCO6, _derived, grid_rules, rules

FROZEN = "v20261024"  # 与 daily.FROZEN 一致
ARMS = ("tcgrid", "g3", "de_trf", "de_trf_cold")
REF_ARM = "tcgrid"
PRIMARY_SCALES = ("6-12m", "12-24m")  # 唯一有开发段评价的两档
ALARM_THR = 0.05  # 线上报警阈值（box 置信度 ≥ 0.05）
SSE_TOL = 0.01  # SSE 相对差超过 1% 视为“找到的最优解不同”
DEFAULT_SYMBOLS = ("sh000001", "sh000300", "sz399006")
DEV_START = "2000-01-01"  # 预登记开发段 2000–2018
DEV_END = "2018-12-31"
DEFAULT_START = DEV_START
DEFAULT_STEP = 120
# 锚点：开发段首次预警日与两轮大泡沫顶附近（单独报告，不进裁决）
ANCHORS = ("2007-08-17", "2007-10-16", "2015-04-01", "2015-06-12")  # 全部在开发段内
OUT_COLS = ["symbol", "date", "arm", "is_anchor", "n", "scale", "tc", "ahead", "m", "w", "B", "D", "osc",
            "rel_err", "r2", "sse", "box", "standard", "seconds"]

# ---- 预登记判据（运行前冻结；改动会改变 criteria_sha256）----
CRITERIA = {
    "sse_worse_share_max": 0.05,  # de_trf 的 SSE 比 tcgrid 差 >1% 的窗口占比上限
    "conf_mae_max": 0.02,  # 主尺度 box 置信度平均绝对差上限（6–12m 约半个窗口翻转）
    "conf_p95_max": 0.08,  # 主尺度 box 置信度绝对差 95% 分位上限（约 2 个窗口）
    "alarm_agreement_min": 0.95,  # 主尺度报警（≥0.05）一致的日期占比下限
    "alarm_jaccard_min": 0.80,  # 主尺度报警日集合 Jaccard 下限（两臂都无报警时记为不可评）
}


def criteria_sha256(criteria: dict = CRITERIA) -> str:
    return hashlib.sha256(json.dumps(criteria, sort_keys=True).encode()).hexdigest()


# ------------------------------------------------------------------ 纯函数（numpy/pandas，无 scipy）


def scale_of(n) -> pd.Series:
    """窗口长度 → FCO 六档标签（区间互不重叠、含端点）；不在任何档内为 None。"""
    s = pd.Series(n, dtype="int64")
    out = pd.Series([None] * len(s), index=s.index, dtype=object)
    for name, (lo, hi) in SCALES_FCO6.items():
        out[s.between(lo, hi)] = name
    return out


def primary_windows(windows) -> tuple[int, ...]:
    """只保留落在主尺度内的窗口（默认审计范围）。"""
    keep = []
    for n in windows:
        for sc in PRIMARY_SCALES:
            lo, hi = SCALES_FCO6[sc]
            if lo <= int(n) <= hi:
                keep.append(int(n))
    return tuple(sorted(set(keep)))


def pick_dates(index: pd.DatetimeIndex, start: str, end: str | None, step: int, anchors=ANCHORS,
               min_bars: int = 1) -> pd.DataFrame:
    """常规网格（每 step 个交易日一个，外加末日）+ 锚点（取 ≤ 锚点的最近交易日）。返回 date, is_anchor。
    min_bars：日期本身须已有至少 min_bars 根 K 线（含当日），即最长窗口可拟合。"""
    idx = pd.DatetimeIndex(index).sort_values()
    lo = pd.Timestamp(start)
    hi = pd.Timestamp(end) if end else idx[-1]
    if min_bars > 1:
        if len(idx) < min_bars:
            return pd.DataFrame(columns=["date", "is_anchor"])
        lo = max(lo, idx[min_bars - 1])
    sel = idx[(idx >= lo) & (idx <= hi)]
    if not len(sel):
        return pd.DataFrame(columns=["date", "is_anchor"])
    grid = set(sel[::max(1, int(step))]) | {sel[-1]}
    rows = [(d, False) for d in sorted(grid)]
    for a in anchors:
        a = pd.Timestamp(a)
        prior = sel[sel <= a]
        if len(prior) and (a - prior[-1]).days <= 7:
            d = prior[-1]
            if d not in grid:
                rows.append((d, True))
    return pd.DataFrame(rows, columns=["date", "is_anchor"]).sort_values("date").reset_index(drop=True)


def evaluate_fits(d: pd.DataFrame) -> pd.DataFrame:
    """生产口径的派生量与过滤：box（rules）与 FCO standard（grid_rules）。d 需含 COLS 与 y_std。"""
    dd = _derived(d)
    r = rules(dd)
    g = grid_rules(dd)
    out = dd[["date", "n", "tc", "ahead", "m", "w", "B", "D", "osc", "rel_err", "r2", "sse"]].copy()
    out["box"] = r["box"].to_numpy(bool)
    out["standard"] = g["g_fco_standard"].to_numpy(bool)
    out["scale"] = scale_of(out["n"]).to_numpy()
    return out


def scale_confidence(windows: pd.DataFrame) -> pd.DataFrame:
    """每个 (symbol, date, arm, scale)：窗口数、box 置信度、standard 置信度。"""
    w = windows.dropna(subset=["scale"])
    g = w.groupby(["symbol", "date", "arm", "scale"], sort=True)
    out = g.agg(n_windows=("n", "size"), conf_box=("box", "mean"), conf_standard=("standard", "mean"),
                is_anchor=("is_anchor", "max")).reset_index()
    return out


def cohen_kappa(a, b) -> float:
    a = np.asarray(a, bool)
    b = np.asarray(b, bool)
    if not len(a):
        return float("nan")
    po = float(np.mean(a == b))
    pa, pb = float(a.mean()), float(b.mean())
    pe = pa * pb + (1 - pa) * (1 - pb)
    if pe >= 1.0:
        return 1.0 if po == 1.0 else float("nan")
    return (po - pe) / (1 - pe)


def _pair(left: pd.DataFrame, right: pd.DataFrame, keys: list[str], cols: list[str]) -> pd.DataFrame:
    a = left[keys + cols].rename(columns={c: f"{c}_ref" for c in cols})
    b = right[keys + cols].rename(columns={c: f"{c}_alt" for c in cols})
    return a.merge(b, on=keys, how="inner", validate="one_to_one")


def compare(windows: pd.DataFrame, alt: str, ref: str = REF_ARM, anchors: bool = False) -> dict:
    """两臂配对比较。anchors=False 只用常规网格日期（裁决口径）；True 只用锚点日期（单独报告）。"""
    w = windows[windows.is_anchor == anchors]
    wr, wa = w[w.arm == ref], w[w.arm == alt]
    keys = ["symbol", "date", "n"]
    pw = _pair(wr, wa, keys, ["sse", "box", "standard", "ahead", "scale"])
    out: dict = {"ref": ref, "alt": alt, "dates": "anchor" if anchors else "grid", "n_windows_paired": int(len(pw))}
    if not len(pw):
        return out
    rel = pw.sse_alt / pw.sse_ref - 1.0
    both_box = pw.box_ref & pw.box_alt
    out["window"] = {
        "sse_worse_share": float(np.mean(rel > SSE_TOL)),
        "sse_better_share": float(np.mean(rel < -SSE_TOL)),
        "sse_rel_median": float(np.median(rel)),
        "sse_rel_p95": float(np.quantile(rel, 0.95)),
        "box_agreement": float(np.mean(pw.box_ref == pw.box_alt)),
        "box_kappa": cohen_kappa(pw.box_ref, pw.box_alt),
        "box_pass_ref": float(pw.box_ref.mean()),
        "box_pass_alt": float(pw.box_alt.mean()),
        "standard_agreement": float(np.mean(pw.standard_ref == pw.standard_alt)),
        "ahead_absdiff_median_both_box": float(np.median(np.abs(pw.ahead_alt - pw.ahead_ref)[both_box]))
        if both_box.any() else None,
    }
    sc = scale_confidence(w[w.arm.isin([ref, alt])])
    ps = _pair(sc[sc.arm == ref], sc[sc.arm == alt], ["symbol", "date", "scale"], ["conf_box", "conf_standard", "n_windows"])
    per = {}
    for name in PRIMARY_SCALES:
        s = ps[ps.scale == name]
        if not len(s):
            per[name] = {"n_dates": 0}
            continue
        diff = s.conf_box_alt - s.conf_box_ref
        ar, aa = s.conf_box_ref >= ALARM_THR, s.conf_box_alt >= ALARM_THR
        either = int((ar | aa).sum())
        per[name] = {
            "n_dates": int(len(s)),
            "windows_mismatch_dates": int((s.n_windows_ref != s.n_windows_alt).sum()),
            "conf_mae": float(np.mean(np.abs(diff))),
            "conf_p95": float(np.quantile(np.abs(diff), 0.95)),
            "conf_max": float(np.max(np.abs(diff))),
            "conf_bias": float(np.mean(diff)),
            "alarms_ref": int(ar.sum()),
            "alarms_alt": int(aa.sum()),
            "alarm_only_ref": int((ar & ~aa).sum()),
            "alarm_only_alt": int((aa & ~ar).sum()),
            "alarm_agreement": float(np.mean(ar == aa)),
            "alarm_jaccard": float((ar & aa).sum() / either) if either else None,
        }
    out["scales"] = per
    return out


def verdict(result: dict, criteria: dict = CRITERIA) -> dict:
    """按预登记判据逐条判定。返回每条 pass/fail/not_evaluable 与总体结论。"""
    checks = []
    win = result.get("window")
    if not win:
        return {"overall": "not_evaluable", "checks": [], "reason": "没有可配对的窗口"}
    checks.append(("sse_worse_share", win["sse_worse_share"], "<=", criteria["sse_worse_share_max"]))
    for name in PRIMARY_SCALES:
        s = result.get("scales", {}).get(name) or {}
        if not s.get("n_dates"):
            checks.append((f"{name}.n_dates", 0, ">", 0))
            continue
        checks.append((f"{name}.conf_mae", s["conf_mae"], "<=", criteria["conf_mae_max"]))
        checks.append((f"{name}.conf_p95", s["conf_p95"], "<=", criteria["conf_p95_max"]))
        checks.append((f"{name}.alarm_agreement", s["alarm_agreement"], ">=", criteria["alarm_agreement_min"]))
        checks.append((f"{name}.alarm_jaccard", s["alarm_jaccard"], ">=", criteria["alarm_jaccard_min"]))
    rows = []
    for key, value, op, thr in checks:
        if value is None:
            status = "not_evaluable"
        elif op == "<=":
            status = "pass" if value <= thr else "fail"
        elif op == ">=":
            status = "pass" if value >= thr else "fail"
        else:
            status = "pass" if value > thr else "fail"
        rows.append({"check": key, "value": value, "op": op, "threshold": thr, "status": status})
    statuses = {r["status"] for r in rows}
    overall = "fail" if "fail" in statuses else ("not_evaluable" if "not_evaluable" in statuses else "pass")
    return {"overall": overall, "checks": rows, "criteria_sha256": criteria_sha256(criteria)}


def render_markdown(summary: dict) -> str:
    lines = [f"# 优化器一致性审计：{summary['tag']}", "",
             f"- 生成：{summary['generated_at']}　代码：`{summary.get('git_commit') or 'unknown'}`",
             f"- 数据：冻结 `{summary['frozen']}`；标的 {', '.join(summary['symbols'])}；网格步长 {summary['step']} 个交易日",
             f"- 窗口：{summary['window_mode']}（{summary['n_windows_config']} 个）；判据 sha256 `{summary['criteria_sha256'][:12]}`",
             ""]
    for cmp_ in summary["comparisons"]:
        v = cmp_["verdict"]
        lines += [f"## {cmp_['alt']} vs {cmp_['ref']}（常规网格日期）：**{v['overall']}**", "",
                  "| 判据 | 值 | 门槛 | 结果 |", "|---|---|---|---|"]
        for r in v["checks"]:
            val = "—" if r["value"] is None else f"{r['value']:.4f}"
            lines.append(f"| {r['check']} | {val} | {r['op']} {r['threshold']} | {r['status']} |")
        g = cmp_["grid"]
        if g.get("window"):
            w = g["window"]
            lines += ["", f"窗口级：配对 {g['n_windows_paired']}；SSE 更差 {w['sse_worse_share']:.1%}，更好 "
                      f"{w['sse_better_share']:.1%}；box 一致 {w['box_agreement']:.1%}（κ={w['box_kappa']:.3f}）；"
                      f"box 通过率 ref {w['box_pass_ref']:.1%} / alt {w['box_pass_alt']:.1%}"]
        a = cmp_["anchor"]
        if a.get("scales"):
            lines += ["", "锚点日期（不进裁决）："]
            for name, s in a["scales"].items():
                if s.get("n_dates"):
                    lines.append(f"- {name}：{s['n_dates']} 个日期，MAE {s['conf_mae']:.3f}，报警 ref {s['alarms_ref']} / alt {s['alarms_alt']}")
        lines.append("")
    lines += ["## 解读", "",
              "- pass：在本审计范围内，线上优化器与评测优化器给出相同的报警结论，可以继续沿用开发段证据。",
              "- fail：线上数字不再受开发段评测覆盖。应回退到 tcgrid，或把 de_trf 当作新方法重新走预登记评测。",
              "- 本审计只覆盖主尺度窗口；其他四档未比较。"]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ 拟合执行（需 scipy；仅在 worker 中导入）


def _init_worker() -> None:
    """spawn 进程不会继承父进程对模块全局变量的修改，必须在这里显式设置（审查 P1-9）。"""
    os.environ["LPPLS_BOX"] = "v2"
    from ..lppls import core

    core.ALLOW_INSIDE = True


def _worker_state() -> dict:
    from ..features import lppls_scan
    from ..lppls import core

    return {"box": lppls_scan.BOX, "allow_inside": bool(core.ALLOW_INSIDE)}


def _check_env() -> None:
    state = _worker_state()
    if state["box"] != "v2":
        raise RuntimeError(f"lppls_scan.BOX={state['box']!r}，必须是 'v2'（设置 LPPLS_BOX=v2 后再导入）")
    if not state["allow_inside"]:
        raise RuntimeError("core.ALLOW_INSIDE=False：v2 必须允许窗内 t_c（spawn 进程需经 _init_worker）")


@lru_cache(maxsize=16)
def load_logp(sym: str, frozen: str = FROZEN) -> pd.Series:
    from ..data import cache

    df = cache.load(sym, frozen=frozen, auto_refresh=False).sort_values("date")
    return pd.Series(np.log(df.close.to_numpy(float)), index=pd.DatetimeIndex(df.date))


def fit_arm(logp: pd.Series, asof: pd.Timestamp, windows: tuple[int, ...], arm: str) -> pd.DataFrame:
    """在 asof 上按指定臂拟合全部窗口，返回 COLS + y_std（与 daily.fit_asof 同形）。"""
    _check_env()
    from ..features.lppls_scan import COLS, fit_one
    from ..pipeline import daily

    logp = logp[logp.index <= asof]
    if arm in ("tcgrid", "g3", "de_trf"):
        return daily.fit_asof(logp, asof, windows, opt=arm)
    if arm != "de_trf_cold":
        raise ValueError(f"未知臂 {arm!r}，可选 {ARMS}")
    i = int(logp.index.get_indexer([asof])[0])
    if i < 0:
        raise ValueError(f"as-of {asof.date()} 不是交易日")
    lp = logp.to_numpy()
    rows = [(asof, *fit_one(lp[i + 1 - n: i + 1], opt="de_trf", warm_starts=None)) for n in windows if i + 1 >= n]
    d = pd.DataFrame(rows, columns=COLS)
    d["y_std"] = [lp[i + 1 - n: i + 1].std() for n in d.n]
    return d


def run_task(sym: str, asof: str, arm: str, windows: tuple[int, ...], is_anchor: bool, frozen: str = FROZEN) -> pd.DataFrame:
    t0 = time.perf_counter()
    d = fit_arm(load_logp(sym, frozen), pd.Timestamp(asof), windows, arm)
    out = evaluate_fits(d)
    out.insert(0, "symbol", sym)
    out.insert(2, "arm", arm)
    out.insert(3, "is_anchor", bool(is_anchor))
    out["seconds"] = time.perf_counter() - t0
    return out[OUT_COLS]


def _part_path(out: Path, sym: str, asof: pd.Timestamp, arm: str) -> Path:
    return out / "parts" / f"{sym}_{asof:%Y%m%d}_{arm}.parquet"


def _git_commit() -> str | None:
    try:
        import subprocess

        return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001
        return None


def summarize(windows: pd.DataFrame, arms: tuple[str, ...], meta: dict, refs: tuple[str, ...] = (REF_ARM,)) -> dict:
    comps = []
    for ref in refs:
        for alt in arms:
            if alt == ref or (alt in refs and refs.index(alt) < refs.index(ref)):
                continue
            grid = compare(windows, alt, ref=ref, anchors=False)
            comps.append({"ref": ref, "alt": alt, "grid": grid,
                          "anchor": compare(windows, alt, ref=ref, anchors=True), "verdict": verdict(grid)})
    return {**meta, "criteria": CRITERIA, "criteria_sha256": criteria_sha256(), "comparisons": comps}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEV_END)
    ap.add_argument("--allow-post-dev", action="store_true", help="允许 --end 晚于开发段（仅事后复核，不用于裁决）")
    ap.add_argument("--step", type=int, default=DEFAULT_STEP)
    ap.add_argument("--arms", default="tcgrid,g3,de_trf")
    ap.add_argument("--refs", default="tcgrid,g3", help="逐个作为参照臂；每个 alt 与每个 ref 比较一次")
    ap.add_argument("--all-scales", action="store_true", help="使用 full_windows 全部窗口（默认只用主尺度窗口）")
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--frozen", default=FROZEN)
    ap.add_argument("--out", type=Path, default=Path("reports/optimizer_parity/v1"))
    ap.add_argument("--dry-run", action="store_true", help="只打印任务数，不拟合")
    a = ap.parse_args(argv)
    if a.end is None or pd.Timestamp(a.end) > pd.Timestamp(DEV_END):
        if not a.allow_post_dev:
            raise SystemExit(f"--end={a.end!r} 晚于开发段 {DEV_END}；本审计只用开发段（如需事后复核加 --allow-post-dev）")

    if os.environ.get("LPPLS_BOX", "v2") != "v2":
        raise SystemExit(f"LPPLS_BOX={os.environ['LPPLS_BOX']!r}，本审计只支持 v2")
    os.environ["LPPLS_BOX"] = "v2"
    arms = tuple(x for x in a.arms.split(",") if x)
    refs = tuple(x for x in a.refs.split(",") if x)
    if any(x not in ARMS for x in arms) or not refs or any(x not in arms for x in refs):
        raise SystemExit(f"--arms 可选 {ARMS}；--refs 必须是 --arms 的子集")
    symbols = tuple(x for x in a.symbols.split(",") if x)
    from ..features.lppls_scan import full_windows

    out = a.out
    (out / "parts").mkdir(parents=True, exist_ok=True)
    tasks = []
    n_windows_config = 0
    for sym in symbols:
        logp = load_logp(sym, a.frozen)
        ws = full_windows(len(logp))
        ws = ws if a.all_scales else primary_windows(ws)
        n_windows_config = max(n_windows_config, len(ws))
        for _, row in pick_dates(logp.index, a.start, a.end, a.step, min_bars=max(ws)).iterrows():
            for arm in arms:
                if not _part_path(out, sym, row.date, arm).exists():
                    tasks.append((sym, str(row.date.date()), arm, ws, bool(row.is_anchor)))
    print(f"{len(tasks)} 个任务待算（已完成的会跳过），{a.procs} 进程，spawn", flush=True)
    if a.dry_run:
        return 0
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(a.procs, mp_context=ctx, initializer=_init_worker) as ex:
        futs = {ex.submit(run_task, *t, a.frozen): t for t in tasks}
        for k, fut in enumerate(as_completed(futs), 1):
            sym, asof, arm, _, _ = futs[fut]
            df = fut.result()
            df.to_parquet(_part_path(out, sym, pd.Timestamp(asof), arm))
            if k % 10 == 0 or k == len(futs):
                print(f"{k}/{len(futs)} 完成（最近：{sym} {asof} {arm}，{df.seconds.iloc[0]:.0f}s）", flush=True)
    parts = sorted((out / "parts").glob("*.parquet"))
    windows = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    windows = windows[windows.symbol.isin(symbols) & windows.arm.isin(arms)]
    windows.to_parquet(out / "windows.parquet")
    meta = {"tag": out.name, "generated_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
            "git_commit": _git_commit(), "frozen": a.frozen, "symbols": list(symbols), "step": a.step,
            "start": a.start, "end": a.end, "post_dev": bool(a.allow_post_dev), "arms": list(arms), "window_mode": "all" if a.all_scales else "primary",
            "n_windows_config": n_windows_config, "python": sys.version.split()[0]}
    meta["refs"] = list(refs)
    summary = summarize(windows, arms, meta, refs)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "summary.md").write_text(render_markdown(summary), encoding="utf-8")
    for c in summary["comparisons"]:
        print(f"{c['alt']} vs {c['ref']}: {c['verdict']['overall']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
