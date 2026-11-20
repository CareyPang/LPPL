"""Project observations from immutable index seals and individual stock job blobs."""
import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

SHANGHAI = timezone(timedelta(hours=8))
REPO = "https://github.com/CareyPang/LPPL/blob"
STOCK_JOB = re.compile(r"stock/jobs/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/(\d{6})(_error)?\.json")


def day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("invalid asof")
    return value


def stamp(value):
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("invalid archive timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("missing archive timezone")
    return parsed


def as_day(value):
    try:
        return day(value)
    except ValueError:
        return None


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def tree(root, ref, directory):
    entries = git(root, "ls-tree", "-r", "-z", ref, "--", directory).split(b"\0")
    files = {}
    for entry in filter(None, entries):
        meta, path = entry.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        if kind == "blob" and mode in ("100644", "100755"):
            files[path.decode()] = oid
    return files


@contextmanager
def blobs(root):
    """One Git process for all job blobs. Verify content against the pinned tree."""
    with subprocess.Popen(["git", "-C", str(root), "cat-file", "--batch"],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE) as proc:
        def read(oid):
            proc.stdin.write(oid.encode() + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline().split()
            if len(header) != 3 or header[:2] != [oid.encode(), b"blob"]:
                raise ValueError("missing immutable blob")
            raw = proc.stdout.read(int(header[2]))
            if proc.stdout.read(1) != b"\n" or len(raw) != int(header[2]):
                raise RuntimeError("truncated git cat-file stream")
            framed = b"blob " + header[2] + b"\0" + raw
            algorithm = "sha1" if len(oid) == 40 else "sha256"
            if hashlib.new(algorithm, framed).hexdigest() != oid:
                raise ValueError("Git blob fingerprint mismatch")
            return raw
        try:
            yield read
        finally:
            proc.stdin.close()


def observation(raw, raw_bytes, asset, commit, path, sealed_at=None):
    kind, code = asset.split(":")
    cutoff = day(raw["asof"])
    symbol = code if kind == "index" else ("sh" if code.startswith("6") else "sz" if code[0] in "03" else "bj") + code
    if raw.get("symbol") != symbol:
        raise ValueError("asset identity mismatch")
    if not all(isinstance(raw.get(k), str) and raw[k] for k in ("model_version", "data_version")):
        raise ValueError("missing archive version")
    top = raw.get("top")
    if (not isinstance(top, dict) or not isinstance(top.get("indicators"), dict) or not top["indicators"]
            or not isinstance(top.get("lppls_confidence"), dict) or not top["lppls_confidence"]):
        raise ValueError("incomplete model evidence")
    # The first index seals legitimately predate embedded price history. Keep their
    # verified model states. A supplied but inconsistent price series indicates corruption.
    dates = []
    if "price_history" in raw:
        prices = raw["price_history"]
        dates, closes = prices["dates"], prices["close"]
        if (not isinstance(dates, list) or not dates or not isinstance(closes, list)
                or len(dates) != len(closes) or dates != sorted(set(day(d) for d in dates))
                or dates[-1] != cutoff):
            raise ValueError("incomplete asof price series")
    generated = raw.get("generated_at")
    archive_stamp = stamp(sealed_at or generated)
    local = archive_stamp.astimezone(SHANGHAI)
    if local.date().isoformat() < cutoff or (local.date().isoformat() == cutoff and local.time() < time(15)):
        raise ValueError("archive timestamp predates close")
    if sealed_at and local.date().isoformat() != cutoff:
        raise ValueError("index seal outside trading date")
    # Reuse the investor workspace's actual evidence and display policy in one batch.
    # No price arrays, model fitting, history replay or private watchlist are needed.
    summary_input = {k: raw[k] for k in ("symbol", "asof", "model_version", "data_version")}
    summary_input["stock_meta"] = {"evidence": (raw.get("stock_meta") or {}).get("evidence")}
    summary_input["top"] = {k: top[k] for k in ("indicators", "lppls_confidence", "window",
                                                 "scale_windows", "scale_clusters") if k in top}
    fingerprint = hashlib.sha256(raw_bytes).hexdigest()
    return {
        "asof": cutoff, "model_version": raw["model_version"], "data_version": raw["data_version"],
        "sha256": fingerprint, "source_url": f"{REPO}/{commit}/{path}",
        "has_bars": bool(dates),
        "chart_path": ("watchlist-archive/originals/" + fingerprint + ".json" if sealed_at else path) if dates else None,
        "provenance": "index_seal" if sealed_at else "stock_job", "sealed_at": sealed_at,
        "generated_at": generated, "public_first_published_at": None,
        "_previous_day": dates[-2] if len(dates) > 1 else None,
        "_sort": archive_stamp.timestamp(), "_input": summary_input,
    }


def collect_indices(root, commit, read, observations, gaps, originals):
    files = tree(root, commit, "forward_log")
    rows = [json.loads(line) for line in read(files["forward_log/ledger.jsonl"]).splitlines() if line.strip()]
    counts = Counter((r["symbol"], r["asof"]) for r in rows)
    expected = set()
    for row in rows:
        code = row["symbol"]
        if not re.fullmatch(r"(?:sh|sz|bj)\d{6}", code):
            raise ValueError("invalid ledger symbol")
        asset = f"index:{code}"
        cutoff = as_day(row["asof"])
        path = f"forward_log/{cutoff}/{code}.json"
        expected.add(path)
        try:
            if not cutoff or counts[(code, cutoff)] != 1:
                raise ValueError("invalid or duplicate ledger key")
            if row["path"] != path or path not in files:
                raise ValueError("ledger path or blob missing")
            data = read(files[path])
            if hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("seal SHA-256 mismatch")
            raw = json.loads(data)
            if any(raw.get(k) != row[k] for k in ("asof", "model_version", "data_version")):
                raise ValueError("ledger identity or version mismatch")
            stamp(row["sealed_at"])
            entry = observation(raw, data, asset, commit, path, row["sealed_at"])
            observations[asset].append(entry)
            if entry["has_bars"]:
                entry["_chart_blob"] = files[path]
                originals.mkdir(parents=True, exist_ok=True)
                (originals / (entry["sha256"] + ".json")).write_bytes(data)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            gaps[asset].append({"asof": cutoff, "reason": str(exc)})
    for path in files.keys() - expected:
        orphan = re.fullmatch(r"forward_log/(\d{4}-\d{2}-\d{2})/((?:sh|sz|bj)\d{6})\.json", path)
        if orphan:
            gaps["index:" + orphan[2]].append({"asof": as_day(orphan[1]), "reason": "seal missing ledger entry"})


def collect_stocks(root, commit, read, observations, gaps):
    for path, oid in tree(root, commit, "stock/jobs").items():
        job = STOCK_JOB.fullmatch(path)
        if job is None:
            continue
        asset = "stock:" + job[2]
        cutoff = None
        try:
            data = read(oid)
            raw = json.loads(data)
            cutoff = as_day(raw.get("asof"))
            if raw.get("code") != job[2] or raw.get("job_id") != job[1]:
                raise ValueError("job identity mismatch")
            if job[3] and raw.get("mode") == "history":
                continue
            if job[3] or raw.get("mode") != "current":
                # A failed run has no model result. An explicit asof is preferred;
                # a missing asof is disclosed, never repaired with today's date.
                raise ValueError("current job failed or invalid mode")
            entry = observation(raw, data, asset, commit, path)
            if entry["has_bars"]:
                entry["_chart_blob"] = oid
            observations[asset].append(entry)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            gaps[asset].append({"asof": cutoff, "reason": str(exc)})


def summarize(core, observations):
    # Calling the same module as the browser keeps descriptive/failure gates identical.
    program = """
const fs = require('node:fs');
const core = require(process.argv[1]);
const rows = JSON.parse(fs.readFileSync(0, 'utf8'));
const results = rows.map(([id, raw]) => {
  const [kind, code] = id.split(':');
  const summary = core.summarize(core.asset(kind, code), raw);
  if (!summary || !summary.asof) return null;
  return { status: summary.status, windows: summary.windows, evidence: summary.evidence };
});
process.stdout.write(JSON.stringify(results));
"""
    pairs = [(asset, row) for asset, rows in observations.items() for row in rows]
    inputs = [[asset, row.pop("_input")] for asset, row in pairs]
    output = subprocess.run(["node", "-e", program, str(core)], input=json.dumps(inputs).encode(),
                            stdout=subprocess.PIPE, check=True)
    for (_, row), summary in zip(pairs, json.loads(output.stdout), strict=True):
        if not summary:
            raise ValueError("workspace cannot verify this asset identity")
        row.update(summary)


def timeline(asset, rows, gaps):
    rows.sort(key=lambda x: (x["_sort"], x["asof"], x["sha256"]))
    counts = Counter(row["_sort"] for row in rows)
    observations = []
    events = []
    prior = None
    previous_index = None
    for row in rows:
        when = row.pop("_sort")
        previous_day = row.pop("_previous_day")
        if counts[when] != 1:
            gaps.append({"asof": row["asof"], "reason": "ambiguous archive timestamp"})
            prior = None
            continue
        if prior:
            if row["asof"] < prior["asof"]:
                gaps.append({"asof": row["asof"], "reason": "late older-asof job"})
                prior = None
            elif (row["asof"] != prior["asof"] and previous_day != prior["asof"]
                  and (previous_day is not None or
                       date.fromisoformat(row["asof"]) - date.fromisoformat(prior["asof"]) != timedelta(days=1))):
                gaps.append({"asof": row["asof"], "reason": "no adjacent trading observation"})
                prior = None
            elif any(gap["asof"] is None or prior["asof"] <= gap["asof"] <= row["asof"] for gap in gaps
                     if gap["reason"] != "no adjacent trading observation"):
                prior = None
        curr = len(observations)
        observations.append(row)
        kind = None
        if prior is None:
            kind = "baseline"
        elif prior["windows"] != row["windows"]:
            if not prior["windows"]:
                kind = "window_appeared"
            elif row["windows"]:
                kind = "window_revised"
            else:
                kind = "window_ended" if row["status"] in ("no_cluster", "no_qualified_fit") else "state_changed"
        elif any(prior[k] != row[k] for k in ("status", "evidence", "model_version")):
            kind = "state_changed"
        if kind:
            events.append({"kind": kind, "current": curr, "previous": previous_index if prior else None})
        prior, previous_index = row, curr
    gaps = [{"asof": a, "reason": r} for a, r in sorted({(g["asof"], g["reason"]) for g in gaps},
                                                        key=lambda x: (x[0] or "", x[1]))]
    return {"schema_version": 1, "asset_id": asset, "observations": observations, "events": events, "gaps": gaps}


def build(root, out, stock_ref=None, core=None):
    commit = git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    stocks = git(root, "rev-parse", "--verify", stock_ref + "^{commit}").decode().strip() if stock_ref else None
    records, gaps = defaultdict(list), defaultdict(list)
    with blobs(root) as read:
        collect_indices(root, commit, read, records, gaps, out / "originals")
        if stocks:
            collect_stocks(root, stocks, read, records, gaps)
    summarize(core or root / "frontend/app/research-workspace-core.js", records)
    chart_rows = [row for items in records.values() for row in items if row["has_bars"]]
    if chart_rows:
        objects = sorted({row["_chart_blob"] for row in chart_rows})
        helper = Path(__file__).with_name("archive_chart_digests.cjs")
        response = subprocess.run(["node", str(helper), str(root)], input=json.dumps(objects).encode(),
                                  stdout=subprocess.PIPE, check=True)
        digests = json.loads(response.stdout)
        for row in chart_rows:
            digest = digests[row.pop("_chart_blob")]
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("invalid decoded chart digest")
            row["chart_content_sha256"] = digest
    assets = {}
    out.mkdir(parents=True, exist_ok=True)

    def write(name, data):
        (out / name).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"),
                                           allow_nan=False) + "\n", encoding="utf-8")

    for asset in sorted(records.keys() | gaps.keys()):
        payload = timeline(asset, records[asset], gaps[asset])
        name = asset.replace(":", "-") + ".json"
        write(name, payload)
        assets[asset] = {"path": "watchlist-archive/" + name,
                         **{k: len(payload[k]) for k in ("observations", "events", "gaps")}}
    manifest = {"schema_version": 1, "stock_jobs_available": stocks is not None,
                "index_commit": commit, "stock_commit": stocks, "assets": assets}
    write("index.json", manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--stock-ref")
    args = parser.parse_args()
    build(args.root.resolve(), args.out, args.stock_ref)
