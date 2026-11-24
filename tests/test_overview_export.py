"""测试轻量全市场摘要生成器 overview_export.py。"""
from __future__ import annotations

import json
from pathlib import Path

from research.pipeline.overview_export import _classify_tier, build_overview, export_overview


def test_build_overview_covers_all_7_indices_and_compact_size(tmp_path: Path):
    data_dir = Path("web/mock/data")
    payload = build_overview(data_dir)
    assert payload["schema_version"] == "overview_v1"
    assert payload["asof"] >= "2026-11-20"
    assert len(payload["indices"]) == 7

    by_sym = {row["sym"]: row for row in payload["indices"]}
    assert by_sym["sh000688"]["tier"] == "bottom_probe"
    assert by_sym["sh000688"]["bottom_score"] == 50.6
    assert by_sym["sh000905"]["tier"] == "neutral"
    assert by_sym["sh000001"]["tier"] == "neutral"
    assert all("target_pct" not in row for row in payload["indices"])

    out = export_overview(data_dir, tmp_path / "overview_latest.json")
    assert out.stat().st_size < 15 * 1024
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert sum(parsed["counts"].values()) == 7


def test_tiers_use_unrounded_score_and_missing_is_unavailable():
    assert _classify_tier(False, 29.9) == "neutral"
    assert _classify_tier(False, 30.0) == "bottom_watch"
    assert _classify_tier(False, 49.9) == "bottom_watch"
    assert _classify_tier(False, 50.0) == "bottom_probe"
    assert _classify_tier(False, None) == "unavailable"
    assert _classify_tier(True, None) == "top_risk"


def test_missing_score_is_not_exported_as_zero(tmp_path: Path):
    missing = {"frames": [{"asof": "2026-11-20", "w": {"6-12m": [None, None]}}]}
    zero = {"frames": [{"asof": "2026-11-20", "fco_neg_intensity": 0.0, "w": {"6-12m": [None, None]}}]}
    (tmp_path / "sh000001_history.json").write_text(json.dumps(missing), encoding="utf-8")
    (tmp_path / "sh000016_history.json").write_text(json.dumps(zero), encoding="utf-8")

    rows = {row["sym"]: row for row in build_overview(tmp_path)["indices"]}
    assert rows["sh000001"]["fco_neg_intensity"] is None
    assert rows["sh000001"]["bottom_score"] is None
    assert rows["sh000001"]["tier"] == "unavailable"
    assert rows["sh000016"]["fco_neg_intensity"] == 0.0
    assert rows["sh000016"]["bottom_score"] == 0.0
    assert rows["sh000016"]["tier"] == "neutral"
