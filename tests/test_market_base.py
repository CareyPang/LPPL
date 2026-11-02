import json
from pathlib import Path

import pandas as pd
import pytest

from research.data import market_base as market

FIXTURES = Path(__file__).parent / "fixtures" / "market"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_board_parser_uses_documented_fields():
    payload = fixture("board_snapshot.json")
    raw = payload["data"]["diff"][0]
    rows, total = market._parse_board_page(payload, "today")

    assert total == payload["data"]["total"]
    assert len(rows) == len(payload["data"]["diff"])
    assert rows[0] == {
        "code": str(raw["f12"]),
        "name": str(raw["f14"]),
        "pct_chg": market._number(raw["f3"]),
        "main_net": market._number(raw["f62"]),
        "main_pct": market._number(raw["f184"]),
        "super_net": market._number(raw["f66"]),
        "large_net": market._number(raw["f72"]),
        "medium_net": market._number(raw["f78"]),
        "small_net": market._number(raw["f84"]),
    }


def test_board_pagination_stops_at_reported_total():
    base = fixture("board_snapshot.json")["data"]["diff"][0]
    rows = [base, {**base, "f12": "BK0476", "f14": "公用事业"}, {**base, "f12": "BK0477"}]

    class Client:
        calls = []

        def get_json(self, url, params, fallback_url=None):
            self.calls.append(params["pn"])
            start = (int(params["pn"]) - 1) * 2
            page_rows = rows[start : start + 2]
            return {"data": {"total": 3, "diff": page_rows}}

    client = Client()
    result = market._fetch_board_period("industry", "today", client)

    assert len(result) == 3
    assert client.calls == ["1", "2"]


def test_board_history_parser_uses_field_order():
    payload = fixture("board_history.json")
    result = market._parse_board_history(payload)
    values = payload["data"]["klines"][-1].split(",")

    assert result.iloc[-1].to_dict() == {
        "date": values[0],
        "main_net": float(values[1]),
        "small_net": float(values[2]),
        "medium_net": float(values[3]),
        "large_net": float(values[4]),
        "super_net": float(values[5]),
    }


def test_board_history_order_matches_board_snapshot():
    snapshot = market._parse_board_page(fixture("board_snapshot.json"), "today")[0][0]
    history = market._parse_board_history(fixture("board_history.json"))

    assert market._verify_history_order(snapshot, history, "2026-10-30") == [
        "main_net",
        "small_net",
        "medium_net",
        "large_net",
        "super_net",
    ]


def test_board_snapshot_has_exact_contract_columns():
    snapshot = fixture("board_snapshot.json")["data"]["diff"][0]
    period_rows = {
        "f62": snapshot,
        "f164": {
            **snapshot,
            "f109": "2.5",
            "f164": "500",
            "f165": "0.3",
            "f257": "华电国际",
        },
        "f174": {
            **snapshot,
            "f160": "4.5",
            "f174": "800",
            "f175": "0.4",
        },
    }

    class Client:
        url_host = "push2delay.eastmoney.com"

        def get_json(self, _url, params, fallback_url=None):
            return {"data": {"total": 1, "diff": [period_rows[params["fid"]]]}}

    result = market.board_flow_snapshot("industry", Client())

    assert result.columns.tolist() == list(market.BOARD_COLUMNS)
    assert result.iloc[0]["main_net_10d"] == 800


def test_limit_pool_parser_and_top_row():
    payload = fixture("limit_pool.json")
    raw = payload["data"]["pool"][0]
    pool = market._parse_pool(payload, "20261030")
    row = market._limit_display_row(pool[0], "zt")

    assert row == {
        "code": str(raw["c"]),
        "name": str(raw["n"]),
        "streak": int(raw["lbc"]),
        "limit_time": market._fmt_limit_time(raw["fbt"]),
    }


def test_limit_pool_summary_uses_fraction_and_all_three_pools():
    payloads = {
        "getTopicZTPool": fixture("limit_pool.json"),
        "getTopicZBPool": fixture("limit_pool_zb.json"),
        "getTopicDTPool": fixture("limit_pool_dt.json"),
    }

    class Client:
        def get_json(self, url, *_args, **_kwargs):
            return payloads[url.rsplit("/", 1)[-1]]

    result = market.limit_pools("2026-10-30", Client())
    zt, zb, dt = (payloads[f"getTopic{name}Pool"]["data"]["pool"] for name in ("ZT", "ZB", "DT"))
    zt_n, zb_n = len(zt), len(zb)

    assert result["zt"] == zt_n
    assert result["zb"] == zb_n
    assert result["dt"] == len(dt)
    assert result["break_rate"] == pytest.approx(zb_n / (zt_n + zb_n))
    assert result["max_streak"] == max(int(row["lbc"]) for row in zt)
    assert len(result["top20"]["zt"]) == zt_n


def test_northbound_fields_are_turnover_only():
    value = market._parse_northbound((FIXTURES / "northbound.js").read_text(encoding="utf-8"))

    assert value["sse_nb_turnover"] == 131148.57
    assert value["szse_nb_turnover"] == 142937.46
    assert value["sse_nb_trades"] == 7655464
    assert value["szse_nb_trades"] == 8491537
    assert not any("net" in key.lower() or "inflow" in key.lower() for key in value)


def test_csindex_parser_normalizes_spaced_headers():
    frame = pd.DataFrame(fixture("valuation_rows.json"))

    assert "指数代码Index Code" in frame.columns
    value = market._parse_index_valuation(frame, "000300")

    assert value["date"] == "2026-10-30"
    assert value["pe1"] == 13.76
    assert value["pe1_pct_10y"] is None


def test_csindex_valuation_parser_uses_only_ten_year_history():
    frame = pd.DataFrame(
        [
            {
                "日期Date": "2016-10-30",
                "指数代码IndexCode": "000300",
                "市盈率1（总股本）P/E1": "10",
                "市盈率2（计算用股本）P/E2": "11",
                "股息率1（总股本）D/P1": "3",
                "股息率2（计算用股本）D/P2": "2.8",
            },
            {
                "日期Date": "2021-10-30",
                "指数代码IndexCode": "000300",
                "市盈率1（总股本）P/E1": "15",
                "市盈率2（计算用股本）P/E2": "16",
                "股息率1（总股本）D/P1": "2",
                "股息率2（计算用股本）D/P2": "1.8",
            },
            {
                "日期Date": "2026-10-30",
                "指数代码IndexCode": "000300",
                "市盈率1（总股本）P/E1": "13.2",
                "市盈率2（计算用股本）P/E2": "14",
                "股息率1（总股本）D/P1": "2.5",
                "股息率2（计算用股本）D/P2": "2.3",
            },
        ]
    )
    value = market._parse_index_valuation(frame, "000300")

    assert value["date"] == "2026-10-30"
    assert value["pe1"] == 13.2
    assert value["pe1_pct_10y"] == pytest.approx(2 / 3)


def test_eastmoney_403_is_not_retried():
    class Response:
        status_code = 403
        url = market.EM_BOARD_URL

        def raise_for_status(self):
            raise AssertionError("403 is handled before raise_for_status")

    class Session:
        headers = {}
        calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return Response()

    session = Session()
    client = market.EMClient(session=session, sleep=lambda _: None, jitter=lambda *_: 0)

    with pytest.raises(market.EMBlocked):
        client.get(market.EM_BOARD_URL)

    assert session.calls == 1


def test_partial_failure_still_writes_both_json_files(tmp_path, monkeypatch):
    def board(kind, _client):
        if kind == "industry":
            raise RuntimeError("industry unavailable")
        return pd.DataFrame(columns=market.BOARD_COLUMNS)

    monkeypatch.setattr(market, "board_flow_snapshot", board)
    monkeypatch.setattr(
        market,
        "limit_pools",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("pool unavailable")),
    )
    monkeypatch.setattr(market, "hkex_northbound", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        market,
        "csindex_valuation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("valuation unavailable")),
    )
    monkeypatch.setattr(
        market,
        "_margin_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("cache missing")),
    )
    payload = market.fetch_market("2026-11-02", em_client=market.EMClient())

    latest, dated, board_csv = market.write_snapshot(
        payload, tmp_path / "out", board_dir=tmp_path / "board"
    )

    assert latest.exists() and dated.exists()
    assert board_csv is None
    assert not (tmp_path / "board" / "2026-11-02.csv.gz").exists()
    saved = json.loads(latest.read_text(encoding="utf-8"))
    assert saved["sources"]["board_flow_industry"]["ok"] is False
    assert saved["sources"]["limit_pools"]["ok"] is False
    assert saved["board_flow"]["concept"] == []


def _synthetic_margin_frame(dates, calendar):
    calendar = pd.DatetimeIndex(calendar)
    indices = {date: i for i, date in enumerate(calendar)}
    rows = []
    for i, value_date in enumerate(dates):
        next_index = indices[value_date] + 1
        available_date = calendar[next_index] if next_index < len(calendar) else pd.NaT
        rows.append(
            {
                "date": value_date,
                "avail_date": available_date,
                "fin_balance_sse": float((i + 100) * 1e8),
                "fin_balance_szse": float((i + 100) * 1e8),
                "fin_balance_all": float(i + 100),
                "total_balance_all": float((i + 100) * 2),
            }
        )
    return pd.DataFrame(rows)


def test_margin_snapshot_reports_latest_date_and_trading_day_staleness(monkeypatch):
    calendar = pd.date_range("2026-10-01", periods=30, freq="D")
    fresh_frame = _synthetic_margin_frame(calendar[:-1], calendar)
    stale_frame = _synthetic_margin_frame(calendar[:20], calendar)

    monkeypatch.setattr(
        market,
        "_refresh_margin_frame",
        lambda *_args, **_kwargs: (fresh_frame.copy(), None, pd.DatetimeIndex(calendar)),
    )
    fresh = market._margin_snapshot(calendar[-1].date().isoformat())
    assert fresh["latest_date"] == calendar[-2].date().isoformat()
    assert fresh["stale"] is False

    monkeypatch.setattr(
        market,
        "_refresh_margin_frame",
        lambda *_args, **_kwargs: (stale_frame.copy(), "refresh failed", pd.DatetimeIndex(calendar)),
    )
    stale = market._margin_snapshot(calendar[-1].date().isoformat())
    assert stale["latest_date"] == calendar[19].date().isoformat()
    assert stale["stale"] is True
    assert "refresh failed" in stale["_refresh_error"]


def test_margin_refresh_uses_existing_exchange_fetchers(tmp_path, monkeypatch):
    dates = pd.date_range("2026-10-28", periods=3, freq="D")
    sse = pd.DataFrame(
        {
            "date": dates,
            "fin_balance": [100.0, 101.0, 102.0],
            "fin_buy": [10.0, 11.0, 12.0],
            "sec_qty": [1.0, 1.0, 1.0],
            "sec_balance": [20.0, 20.0, 20.0],
            "sec_sell_qty": [1.0, 1.0, 1.0],
            "total_balance": [300.0, 301.0, 302.0],
        }
    )
    szse_values = {
        "date": dates,
        "融资余额": [200.0, 201.0, 202.0],
        "融资买入额": [20.0, 21.0, 22.0],
        "融券余量": [2.0, 2.0, 2.0],
        "融券余额": [30.0, 30.0, 30.0],
        "融券卖出量": [2.0, 2.0, 2.0],
        "融资融券余额": [400.0, 401.0, 402.0],
    }
    calls = {}

    def fake_sse(start, end):
        calls["sse"] = (start, end)
        return sse.copy()

    def fake_szse(fetch_dates, out, pause):
        calls["szse"] = (pd.DatetimeIndex(fetch_dates), pause)
        pd.DataFrame(szse_values).to_parquet(out, index=False)
        out.with_suffix(".failed.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(market, "fetch_sse", fake_sse)
    monkeypatch.setattr(market, "fetch_szse", fake_szse)

    frame, error, trading_dates = market._refresh_margin_frame("2026-10-30", tmp_path)

    assert calls["sse"] == ("20260831", "20261030")
    assert calls["szse"][0].equals(pd.DatetimeIndex(dates))
    assert calls["szse"][1] == 0.8
    assert error is None
    assert trading_dates.equals(pd.DatetimeIndex(dates))
    assert frame.iloc[-1]["fin_balance_all"] == 20_200_000_102.0
    assert frame.iloc[-1]["total_balance_all"] == 40_200_000_302.0


def test_stale_margin_marks_source_failed_but_keeps_data(monkeypatch):
    monkeypatch.setattr(
        market,
        "board_flow_snapshot",
        lambda *_args, **_kwargs: pd.DataFrame(columns=market.BOARD_COLUMNS),
    )
    monkeypatch.setattr(
        market,
        "limit_pools",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )
    monkeypatch.setattr(market, "hkex_northbound", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        market,
        "csindex_valuation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )
    margin_data = {
        "latest_date": "2026-10-20",
        "stale": True,
        "trading_days_stale": 6,
        "fin_balance_sse": 100.0,
        "fin_balance_szse": 20.0,
        "fin_balance_all": 100.0,
        "_refresh_error": "fetch failed",
    }
    monkeypatch.setattr(market, "_margin_snapshot", lambda *_args, **_kwargs: margin_data.copy())

    payload = market.fetch_market("2026-10-30", em_client=market.EMClient())

    assert payload["sources"]["margin"]["ok"] is False
    assert "fetch failed" in payload["sources"]["margin"]["error"]
    assert "stale" in payload["sources"]["margin"]["error"]
    assert "SZSE/SSE ratio out of range" in payload["sources"]["margin"]["error"]
    assert payload["margin"]["data"]["latest_date"] == "2026-10-20"


def test_board_csv_is_written_only_with_rows(tmp_path):
    frame = pd.DataFrame([{column: None for column in market.BOARD_COLUMNS}], columns=market.BOARD_COLUMNS)
    frame.loc[0, ["code", "name"]] = ["BK0438", "食品饮料"]
    payload = {"asof": "2026-10-30", "_board_frames": [frame]}

    _, _, board_csv = market.write_snapshot(
        payload, tmp_path / "out", board_dir=tmp_path / "board"
    )

    assert board_csv is not None and board_csv.exists()
    assert pd.read_csv(board_csv).columns.tolist() == list(market.BOARD_COLUMNS)
