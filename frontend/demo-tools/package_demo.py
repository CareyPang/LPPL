"""Package the real home/stock pages and local assets; never deploy or overwrite."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    target = args.out.resolve()
    archive = target.with_suffix(".zip")
    if target.exists() or archive.exists():
        raise FileExistsError("choose a new artifact destination; existing demos are preserved")
    target.mkdir(parents=True, exist_ok=False)
    for name in ("home.html", "stock.html"):
        shutil.copy2(FRONTEND / name, target / name)
    for name in ("app", "assets", "demo-data"):
        source = FRONTEND / name
        if source.exists():
            shutil.copytree(source, target / name)
    for name in ("Start-Demo.ps1", "Start-Demo.cmd"):
        shutil.copy2(Path(__file__).parent / name, target / name)
    (target / "index.html").write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=home.html?demo=1"><a href="home.html?demo=1">打开海洋观测台演示</a>\n', encoding="utf-8", newline="\n")
    (target / "打开演示说明.txt").write_text(
        "临界点 · 海洋观测台演示\n\n"
        "Windows：解压整个文件夹，双击 Start-Demo.cmd。浏览器将自动打开。\n"
        "无需安装Python或Node；不需要账户，不会发布到网络。演示结束关闭启动窗口即可。\n"
        "其他系统或不启动服务：打开 index.html，可使用静态海面和离线工作站；完整视频下潜请用本地HTTP服务。\n\n"
        "演示顺序：海面首页 → 下潜了解两级时间结构 → 进入工作站 → 选择演示资产 → 查看K线和成交量 → 演示任务状态。\n"
        "行情为明确标注日期的历史快照，任务为界面演示；不运行模型，不产生真实预测或交易建议。\n"
        "实际回测结果与真实提前发布记录分开研究；本演示不声称已能精确预测顶部。\n"
        "如字体服务离线，页面自动使用系统字体。\n", encoding="utf-8", newline="\n")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    files = {p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(target.rglob("*")) if p.is_file()}
    manifest = {"purpose": "LOCAL_PRESENTATION_DEMO_NOT_PRODUCTION", "base_commit": revision,
                "source_state": "working-tree files; file hashes are authoritative", "files_sha256": files}
    (target / "demo-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(target.rglob("*")):
            if path.is_file():
                bundle.write(path, target.name + "/" + path.relative_to(target).as_posix())
    print(json.dumps({"folder": str(target), "zip": str(archive), "bytes": archive.stat().st_size,
                      "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "files": len(files)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
