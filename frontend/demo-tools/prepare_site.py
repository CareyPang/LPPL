"""Prepare an independent, presentation-only Sites checkout from this frontend."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
MODE_SWITCH = "const demoMode = new URLSearchParams(location.search).get('demo') === '1';"


def prepare(site_root: Path) -> dict:
    site_root = site_root.resolve()
    if site_root == ROOT or ROOT in site_root.parents:
        raise ValueError("use a separate Sites checkout, outside the LPPL repository")
    manifest = json.loads((site_root / ".openai/hosting.json").read_text(encoding="utf-8"))
    if not manifest.get("project_id") or manifest.get("static", {}).get("directory") != "dist":
        raise ValueError("persist the selected Site ID and static.directory=dist first")
    target = site_root / "dist"
    if target.is_symlink():
        raise ValueError("dist must not be a symlink")
    if target.exists() and any(target.iterdir()) and not (target / "preview-build.json").is_file():
        raise ValueError("refusing to replace an unrelated static directory")
    stock = (FRONTEND / "stock.html").read_text(encoding="utf-8")
    if stock.count(MODE_SWITCH) != 1:
        raise ValueError("stock mode switch changed; review the presentation isolation")
    target.mkdir(parents=True, exist_ok=True)
    inputs = {}
    sources = [FRONTEND / "home.html", FRONTEND / "stock.html"]
    for directory in ("app", "assets"):
        sources.extend(sorted((FRONTEND / directory).rglob("*")))
    for source in sources:
        if not source.is_file():
            continue
        relative = source.relative_to(FRONTEND)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        inputs[relative.as_posix()] = hashlib.sha256(source.read_bytes()).hexdigest()
    stock = stock.replace(MODE_SWITCH, "const demoMode = true; // Hosted presentation only; URL cannot enable production.")
    stock = stock.replace("离线演示", "交互演示")
    (target / "stock.html").write_text(stock, encoding="utf-8", newline="\n")
    for name in ("home.html", "stock.html"):
        page = (target / name).read_text(encoding="utf-8")
        page = page.replace("<head>", '<head>\n<meta name="robots" content="noindex, nofollow">', 1)
        (target / name).write_text(page, encoding="utf-8", newline="\n")
    (target / "index.html").write_text(
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="robots" content="noindex, nofollow">'
        '<meta http-equiv="refresh" content="0;url=home.html?demo=1">'
        '<title>临界点 · 海洋观测台预览</title></head>'
        '<body><a href="home.html?demo=1">进入海洋观测台预览</a></body></html>\n',
        encoding="utf-8", newline="\n")
    (target / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8", newline="\n")
    outputs = {p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(target.rglob("*")) if p.is_file() and p.name != "preview-build.json"}
    result = {
        "purpose": "INDEPENDENT_PRESENTATION_SITE_NO_MODEL_EXECUTION",
        "lppl_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "site_project_id": manifest["project_id"],
        "transformations": ["force stock demoMode=true, including direct URLs and demo=0",
                            "replace stock offline-demo label with interactive-demo label",
                            "add noindex hints and index redirect"],
        "inputs_sha256": inputs,
        "outputs_sha256": outputs,
    }
    (target / "preview-build.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    (site_root / ".gitattributes").write_text("* -text\n", encoding="utf-8", newline="\n")
    return {"project_id": manifest["project_id"], "directory": str(target),
            "lppl_commit": result["lppl_commit"], "files": len(outputs)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().site_root), ensure_ascii=False))
