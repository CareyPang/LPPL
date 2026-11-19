from __future__ import annotations

import argparse
import json
from numbers import Integral
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd

from research.data import top_risk
from research.data.sources import fetch_ak_csindex_index
from research.data.top_risk_episodes import INDEXES

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


def _stored_states(code: str, rows: list[dict], asof: str) -> dict[str, dict]:
    if not isinstance(rows, list):
        raise ValueError(f"{code}: expected an array of stored risk states")
    states = {}
    flags = ("concentration_on", "margin_on", "index_on")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{code}: invalid stored risk state")
        date = row.get("date")
        if not isinstance(date, str) or date != top_risk._date_text(date):
            raise ValueError(f"{code}: invalid risk state date {date!r}")
        if date in states or date > asof:
            raise ValueError(f"{code}: duplicate or future risk state {date}")
        count = row.get("n_on")
        if isinstance(count, bool) or not isinstance(count, Integral) or not 0 <= count <= 3:
            raise ValueError(f"{code}: invalid stored n_on on {date}")
        if any(field in row for field in flags) and (
            not all(isinstance(row.get(field), bool) for field in flags)
            or sum(row[field] for field in flags) != count
        ):
            raise ValueError(f"{code}: stored risk flags disagree with n_on on {date}")
        states[date] = row
    return states


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
        require_full_windows=True,
    )
    previous_states = previous_states or {}
    states = {}
    for code, rows in current_states.items():
        merged = _stored_states(code, previous_states.get(code, []), asof)
        for row in rows:
            merged.setdefault(row["date"], row)
        states[code] = [merged[day] for day in sorted(merged)]
    history_dir = history_dir or ROOT / "web" / "mock" / "data"
    outputs = {}
    for code, _ in INDEXES:
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
            asof=str(frame["date"].iloc[-1]),
            missing_open_days=int(frame["open"].isna().sum()),
        )
        outputs[code] = result
    # Stage every byte before exposing any output. A new output directory appears
    # in one rename; existing destinations receive complete files, with history last.
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=out_dir.parent) as scratch:
        staged = Path(scratch) / "strategy"
        staged.mkdir()
        files = {**outputs, "n_on_history": states}
        for name, content in files.items():
            (staged / f"{name}.json").write_text(
                json.dumps(content, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
        if not out_dir.exists():
            staged.rename(out_dir)
        else:
            for name in files:
                (staged / f"{name}.json").replace(out_dir / f"{name}.json")
    return outputs


def run_live(
    asof: str,
    breadth_path: Path,
    out_dir: Path,
    previous_history_path: Path | None = None,
) -> dict[str, Any]:
    seed_path = ROOT / "data" / "top_risk_n_on_history.json"
    history_path = (
        previous_history_path
        if previous_history_path and previous_history_path.is_file()
        else seed_path
    )
    if not history_path.is_file():
        raise FileNotFoundError(
            "R-TR1 requires a historical n_on seed or previous strategy/n_on_history.json; "
            "the daily snapshot cannot reconstruct the development period"
        )
    previous_states = json.loads(history_path.read_text(encoding="utf-8"))
    breadth_snapshot = json.loads(breadth_path.read_text(encoding="utf-8"))
    breadth_history = top_risk._clean_breadth_history(breadth_snapshot, asof)
    margin_rows = top_risk.fetch_margin_history(asof)
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
