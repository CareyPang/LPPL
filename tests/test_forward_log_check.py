import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from research.pipeline import forward_log as fl


def _mk(tmp: Path, monkeypatch, asofs, syms=("sh000001", "sh000016")):
    root = tmp / "forward_log"
    root.mkdir()
    led = root / "ledger.jsonl"
    monkeypatch.setattr(fl, "ROOT", root)
    monkeypatch.setattr(fl, "LEDGER", led)
    for a in asofs:
        for s in syms:
            p = root / a / f"{s}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(dict(symbol=s, asof=a, top={}, bottom={}, model_version="v")))
            row = dict(asof=a, symbol=s, sha256=hashlib.sha256(p.read_bytes()).hexdigest(), sealed_at="x",
                       data_version="d", model_version="v", path=str(p))
            with led.open("a") as f:
                f.write(json.dumps(row) + "\n")
    return root, led


def test_check_clean(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch, ["2026-10-27", "2026-10-28"])
    c = fl.check(max_stale_bdays=10**6)
    assert c["ok"] and not c["bad_hash"] and not c["schema_drift"] and not c["duplicates"] and c["missing_bdays"] == [] and not c["stale"]


def test_check_tamper_detected(tmp_path, monkeypatch):
    root, _ = _mk(tmp_path, monkeypatch, ["2026-10-27"])
    p = root / "2026-10-27" / "sh000001.json"
    d = json.loads(p.read_text())
    d["top"] = {"changed": 1}
    p.write_text(json.dumps(d))
    c = fl.check(max_stale_bdays=10**6)
    assert not c["ok"] and c["bad_hash"] == [str(p)]


def test_check_schema_drift_and_gap(tmp_path, monkeypatch):
    root, led = _mk(tmp_path, monkeypatch, ["2026-10-27", "2026-10-29"])
    p = root / "2026-10-29" / "sh000016.json"
    d = json.loads(p.read_text())
    del d["bottom"]
    d["extra_field"] = 1
    p.write_text(json.dumps(d))
    rows = [json.loads(x) for x in led.read_text().splitlines()]
    for r in rows:
        if r["path"] == str(p):
            r["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    led.write_text("".join(json.dumps(r) + "\n" for r in rows))
    c = fl.check(max_stale_bdays=10**6)
    assert not c["ok"]
    assert c["schema_drift"] == [dict(path=str(p), missing=["bottom"])]
    assert c["schema_added"] == [dict(path=str(p), extra=["extra_field"])]
    assert c["missing_bdays"] == ["2026-10-28"]


def test_trading_days_after_skips_chinese_holidays():
    assert fl._trading_days_after(date(2025, 9, 30), date(2025, 10, 8)) == []


def test_check_missing_days_skip_chinese_holidays(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch, ["2025-09-29", "2025-10-13"])

    c = fl.check(max_stale_bdays=10**6)

    assert c["missing_bdays"] == ["2025-09-30", "2025-10-09", "2025-10-10"]


def test_check_stale_days_skip_chinese_holidays(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch, ["2025-09-30"])

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2025, 10, 8, 12, tzinfo=tz)

    monkeypatch.setattr(fl, "datetime", FrozenDatetime)

    c = fl.check(max_stale_bdays=0)

    assert c["stale_bdays"] == 0 and not c["stale"]


def test_check_counts_null_model_version(tmp_path, monkeypatch):
    _, ledger = _mk(tmp_path, monkeypatch, ["2026-10-27"])
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    rows[0]["model_version"] = None
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))

    c = fl.check(max_stale_bdays=10**6)

    versions = {row["model_version"]: row["count"] for row in c["model_versions"]}
    assert versions == {"<null>": 1, "v": 1}


def test_check_duplicate_and_stale(tmp_path, monkeypatch):
    root, led = _mk(tmp_path, monkeypatch, ["2026-10-27"])
    led.write_text(led.read_text() + led.read_text().splitlines()[0] + "\n")
    c = fl.check(max_stale_bdays=0)
    assert not c["ok"] and len(c["duplicates"]) == 2 and c["stale"]


@pytest.mark.skipif(not Path("forward_log/ledger.jsonl").exists(), reason="仓库内无 ledger")
def test_repo_ledger_hashes_intact():
    c = fl.check(max_stale_bdays=10**6)
    assert c["bad_hash"] == [] and c["duplicates"] == [] and c["schema_drift"] == []


def test_alarm_matrix_from_ledger(tmp_path, monkeypatch):
    import numpy as np
    import pandas as pd

    root, _ = _mk(tmp_path, monkeypatch, ["2026-10-27", "2026-10-28", "2026-10-29"])
    p = root / "2026-10-28" / "sh000001.json"
    d = json.loads(p.read_text())
    d["top"] = {"indicators": {"12-24m": {"confidence": {"box": 0.3, "standard": 0.0, "end": None}}}}
    p.write_text(json.dumps(d))
    led = fl._ledger()
    led = led[led.symbol == "sh000001"]
    cal = pd.DatetimeIndex(pd.bdate_range("2026-10-20", "2026-11-30"))
    gpos, al = fl._alarm_matrix(led, cal, mature_end=len(cal) - 1, q=0.05)
    assert list(cal[gpos].strftime("%Y-%m-%d")) == ["2026-10-27", "2026-10-28", "2026-10-29"]
    assert al["box__12-24m"].tolist() == [False, True, False]
    assert not al["standard__12-24m"].any() and not al["end__12-24m"].any() and not al["box__6-12m"].any()
    gpos2, _ = fl._alarm_matrix(led, cal, mature_end=int(np.flatnonzero(cal == "2026-10-27")[0]), q=0.05)
    assert len(gpos2) == 1
