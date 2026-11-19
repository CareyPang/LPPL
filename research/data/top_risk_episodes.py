from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import top_risk

INDEXES = (
    ("sh000001", "上证指数"),
    ("sh000300", "沪深300"),
    ("sh000852", "中证1000"),
    ("sh000688", "科创50"),
)
DEFINITION = (
    "集中度前100名成交额占比5日均值≥30%，融资余额252日分位≥80%，"
    "指数收盘价252日分位≥80%且离250日低点涨幅≥15%，三项同时满足；"
    "相隔≤20个交易日的合并为一段"
)
JUDGE_DEFINITION = (
    "之后120个交易日不再高出该段最高价5%以上，且最大回撤≥10%，"
    "记为“顶部区间”，否则“偏早”"
)


def clusters(on: list[bool] | np.ndarray, gap: int = 20) -> list[tuple[int, int]]:
    indexes = np.flatnonzero(on)
    groups: list[list[int]] = []
    for index in indexes:
        value = int(index)
        if groups and value - groups[-1][1] <= gap:
            groups[-1][1] = value
        else:
            groups.append([value, value])
    return [(start, end) for start, end in groups]


def judge(
    prices: pd.Series, start: int, end: int, up: float = 0.05, drawdown: float = 0.10
) -> bool | None:
    if end + 121 > len(prices):
        return None
    peak = prices.iloc[start : end + 1].max()
    after = prices.iloc[end + 1 : end + 121]
    return bool(
        after.max() <= peak * (1 + up)
        and after.min() <= peak * (1 - drawdown)
    )


def build_episode_report(
    n_on_history: dict[str, list[dict[str, Any]]],
    index_histories: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "definition": DEFINITION,
        "judge": JUDGE_DEFINITION,
        "episodes": [],
        "stats": [],
    }
    rng = np.random.default_rng(0)

    for code, name in INDEXES:
        prices = index_histories.get(code, [])
        states = n_on_history.get(code, [])
        close_by_date = {
            top_risk._date_text(row["date"]): float(row["close"])
            for row in prices
            if row.get("date") is not None
            and np.isfinite(pd.to_numeric(row.get("close"), errors="coerce"))
        }
        dates = sorted(close_by_date)
        if not dates:
            continue
        price = pd.Series(
            [close_by_date[day] for day in dates],
            index=pd.Index(dates, name="date"),
            dtype=float,
        )
        states_by_date = {
            top_risk._date_text(row["date"]): row for row in states
        }
        on = np.asarray(
            [states_by_date.get(day, {}).get("n_on") == 3 for day in dates],
            dtype=bool,
        )
        position_on = np.asarray(
            [states_by_date.get(day, {}).get("index_on", False) for day in dates],
            dtype=bool,
        )
        groups = clusters(on)
        results: list[bool] = []

        for start, end in groups:
            episode_peak = float(price.iloc[start : end + 1].max())
            after = price.iloc[end + 1 : end + 121]
            result = judge(price, start, end)
            report["episodes"].append(
                {
                    "index": name,
                    "start": dates[start],
                    "end": dates[end],
                    "days": int(on[start : end + 1].sum()),
                    "peak": round(episode_peak, 2),
                    "after120_max_pct": round(
                        float(after.max() / episode_peak - 1), 4
                    )
                    if len(after)
                    else None,
                    "after120_min_pct": round(
                        float(after.min() / episode_peak - 1), 4
                    )
                    if len(after)
                    else None,
                    "verdict": None
                    if result is None
                    else ("顶部区间" if result else "偏早"),
                }
            )
            if result is not None:
                results.append(result)

        candidates = np.flatnonzero(position_on[: max(0, len(dates) - 121)])
        median_length = (
            int(np.median([end - start + 1 for start, end in groups]))
            if groups
            else 1
        )
        simulations = [
            np.mean(
                [
                    judge(
                        price,
                        int(start),
                        min(int(start) + median_length - 1, len(dates) - 122),
                    )
                    for start in rng.choice(candidates, max(1, len(results)))
                ]
            )
            for _ in range(300)
        ] if len(candidates) else []
        report["stats"].append(
            {
                "index": name,
                "n": len(results),
                "hit": round(float(np.mean(results)), 3) if results else None,
                "base": round(float(np.mean(simulations)), 3)
                if simulations
                else None,
            }
        )
    return report


def build_top_risk_episodes(
    breadth_history: list[dict[str, Any]],
    margin_rows: list[dict[str, Any]],
    index_histories: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    states = top_risk.build_n_on_history(
        breadth_history,
        margin_rows,
        index_histories,
    )
    return build_episode_report(states, index_histories), states


def _read_table(path: Path) -> pd.DataFrame:
    frame = (
        pd.read_parquet(path)
        if path.suffix.lower() == ".parquet"
        else pd.read_csv(path)
    )
    if "date" not in frame.columns:
        frame = frame.rename(columns={frame.columns[0]: "date"})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )
    return frame.dropna(subset=["date"])


def _load_inputs(
    breadth_path: Path,
    concentration_path: Path,
    margin_path: Path,
    price_specs: list[str],
    asof: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    breadth = _read_table(breadth_path)
    concentration = _read_table(concentration_path)
    margin = _read_table(margin_path)
    breadth = breadth.merge(
        concentration[["date", "top50", "top100"]],
        on="date",
        how="inner",
        validate="one_to_one",
    )
    breadth_history = [
        {
            "date": row.date,
            "MCL": row.MCL,
            "top50_share": row.top50,
            "top100_share": row.top100,
        }
        for row in breadth.itertuples(index=False)
        if row.date <= asof
    ]
    margin_rows = [
        {"DIM_DATE": row.date, "RZYE": row.RZYE}
        for row in margin.itertuples(index=False)
        if row.date <= asof
    ]
    price_rows: dict[str, dict[str, float]] = {}
    for spec in price_specs:
        code, separator, value = spec.partition("=")
        if not separator or code not in dict(INDEXES):
            raise ValueError(f"invalid --price value: {spec}")
        source, delimiter, column = value.rpartition("#")
        path = Path(source if delimiter else value)
        frame = _read_table(path)
        close_column = column if delimiter else "close"
        if close_column not in frame.columns:
            raise ValueError(f"price history lacks {close_column}: {path}")
        frame = frame.loc[
            (frame["date"] <= asof)
            & frame["date"].ne("2005-01-01")
            & pd.to_numeric(frame[close_column], errors="coerce").notna(),
            ["date", close_column],
        ]
        prices = price_rows.setdefault(code, {})
        for row in frame.itertuples(index=False, name=None):
            day, close = row
            prices[day] = float(close)
    index_histories = {
        code: [
            {"date": day, "close": close}
            for day, close in sorted(prices.items())
        ]
        for code, prices in price_rows.items()
    }
    return breadth_history, margin_rows, index_histories


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate top-risk episodes from the published daily n_on rules"
    )
    parser.add_argument("--breadth", type=Path, required=True)
    parser.add_argument("--concentration", type=Path, required=True)
    parser.add_argument("--margin", type=Path, required=True)
    parser.add_argument(
        "--price",
        action="append",
        required=True,
        metavar="SYMBOL=PATH",
        help="daily close history; repeat as SYMBOL=PATH#CLOSE_COLUMN to merge sources",
    )
    parser.add_argument("--asof", required=True)
    parser.add_argument("--out", type=Path, default=top_risk.DEFAULT_EPISODES)
    parser.add_argument("--history-out", type=Path)
    args = parser.parse_args(argv)
    day = top_risk._date_text(args.asof)
    breadth, margin, prices = _load_inputs(
        args.breadth,
        args.concentration,
        args.margin,
        args.price,
        day,
    )
    report, states = build_top_risk_episodes(breadth, margin, prices)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=1, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    if args.history_out:
        args.history_out.parent.mkdir(parents=True, exist_ok=True)
        args.history_out.write_text(
            json.dumps(states, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report["stats"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
