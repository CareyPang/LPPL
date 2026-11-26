"""将 web/mock/data/<sym>_history.json 从冻结段末尾补扫延续至最新交易日（严格 PIT）。

设计原则：
1. 原 dev / cal / test 冻结帧完整保留，不改写原预登记三段验证历史；
2. 仅对最后冻结日之后的每 5 个交易日（周度截止日，含最新交易日）运行 LPPLS 扫描
   （窗长 130–500 步长 5、优化器 g3，与冻结帧 HISTORY_SCANS 同口径；优化器一致性审计见
   reports/optimizer_parity/v1：g3 对预登记评测的 tcgrid 过门，de_trf 未过），
   并标记 split="live"、写入 method；已有且 method 相同的 live 帧直接复用，只补算新截止日；
3. 合并后统一重算：
   - 严格 PIT 事后确认顶 tops（仅当 i + 126 <= len - 1 时确认）；
   - first_alert_flag（每轮 6–12m 顶部聚类首次预警日）；
   - 底分 fco_neg_intensity、bottom_first_alert_flag、bottom_factors；
   - 顶部事件级回测 episode_summary 与底部事件级回测 bottom_summary。

用法：
  LPPLS_BOX=v2 python -m research.pipeline.history_extend sh000001 [--opt g3] [--step 5]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from ..data import cache
from ..data.trading_calendar import future_calendar_metadata
from ..eval.bottom_dashboard import (
    BOTTOM_SCORE_ID,
    bottom_score_meta,
    compute_fco_neg_intensity_series,
    summarize_bottom_backtest,
    summarize_phase_rule,
)
from ..eval.episode_backtest import summarize_history_episodes
from ..eval.export_contract import (
    HISTORY_SCALES,
    LOOK,
    _history_frame,
)
from ..features.lppls_rules import _derived, rules
from ..features.lppls_scan import BOX, BOXES, OPTIMIZER_NAMES
from ..lppls import core as _core
from ..price_layer.drawdown_table import qualified_turns
from .daily import fit_asof

log = logging.getLogger(__name__)

# 与冻结帧（lppls_v2_g3*，130–500 步长 5）相同的窗口：6–12m 25 个、12–24m 50 个，置信度粒度 1/25、1/50
EXTEND_WINDOWS: tuple[int, ...] = tuple(range(130, 501, 5))
EXTEND_WINDOWS_LABEL = "130-500/5"
# stock-results 的行情只有最近 756 日，早期 live 截止日凑不满 500 日窗口，用仓库内冻结行情补齐前段
FROZEN_PRICE_VERSION = "v20261104"


def _with_frozen_prefix(sym: str, df: pd.DataFrame) -> pd.DataFrame:
    try:
        frozen = cache.load(sym, frozen=FROZEN_PRICE_VERSION)
    except (FileNotFoundError, ValueError) as exc:
        log.warning("%s: 无冻结行情可补前段：%r", sym, exc)
        return df
    cols = ["date", "open", "high", "low", "close", "volume"]
    older = frozen.loc[frozen["date"] < df["date"].min(), cols]
    return pd.concat([older, df[cols]], ignore_index=True)
DEFAULT_OPT = "g3"
DEFAULT_DATA_DIR = Path("web/mock/data")


def _load_live_ohlc(sym: str, prefer_git_results: bool = True) -> pd.DataFrame:
    if prefer_git_results:
        try:
            raw = subprocess.check_output(
                ["git", "show", f"origin/stock-results:index/{sym}_latest.json"],
                stderr=subprocess.DEVNULL,
            )
            payload = json.loads(raw.decode("utf-8"))
            ph = payload.get("price_history") or {}
            dates = ph.get("dates") or []
            closes = ph.get("close") or []
            if dates and len(dates) == len(closes):
                df = pd.DataFrame(
                    {
                        "date": pd.to_datetime(dates),
                        "open": pd.to_numeric(ph.get("open", closes), errors="coerce"),
                        "high": pd.to_numeric(ph.get("high", closes), errors="coerce"),
                        "low": pd.to_numeric(ph.get("low", closes), errors="coerce"),
                        "close": pd.to_numeric(closes, errors="coerce"),
                        "volume": pd.to_numeric(ph.get("volume", [0.0] * len(dates)), errors="coerce"),
                    }
                ).dropna(subset=["date", "close"])
                df = df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
                return _with_frozen_prefix(sym, df)
        except (subprocess.CalledProcessError, OSError, ValueError, TypeError) as exc:
            log.warning("%s: 读取 stock-results 最新行情失败，改用本地缓存：%r", sym, exc)
    cache.refresh(sym)
    df = cache.load(sym, auto_refresh=False)
    df = df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    return df


def _pick_extend_dates(cal: pd.DatetimeIndex, after_date: str, step: int = 5) -> list[pd.Timestamp]:
    cutoff = pd.Timestamp(after_date)
    future_cal = cal[cal > cutoff]
    if len(future_cal) == 0:
        return []
    picked = list(future_cal[step - 1 :: step])
    if not picked or picked[-1] != future_cal[-1]:
        picked.append(future_cal[-1])
    return picked


def _fit_one_date_worker(args: tuple[pd.Series, pd.Timestamp, tuple[int, ...], str]) -> pd.DataFrame:
    sub_logp, dt, ws, opt = args
    _core.ALLOW_INSIDE = bool(BOXES[BOX]["inside"])
    return fit_asof(sub_logp, dt, ws, opt=opt)


def extend_history(
    sym: str,
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    opt: str = DEFAULT_OPT,
    step: int = 5,
    workers: int = 1,
    market: str = "cn",
) -> Path:
    _core.ALLOW_INSIDE = bool(BOXES[BOX]["inside"])
    path = data_dir / f"{sym}_history.json"
    if not path.exists():
        raise FileNotFoundError(f"未找到历史回测文件: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    base_frames = [f for f in (payload.get("frames") or []) if f.get("split") != "live"]
    if not base_frames:
        raise ValueError(f"{path} 缺少基础历史帧")

    last_base_asof = str(base_frames[-1]["asof"])
    ohlc = _load_live_ohlc(sym)
    cal = pd.DatetimeIndex(ohlc["date"])
    close = pd.Series(ohlc["close"].to_numpy(float), index=cal)
    logp = pd.Series(np.log(close.to_numpy(float)), index=cal)

    extend_dates = _pick_extend_dates(cal, last_base_asof, step=step)
    # 行情停在周中、而其后已有发布帧时，行情末日只是临时收盘，不能和后面的周并存
    last_feed = str(cal[-1].date())
    n_future = int((cal > pd.Timestamp(last_base_asof)).sum())
    published_later = any(
        f.get("split") == "live" and str(f["asof"]) > last_feed for f in (payload.get("frames") or [])
    )
    if extend_dates and n_future % step != 0 and published_later:
        extend_dates = extend_dates[:-1]
    method = {"optimizer": opt, "windows": EXTEND_WINDOWS_LABEL}
    # 口径相同的已发布 live 帧直接复用；口径不同（旧 de_trf / 步长 10）的丢弃重算
    reusable = {
        str(f["asof"]): f
        for f in (payload.get("frames") or [])
        if f.get("split") == "live" and f.get("method") == method
    }
    new_frames: dict[str, dict] = {}
    todo = [dt for dt in extend_dates if str(dt.date()) not in reusable]
    if todo:
        tasks = []
        for dt in todo:
            sub_logp = logp[logp.index <= dt]
            ws = tuple(n for n in EXTEND_WINDOWS if n <= len(sub_logp))
            if ws == EXTEND_WINDOWS:  # 历史不足 500 日的截止日不出帧，避免小窗口集被标成完整口径
                tasks.append((sub_logp, dt, ws, opt))
        scan_parts: list[pd.DataFrame] = []
        if tasks:
            eff_workers = max(1, min(workers, len(tasks)))
            if eff_workers > 1:
                with ProcessPoolExecutor(max_workers=eff_workers) as pool:
                    scan_parts = list(pool.map(_fit_one_date_worker, tasks))
            else:
                scan_parts = [_fit_one_date_worker(t) for t in tasks]
        if scan_parts:
            d = _derived(pd.concat(scan_parts, ignore_index=True))
            r = rules(d)
            for dt in todo:
                if not (d["date"] == dt).any():
                    continue
                frame = _history_frame(d, r, dt, cal, float(close.loc[dt]), "live", market=market)
                frame["method"] = dict(method)
                new_frames[str(dt.date())] = frame
    # 已发布但本次无法按新口径重算的 live 周保留原帧（method 仍是旧口径），不从回测里删掉
    old_live = {str(f["asof"]): f for f in (payload.get("frames") or []) if f.get("split") == "live"}
    # 行情里有、但不在本次周度采样日上的旧帧是被取代的临时收盘帧，丢弃（否则回测多数出一周）；
    # 行情里没有的日期（行情滞后或缺段）无从判断，原帧保留
    wanted = {str(dt.date()) for dt in extend_dates}
    known = {str(dt.date()) for dt in cal}
    by_date = {k: v for k, v in {**old_live, **new_frames, **reusable}.items() if k in wanted or k not in known}
    kept_old = sorted(k for k in by_date if k not in new_frames and k not in reusable)
    if kept_old:
        log.warning("%s: %d 个 live 周无法按 %s 重算，保留原帧：%s…", sym, len(kept_old), method, kept_old[:3])
    live_frames = [by_date[k] for k in sorted(by_date)]

    frames = base_frames + live_frames

    # 重算严格 as-of 首次预警标记
    prev_active = False
    for frame in frames:
        w_map = frame.get("w") or {}
        cl_map = frame.get("clusters") or {}
        cur_active = bool(w_map.get("6-12m") or cl_map.get("6-12m"))
        frame["first_alert_flag"] = bool(cur_active and not prev_active)
        prev_active = cur_active

    # 底分、绿柱档位、阶段
    frames = compute_fco_neg_intensity_series(frames)

    # 保留原冻结段已确认历史顶，并合并新日线窗口中确认期已走完（i + LOOK <= len - 1）的新顶
    existing_tops = {
        str(t["date"]): {"date": str(t["date"]), "max_dd": t.get("max_dd")}
        for t in (payload.get("tops") or [])
        if t.get("date")
    }
    lp_vals = logp.to_numpy()
    peaks, _ = qualified_turns(lp_vals)
    peaks = peaks[peaks + LOOK <= len(lp_vals) - 1]
    for i in peaks:
        d_str = str(cal[i].date())
        existing_tops[d_str] = {
            "date": d_str,
            "max_dd": round(float(np.exp(lp_vals[i + 1 : i + LOOK + 1].min() - lp_vals[i]) - 1.0), 3),
        }
    tops = [existing_tops[k] for k in sorted(existing_tops)]

    payload["future_calendar"] = future_calendar_metadata(cal, market)
    payload["frames"] = frames
    payload["tops"] = tops
    payload["episode_summary"] = summarize_history_episodes(frames, tops, scales=HISTORY_SCALES)
    payload["bottom_summary"] = summarize_bottom_backtest(frames)
    payload["phase_rule"] = summarize_phase_rule(frames)
    payload["bottom_score"] = bottom_score_meta()
    payload["score_version"] = BOTTOM_SCORE_ID
    payload["extended_through"] = str(frames[-1]["asof"])

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="补扫延续指数 history.json 至最新交易日")
    ap.add_argument("sym", help="指数代码，如 sh000001")
    ap.add_argument("--opt", default=DEFAULT_OPT, choices=sorted(OPTIMIZER_NAMES))
    ap.add_argument("--step", type=int, default=5, help="补扫步长（交易日），默认 5（每周）")
    ap.add_argument("--workers", type=int, default=max(1, min(os.cpu_count() or 2, 8)), help="并行进程数")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = ap.parse_args()
    out = extend_history(args.sym, data_dir=args.data_dir, opt=args.opt, step=args.step, workers=args.workers)
    data = json.loads(out.read_text(encoding="utf-8"))
    live_n = sum(1 for f in data["frames"] if f.get("split") == "live")
    bs = data.get("bottom_summary") or {}
    print(
        f"{out.name}: total={len(data['frames'])} live={live_n} last={data['frames'][-1]['asof']} "
        f"tops={len(data['tops'])} bottom_events={bs.get('n_events')} win50w={bs.get('win_rate_50w')}"
    )


if __name__ == "__main__":
    main()
