"""Build the existing isolated Sites preview with its own real-compute bridge.

No production LPPL endpoint, Pages branch, or production deployment is changed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
PROJECT = "appgprj_6aedbc87f8808191b58788204795e049"

def prepare(site_root: Path) -> dict:
    site_root = site_root.resolve()
    if ROOT == site_root or ROOT in site_root.parents:
        raise ValueError("use the independent preview checkout")
    config_file = site_root / ".openai/hosting.json"
    config = json.loads(config_file.read_text(encoding="utf-8"))
    if config.get("project_id") != PROJECT:
        raise ValueError("this build is restricted to the existing independent preview")
    target = site_root / "dist"
    if target.is_symlink() or target.resolve().parent != site_root:
        raise ValueError("generated dist must be a regular direct child of the preview checkout")
    if target.exists() and not any((target / path).is_file() for path in
                                   ["preview-build.json", "client/preview-build.json"]):
        raise ValueError("refusing to replace an unrelated dist directory")
    stage = Path(tempfile.mkdtemp(prefix="lppl-real-site-"))
    source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    try:
        client = stage / "client"
        client.mkdir()
        for directory in ["app", "assets"]:
            shutil.copytree(FRONTEND / directory, client / directory)
        for name in ["home.html", "stock.html"]:
            page = (FRONTEND / name).read_text(encoding="utf-8")
            page = page.replace("<head>", '<head>\n<meta name="robots" content="noindex,nofollow">', 1)
            if name == "stock.html":
                page = page.replace('<script src="app/lppl-data.js"></script>',
                    '<script>window.LPPL_REAL_PREVIEW=true;window.LPPL_QUERY_API="/api/preview";</script>\n'
                    '<script src="app/lppl-data.js"></script>')
            (client / name).write_text(page, encoding="utf-8", newline="\n")
        (client / "index.html").write_text(
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="robots" content="noindex,nofollow">'
            '<meta http-equiv="refresh" content="0;url=home.html">'
            '<title>临界点 · 海洋观测台</title></head><body>'
            '<a href="home.html">进入海洋观测台</a></body></html>', encoding="utf-8")
        (client / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
        config.pop("static", None)
        config["d1"] = "DB"
        config["r2"] = None
        (stage / "server").mkdir()
        shutil.copy2(FRONTEND / "demo-tools/preview-worker.mjs", stage / "server/index.js")
        result = {"purpose": "ISOLATED_REAL_CURRENT_RESEARCH_PREVIEW", "lppl_commit": source_sha,
                  "site_project_id": PROJECT, "assets": ["sh000001", "sh600519"],
                  "production_pages_enabled": False,
                  "outputs_sha256": {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sorted(stage.rglob("*")) if p.is_file()}}
        (client / "preview-build.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        # The resolved target was checked above and is generated output identified by its manifest.
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(stage, target)
        config_file.write_text(json.dumps(config, indent=2)+"\n", encoding="utf-8")
        (target / ".openai").mkdir()
        shutil.copy2(config_file, target / ".openai/hosting.json")
        migrations = site_root / "drizzle"
        (migrations / "meta").mkdir(parents=True, exist_ok=True)
        sql = (FRONTEND / "demo-tools/preview-schema.sql").read_text(encoding="utf-8")
        existing = migrations / "0000_preview.sql"
        if existing.exists() and existing.read_text(encoding="utf-8") != sql:
            raise ValueError("existing migration is immutable; create a new migration")
        existing.write_text(sql, encoding="utf-8", newline="\n")
        journal = {"version": "7", "dialect": "sqlite", "entries": [{"idx": 0, "version": "6",
                   "when": 1794010000000, "tag": "0000_preview", "breakpoints": True}]}
        (migrations / "meta/_journal.json").write_text(json.dumps(journal, indent=2)+"\n", encoding="utf-8")
        return {"project_id": PROJECT, "directory": str(target), "lppl_commit": source_sha,
                "files": len(result["outputs_sha256"])}
    finally:
        shutil.rmtree(stage)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().site_root), ensure_ascii=False))
