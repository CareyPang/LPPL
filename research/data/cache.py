"""本地行情缓存、Point-in-Time 版本与冻结数据集。"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from . import sources as S

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2] / "data" / "cache"
FROZEN_ROOT = Path(__file__).resolve().parents[2] / "data" / "frozen"


@dataclass
class Vintage:
    vintage: str
    source: str
    rows: int
    first_date: str
    last_date: str
    sha256: str
    path: str
    downloaded_at: str
    adjust: str
    attempts: list[dict[str, str]]


def _sym_dir(sym: str, adjust: str) -> Path:
    directory = ROOT / sym / (adjust or "raw")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _manifest(directory: Path) -> list[dict]:
    path = directory / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else []


def quality_check(df: pd.DataFrame) -> dict:
    """基本有效性：缺口、非正价、极端跳变（可能是复权错误）。"""
    gaps = df["date"].diff().dt.days
    returns = df["close"].pct_change().abs()
    return {
        "rows": int(len(df)),
        "first": df["date"].iloc[0].strftime("%Y-%m-%d"),
        "last": df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "nonpositive": int((df["close"] <= 0).sum()),
        "max_gap_days": int(gaps.max()) if len(df) > 1 else 0,
        "jumps_gt_25pct": int((returns > 0.25).sum()),
        "dup_dates": int(df["date"].duplicated().sum()),
    }


def validate(df: pd.DataFrame, name: str = "") -> None:
    """来源级质量门：拒绝过短、非正价和异常跳变的数据。"""
    q = quality_check(df)
    if q["rows"] < 60:
        raise S.SourceError(f"{name} 行数过少: {q['rows']}")
    if q["nonpositive"] > 0:
        raise S.SourceError(f"{name} 含非正价格 {q['nonpositive']} 行（疑似加法复权）")
    if q["jumps_gt_25pct"] > max(5, q["rows"] // 500):
        raise S.SourceError(f"{name} >25% 跳变过多: {q['jumps_gt_25pct']}")


def _download_with_attempts(
    code: str,
    adjust: str = "qfq",
    order=None,
    retries: int = 3,
    backoff: float = 2.0,
) -> tuple[pd.DataFrame, str, list[dict[str, str]]]:
    market, six, is_index = S.parse_code(code)
    order = order or (S.DEFAULT_ORDER if is_index else S.STOCK_ORDER)
    attempts = []
    for name in order:
        fn = S.SOURCES[name]
        for attempt in range(retries):
            try:
                df = fn(market, six, is_index, adjust)
                validate(df, name)
                return df, name, attempts
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {str(exc)[:120]}"
                attempts.append({"source": name, "error": error})
                time.sleep(backoff**attempt * 0.5)
    details = "\n".join(f"{item['source']}: {item['error']}" for item in attempts)
    raise S.SourceError(f"所有数据源失败:\n{details}")


def download(
    code: str, adjust: str = "qfq", order=None, retries: int = 3, backoff: float = 2.0
) -> tuple[pd.DataFrame, str]:
    """按来源顺序、指数退避和质量门下载，返回 (df, source_name)。"""
    df, source, _ = _download_with_attempts(code, adjust, order, retries, backoff)
    return df, source


def refresh(code: str, adjust: str = "qfq", **kwargs) -> Vintage:
    """下载并写入今日 vintage；同一天重复调用会覆盖当天文件。"""
    market, six, _ = S.parse_code(code)
    symbol = f"{market}{six}"
    df, source, attempts = _download_with_attempts(code, adjust, **kwargs)
    directory = _sym_dir(symbol, adjust)
    vintage = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d")
    path = directory / f"{vintage}.parquet"
    df.to_parquet(path, index=False)
    now = pd.Timestamp.now(tz="UTC").isoformat()
    record = Vintage(
        vintage=vintage,
        source=source,
        rows=len(df),
        first_date=df["date"].iloc[0].strftime("%Y-%m-%d"),
        last_date=df["date"].iloc[-1].strftime("%Y-%m-%d"),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        path=str(path),
        downloaded_at=now,
        adjust=adjust,
        attempts=attempts,
    )
    manifest = [item for item in _manifest(directory) if item["vintage"] != vintage]
    manifest.append(asdict(record))
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1)
    )
    log.info(
        "refresh %s %s <- %s rows=%d last=%s",
        symbol,
        adjust,
        source,
        len(df),
        record.last_date,
    )
    return record


def _frozen_entry(sym: str, adjust: str, frozen: str) -> tuple[dict, Path]:
    if not frozen or Path(frozen).name != frozen:
        raise ValueError(f"无效冻结版本名称: {frozen}")
    directory = FROZEN_ROOT / frozen
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"无冻结版本: {frozen}")
    manifest = json.loads(manifest_path.read_text())
    entry = next(
        (
            item
            for item in manifest
            if item["symbol"] == sym and item["adjust"] == adjust
        ),
        None,
    )
    if entry is None:
        raise FileNotFoundError(f"冻结版本 {frozen} 无数据: {sym}/{adjust}")
    path = directory / f"{sym}_{adjust or 'raw'}.parquet"
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != entry["sha256"]:
        raise ValueError(f"冻结数据校验失败: {path}")
    return entry, path


def load(
    code: str,
    asof: str | pd.Timestamp | None = None,
    adjust: str = "qfq",
    frozen: str | None = None,
    auto_refresh: bool = True,
) -> pd.DataFrame:
    """PIT 读取缓存或冻结数据，返回含 vintage/source/pit_approx 属性的 DataFrame。"""
    market, six, _ = S.parse_code(code)
    symbol = f"{market}{six}"
    asof_ts = pd.Timestamp(asof) if asof is not None else None
    if frozen is not None:
        entry, path = _frozen_entry(symbol, adjust, frozen)
        df = pd.read_parquet(path)
        pit_approx = asof_ts is not None and asof_ts.normalize() < pd.Timestamp(
            entry["vintage"]
        )
        if asof_ts is not None:
            df = df[df["date"] <= asof_ts].reset_index(drop=True)
        df.attrs.update(
            vintage=entry["vintage"],
            source=entry["source"],
            frozen=frozen,
            pit_approx=pit_approx,
            symbol=symbol,
        )
        return df

    directory = _sym_dir(symbol, adjust)
    manifest = sorted(_manifest(directory), key=lambda item: item["vintage"])
    if not manifest and auto_refresh:
        refresh(code, adjust)
        manifest = sorted(_manifest(directory), key=lambda item: item["vintage"])
    if not manifest:
        raise FileNotFoundError(f"无缓存: {symbol}")
    eligible = [
        item
        for item in manifest
        if asof_ts is None or pd.Timestamp(item["vintage"]) <= asof_ts
    ]
    pit_approx = not eligible
    entry = (eligible or manifest)[-1 if eligible else 0]
    df = pd.read_parquet(entry["path"])
    if asof_ts is not None:
        df = df[df["date"] <= asof_ts].reset_index(drop=True)
    df.attrs.update(
        vintage=entry["vintage"],
        source=entry["source"],
        pit_approx=pit_approx,
        symbol=symbol,
    )
    return df


DEFAULT_FREEZE_CODES = (
    "sh000001",
    "sh000016",
    "sh000300",
    "sh000905",
    "sh000688",
    "sz399001",
    "sz399006",
    "600519",
)


def freeze(name: str, codes=None, adjust: str = "qfq") -> list[dict]:
    """Create a named, checksum-verified data snapshot."""
    if not name or Path(name).name != name:
        raise ValueError(f"无效冻结版本名称: {name}")
    codes = list(DEFAULT_FREEZE_CODES if codes is None else codes)
    target = FROZEN_ROOT / name
    target.mkdir(parents=True, exist_ok=True)
    today = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d")
    records = []
    for code in codes:
        market, six, _ = S.parse_code(code)
        symbol = f"{market}{six}"
        cached_dir = _sym_dir(symbol, adjust)
        current = next(
            (
                item
                for item in _manifest(cached_dir)
                if item["vintage"] == today
                and Path(item["path"]).exists()
            ),
            None,
        )
        if current is None:
            current = asdict(refresh(code, adjust))
        source_path = Path(current["path"])
        frozen_path = target / f"{symbol}_{adjust or 'raw'}.parquet"
        shutil.copyfile(source_path, frozen_path)
        df = pd.read_parquet(frozen_path)
        record = {
            "symbol": symbol,
            "adjust": adjust,
            "source": current["source"],
            "vintage": current["vintage"],
            "downloaded_at": current.get(
                "downloaded_at", pd.Timestamp.now(tz="UTC").isoformat()
            ),
            "rows": len(df),
            "first_date": df["date"].iloc[0].strftime("%Y-%m-%d"),
            "last_date": df["date"].iloc[-1].strftime("%Y-%m-%d"),
            "sha256": hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
            "quality_check": quality_check(df),
            "attempts": current.get("attempts", []),
        }
        records.append(record)
    (target / "manifest.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2)
    )
    lines = [
        f"# 冻结数据版本 {name}",
        "",
        f"复权方式：`{adjust}`。文件内容以各自的 SHA-256 校验。",
        "",
        "| 代码 | 来源 | Vintage | 行数 | 首日 | 末日 |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    lines.extend(
        "| {symbol} | {source} | {vintage} | {rows} | {first_date} | {last_date} |".format(
            **record
        )
        for record in records
    )
    lines.append("")
    (target / "README.md").write_text("\n".join(lines))
    return records
