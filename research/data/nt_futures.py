"""Daily CFFEX seat / basis readings for the 宽基ETF page. Descriptive only: no rule here passed its registered test."""
from __future__ import annotations

import csv
import json
import re
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = ROOT / "data" / "nt_futures" / "panel_2015_2026.json"
REPORT_PATH = ROOT / "reports" / "nt_futures_signal.json"
RANK_URL = "http://www.cffex.com.cn/sj/ccpm/{ym}/{dd}/{product}_1.csv"
QUOTE_URL = "http://www.cffex.com.cn/sj/hqsj/rtj/{ym}/{dd}/{ymd}_1.csv"
HEADERS = {"Referer": "http://www.cffex.com.cn/", "User-Agent": "Mozilla/5.0"}
SPOT = {"IF": "sh000300", "IH": "sh000016", "IC": "sh000905", "IM": "sh000852"}
SEAT = "中信期货"
SEAT_STEP = 5000
INDEX_JUMP = 0.02
KEEP = 120
FIELDS = ("spot", "fut", "sym", "basis", "cl", "clc", "cs", "csc", "tl", "ts")
EVENTS = (
    ("E1", "中信 IF+IH 多单单日增加 ≥ 5,000 手"),
    ("E2", "IC 主力合约基差由负转正"),
    ("E3", "多单增加与 IC 基差转正同日"),
    ("E4", "多单增加、基差转正、前 20 净空减少、沪深300 涨 ≥ 2% 同日"),
    ("E5", "多单增加但前 20 净空扩大"),
    ("E6", "中信 IF+IH 多单单日减少 ≥ 5,000 手"),
)


def _num(value) -> float:
    try:
        return float(str(value).strip())
    except ValueError:
        return 0.0


def parse_rank(text: str, ymd: str) -> dict:
    """Seat (中信期货, any suffix) and top-20 long / short totals over all listed contracts of one product."""
    out = {"cl": 0.0, "clc": 0.0, "cs": 0.0, "csc": 0.0, "tl": 0.0, "ts": 0.0}
    seen = 0
    for row in csv.reader(text.splitlines()):
        if len(row) < 12 or not row[2].strip().isdigit():
            continue
        if row[0].strip() != ymd:
            raise RuntimeError(f"CFFEX rank date mismatch: {row[0]!r}")
        seen += 1
        out["tl"] += _num(row[7])
        out["ts"] += _num(row[10])
        for col, key in ((6, "cl"), (9, "cs")):
            if row[col].strip().startswith(SEAT):
                out[key] += _num(row[col + 1])
                out[key + "c"] += _num(row[col + 2])
    if not seen:
        raise RuntimeError("CFFEX rank file has no rows")
    return out


def _third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7 + 14)


def parse_quotes(text: str, day: str) -> dict[str, tuple[float, str]]:
    """Close and symbol of the most traded unexpired contract per product."""
    today, best = date.fromisoformat(day), {}
    for row in csv.reader(text.splitlines()):
        match = re.fullmatch(r"(IF|IH|IC|IM)(\d\d)(\d\d)", row[0].strip()) if row else None
        if not match or len(row) < 9:
            continue
        volume, close = _num(row[4]), _num(row[8])
        if close <= 0 or _third_friday(2000 + int(match[2]), int(match[3])) < today:
            continue
        if match[1] not in best or volume > best[match[1]][0]:
            best[match[1]] = (volume, close, row[0].strip())
    return {product: (close, symbol) for product, (_, close, symbol) in best.items()}


def fetch_day(session, day: str, spot: dict[str, float]) -> dict:
    ym, dd, ymd = day[:7].replace("-", ""), day[-2:], day.replace("-", "")

    def get(url):
        response = session.get(url, headers=HEADERS, timeout=20, allow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError(f"CFFEX HTTP {response.status_code}: {url}")
        return response.content.decode("gbk", "replace")

    quotes = parse_quotes(get(QUOTE_URL.format(ym=ym, dd=dd, ymd=ymd)), day)
    row = {"date": day}
    for product in SPOT:
        close, symbol = quotes[product]
        row[product] = {
            "spot": spot[product], "fut": close, "sym": symbol, "basis": (close / spot[product] - 1) * 100,
            **parse_rank(get(RANK_URL.format(ym=ym, dd=dd, product=product)), ymd),
        }
    return row


def seed_rows() -> list[dict]:
    panel = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    return [
        {"date": day, **{p: {k: panel[day][p].get(k) for k in FIELDS} for p in SPOT}}
        for day in sorted(panel)[-KEEP:]
    ]


def _seat(row) -> float:
    return row["IF"]["cl"] + row["IH"]["cl"]


def _net_short(row) -> float:
    return sum(row[p]["ts"] - row[p]["tl"] for p in SPOT)


def reading(rows: list[dict]) -> dict | None:
    """The latest day against the day before, using the registered definitions."""
    if len(rows) < 2:
        return None
    prev, last = rows[-2], rows[-1]
    seat_chg = _seat(last) - _seat(prev)
    net_chg = _net_short(last) - _net_short(prev)
    index_pct = last["IF"]["spot"] / prev["IF"]["spot"] - 1
    r1, x1 = seat_chg >= SEAT_STEP, seat_chg <= -SEAT_STEP
    r2 = prev["IC"]["basis"] < 0 < last["IC"]["basis"]
    r3, r4 = net_chg < 0, index_pct >= INDEX_JUMP
    hit = {"E1": r1, "E2": r2, "E3": r1 and r2, "E4": r1 and r2 and r3 and r4, "E5": r1 and not r3, "E6": x1}
    return {
        "date": last["date"], "previous_date": prev["date"],
        "seat_long_chg": seat_chg, "net_short": _net_short(last), "net_short_chg": net_chg,
        "index_pct": index_pct * 100,
        "basis": {p: last[p]["basis"] for p in SPOT}, "basis_previous": {p: prev[p]["basis"] for p in SPOT},
        "events": [key for key, _ in EVENTS if hit[key]],
    }


def evidence() -> dict:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    keys = ("n", "median_20", "up_20", "passed")
    return {
        "first": report["first"], "last": report["last"],
        "baseline": {k: report["baseline"][k] for k in ("n", "median_20", "up_20")},
        "events": [{"key": key, "label": label, **{k: report["events"][key][k] for k in keys}} for key, label in EVENTS],
        "note": "次数按 20 个交易日内重复出现只计一次统计。条件在查看之后走势前登记，各检验一次；没有一项通过，只作当日读数，不作买卖依据。",
    }


def update(asof: str, previous: dict | None, session, closes) -> dict:
    """Append every trading day after the last published row. `closes(symbol, start, end)` returns {date: close}."""
    rows = list((previous or {}).get("rows") or seed_rows())
    last = rows[-1]["date"]
    error = None
    if last < asof:
        try:
            spot = {p: closes(symbol, last, asof) for p, symbol in SPOT.items()}
            for day in sorted(d for d in spot["IF"] if last < d <= asof):
                rows.append(fetch_day(session, day, {p: spot[p][day] for p in SPOT}))
        except Exception as exc:  # keep what was appended before the failure; the next run resumes from there
            error = f"{type(exc).__name__}: {exc}"
    rows = rows[-KEEP:]
    return {
        "schema": "nt_futures_v1", "asof": rows[-1]["date"], "error": error, "rows": rows,
        "today": reading(rows), "evidence": evidence(),
        "thresholds": {"seat_step": SEAT_STEP, "index_jump_pct": INDEX_JUMP * 100},
    }
