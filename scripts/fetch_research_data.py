"""下载并解压不入库的研究数据（data/features、data/labels、data/cache、data/oof）。

数据作为 GitHub Release 附件发布（单文件上限 2 GB，已分卷）。跨平台（Windows 可用）：
    pip install zstandard
    python scripts/fetch_research_data.py            # 默认 tag
    python scripts/fetch_research_data.py --tag research-data-v20261101 --keep
"""
from __future__ import annotations

import argparse
import hashlib
import tarfile
import urllib.request
from pathlib import Path

REPO = "CareyPang/LPPL"
TAG = "research-data-v20261101"
BASE = "lppl_research_data.tar.zst"


def _get(url: str, dest: Path) -> None:
    if dest.exists():
        return
    print("下载", url)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 22):
            f.write(chunk)
    tmp.rename(dest)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=TAG)
    ap.add_argument("--dir", default="data/_download")
    ap.add_argument("--keep", action="store_true", help="保留下载的分卷")
    a = ap.parse_args()
    import zstandard

    root = f"https://github.com/{REPO}/releases/download/{a.tag}/"
    d = Path(a.dir)
    d.mkdir(parents=True, exist_ok=True)
    _get(root + "SHA256SUMS", d / "SHA256SUMS")
    sums = [ln.split() for ln in (d / "SHA256SUMS").read_text().splitlines() if ln.strip()]
    parts = []
    for digest, name in sorted(sums, key=lambda x: x[1]):
        p = d / name
        _get(root + name, p)
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(1 << 22):
                h.update(chunk)
        if h.hexdigest() != digest:
            p.unlink()
            raise SystemExit(f"{name} 校验失败，已删除，请重跑")
        parts.append(p)

    class _Cat:
        def __init__(self, files):
            self.files, self.f = iter(files), None

        def read(self, n=-1):
            while True:
                if self.f is None:
                    nxt = next(self.files, None)
                    if nxt is None:
                        return b""
                    self.f = open(nxt, "rb")
                b = self.f.read(n)
                if b:
                    return b
                self.f.close()
                self.f = None

    with zstandard.ZstdDecompressor().stream_reader(_Cat(parts)) as zr, tarfile.open(fileobj=zr, mode="r|") as tf:
        for m in tf:
            if not m.name.startswith("data/") or ".." in Path(m.name).parts or not (m.isfile() or m.isdir()):
                raise SystemExit(f"非法路径 {m.name}")
            tf.extract(m, ".")
    if not a.keep:
        for p in parts:
            p.unlink()
    print("完成：data/features data/labels data/cache data/oof")


if __name__ == "__main__":
    main()
