import json

import pytest

from research.data import lhb_seats


def test_aggregate_merges_side_tables_deduplicates_and_classifies_seats():
    summary = [
        {
            "SECURITY_CODE": "600001",
            "SECURITY_NAME_ABBR": "甲股份",
            "EXPLANATION": "连续三个交易日内，涨幅偏离值累计达到20%",
        },
        {
            "SECURITY_CODE": "000002",
            "SECURITY_NAME_ABBR": "乙科技",
            "EXPLANATION": "日涨幅偏离值达到7%",
        },
    ]
    buy = [
        {
            "SECURITY_CODE": "600001",
            "SECURITY_NAME_ABBR": "甲股份",
            "OPERATEDEPT_CODE": "dept-a",
            "OPERATEDEPT_NAME": "某营业部",
            "BUY": 100_000,
            "EXPLANATION": summary[0]["EXPLANATION"],
        },
        {
            "SECURITY_CODE": "600001",
            "SECURITY_NAME_ABBR": "甲股份",
            "OPERATEDEPT_CODE": "dept-a",
            "OPERATEDEPT_NAME": "某营业部",
            "BUY": 100_000,
            "EXPLANATION": summary[0]["EXPLANATION"],
        },
        {
            "SECURITY_CODE": "000002",
            "SECURITY_NAME_ABBR": "乙科技",
            "OPERATEDEPT_CODE": "0",
            "OPERATEDEPT_NAME": "机构专用",
            "BUY": 80_000,
            "EXPLANATION": summary[1]["EXPLANATION"],
        },
    ]
    sell = [
        {
            "SECURITY_CODE": "600001",
            "SECURITY_NAME_ABBR": "甲股份",
            "OPERATEDEPT_CODE": "dept-a",
            "OPERATEDEPT_NAME": "某营业部",
            "SELL": 30_000,
            "EXPLANATION": summary[0]["EXPLANATION"],
        },
        {
            "SECURITY_CODE": "000002",
            "SECURITY_NAME_ABBR": "乙科技",
            "OPERATEDEPT_CODE": "0",
            "OPERATEDEPT_NAME": "机构专用",
            "SELL": 10_000,
            "EXPLANATION": summary[1]["EXPLANATION"],
        },
        {
            "SECURITY_CODE": "000002",
            "SECURITY_NAME_ABBR": "乙科技",
            "OPERATEDEPT_CODE": "sct",
            "OPERATEDEPT_NAME": "深股通专用",
            "SELL": 5_000,
            "EXPLANATION": summary[1]["EXPLANATION"],
        },
    ]

    result = lhb_seats.aggregate_lhb_seats(
        "2026-11-18",
        summary,
        buy,
        sell,
        {"某营业部": {"alias": "游资甲", "source": "公开报道"}},
    )

    assert result["totals"] == {
        "buy": 180_000,
        "sell": 45_000,
        "institution_net": 70_000,
        "n_stocks_single": 1,
        "n_stocks_multi": 1,
    }
    assert [seat["seat"] for seat in result["seats"]] == ["某营业部", "机构专用", "深股通专用"]
    assert result["seats"][0]["alias"] == "游资甲"
    assert result["seats"][0]["kind"] == "dept"
    assert result["seats"][0]["net"] == 70_000
    assert result["seats"][0]["trades"] == [
        {
            "code": "600001",
            "name": "甲股份",
            "side": "in",
            "amount": 100_000,
            "list": "multi",
        },
        {
            "code": "600001",
            "name": "甲股份",
            "side": "out",
            "amount": 30_000,
            "list": "multi",
        },
    ]
    assert result["seats"][1]["kind"] == "institution"
    assert result["seats"][2]["kind"] == "northbound"


def test_fetch_report_paginates_and_checks_count():
    class Client:
        def __init__(self):
            self.pages = []

        def get_json(self, _url, params):
            page = int(params["pageNumber"])
            assert params["columns"] == "ALL"
            assert params["filter"] == "(TRADE_DATE='2026-11-18')"
            assert params["pageSize"] == "500"
            self.pages.append(page)
            if page == 1:
                return {
                    "code": 0,
                    "result": {
                        "pages": 2,
                        "count": 501,
                        "data": [{}] * 500,
                    },
                }
            return {
                "code": 0,
                "result": {"pages": 2, "count": 501, "data": [{}]},
            }

    client = Client()
    rows = lhb_seats._fetch_report(client, "report", "2026-11-18")
    assert len(rows) == 501
    assert client.pages == [1, 2]


def test_failed_fetch_reuses_previous_json(monkeypatch, tmp_path):
    previous = tmp_path / "previous.json"
    previous.write_text('{"asof":"2026-11-17"}', encoding="utf-8")
    output = tmp_path / "out" / "lhb_seats_latest.json"
    monkeypatch.setattr(
        lhb_seats,
        "fetch_lhb_seats",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    with pytest.raises(RuntimeError, match="offline"):
        lhb_seats.main(
            [
                "--date",
                "2026-11-18",
                "--out",
                str(output),
                "--previous",
                str(previous),
            ]
        )

    assert json.loads(output.read_text(encoding="utf-8")) == {"asof": "2026-11-17"}
