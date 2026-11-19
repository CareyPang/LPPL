from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from research.data import top_risk
from research.data.sources import fetch_ak_csindex_index
from research.data.top_risk_episodes import (
    INDEXES,
    build_episode_report,
)

from .report import build_strategy_report

ROOT = Path(__file__).resolve().parents[2]


def _frame_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    normalized = frame.copy()
    normalized["date"] = pd.to_datetime(normalized["date"]).dt.strftime("%Y-%m-%d")
    return normalized.to_dict("records")


def _strategy_prices(frame: pd.DataFrame, asof: str) -> pd.DataFrame:
    prices = frame.copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.strftime("%Y-%m-%d")
    prices = prices.loc[
        (prices["date"] <= asof)
        & prices["date"].ge("2014-01-01")
        & prices["date"].ne("2005-01-01")
    ].sort_values("date")
    if "prev_close" not in prices:
        prices["prev_close"] = prices["close"].shift(1)
    prices["prev_close"] = prices["prev_close"].fillna(prices["close"])
    return prices.loc[
        :, ["date", "open", "high", "low", "close", "prev_close"]
    ].reset_index(drop=True)


def build_outputs(
    breadth_history: list[dict[str, Any]],
    margin_rows: list[dict[str, Any]],
    index_histories: dict[str, list[dict[str, Any]]],
    price_frames: dict[str, pd.DataFrame],
    asof: str,
    out_dir: Path,
    history_dir: Path | None = None,
    previous_states: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, dict[str, Any]]:
    current_states = top_risk.build_n_on_history(
        breadth_history,
        margin_rows,
        index_histories,
    )
    previous_states = previous_states or {}
    states = {}
    for code, rows in current_states.items():
        merged = {
            row["date"]: row
            for row in previous_states.get(code, [])
            if row.get("date") is not None
        }
        merged.update({row["date"]: row for row in rows})
        states[code] = [merged[day] for day in sorted(merged)]
    episode_report = build_episode_report(states, index_histories)
    episode_by_name = {
        name: [
            row for row in episode_report["episodes"] if row["index"] == name
        ]
        for _, name in INDEXES
    }
    history_dir = history_dir or ROOT / "web" / "mock" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for code, name in INDEXES:
        frame = _strategy_prices(price_frames[code], asof)
        state_frame = pd.DataFrame(states[code])
        if state_frame.empty:
            n_on = pd.Series(dtype=float)
        else:
            state_frame = state_frame.set_index("date")
            n_on = state_frame["n_on"]
        history_path = history_dir / f"{code}_history.json"
        frames = (
            json.loads(history_path.read_text(encoding="utf-8")).get("frames", [])
            if history_path.is_file()
            else []
        )
        result = build_strategy_report(
            code,
            frame,
            n_on,
            frames,
            episode_by_name[name],
            asof=str(frame["date"].iloc[-1]),
            missing_open_days=int(frame["open"].isna().sum()),
        )
        destination = out_dir / f"{code}.json"
        destination.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        outputs[code] = result
    (out_dir / "n_on_history.json").write_text(
        json.dumps(states, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return outputs


def run_live(
    asof: str,
    breadth_path: Path,
    out_dir: Path,
    previous_history_path: Path | None = None,
) -> dict[str, Any]:
    breadth_snapshot = json.loads(breadth_path.read_text(encoding="utf-8"))
    breadth_history = top_risk._clean_breadth_history(breadth_snapshot, asof)
    margin_rows = top_risk.fetch_margin_history(asof)
    seed_path = ROOT / "data" / "top_risk_n_on_history.json"
    history_path = (
        previous_history_path
        if previous_history_path and previous_history_path.is_file()
        else seed_path
    )
    previous_states = (
        json.loads(history_path.read_text(encoding="utf-8"))
        if history_path.is_file()
        else {}
    )
    price_frames = {}
    index_histories = {}
    for code, _ in INDEXES:
        frame = fetch_ak_csindex_index(
            code[:2],
            code[2:],
            True,
            start="20050101",
            end=asof.replace("-", ""),
        )
        frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
        frame = frame.loc[
            (frame["date"] <= asof) & frame["date"].ne("2005-01-01")
        ].sort_values("date")
        price_frames[code] = frame
        index_histories[code] = _frame_rows(frame[["date", "close"]])
    return build_outputs(
        breadth_history,
        margin_rows,
        index_histories,
        price_frames,
        asof,
        out_dir,
        previous_states=previous_states,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build and publish descriptive strategy replay JSON"
    )
    parser.add_argument("--date", required=True)
    parser.add_argument("--breadth", type=Path, default=Path("out/market/breadth_latest.json"))
    parser.add_argument("--out", type=Path, default=Path("out/strategy"))
    parser.add_argument("--previous-history", type=Path)
    args = parser.parse_args(argv)
    day = top_risk._date_text(args.date)
    result = run_live(day, args.breadth, args.out, args.previous_history)
    print(
        json.dumps(
            {
                code: {
                    "asof": value["asof"],
                    "selected_variant": value["selected_variant"],
                }
                for code, value in result.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
