"""计划 H：季度复盘工具对注入的缺日/篡改/版本切换/报警簇是否正确出表。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from research.pipeline.forward_review import quarter_range, review_quarter


def _mk(root: Path, asof: str, sym: str, conf: float = 0.0, model: str = "m1") -> None:
    d = root / asof
    d.mkdir(parents=True, exist_ok=True)
    j = {"symbol": sym, "asof": asof, "top": {"indicators": {"12-24m": {"confidence": {"box": conf, "standard": 0.0, "end": 0.0}},
                                                             "6-12m": {"confidence": {"box": 0.0, "standard": 0.0, "end": 0.0}}}}}
    p = d / f"{sym}.json"
    p.write_text(json.dumps(j))
    rec = dict(asof=asof, symbol=sym, sha256=hashlib.sha256(p.read_bytes()).hexdigest(), sealed_at=asof,
               data_version="v", model_version=model, path=f"forward_log/{asof}/{sym}.json")
    with (root / "ledger.jsonl").open("a") as f:
        f.write(json.dumps(rec) + "\n")


def test_quarter_range():
    a, b = quarter_range("2026Q4")
    assert a == pd.Timestamp("2026-10-01") and b == pd.Timestamp("2026-12-31")


def test_injections(tmp_path, monkeypatch):
    import research.pipeline.forward_review as fr

    monkeypatch.setattr(fr, "trading_days", lambda s, e, sym: pd.bdate_range(s, e))
    days = [d.date().isoformat() for d in pd.bdate_range("2026-10-05", "2026-10-13")]  # 7 个工作日
    for i, d in enumerate(days):
        if d == "2026-10-08":
            continue  # 注入缺日
        _mk(tmp_path, d, "sh000001", conf=0.3 if d in ("2026-10-09", "2026-10-12") else 0.0, model="m1" if i < 4 else "m2")
        _mk(tmp_path, d, "sz399001")
    # 注入篡改
    p = tmp_path / "2026-10-06" / "sz399001.json"
    p.write_text(p.read_text().replace("0.0", "0.9", 1))

    tab, miss, ev = review_quarter("2026Q4", tmp_path)
    assert ev == "descriptive"
    t = tab.set_index("symbol")
    assert t.loc["sh000001", "n_sealed"] == 6 and t.loc["sz399001", "n_sealed"] == 6
    assert t.loc["sz399001", "n_tampered"] == 1 and t.loc["sh000001", "n_tampered"] == 0
    assert t.loc["sh000001", "n_alarm_clusters"] == 1 and "box__12-24m:2026-10-09..2026-10-12(n=2)" in t.loc["sh000001", "alarm_clusters"]
    assert t.loc["sz399001", "n_alarm_clusters"] == 0
    assert "m1:2026-10-05..2026-10-07(n=3)" in t.loc["sh000001", "model_versions"] and "m2:" in t.loc["sh000001", "model_versions"]
    assert set(miss[miss.symbol == "sh000001"].date) == {"2026-10-08"} and set(miss[miss.symbol == "sz399001"].date) == {"2026-10-08"}
    # 季度外无记录
    tab2, miss2, _ = review_quarter("2026Q3", tmp_path)
    assert len(tab2) == 0 and len(miss2) == 0
