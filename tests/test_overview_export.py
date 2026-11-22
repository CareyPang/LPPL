"""测试轻量全市场摘要生成器 overview_export.py。"""
from __future__ import annotations

import json
from pathlib import Path

from research.pipeline.overview_export import build_overview, export_overview


def test_build_overview_covers_all_7_indices_and_compact_size(tmp_path: Path):
    data_dir = Path("web/mock/data")
    payload = build_overview(data_dir)
    assert payload["schema_version"] == "overview_v1"
    assert payload["asof"] >= "2026-11-20"
    assert len(payload["indices"]) == 7

    by_sym = {row["sym"]: row for row in payload["indices"]}
    assert by_sym["sh000688"]["tier"] == "bottom_probe"
    assert by_sym["sh000688"]["target_pct"] == 30
    assert by_sym["sh000688"]["bottom_score"] >= 50
    assert by_sym["sh000905"]["tier"] == "left_wait"
    assert by_sym["sh000001"]["tier"] == "neutral"

    out = export_overview(data_dir, tmp_path / "overview_latest.json")
    assert out.stat().st_size < 15 * 1024
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert sum(parsed["counts"].values()) == 7
