"""本地缓存 + Point-in-Time 版本（vintage）。

目录结构::

    data/cache/<sym>/<adjust>/<vintage YYYYMMDD>.parquet   # 某次下载的完整日线
    data/cache/<sym>/<adjust>/manifest.json                # 每个 vintage 的来源、行数、末日、校验

PIT 规则：研究代码只能通过 ``load(sym, asof=...)`` 取数，它返回 **下载日期 <= asof** 的
最新 vintage，并再按 ``date <= asof`` 截断。这样既防止使用未来的 K 线，也防止使用
未来才发生的复权调整（前复权会改写历史价格）。首次使用历史 asof 时没有旧 vintage，
会回退到最早的 vintage 并打上 ``pit_approx=True`` 标记，调用方必须在报告中注明。
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import sources as S

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2] / "data" / "cache"


@dataclass
class Vintage:
    vintage: str
    source: str
    rows: int
    last_date: str
    sha1: str
    path: str


def _sym_dir(sym: str, adjust: str) -> Path:
    d = ROOT / sym / (adjust or "raw")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _manifest(d: Path) -> list[dict]:
    p = d / "manifest.json"
    return json.loads(p.read_text()) if p.exists() else []


def validate(df: pd.DataFrame, name: str = "") -> None:
    """来源级质量门：行数、非正价、过多 >25% 跳变（加法复权或错误复权的典型症状）。不通过抛 SourceError。"""
    q = quality_check(df)
    if q["rows"] < 60:
        raise S.SourceError(f"{name} 行数过少: {q['rows']}")
    if q["nonpositive"] > 0:
        raise S.SourceError(f"{name} 含非正价格 {q['nonpositive']} 行（疑似加法复权）")
    if q["jumps_gt_25pct"] > max(5, q["rows"] // 500):
        raise S.SourceError(f"{name} >25% 跳变过多: {q['jumps_gt_25pct']}")


def download(code: str, adjust: str = "qfq", order=None, retries: int = 3, backoff: float = 2.0) -> tuple[pd.DataFrame, str]:
    """按源顺序 + 指数退避重试 + 质量门，返回 (df, source_name)。全部失败抛 SourceError。"""
    market, six, is_index = S.parse_code(code)
    order = order or (S.DEFAULT_ORDER if is_index else S.STOCK_ORDER)
    errors = []
    for name in order:
        fn = S.SOURCES[name]
        for k in range(retries):
            try:
                df = fn(market, six, is_index, adjust)
                validate(df, name)
                return df, name
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name}#{k}: {type(e).__name__}: {str(e)[:80]}")
                time.sleep(backoff**k * 0.5)
    raise S.SourceError("所有数据源失败:\n" + "\n".join(errors))


def refresh(code: str, adjust: str = "qfq", **kw) -> Vintage:
    """下载并写入今日 vintage；同一天重复调用会覆盖当天文件。"""
    market, six, _ = S.parse_code(code)
    sym = f"{market}{six}"
    df, src = download(code, adjust, **kw)
    d = _sym_dir(sym, adjust)
    vint = pd.Timestamp.today().strftime("%Y%m%d")
    path = d / f"{vint}.parquet"
    df.to_parquet(path, index=False)
    sha = hashlib.sha1(path.read_bytes()).hexdigest()[:12]
    v = Vintage(vint, src, len(df), df["date"].iloc[-1].strftime("%Y-%m-%d"), sha, str(path))
    man = [m for m in _manifest(d) if m["vintage"] != vint] + [v.__dict__]
    (d / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1))
    log.info("refresh %s %s <- %s rows=%d last=%s", sym, adjust, src, len(df), v.last_date)
    return v


def load(code: str, asof: str | pd.Timestamp | None = None, adjust: str = "qfq", auto_refresh: bool = True) -> pd.DataFrame:
    """PIT 读取。见模块说明。返回 df.attrs 含 vintage/source/pit_approx。"""
    market, six, _ = S.parse_code(code)
    sym = f"{market}{six}"
    d = _sym_dir(sym, adjust)
    man = sorted(_manifest(d), key=lambda m: m["vintage"])
    if not man and auto_refresh:
        refresh(code, adjust)
        man = sorted(_manifest(d), key=lambda m: m["vintage"])
    if not man:
        raise FileNotFoundError(f"无缓存: {sym}")
    asof_ts = pd.Timestamp(asof) if asof is not None else pd.Timestamp.max
    eligible = [m for m in man if pd.Timestamp(m["vintage"]) <= asof_ts]
    pit_approx = not eligible
    m = (eligible or man)[-1 if eligible else 0]
    df = pd.read_parquet(m["path"])
    if asof is not None:
        df = df[df["date"] <= asof_ts].reset_index(drop=True)
    df.attrs.update(vintage=m["vintage"], source=m["source"], pit_approx=pit_approx, symbol=sym)
    return df


def quality_check(df: pd.DataFrame) -> dict:
    """基本有效性：缺口、非正价、极端跳变（可能是复权错误）。"""
    gaps = df["date"].diff().dt.days
    ret = df["close"].pct_change().abs()
    return {
        "rows": int(len(df)),
        "first": df["date"].iloc[0].strftime("%Y-%m-%d"),
        "last": df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "nonpositive": int((df["close"] <= 0).sum()),
        "max_gap_days": int(gaps.max()) if len(df) > 1 else 0,
        "jumps_gt_25pct": int((ret > 0.25).sum()),
        "dup_dates": int(df["date"].duplicated().sum()),
    }
