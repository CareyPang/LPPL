import json

import pandas as pd
import pytest

from research.data import top_risk

ASOF = "2026-11-18"


def _breadth():
    dates = pd.date_range(end=ASOF, periods=260, freq="D")
    mcl = [0.0] * 250 + [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 1.0]
    return {
        "schema": "breadth.v1",
        "asof": ASOF,
        "risk_history": [
            {
                "date": day.date().isoformat(),
                "MCL": value,
                "top50_share": 0.22,
                "top100_share": 0.32 if index >= 255 else 0.20,
            }
            for index, (day, value) in enumerate(zip(dates, mcl, strict=True))
        ],
    }


def _margin_rows():
    dates = pd.date_range(end="2026-11-17", periods=252, freq="D")
    return [
        {"DIM_DATE": day.date().isoformat(), "RZYE": index + 1}
        for index, day in enumerate(dates)
    ] + [{"DIM_DATE": ASOF, "RZYE": 10000}]


def _index_histories():
    dates = pd.date_range(end=ASOF, periods=260, freq="D")
    return {
        code: [
            {"date": day.date().isoformat(), "close": 100.0 + index}
            for index, day in enumerate(dates)
        ]
        for code, _ in top_risk.INDEXES
    }


def test_fetch_margin_history_requests_sorted_500_rows_and_excludes_asof():
    class Client:
        def __init__(self):
            self.params = []

        def get_json(self, _url, params):
            self.params.append(params)
            return {
                "code": 0,
                "result": {
                    "pages": 1,
                    "count": len(_margin_rows()),
                    "data": [
                        {
                            "DIM_DATE": row["DIM_DATE"],
                            "RZYE": row["RZYE"],
                            "RZMRE": 0,
                        }
                        for row in reversed(_margin_rows())
                    ],
                },
            }

    client = Client()
    rows = top_risk.fetch_margin_history(ASOF, client)

    assert len(rows) == 252
    assert rows[-1]["date"] == "2026-11-17"
    assert client.params[0]["reportName"] == "RPTA_RZRQ_LSHJ"
    assert client.params[0]["columns"] == "DIM_DATE,RZYE,RZMRE"
    assert client.params[0]["pageSize"] == "500"
    assert client.params[0]["sortColumns"] == "DIM_DATE"
    assert client.params[0]["sortTypes"] == "-1"
    assert "DIM_DATE<'2026-11-18'" in client.params[0]["filter"]


def test_percentile_rank_and_risk_level_thresholds():
    assert top_risk.percentile_rank(list(range(1, 121))) == 1
    assert top_risk.risk_level(0) == "未触发"
    assert top_risk.risk_level(1) == "未触发"
    assert top_risk.risk_level(2) == "偏高"
    assert top_risk.risk_level(3) == "顶部风险高"


def test_build_snapshot_uses_required_thresholds_and_passes_research_results_unchanged():
    research = json.loads(top_risk.DEFAULT_EPISODES.read_text(encoding="utf-8"))

    snapshot = top_risk.build_snapshot(
        ASOF,
        _breadth(),
        _margin_rows(),
        _index_histories(),
    )

    assert snapshot["conc"]["top100_5d"] == pytest.approx(0.32)
    assert snapshot["conc"]["on"] is True
    assert snapshot["margin"]["date"] == "2026-11-17"
    assert snapshot["margin"]["pct252"] == 1
    assert snapshot["margin"]["on"] is True
    assert snapshot["breadth_drop"]["on"] is True
    assert snapshot["breadth_drop"]["threshold"] == pytest.approx(
        snapshot["breadth_drop"]["mcl_max10"]
        - 0.5 * snapshot["breadth_drop"]["std250"]
    )
    assert 0 <= snapshot["breadth_drop"]["mcl_pct250"] <= 1
    assert len(snapshot["indices"]) == 4
    assert snapshot["indices"][0]["pos_pct252"] == 1
    assert snapshot["indices"][0]["gain_from_250_low"] >= 0.15
    assert snapshot["indices"][0]["n_on"] == 3
    assert snapshot["indices"][0]["level"] == "顶部风险高"
    assert snapshot["episodes"] == research["episodes"]
    assert snapshot["stats"] == research["stats"]
    assert snapshot["definition"] == research["definition"]
    assert snapshot["judge"] == research["judge"]
    assert any(row["verdict"] is None for row in snapshot["episodes"])


def test_margin_metrics_uses_latest_strictly_before_asof():
    metrics = top_risk.margin_metrics(_margin_rows(), ASOF)

    assert metrics["date"] == "2026-11-17"
    assert metrics["rzye_yi"] == pytest.approx(252 / 1e8)
    assert metrics["pct252"] == 1


def test_pipeline_copies_previous_snapshot_when_source_fails(tmp_path, monkeypatch):
    breadth_path = tmp_path / "breadth.json"
    breadth_path.write_text(json.dumps(_breadth()), encoding="utf-8")
    previous_path = tmp_path / "previous.json"
    previous_bytes = b'{\n  "schema": "top_risk.v1",\n  "asof": "2026-11-17"\n}\n'
    previous_path.write_bytes(previous_bytes)
    output_path = tmp_path / "market" / "top_risk_latest.json"

    def fail(*_args, **_kwargs):
        raise RuntimeError("Eastmoney unavailable")

    monkeypatch.setattr(top_risk, "fetch_margin_history", fail)

    with pytest.raises(RuntimeError, match="Eastmoney unavailable"):
        top_risk.run_pipeline(
            output_path,
            asof=ASOF,
            breadth_path=breadth_path,
            previous_path=previous_path,
        )

    assert output_path.read_bytes() == previous_bytes


def test_index_metrics_counts_only_two_primary_conditions_when_c3_fails():
    dates = pd.date_range(end=ASOF, periods=250, freq="D")
    rows = [
        {"date": day.date().isoformat(), "close": 100.0 + index}
        for index, day in enumerate(dates)
    ]
    rows[-1]["close"] = 100.0

    result = top_risk.index_metrics(
        "sh000001",
        "上证指数",
        rows,
        concentration_on=True,
        margin_on=True,
        asof=ASOF,
    )

    assert result["on"] is False
    assert result["n_on"] == 2
    assert result["level"] == "偏高"


def test_build_n_on_history_uses_daily_metrics_and_excludes_asof_margin_row():
    history = top_risk.build_n_on_history(
        _breadth()["risk_history"],
        _margin_rows(),
        _index_histories(),
    )

    latest = history["sh000001"][-1]
    assert latest["date"] == ASOF
    assert latest["concentration_on"] is True
    assert latest["margin_on"] is True
    assert latest["index_on"] is True
    assert latest["n_on"] == 3
