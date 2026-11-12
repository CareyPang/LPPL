import json
from pathlib import Path

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


def test_flow_is_none_if_either_share_observation_is_missing():
    assert nt_etf.flow_yuan(2, 1, 3) == 3
    assert nt_etf.flow_yuan(None, 1, 3) is None
    assert nt_etf._window([["a", 1, 1, 2], ["b", 2, 1, None], ["c", 3, 1, -1]], 3) == (1, 2)
    latest, previous = nt_etf._latest_share_observations(
        [["2026-11-10", 1, 1, 1], ["2026-11-11", None, 2, None], ["2026-11-12", 3, 3, None]]
    )
    assert latest[0] == "2026-11-12"
    assert previous[0] == "2026-11-10"


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
