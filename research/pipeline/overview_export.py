"""生成全市场轻量摘要 web/mock/data/overview_latest.json（< 15 KB）。

将 7 大宽基指数的最新周度帧（顶部红柱、A 股多维底部综合分、四维因子、50 周历史实证）
汇总为单份紧凑 JSON，供首页、指数终端顶部切换条与历史回测页横向对比条秒级加载，
避免浏览器为渲染总览一次性拉取多份数百 KB 的完整 *_history.json。

用法：
  python -m research.pipeline.overview_export
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DATA_DIR = Path("web/mock/data")

INDEX_LIST: tuple[tuple[str, str, str], ...] = (
    ("sh000001", "上证指数", "000001"),
    ("sh000016", "上证50", "000016"),
    ("sh000300", "沪深300", "000300"),
    ("sh000905", "中证500", "000905"),
    ("sh000688", "科创50", "000688"),
    ("sz399001", "深证成指", "399001"),
    ("sz399006", "创业板指", "399006"),
)


def _classify_tier(has_top: bool, score: float | None) -> str:
    """与前端 frontend/app/bottom-action.js 使用相同的底分档位。"""
    if has_top:
        return "top_risk"
    if score is None:
        return "unavailable"
    if score < 30:
        return "neutral"
    if score < 50:
        return "bottom_watch"
    return "bottom_probe"


def build_overview(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, Any]:
    indices: list[dict[str, Any]] = []
    counts = {"top_risk": 0, "unavailable": 0, "neutral": 0, "bottom_watch": 0, "bottom_probe": 0}
    latest_asof = ""

    for sym, name, code in INDEX_LIST:
        hist_path = data_dir / f"{sym}_history.json"
        if not hist_path.exists():
            continue
        hist = json.loads(hist_path.read_text(encoding="utf-8"))
        frames = hist.get("frames") or []
        if not frames:
            continue
        last = frames[-1]
        asof = str(last.get("asof") or "")
        if asof > latest_asof:
            latest_asof = asof

        w6 = (last.get("w") or {}).get("6-12m")
        has_top = bool(isinstance(w6, list) and len(w6) == 2 and w6[0])
        raw_value = last.get("fco_neg_intensity")
        raw_neg = float(raw_value) if raw_value is not None else None
        score = round(raw_neg * 100, 1) if raw_neg is not None else None
        factors = last.get("bottom_factors") or None
        tier = _classify_tier(has_top, score)
        counts[tier] = counts.get(tier, 0) + 1

        bs = hist.get("bottom_summary") or {}
        summary = {
            "n_events": bs.get("n_events"),
            "win_rate_50w": bs.get("win_rate_50w"),
            "baseline_win_rate_50w": bs.get("baseline_win_rate_50w"),
            "win_rate_lift_50w": bs.get("win_rate_lift_50w"),
            "median_ret_50w": bs.get("median_ret_50w"),
            "median_post_min_50w": bs.get("median_post_min_50w"),
        } if bs else None

        indices.append(
            {
                "sym": sym,
                "name": name,
                "code": code,
                "asof": asof,
                "close": last.get("close"),
                "has_top": has_top,
                "fco_intensity": float(last.get("fco_intensity") or 0.0),
                "fco_neg_intensity": raw_neg,
                "bottom_score": score,
                "bottom_first_alert_flag": bool(last.get("bottom_first_alert_flag")),
                "bottom_factors": factors,
                "bottom_summary": summary,
                "tier": tier,
            }
        )

    return {
        "schema_version": "overview_v1",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof": latest_asof,
        "counts": counts,
        "indices": indices,
    }


def export_overview(data_dir: Path = DEFAULT_DATA_DIR, out_path: Path | None = None) -> Path:
    payload = build_overview(data_dir)
    dest = out_path or (data_dir / "overview_latest.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description="Export lightweight market overview_latest.json")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    dest = export_overview(args.data_dir, args.out)
    size_kb = dest.stat().st_size / 1024.0
    print(f"Exported {dest} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
