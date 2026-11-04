"""Build the corrected v20261104 frozen index dataset without replacing older versions."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import pandas as pd

from research.data.cache import quality_check

ROOT = Path(__file__).resolve().parents[2]
FROZEN_ROOT = ROOT / "data" / "frozen"
SOURCE_ROOT = FROZEN_ROOT / "v20261024"
A90S_ROOT = FROZEN_ROOT / "a90s_v20261104"
OUTPUT_ROOT = FROZEN_ROOT / "v20261104"
VINTAGE = "20261104"
SPLICE_START = pd.Timestamp("2001-01-02")
SPLICE_END = pd.Timestamp("2000-12-29")
SPLICE_SYMBOLS = {"sh000001", "sz399001"}
SOURCE_LABEL = "a90s_v20261104(<=2000-12-29)+v20261024(>=2001-01-02)"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(directory: Path) -> bool:
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        print(f"缺少 manifest: {manifest_path}")
        return False

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    valid = True
    for record in manifest:
        path = directory / f"{record['symbol']}_{record['adjust']}.parquet"
        actual = _sha256(path) if path.is_file() else None
        matches = actual == record["sha256"]
        valid &= matches
        print(
            record["symbol"],
            "OK" if matches else f"HASH MISMATCH (have {actual}, manifest {record['sha256']})",
        )
    return valid


def _normalize_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    frame = frame.loc[:, columns].copy()
    frame["date"] = pd.to_datetime(frame["date"]).astype("datetime64[ns]")
    for column in columns:
        if column != "date":
            frame[column] = pd.to_numeric(frame[column]).astype("float64")
    return frame


def _splice(symbol: str, columns: list[str]) -> pd.DataFrame:
    source = pd.read_parquet(SOURCE_ROOT / f"{symbol}_qfq.parquet")
    a90s = pd.read_parquet(A90S_ROOT / f"{symbol}.parquet")

    old_rows = a90s.loc[a90s["date"] <= SPLICE_END].copy()
    old_rows["volume"] = (old_rows["volume"] / 100).astype("float64")
    old_rows["amount"] = old_rows["amount"].astype("float64")
    old_rows = _normalize_columns(old_rows, columns)

    new_rows = source.loc[source["date"] >= SPLICE_START].copy()
    new_rows = _normalize_columns(new_rows, columns)
    if old_rows.empty or new_rows.empty:
        raise ValueError(f"{symbol}: 拼接边界一侧无数据")

    combined = pd.concat([old_rows, new_rows], ignore_index=True)
    combined = combined.sort_values("date", kind="stable").reset_index(drop=True)
    if combined["date"].duplicated().any():
        raise ValueError(f"{symbol}: 拼接后存在重复日期")
    return combined


def _write_readme(directory: Path, records: list[dict]) -> None:
    lines = [
        f"# 冻结数据版本 v{VINTAGE}",
        "",
        "复权方式：`qfq`。文件内容以各自的 SHA-256 校验。",
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
    lines.extend(
        [
            "",
            "## 与 v20261024 的差异",
            "",
            "按 §21.8，sh000001 与 sz399001 的 2000-12-29 及以前数据采用 "
            "`a90s_v20261104`，其中 OHLC 保持原值、成交量除以 100；"
            "2001-01-02 起的数据来自 `v20261024`。其余六个 parquet 文件与 "
            "`v20261024` 逐字节相同。",
            "",
            "本版本不改变已登记结果或代码默认值，默认仍为 `v20261024`。"
            "sz399001 的 1991-04-03—1994-07-19 属回算段，评价时单列。",
            "",
        ]
    )
    (directory / "README.md").write_text("\n".join(lines), encoding="utf-8")


def build(directory: Path = OUTPUT_ROOT) -> list[dict]:
    if directory.exists():
        raise FileExistsError(f"拒绝覆盖已存在的冻结目录: {directory}")

    source_manifest = json.loads((SOURCE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    source_records = {record["symbol"]: record for record in source_manifest}
    source_files = {path.stem.removesuffix("_qfq"): path for path in SOURCE_ROOT.glob("*_qfq.parquet")}
    if set(source_files) != set(source_records):
        raise ValueError("v20261024 parquet 文件与 manifest 不一致")
    if not SPLICE_SYMBOLS.issubset(source_files):
        raise ValueError("v20261024 缺少待拼接指数文件")

    a90s_manifest = json.loads((A90S_ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    a90s_fetched_at = a90s_manifest["fetched_utc"]
    records = []

    with tempfile.TemporaryDirectory(prefix=".v20261104-", dir=FROZEN_ROOT) as temp_dir:
        staging = Path(temp_dir)
        for source_record in source_manifest:
            symbol = source_record["symbol"]
            filename = f"{symbol}_qfq.parquet"
            output_file = staging / filename
            if symbol in SPLICE_SYMBOLS:
                source_frame = pd.read_parquet(source_files[symbol])
                frame = _splice(symbol, list(source_frame.columns))
                frame.to_parquet(output_file, index=False)
                source_label = SOURCE_LABEL
                downloaded_at = a90s_fetched_at
            else:
                shutil.copyfile(source_files[symbol], output_file)
                frame = pd.read_parquet(output_file)
                source_label = source_record["source"]
                downloaded_at = source_record["downloaded_at"]

            frame = _normalize_columns(frame, list(frame.columns))
            if not frame["date"].is_monotonic_increasing:
                raise ValueError(f"{symbol}: 日期未排序")
            if frame["date"].duplicated().any():
                raise ValueError(f"{symbol}: 存在重复日期")
            if frame["date"].isna().any() or (frame["date"].dt.day_of_week >= 5).any():
                raise ValueError(f"{symbol}: 日期为空或包含周末")
            if (frame[["open", "high", "low", "close"]] <= 0).any().any():
                raise ValueError(f"{symbol}: OHLC 含非正价格")

            record = {
                "symbol": symbol,
                "adjust": source_record["adjust"],
                "source": source_label,
                "vintage": VINTAGE,
                "downloaded_at": downloaded_at,
                "rows": int(len(frame)),
                "first_date": frame["date"].iloc[0].strftime("%Y-%m-%d"),
                "last_date": frame["date"].iloc[-1].strftime("%Y-%m-%d"),
                "sha256": _sha256(output_file),
                "quality_check": quality_check(frame),
                "attempts": source_record.get("attempts", []),
            }
            records.append(record)

        (staging / "manifest.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _write_readme(staging, records)
        if not verify(staging):
            raise ValueError("生成的 v20261104 哈希校验失败")
        if directory.exists():
            raise FileExistsError(f"拒绝覆盖已存在的冻结目录: {directory}")
        staging.rename(directory)

    return records


def main() -> int:
    if OUTPUT_ROOT.exists():
        print(f"{OUTPUT_ROOT.name} 已存在：只校验哈希，不覆写")
        return 0 if verify(OUTPUT_ROOT) else 1

    records = build()
    print(json.dumps(records, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
