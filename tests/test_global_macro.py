import json
from datetime import date, timedelta
from pathlib import Path

from research.data import global_macro as macro

FIXTURES = Path(__file__).parent / "fixtures" / "global_macro"


def fixture_text(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_json(name):
    return json.loads(fixture_text(name))


def test_parse_treasury_csv_preserves_all_tenors():
    rows = macro.parse_treasury_csv(fixture_text("treasury_current.csv"))

    assert len(rows) == 2
    assert rows[0]["date"] == "2026-11-12"
    assert rows[0]["curve"]["1 Mo"] == 3.88
    assert rows[0]["curve"]["30 Yr"] == 4.90


def test_treasury_spreads_and_lookback_observations():
    template = macro.parse_treasury_csv(fixture_text("treasury_current.csv"))[0]
    rows = []
    current_date = date(2025, 1, 1)
    while len(rows) < 251:
        if current_date.weekday() < 5:
            index = len(rows)
            curve = dict(template["curve"])
            curve["2 Yr"] = float(index)
            curve["3 Mo"] = float(index - 1)
            curve["10 Yr"] = float(index + 2)
            rows.append({"date": current_date.isoformat(), "curve": curve})
        current_date += timedelta(days=1)

    snapshot = macro._treasury_snapshot(rows)

    assert snapshot["spreads"] == {"10y_minus_2y": 2.0, "10y_minus_3m": 3.0}
    assert snapshot["20d_ago"]["date"] == rows[-21]["date"]
    assert snapshot["250d_ago"]["date"] == rows[0]["date"]
    assert len(snapshot["series_250d"]) == 250


def test_fetch_treasury_joins_previous_year_when_current_year_is_short(monkeypatch):
    class Response:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    class Session:
        def __init__(self):
            self.urls = []

        def get(self, url, **_kwargs):
            self.urls.append(url)
            if "/2026/" in url:
                return Response(fixture_text("treasury_current.csv"))
            return Response(fixture_text("treasury_previous.csv"))

    captured = {}

    def snapshot(rows):
        captured["dates"] = sorted(row["date"] for row in rows)
        return {"asof": captured["dates"][-1], "dates": captured["dates"]}

    monkeypatch.setattr(macro, "_treasury_snapshot", snapshot)
    session = Session()
    result = macro.fetch_treasury(session, "2026-11-12")

    assert len(session.urls) == 2
    assert "/2026/" in session.urls[0]
    assert "/2025/" in session.urls[1]
    assert result["dates"] == [
        "2025-12-31",
        "2026-11-11",
        "2026-11-12",
    ]


def test_parse_effr_keeps_target_range():
    rows = macro.parse_nyfed(fixture_json("nyfed_effr.json"), "effr")

    assert rows[-1] == {
        "date": "2026-11-11",
        "rate": 3.87,
        "volume_in_billions": 80.1,
        "target_rate_from": 3.75,
        "target_rate_to": 4.0,
    }


def test_h10_parser_keeps_requested_currencies_and_broad_index():
    parsed = macro.parse_h10_csv(fixture_text("fed_h10.csv"))
    snapshot = macro._h10_snapshot(parsed)

    assert set(snapshot["series"]) == {"CNY", "JPY", "EUR", "USD_BROAD"}
    assert snapshot["series"]["CNY"]["latest"]["value"] == 7.108
    assert snapshot["series"]["EUR"]["quote"] == "USD per 1 EUR"
    assert snapshot["series"]["USD_BROAD"]["latest"]["value"] == 117.30


def test_sources_fail_independently_and_reuse_previous_values():
    class Response:
        def __init__(self, *, text=None, payload=None):
            self.text = text
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Session:
        def get(self, url, **_kwargs):
            if "daily-treasury-rates.csv" in url:
                raise ConnectionError("Treasury temporarily unavailable")
            if url == macro.NYFED_URLS["sofr"]:
                return Response(payload=fixture_json("nyfed_sofr.json"))
            if url == macro.NYFED_URLS["effr"]:
                return Response(payload=fixture_json("nyfed_effr.json"))
            if url == macro.FED_URL:
                return Response(text=fixture_text("fed_h10.csv"))
            raise AssertionError(f"unexpected URL: {url}")

    previous_path = FIXTURES / "macro_previous.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8"))
    result = macro.fetch_macro(
        "2026-11-12",
        http_session=Session(),
        previous_path=previous_path,
    )

    assert result["treasury"] == previous["treasury"]
    assert result["sources"]["treasury"]["ok"] is False
    assert result["sources"]["treasury"]["stale"] is True
    assert result["sources"]["treasury"]["asof"] == "2026-11-10"
    assert "Treasury temporarily unavailable" in result["sources"]["treasury"]["error"]
    assert result["sources"]["nyfed"]["ok"] is True
    assert result["sources"]["fed_h10"]["ok"] is True
    assert result["rates"]["sofr"]["latest"]["rate"] == 3.89
