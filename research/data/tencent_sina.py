"""第二来源：腾讯 fqkline 不复权日线（三入口轮换、640 根分段翻页）+ 新浪比例复权因子。

做法来自 simonlin1212/a-stock-data SKILL.md V3.10（§1.2 腾讯 K 线、§1.6 新浪复权因子，MIT）；本文件为独立精简实现。
腾讯自带 qfq 是等差口径（逐次减分红，高分红老股早年会为负），不可用；指数无复权直接取 day。
qfq：前复权价 = 不复权价 ÷ factor；hfq：后复权价 = 不复权价 × factor；因子按"生效日 ≤ 交易日"取最近一条。
对账（2026-10-27）：sh000001 收盘与冻结数据 0 差；600519 与东财 qfq 缓存中位差 0.001%、p99 0.04%。
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import requests

from .sources import COLS, UA, SourceError, rate_limit

HOSTS = ("https://web.ifzq.gtimg.cn", "https://proxy.finance.qq.com/ifzqgtimg", "https://ifzq.gtimg.cn")
_cooldown: dict[str, float] = {}
SEG = 640


def _tencent_segment(symbol: str, start: str, end: str, timeout: float) -> list[list]:
    last = None
    for host in HOSTS:
        if _cooldown.get(host, 0) > time.monotonic():
            continue
        rate_limit()
        try:
            r = requests.get(f"{host}/appstock/app/fqkline/get", params={"param": f"{symbol},day,{start},{end},{SEG},"},
                             headers=UA, timeout=timeout)
            r.raise_for_status()
            data = (r.json().get("data") or {}).get(symbol) or {}
            rows = data.get("day")
            if rows is None:
                raise SourceError("empty json")
            return rows
        except Exception as e:  # noqa: BLE001 — 换入口
            last = e
            _cooldown[host] = time.monotonic() + 120
    raise SourceError(f"tencent 三入口均失败: {symbol}: {last}")


def tencent_raw(symbol: str, start: str = "1990-01-01", end: str | None = None, timeout: float = 15) -> pd.DataFrame:
    """不复权日线，按 ≤640 根分段向前翻页直到起点之前无数据。"""
    end = end or str(pd.Timestamp.today().date())
    frames, cur_end = [], end
    while True:
        rows = _tencent_segment(symbol, start, cur_end, timeout)
        if not rows:
            break
        df = pd.DataFrame([[r[0], r[1], r[3], r[4], r[2], r[5], None] for r in rows], columns=COLS)
        frames.append(df)
        first = df.date.min()
        if len(rows) < SEG or first <= start:
            break
        cur_end = str((pd.Timestamp(first) - pd.Timedelta(days=1)).date())
    if not frames:
        raise SourceError(f"tencent 无数据: {symbol}")
    out = pd.concat(frames).drop_duplicates("date").sort_values("date")
    out = out[out.date >= start]
    for c in ("open", "high", "low", "close", "volume"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.reset_index(drop=True)


def sina_factors(symbol: str, kind: str = "qfq", timeout: float = 10) -> pd.DataFrame:
    """新浪 realstock {symbol}/{qfq|hfq}.js → DataFrame(date, factor)，按日期升序。"""
    rate_limit()
    r = requests.get(f"https://finance.sina.com.cn/realstock/company/{symbol}/{kind}.js",
                     headers={**UA, "Referer": "https://finance.sina.com.cn/"}, timeout=timeout)
    r.raise_for_status()
    text = r.text
    data, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
    f = pd.DataFrame([{"date": it["d"], "factor": float(it["f"])} for it in data.get("data", [])])
    if f.empty:
        raise SourceError(f"sina 复权因子为空: {symbol}")
    return f.sort_values("date").reset_index(drop=True)


def apply_factors(raw: pd.DataFrame, factors: pd.DataFrame, kind: str = "qfq") -> pd.DataFrame:
    fd = factors.date.to_numpy().astype(str)
    idx = np.searchsorted(fd, raw.date.to_numpy().astype(str), side="right") - 1
    fac = np.where(idx >= 0, factors.factor.to_numpy()[np.maximum(idx, 0)], np.nan)
    if np.isnan(fac).any():
        fac = pd.Series(fac).bfill().to_numpy()
    out = raw.copy()
    for c in ("open", "high", "low", "close"):
        out[c] = out[c] / fac if kind == "qfq" else out[c] * fac
    return out


def fetch_tencent_sina(market: str, six: str, is_index: bool, adjust: str = "qfq", timeout: float = 15) -> pd.DataFrame:
    from .sources import _norm

    symbol = f"{market}{six}"
    raw = tencent_raw(symbol, timeout=timeout)
    if is_index or adjust == "":
        return _norm(raw)
    return _norm(apply_factors(raw, sina_factors(symbol, adjust, timeout), adjust))
