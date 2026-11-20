import json

import pandas as pd
import pytest

from research.backtest import publish

DATES = ["2014-10-17", "2022-12-30", "2023-01-03", "2023-01-04"]


def _inputs(monkeypatch):
    prices = pd.DataFrame({
        "date": DATES, **{field: [100.0] * 4 for field in ("open", "high", "low", "close")}
    })
    previous = {
        code: [{"date": day, "n_on": 0} for day in DATES[:-1]]
        for code, _ in publish.INDEXES
    }
    def current(*args, require_full_windows):
        assert require_full_windows
        return {
            code: [{"date": day, "n_on": 3} for day in DATES[-2:]]
            for code in previous
        }
    monkeypatch.setattr(publish.top_risk, "build_n_on_history", current)
    return {code: prices for code in previous}, previous


def test_incremental_publication_keeps_existing_dates_and_is_idempotent(tmp_path, monkeypatch):
    prices, previous = _inputs(monkeypatch)
    for _ in range(2):
        publish.build_outputs([], [], {}, prices, DATES[-1], tmp_path,
                              history_dir=tmp_path, previous_states=previous)
        previous = json.loads((tmp_path / "n_on_history.json").read_text(encoding="utf-8"))
        for rows in previous.values():
            assert [row["n_on"] for row in rows] == [0, 0, 0, 3]


@pytest.mark.parametrize("missing_day", DATES[:2])
def test_missing_seed_day_keeps_last_reports_and_no_partial_write(tmp_path, monkeypatch, missing_day):
    prices, previous = _inputs(monkeypatch)
    code = publish.INDEXES[-1][0]
    previous[code] = [row for row in previous[code] if row["date"] != missing_day]
    original = tmp_path / f"{publish.INDEXES[0][0]}.json"
    original.write_bytes(b'{"prior":true}')
    with pytest.raises(ValueError, match=missing_day):
        publish.build_outputs([], [], {}, prices, DATES[-1], tmp_path,
                              history_dir=tmp_path, previous_states=previous)
    assert list(tmp_path.iterdir()) == [original]
    assert original.read_bytes() == b'{"prior":true}'


def test_live_requires_seed_before_fetching(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "ROOT", tmp_path)
    with pytest.raises(FileNotFoundError, match="historical n_on seed"):
        publish.run_live(DATES[-1], tmp_path / "no-breadth.json", tmp_path / "out")


@pytest.mark.parametrize("rows", [
    [{"date": DATES[0], "n_on": 0}, {"date": DATES[0], "n_on": 0}],
    [{"date": DATES[0], "n_on": False}],
    [{"date": DATES[0], "n_on": 2,
      "concentration_on": False, "margin_on": False, "index_on": False}],
    [{"date": "2023-01-05", "n_on": 1}],
])
def test_invalid_or_future_seed_is_rejected(rows):
    with pytest.raises(ValueError):
        publish._stored_states("sh000001", rows, DATES[-1])


def test_unserializable_later_report_never_replaces_prior_bundle(tmp_path, monkeypatch):
    prices, previous = _inputs(monkeypatch)
    original = tmp_path / f"{publish.INDEXES[0][0]}.json"
    original.write_bytes(b'{"prior":true}')
    def report(code, *args, **kwargs):
        return {"value": float("nan") if code == publish.INDEXES[-1][0] else 0}
    monkeypatch.setattr(publish, "build_strategy_report", report)
    with pytest.raises(ValueError, match="JSON"):
        publish.build_outputs([], [], {}, prices, DATES[-1], tmp_path,
                              history_dir=tmp_path, previous_states=previous)
    assert list(tmp_path.iterdir()) == [original]
    assert original.read_bytes() == b'{"prior":true}'
