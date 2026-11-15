import json
from pathlib import Path

import pandas as pd
import pytest

from research.data import nt_etf

FIXTURES = Path(__file__).parent / "fixtures" / "nt_etf"


def fixture_json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_sse_fixture_validates_total_and_date():
    payload = fixture_json("sse_shares.json")
    rows = nt_etf._parse_sse(payload, "2026-11-11")
    assert rows["510300"]["shares_10k"] > 0
    payload["pageHelp"]["total"] = 2
    with pytest.raises(RuntimeError, match="total mismatch"):
        nt_etf._parse_sse(payload, "2026-11-11")


def test_szse_history_fixture_and_holder_filters():
    payload = fixture_json("szse_history.json")
    rows, pages = nt_etf._parse_szse_history(payload)
    assert pages == 1
    assert rows["2026-11-11"] == 1381701.66
    captured_holders = nt_etf._parse_holders(fixture_json("holders.json"))
    assert captured_holders["nt_shares_yi"] > 0
    holders = nt_etf._parse_holders({
        "result": {"data": [
            {"cyrmc": "中央汇金资产管理有限责任公司", "cyfe": "100000000", "zfeb": "1.2"},
            {"cyrmc": "华夏沪深300ETF联接", "cyfe": "90000000", "zfeb": "2.1"},
        ]}
    })
    assert holders["nt"][0]["group"] == "中央汇金"
    assert holders["nt_shares_yi"] == 1
    assert len(rows) == 2


def test_cffex_fixture_aggregates_client_long_short():
    text = (FIXTURES / "cffex_if.csv").read_bytes().decode("gbk")
    result = nt_etf._parse_cffex(text, "20261112", "IF")
    assert result["long"] > 0
    assert result["short"] > 0
    assert result["net_short"] == result["short"] - result["long"]


def test_holder_structure_fixture_parses_latest_and_previous_three_rows():
    structure = nt_etf._parse_holder_structure(
        (FIXTURES / "holder_structure.js").read_text(encoding="utf-8")
    )

    assert structure["report_date"] == "2026-06-30"
    assert structure["inst_ratio"] == 61.65
    assert structure["retail_ratio"] == 32.95
    assert structure["internal_ratio"] == 5.4
    assert structure["total_shares_yi"] == 189.15
    assert [row["report_date"] for row in structure["history"]] == [
        "2025-12-31",
        "2025-06-30",
        "2024-12-31",
    ]


def test_holder_structure_header_mismatch_raises():
    payload = (FIXTURES / "holder_structure.js").read_text(encoding="utf-8")
    payload = payload.replace("总份额（亿份）", "总份额")

    with pytest.raises(RuntimeError, match="header changed"):
        nt_etf._parse_holder_structure(payload)


def test_holder_structure_placeholder_is_null_not_zero():
    payload = (FIXTURES / "holder_structure.js").read_text(encoding="utf-8")
    payload = payload.replace(
        "<td>2025-12-31</td><td>60.12%</td>",
        "<td>2025-12-31</td><td>---</td>",
    )

    structure = nt_etf._parse_holder_structure(payload)

    assert structure["history"][0]["inst_ratio"] is None


def test_holder_structure_failure_falls_back_to_previous_snapshot(monkeypatch):
    previous = {
        "report_date": "2025-12-31",
        "inst_ratio": 60.12,
        "retail_ratio": 34.1,
        "internal_ratio": 5.78,
        "total_shares_yi": 177.5,
        "history": [],
        "checked_at": "2025-12-31T00:00:00+00:00",
    }

    def fail(*args, **kwargs):
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(nt_etf, "_holder_structure", fail)
    result, error = nt_etf._holder_structure_with_fallback(
        object(), "510300", previous
    )

    assert result is previous
    assert error == "510300: RuntimeError: fixture failure"


def test_flow_is_none_if_either_share_observation_is_missing():
    assert nt_etf.flow_yuan(2, 1, 3) == 3
    assert nt_etf.flow_yuan(None, 1, 3) is None
    assert nt_etf._window([["a", 1, 1, 2], ["b", 2, 1, None], ["c", 3, 1, -1]], 3) == (1, 2)
    latest, previous = nt_etf._latest_share_observations(
        [["2026-11-10", 1, 1, 1], ["2026-11-11", None, 2, None], ["2026-11-12", 3, 3, None]]
    )
    assert latest[0] == "2026-11-12"
    assert previous[0] == "2026-11-10"


def test_flag_flow_series_share_change_trigger():
    series = nt_etf._flag_flow_series(
        [["2026-11-10", 100.0, 1.0, None], ["2026-11-11", 104.0, 2.0, 8.0]]
    )

    assert series[-1][4] == "large_in"
    assert series[-1][5] == {
        "share_pct": 0.04,
        "median_mult": None,
        "n_obs": 0,
    }


def test_flag_flow_series_median_multiple_trigger():
    prior = [[f"2026-10-{day:02d}", 100.0, 1.0, 1.0] for day in range(1, 21)]
    prior.append(["2026-11-11", 100.5, 1.0, 6.0])

    series = nt_etf._flag_flow_series(prior)

    assert series[-1][4] == "large_in"
    assert series[-1][5]["share_pct"] == 0.005
    assert series[-1][5]["median_mult"] == 6.0
    assert series[-1][5]["n_obs"] == nt_etf.FLAG_MIN_OBS


def test_flag_flow_series_below_minimum_is_not_flagged():
    series = nt_etf._flag_flow_series(
        [["2026-11-10", 100.0, 1.0, 1.0], ["2026-11-11", 105.0, 1.0, 4.99]]
    )

    assert series[-1][4] is None


def test_null_flow_is_not_flagged_or_counted_in_median_history():
    prior = [[f"2026-10-{day:02d}", 100.0, 1.0, 1.0] for day in range(1, 21)]
    prior.extend(
        [
            ["2026-11-10", None, 1.0, None],
            ["2026-11-11", 100.0, 1.0, 6.0],
        ]
    )

    series = nt_etf._flag_flow_series(prior)

    assert series[-2][4] is None
    assert series[-1][4] == "large_in"
    assert series[-1][5]["n_obs"] == nt_etf.FLAG_MIN_OBS
    assert series[-1][5]["median_mult"] == 6.0


def test_fewer_than_minimum_median_observations_uses_share_change_only():
    prior = [[f"2026-11-{day:02d}", 100.0, 1.0, 1.0] for day in range(1, 11)]
    no_share_change = nt_etf._flag_flow_series(
        [*prior, ["2026-11-11", 100.5, 1.0, 6.0]]
    )
    with_share_change = nt_etf._flag_flow_series(
        [*prior, ["2026-11-11", 104.0, 2.0, 8.0]]
    )

    assert no_share_change[-1][4] is None
    assert no_share_change[-1][5]["median_mult"] is None
    assert no_share_change[-1][5]["n_obs"] == 10
    assert with_share_change[-1][4] == "large_in"
    assert with_share_change[-1][5]["median_mult"] is None


def test_flags_latest_keeps_flagged_rows_sorted_by_absolute_flow():
    def etf(code, flow, flag):
        return {
            "code": code,
            "name": code,
            "category": "沪深300",
            "latest": {
                "flow_yi": flow,
                "flag": flag,
                "flag_basis": {"share_pct": None, "median_mult": None, "n_obs": 0},
            },
        }

    rows = nt_etf._flags_latest(
        [etf("510300", 6.0, "large_in"), etf("510310", -8.0, "large_out"), etf("510330", 99, None)]
    )

    assert [row["code"] for row in rows] == ["510310", "510300"]


def test_share_source_failure_does_not_block_szse(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("SSE blocked")

    monkeypatch.setattr(nt_etf, "_shanghai_etf", fail)
    monkeypatch.setattr(nt_etf, "_szse_history", lambda *args: {"2026-11-11": 2})

    class Session:
        def get(self, *args, **kwargs):
            class Response:
                def raise_for_status(self):
                    return None
            return Response()

    universe = [{"code": "510300", "exchange": "SH"}, {"code": "159919", "exchange": "SZ"}]
    sh, sz, sse_errors, szse_errors = nt_etf._fetch_shares(
        universe, ["2026-11-11"], "2026-11-11", "2026-11-11", Session()
    )
    assert not sh and sz["159919"]
    assert sse_errors and not szse_errors


def _fetch_fixture(monkeypatch, tmp_path, universe, previous, prices, share_result):
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(json.dumps(universe), encoding="utf-8")
    monkeypatch.setattr(nt_etf, "UNIVERSE_PATH", universe_path)
    monkeypatch.setattr(nt_etf, "_prices", lambda *_: (prices, []))
    calls = {}

    def fetch_shares(_universe, days, *_args):
        calls["days"] = days
        return share_result

    monkeypatch.setattr(nt_etf, "_fetch_shares", fetch_shares)
    monkeypatch.setattr(
        nt_etf,
        "_holders",
        lambda *_: {
            "report_date": None,
            "nt": [],
            "nt_shares_yi": None,
            "nt_ratio": None,
            "checked_at": None,
        },
    )
    monkeypatch.setattr(
        nt_etf,
        "_holder_structure_with_fallback",
        lambda _session, _code, holder_structure: (holder_structure, None),
    )
    monkeypatch.setattr(
        nt_etf,
        "_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    monkeypatch.setattr(
        nt_etf,
        "tencent_raw",
        lambda *_args, **_kwargs: pd.DataFrame(
            columns=["date", "open", "high", "low", "close"]
        ),
    )
    return nt_etf.fetch(
        "2026-11-13",
        previous=previous,
        session=object(),
    ), calls


def _previous_etf(code, series):
    return {
        "asof": "2026-11-12",
        "etfs": [
            {
                "code": code,
                "series": series,
                "holders": {"nt_shares_yi": None, "nt_ratio": None},
            }
        ],
    }


def test_no_price_days_do_not_invent_an_sse_query_date(monkeypatch, tmp_path):
    universe = [{"code": "510300", "name": "测试ETF", "category": "测试", "exchange": "SH"}]
    previous = _previous_etf(
        "510300",
        [["2026-11-12", 1.0, 4.0, None]],
    )

    payload, calls = _fetch_fixture(
        monkeypatch,
        tmp_path,
        universe,
        previous,
        {},
        ({}, {}, [], []),
    )

    assert calls["days"] == []
    assert payload["sources"]["sse_shares"]["ok"] is False
    assert payload["sources"]["sse_shares"]["latest_day"] == "2026-11-12"


def test_sse_query_retries_day_missing_for_one_priced_etf(monkeypatch, tmp_path):
    universe = [
        {"code": "510300", "name": "测试沪深300", "category": "测试", "exchange": "SH"},
        {"code": "510500", "name": "测试中证500", "category": "测试", "exchange": "SH"},
    ]
    previous = {
        "asof": "2026-11-12",
        "etfs": [
            {
                "code": "510300",
                "series": [["2026-11-12", 1.0, 4.0, None]],
                "holders": {"nt_shares_yi": None, "nt_ratio": None},
            },
            {
                "code": "510500",
                "series": [["2026-11-11", 0.8, 1.3, None]],
                "holders": {"nt_shares_yi": None, "nt_ratio": None},
            },
        ],
    }

    _, calls = _fetch_fixture(
        monkeypatch,
        tmp_path,
        universe,
        previous,
        {
            "510300": {"2026-11-12": 4.1},
            "510500": {"2026-11-12": 1.4},
        },
        ({}, {}, [], []),
    )

    assert calls["days"] == ["2026-11-12"]


@pytest.mark.parametrize(
    ("asof_shares", "expected_ok"),
    [(True, True), (False, False)],
)
def test_sse_ok_requires_shares_for_asof(
    monkeypatch, tmp_path, asof_shares, expected_ok
):
    universe = [{"code": "510300", "name": "测试ETF", "category": "测试", "exchange": "SH"}]
    previous = _previous_etf(
        "510300",
        [["2026-11-12", 1.0, 4.0, None]],
    )
    sh = (
        {"2026-11-13": {"510300": {"shares_10k": 10500}}}
        if asof_shares
        else {}
    )
    errors = [] if asof_shares else ["2026-11-13: ConnectionError: reset"]

    payload, calls = _fetch_fixture(
        monkeypatch,
        tmp_path,
        universe,
        previous,
        {"510300": {"2026-11-12": 4.0, "2026-11-13": 4.1}},
        (sh, {}, errors, []),
    )

    assert calls["days"] == ["2026-11-13"]
    assert payload["sources"]["sse_shares"]["ok"] is expected_ok
    assert payload["sources"]["sse_shares"]["latest_day"] == (
        "2026-11-13" if asof_shares else "2026-11-12"
    )
    if not asof_shares:
        assert "2026-11-13" in payload["sources"]["sse_shares"]["error"]


def test_failed_szse_refresh_keeps_previous_shares_and_marks_them_stale(
    monkeypatch, tmp_path
):
    universe = [{"code": "159919", "name": "测试ETF", "category": "测试", "exchange": "SZ"}]
    previous = _previous_etf(
        "159919",
        [["2026-11-12", 2.5, 1.2, None]],
    )

    payload, _ = _fetch_fixture(
        monkeypatch,
        tmp_path,
        universe,
        previous,
        {"159919": {"2026-11-13": 1.1}},
        ({}, {}, [], ["159919: ConnectionError: reset"]),
    )

    etf = payload["etfs"][0]
    assert payload["sources"]["szse_shares"]["ok"] is False
    assert etf["latest"]["shares_yi"] == 2.5
    assert etf["latest"]["shares_asof"] == "2026-11-12"
    assert etf["latest"]["shares_stale"] is True
