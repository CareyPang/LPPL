from __future__ import annotations

import argparse
import csv
import io
import json
import math
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all"
    "?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv"
)
NYFED_URLS = {
    "sofr": "https://markets.newyorkfed.org/api/rates/secured/sofr/last/250.json",
    "effr": "https://markets.newyorkfed.org/api/rates/unsecured/effr/last/250.json",
}
FED_URL = "https://www.federalreserve.gov/datadownload/Output.aspx"
FED_H10_PACKAGE = "60f32914ab61dfab590e0e470153e3ae"
DATA_DIR = Path(__file__).resolve().parents[2] / "web" / "mock" / "data" / "macro"
DESCRIPTIVE_NOTE = "只作市场背景，不进入 LPPLS 报警或任何模型。"
NYFED_ATTRIBUTION = (
    "The SOFR and EFFR are subject to the Terms of Use posted at newyorkfed.org. "
    "The New York Fed is not responsible for publication of the SOFR and EFFR by LPPL, "
    "does not sanction or endorse any particular republication, and has no liability "
    "for your use."
)

_H10_CURRENCIES = {
    "CNY": "人民币 / 美元",
    "JPY": "日元 / 美元",
    "EUR": "美元 / 欧元",
}
_H10_BROAD_CODE = "DTWEXBGS"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def _number(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", ".", "ND", "N/A", "NA", "-"}:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_date(value: str, formats: tuple[str, ...]) -> str | None:
    text = str(value).strip()
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _source_meta(
    provider: str, ok: bool, asof: str | None = None, error: str | None = None
) -> dict:
    source = {
        "provider": provider,
        "asof": asof,
        "fetched_at": _now(),
        "ok": bool(ok),
        "stale": not ok,
    }
    if error:
        source["error"] = error
    return source


def _get_text(session: requests.Session, url: str, params: dict | None = None) -> str:
    response = session.get(
        url,
        params=params,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (compatible; LPPLMacro/1.0)"},
    )
    response.raise_for_status()
    return response.text


def _get_json(session: requests.Session, url: str) -> dict:
    response = session.get(
        url,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (compatible; LPPLMacro/1.0)"},
    )
    response.raise_for_status()
    return response.json()


def parse_treasury_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "Date" not in reader.fieldnames:
        raise ValueError("Treasury CSV is missing the Date column")
    tenors = [name for name in reader.fieldnames if name and name != "Date"]
    rows = []
    for raw in reader:
        parsed_date = _parse_date(raw.get("Date", ""), ("%m/%d/%Y", "%Y-%m-%d"))
        if parsed_date is None:
            continue
        curve = {tenor: _number(raw.get(tenor)) for tenor in tenors}
        rows.append({"date": parsed_date, "curve": curve})
    if not rows:
        raise ValueError("Treasury CSV contains no dated observations")
    return rows


def _treasury_url(year: int) -> str:
    return TREASURY_URL.format(year=year)


def _spread(curve: dict, long_tenor: str, short_tenor: str) -> float | None:
    long_rate = curve.get(long_tenor)
    short_rate = curve.get(short_tenor)
    if long_rate is None or short_rate is None:
        return None
    return round(long_rate - short_rate, 6)


def _treasury_snapshot(rows: list[dict]) -> dict:
    rows = sorted({row["date"]: row for row in rows}.values(), key=lambda row: row["date"])
    if len(rows) < 251:
        raise ValueError(f"Treasury data has {len(rows)} observations; 251 are required")
    latest = rows[-1]
    twenty = rows[-21]
    two_fifty = rows[-251]
    curve = latest["curve"]
    return {
        "asof": latest["date"],
        "tenors": list(curve),
        "latest": latest,
        "20d_ago": twenty,
        "250d_ago": two_fifty,
        "spreads": {
            "10y_minus_2y": _spread(curve, "10 Yr", "2 Yr"),
            "10y_minus_3m": _spread(curve, "10 Yr", "3 Mo"),
        },
        "series_250d": [
            {
                "date": row["date"],
                "2y": row["curve"].get("2 Yr"),
                "10y": row["curve"].get("10 Yr"),
                "10y_minus_2y": _spread(row["curve"], "10 Yr", "2 Yr"),
            }
            for row in rows[-250:]
        ],
    }


def fetch_treasury(session: requests.Session, asof: str) -> dict:
    asof_date = date.fromisoformat(asof)
    current = parse_treasury_csv(_get_text(session, _treasury_url(asof_date.year)))
    rows = [row for row in current if row["date"] <= asof]
    if len(rows) < 251:
        previous = parse_treasury_csv(_get_text(session, _treasury_url(asof_date.year - 1)))
        rows.extend(row for row in previous if row["date"] <= asof)
    snapshot = _treasury_snapshot(rows)
    snapshot["evidence"] = "descriptive"
    snapshot["note"] = DESCRIPTIVE_NOTE
    return snapshot


def parse_nyfed(payload: dict, rate: str) -> list[dict]:
    if rate not in {"sofr", "effr"}:
        raise ValueError(f"unsupported NY Fed rate: {rate}")
    rows = []
    for raw in payload.get("refRates") or []:
        effective_date = _parse_date(raw.get("effectiveDate", ""), ("%Y-%m-%d",))
        percent_rate = _number(raw.get("percentRate"))
        if effective_date is None or percent_rate is None:
            continue
        row = {
            "date": effective_date,
            "rate": percent_rate,
            "volume_in_billions": _number(raw.get("volumeInBillions")),
        }
        if rate == "effr":
            row["target_rate_from"] = _number(raw.get("targetRateFrom"))
            row["target_rate_to"] = _number(raw.get("targetRateTo"))
        rows.append(row)
    rows.sort(key=lambda row: row["date"])
    if not rows:
        raise ValueError(f"NY Fed {rate.upper()} response contains no valid rates")
    return rows[-250:]


def fetch_nyfed(session: requests.Session) -> tuple[dict, str]:
    sofr = parse_nyfed(_get_json(session, NYFED_URLS["sofr"]), "sofr")
    effr = parse_nyfed(_get_json(session, NYFED_URLS["effr"]), "effr")
    asof = min(sofr[-1]["date"], effr[-1]["date"])
    return (
        {
            "sofr": {"latest": sofr[-1], "series": sofr},
            "effr": {"latest": effr[-1], "series": effr},
            "attribution": NYFED_ATTRIBUTION,
            "evidence": "descriptive",
            "note": DESCRIPTIVE_NOTE,
        },
        asof,
    )


def parse_h10_csv(text: str) -> dict:
    records = list(csv.reader(io.StringIO(text)))
    headers = {
        row[0].strip().rstrip(":"): [cell.strip() for cell in row[1:]]
        for row in records
        if row and not row[0][:1].isdigit()
    }
    codes = headers.get("Time Period")
    if not codes:
        raise ValueError("Federal Reserve H.10 CSV is missing Time Period series")
    descriptions = headers.get("Series Description", [])
    units = headers.get("Unit", [])
    currencies = headers.get("Currency", [])
    unique_ids = headers.get("Unique Identifier", [])
    metadata = {}
    for index, code in enumerate(codes):
        if not code:
            continue
        description = descriptions[index] if index < len(descriptions) else ""
        currency = currencies[index] if index < len(currencies) else ""
        metadata[code] = {
            "name": description,
            "unit": units[index] if index < len(units) else "",
            "currency": currency,
            "unique_id": unique_ids[index] if index < len(unique_ids) else "",
            "quote": (
                "USD per 1 " + currency
                if index < len(unique_ids) and "$US" in unique_ids[index]
                else (currency + " per 1 USD" if currency else "")
            ),
        }
    selected = {
        code for code, meta in metadata.items() if meta["currency"].upper() in _H10_CURRENCIES
    }
    broad_code = _H10_BROAD_CODE if _H10_BROAD_CODE in metadata else None
    if broad_code is None:
        broad_code = next(
            (
                code
                for code, meta in metadata.items()
                if "broad" in meta["name"].lower()
                and ("dollar" in meta["name"].lower() or "trade weighted" in meta["name"].lower())
            ),
            None,
        )
    if broad_code:
        selected.add(broad_code)
    if not selected:
        raise ValueError("Federal Reserve H.10 CSV contains none of the requested series")

    index_by_code = {code: index for index, code in enumerate(codes)}
    rows = []
    for raw in records:
        if not raw or not raw[0][:1].isdigit():
            continue
        row_date = _parse_date(raw[0], ("%Y-%m-%d", "%Y%m%d"))
        if row_date is None:
            continue
        row = {"date": row_date}
        for code in selected:
            index = index_by_code[code] + 1
            row[code] = _number(raw[index]) if index < len(raw) else None
        rows.append(row)
    rows.sort(key=lambda row: row["date"])
    if not rows:
        raise ValueError("Federal Reserve H.10 CSV contains no observations")
    return {"metadata": metadata, "rows": rows, "broad_code": broad_code}


def _h10_snapshot(parsed: dict) -> dict:
    series = {}
    for currency, display_name in _H10_CURRENCIES.items():
        code = next(
            (
                code
                for code, meta in parsed["metadata"].items()
                if meta["currency"].upper() == currency
            ),
            None,
        )
        if code is None:
            continue
        observations = [
            {"date": row["date"], "value": row.get(code)}
            for row in parsed["rows"]
            if row.get(code) is not None
        ][-250:]
        if observations:
            meta = parsed["metadata"][code]
            series[currency] = {
                "code": code,
                "label": display_name,
                "name": meta["name"],
                "unit": meta["unit"],
                "quote": meta["quote"],
                "latest": observations[-1],
                "observations": observations,
            }
    broad_code = parsed.get("broad_code")
    if broad_code:
        observations = [
            {"date": row["date"], "value": row.get(broad_code)}
            for row in parsed["rows"]
            if row.get(broad_code) is not None
        ][-250:]
        if observations:
            meta = parsed["metadata"][broad_code]
            series["USD_BROAD"] = {
                "code": broad_code,
                "label": "美元广义指数",
                "name": meta["name"],
                "unit": meta["unit"],
                "quote": "index points",
                "latest": observations[-1],
                "observations": observations,
            }
    if not series:
        raise ValueError("Federal Reserve H.10 returned no usable requested observations")
    asof = max(item["latest"]["date"] for item in series.values())
    return {
        "asof": asof,
        "series": series,
        "evidence": "descriptive",
        "note": DESCRIPTIVE_NOTE,
    }


def fetch_h10(session: requests.Session) -> dict:
    params = {
        "rel": "H10",
        "series": FED_H10_PACKAGE,
        "lastobs": "300",
        "from": "",
        "to": "",
        "filetype": "csv",
        "label": "include",
        "layout": "seriescolumn",
        "type": "package",
    }
    parsed = parse_h10_csv(_get_text(session, FED_URL, params=params))
    return _h10_snapshot(parsed)


def _empty_snapshot(asof: str) -> dict:
    return {
        "asof": asof,
        "generated": _now(),
        "evidence": "descriptive",
        "note": DESCRIPTIVE_NOTE,
        "sources": {},
        "treasury": {
            "asof": None,
            "tenors": [],
            "latest": None,
            "20d_ago": None,
            "250d_ago": None,
            "spreads": {"10y_minus_2y": None, "10y_minus_3m": None},
            "series_250d": [],
            "evidence": "descriptive",
            "note": DESCRIPTIVE_NOTE,
        },
        "rates": {
            "sofr": {"latest": None, "series": []},
            "effr": {"latest": None, "series": []},
            "attribution": NYFED_ATTRIBUTION,
            "evidence": "descriptive",
            "note": DESCRIPTIVE_NOTE,
        },
        "fx": {
            "asof": None,
            "series": {},
            "evidence": "descriptive",
            "note": DESCRIPTIVE_NOTE,
        },
    }


def _load_previous(path: Path) -> dict:
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
        return previous if isinstance(previous, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def fetch_macro(
    asof: str | None = None,
    http_session: requests.Session | None = None,
    previous_path: Path = DATA_DIR / "macro_latest.json",
) -> dict:
    asof = asof or _today()
    session = http_session or requests.Session()
    previous = _load_previous(Path(previous_path))
    result = _empty_snapshot(asof)
    sources = (
        ("treasury", "treasury", "home.treasury.gov", lambda: fetch_treasury(session, asof)),
        ("nyfed", "rates", "markets.newyorkfed.org", lambda: fetch_nyfed(session)),
        ("fed_h10", "fx", "www.federalreserve.gov", lambda: fetch_h10(session)),
    )
    for source_name, section, provider, fetcher in sources:
        try:
            data = fetcher()
            if source_name == "nyfed":
                section_data, source_asof = data
            else:
                section_data = data
                source_asof = section_data.get("asof")
            result[section] = section_data
            result["sources"][source_name] = _source_meta(provider, True, source_asof)
        except Exception as exc:  # noqa: BLE001 — sources fail independently
            old_section = previous.get(section)
            if not isinstance(old_section, dict):
                old_section = {}
            if old_section:
                result[section] = old_section
            old_sources = previous.get("sources")
            if not isinstance(old_sources, dict):
                old_sources = {}
            old_meta = old_sources.get(source_name, {})
            if not isinstance(old_meta, dict):
                old_meta = {}
            result["sources"][source_name] = _source_meta(
                provider,
                False,
                old_meta.get("asof") or (old_section or {}).get("asof"),
                _error(exc),
            )
        if section == "rates":
            result["rates"]["attribution"] = NYFED_ATTRIBUTION
    return result


def write_snapshot(snapshot: dict, out: Path) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    latest = out / "macro_latest.json"
    dated = out / f"macro_{snapshot['asof']}.json"
    encoded = json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    latest.write_text(encoded, encoding="utf-8")
    dated.write_text(encoded, encoding="utf-8")
    return latest, dated


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch official global macro context")
    parser.add_argument("--out", type=Path, default=DATA_DIR)
    parser.add_argument("--previous", type=Path, default=DATA_DIR / "macro_latest.json")
    args = parser.parse_args()
    snapshot = fetch_macro(previous_path=args.previous)
    latest, dated = write_snapshot(snapshot, args.out)
    print(
        json.dumps(
            {
                "latest": str(latest),
                "dated": str(dated),
                "sources": snapshot["sources"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
