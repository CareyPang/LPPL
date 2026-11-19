import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("watchlist_archive", ROOT / "scripts/build_watchlist_archive.py")
archive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archive)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


def put(root, name, obj):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(obj, ensure_ascii=False).encode()
    path.write_bytes(raw)
    return raw


def result(symbol, asof, start, evidence="dev"):
    top = {"indicators": {"6-12m": {"n_windows": 5, "signal_status": "signal"}},
           "lppls_confidence": {"6-12m": 0.1, "evidence": "dev", "scale_evidence": {"6-12m": evidence}},
           "scale_windows": [{"scale": "6-12m", "start": start, "end": "2026-11-30", "evidence": "dev"}]}
    return {"symbol": symbol, "asof": asof, "model_version": "v1", "data_version": "data",
            "stock_meta": {"evidence": "research_candidate"}, "top": top}


def seal(root, record):
    date, symbol = record["asof"], record["symbol"]
    path = f"forward_log/{date}/{symbol}.json"
    raw = put(root, path, record)
    return {"symbol": symbol, "asof": date, "path": path, "sha256": hashlib.sha256(raw).hexdigest(),
            "model_version": "v1", "data_version": "data", "sealed_at": f"{date}T08:00:00Z"}


def ledger(root, rows):
    folder = root / "forward_log"
    folder.mkdir(exist_ok=True)
    (folder / "ledger.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def commit(root):
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "fixture")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "--quiet")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    return root


def build(repo, out, ref=None):
    return archive.build(repo, out, ref, ROOT / "frontend/app/research-workspace-core.js")


def load(out, asset):
    return json.loads((out / (asset + ".json")).read_text(encoding="utf-8"))


def test_intermediate_window_revisions_come_from_pinned_blobs(repo, tmp_path):
    rows = []
    for i, start in [(16, "2026-11-21"), (17, "2026-11-23"), (18, "2026-11-21")]:
        raw = result("sh000001", f"2026-11-{i}", start)
        if i == 18:
            raw["price_history"] = {"dates": ["2026-11-17", "2026-11-18"], "close": [1.1, 1.0]}
        rows.append(seal(repo, raw))
    ledger(repo, rows)
    sha = commit(repo)
    # Working tree and latest files cannot change an immutable view of the past.
    (repo / rows[1]["path"]).write_bytes(b"changed")
    out = tmp_path / "site"
    catalog = build(repo, out)
    assert catalog["index_commit"] == sha and catalog["stock_jobs_available"] is False
    record = load(out, "index-sh000001")
    assert [e["kind"] for e in record["events"]] == ["baseline", "window_revised", "window_revised"]
    assert [(e["previous"], e["current"]) for e in record["events"]] == [(None, 0), (0, 1), (1, 2)]
    assert [r["sha256"] for r in record["observations"]] == [r["sha256"] for r in rows]
    for raw in record["observations"]:
        assert raw["public_first_published_at"] is None and raw["generated_at"] is None
        assert f"/{sha}/forward_log/" in raw["source_url"] and raw["provenance"] == "index_seal"
    first, _, last = record["observations"]
    assert first["chart_path"] is None and not first["has_bars"]
    archive_file = last["sha256"] + ".json"
    assert last["chart_path"] == f"watchlist-archive/originals/{archive_file}" and last["has_bars"]
    assert len(last["chart_content_sha256"]) == 64
    assert (out / "originals" / archive_file).read_bytes() == (repo / rows[-1]["path"]).read_bytes()
    before = (out / "index-sh000001.json").read_bytes()
    build(repo, out)
    assert (out / "index-sh000001.json").read_bytes() == before


@pytest.mark.parametrize("damage", ["duplicate", "checksum", "price", "missing", "evidence", "after_cutoff"])
def test_invalid_midpoint_breaks_comparison(repo, tmp_path, damage):
    mids = []
    for i in (16, 17, 18):
        raw = result("sh000001", f"2026-11-{i}", f"2026-11-{i+5}")
        if damage == "price" and i == 17:
            raw["price_history"] = {"dates": ["2026-11-18"], "close": [1.0]}
        if damage == "evidence" and i == 17:
            del raw["top"]["indicators"]
        mids.append(seal(repo, raw))
    if damage == "duplicate":
        mids.append(dict(mids[1]))
    if damage == "checksum":
        mids[1]["sha256"] = "a" * 64
    if damage == "missing":
        (repo / mids[1]["path"]).unlink()
    if damage == "after_cutoff":
        mids[1]["sealed_at"] = "2026-11-18T03:01:00Z"
    ledger(repo, mids)
    commit(repo)
    build(repo, tmp_path / "site")
    record = load(tmp_path / "site", "index-sh000001")
    assert [r["asof"] for r in record["observations"]] == ["2026-11-16", "2026-11-18"]
    assert [e["kind"] for e in record["events"]] == ["baseline", "baseline"]
    assert any(g["asof"] == "2026-11-17" for g in record["gaps"])


def test_stock_job_archive_excludes_replays_and_latest_and_obeys_evidence(repo, tmp_path):
    ledger(repo, [])
    code = "600519"
    for i, (start, evidence) in enumerate([("2026-11-24", "dev"), ("2026-11-26", "dev"),
                                          ("2026-11-24", "fail_i")]):
        job = f"debe3ef0-765f-4146-9966-0d374400000{i}"
        raw = result("sh600519", "2026-11-17", start, evidence)
        raw["price_history"] = {"dates": ["2026-11-17"], "close": [1000.0]}
        raw.update(job_id=job, code=code, mode="current", generated_at=f"2026-11-18T03:0{i}:00+08:00")
        put(repo, f"stock/jobs/{job}/{code}.json", raw)
        put(repo, f"stock/jobs/{job}/{code}_history.json", {"mode": "history", "frames": [raw]})
    put(repo, "stock/600519.json", result("sh600519", "2026-11-18", "2026-11-22"))
    put(repo, "stock/600320.json", result("sh600320", "2026-11-18", "2026-11-22"))
    sha = commit(repo)
    out = tmp_path / "site"
    catalog = build(repo, out, sha)
    assert list(catalog["assets"]) == ["stock:600519"]
    assert catalog["stock_jobs_available"] and catalog["stock_commit"] == sha
    record = load(out, "stock-600519")
    assert [e["kind"] for e in record["events"]] == ["baseline", "window_revised", "state_changed"]
    assert [r["asof"] for r in record["observations"]] == ["2026-11-17"] * 3
    assert record["observations"][-1]["windows"] == []
    for row in record["observations"]:
        assert row["sealed_at"] is None and row["public_first_published_at"] is None
        assert row["provenance"] == "stock_job" and f"/{sha}/stock/jobs/" in row["source_url"]
        assert row["has_bars"] and row["chart_path"] == row["source_url"].split(sha + "/")[1]
        assert len(row["chart_content_sha256"]) == 64
