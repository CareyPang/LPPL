import hashlib
import json
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts.build_guanshi_seals import BAR_LIMIT, SYMBOL, build, project


def fixture(asof="2026-11-16"):
    days = [(date.fromisoformat(asof) - timedelta(days=n)).isoformat()
            for n in reversed(range(BAR_LIMIT + 1))]
    original = {
        "symbol": SYMBOL, "name": "上证指数", "asof": asof, "model_version": "m", "data_version": "d",
        "price_history": {"dates": days, "close": list(range(1, len(days) + 1))},
        "top": {"scale_windows": [], "lppls_confidence": {"scale_evidence": {"2-4w": "dev"}}},
    }
    raw = json.dumps(original).encode("utf-8")
    row = {
        "symbol": SYMBOL, "asof": asof, "model_version": "m", "data_version": "d",
        "path": f"forward_log/{asof}/{SYMBOL}.json", "sealed_at": f"{asof}T13:00:00Z",
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return row, raw


def test_compact_index_retains_original_vintage_and_byte_proof():
    row, raw = fixture()
    result = project(row, raw, "a" * 40)
    ph = result["record"]["price_history"]
    assert ph["dates"] == json.loads(raw)["price_history"]["dates"][-BAR_LIMIT:]
    assert ph["close"][-1] == BAR_LIMIT + 1
    assert "volume" not in ph
    assert result["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["path"].endswith("/blob/" + "a" * 40 + "/" + row["path"])
    assert result["sealed_at"] == row["sealed_at"]
    assert "first_visible_at" not in result


@pytest.mark.parametrize(
    "patch",
    [
        {"sealed_at": "2026-11-16T16:01:00Z"},  # 00:01 on the next local day
        {"sealed_at": "2026-11-16T06:59:59Z"},  # before the Shanghai close
        {"sealed_at": "2026-11-16T15:00:00"},  # unknown offset
        {"sha256": "0" * 64},
        {"model_version": "changed"},
        {"data_version": ""},
        {"path": "forward_log/2026-11-17/sh000001.json"},
        {"symbol": "sh600519"},
    ],
)
def test_unverified_seal_never_enters_the_catalog(patch):
    row, raw = fixture()
    with pytest.raises(ValueError):
        project(row | patch, raw, "a" * 40)


def test_later_bars_cannot_be_smuggled_into_the_original_seal():
    row, raw = fixture()
    original = json.loads(raw)
    original["price_history"]["dates"].append("2026-11-17")
    raw = json.dumps(original).encode()
    row["sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="cutoff"):
        project(row, raw, "a" * 40)


def test_uses_only_committed_bytes_and_fails_closed_on_duplicate_ledger_key(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args])

    git("init", "-q")
    git("config", "core.autocrlf", "false")
    git("config", "commit.gpgsign", "false")
    rows = []
    for asof in ["2026-11-16", "2026-11-17"]:
        row, raw = fixture(asof)
        rows.append(row)
        source = tmp_path / row["path"]
        source.parent.mkdir(parents=True)
        source.write_bytes(raw)
    rows.append(rows[1])
    (tmp_path / "forward_log/ledger.jsonl").write_bytes(
        b"\n".join(json.dumps(row).encode() for row in rows)
    )
    git("add", "forward_log")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "seal")
    (Path(tmp_path) / rows[0]["path"]).write_text("changing the checkout cannot change the seal")
    assert [r["asof"] for r in build(tmp_path)["records"]] == ["2026-11-16"]
