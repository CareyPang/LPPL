"""宽基 ETF 融资余额：上交所、深交所收盘后公布的融资融券明细，按 ETF 与分类汇总。只作描述。"""
from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pandas as pd

SSE_URL = "https://query.sse.com.cn/marketdata/tradedata/queryMargin.do"
SZSE_URL = "https://www.szse.cn/api/report/ShowReport"
SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "nt_margin" / "seed.json"
KEEP = 120
BACKFILL = 60
SZSE_COLUMNS = {"证券代码", "融资余额(元)", "融资买入额(元)"}


def _yi(value) -> float:
    return float(str(value).replace(",", "")) / 1e8


def parse_sse(pages: list[dict], day: str) -> dict[str, list[float]]:
    """{代码: [融资余额亿元, 融资买入额亿元]}。分页条数须与官方总数一致，日期须为 day。"""
    rows = [rec for page in pages for rec in (page.get("pageHelp") or {}).get("data") or []]
    total = ((pages[0].get("pageHelp") or {}).get("total")) if pages else None
    if not rows or total is None or len(rows) != int(total):
        raise RuntimeError(f"上交所 {day} 融资融券明细未发布或分页不完整")
    out = {}
    for rec in rows:
        if str(rec.get("opDate")) != day.replace("-", ""):
            raise RuntimeError(f"上交所融资融券明细日期不符：{rec.get('opDate')}")
        out[str(rec["stockCode"])] = [_yi(rec["rzye"]), _yi(rec["rzmre"])]
    return out


def parse_szse(content: bytes, day: str) -> dict[str, list[float]]:
    frame = pd.read_excel(BytesIO(content), dtype=str)
    if not SZSE_COLUMNS.issubset(frame.columns):
        raise RuntimeError("深交所融资融券明细表头发生变化")
    if frame.empty:
        raise RuntimeError(f"深交所 {day} 融资融券明细未发布")
    return {str(r["证券代码"]).zfill(6): [_yi(r["融资余额(元)"]), _yi(r["融资买入额(元)"])] for r in frame.to_dict("records")}


def fetch_day(request, session, day: str, universe: list[dict]) -> dict:
    """request(session, url, **kwargs) 为带限速的 GET。两所都取到才算这一天有数。"""
    pages, page = [], 1
    while True:
        params = {"isPagination": "true", "tabType": "mxtype", "detailsDate": day.replace("-", ""),
                  "pageHelp.pageSize": 5000, "pageHelp.pageNo": page, "pageHelp.beginPage": page,
                  "pageHelp.cacheSize": 1, "pageHelp.endPage": page}
        payload = request(session, SSE_URL, params=params, headers={"Referer": "https://www.sse.com.cn/", "User-Agent": "Mozilla/5.0"}).json()
        pages.append(payload)
        help_ = payload.get("pageHelp") or {}
        if page >= int(help_.get("pageCount") or 1) or not help_.get("data"):
            break
        page += 1
    sh = parse_sse(pages, day)
    sz = parse_szse(request(session, SZSE_URL, params={"SHOWTYPE": "xlsx", "CATALOGID": "1837_xxpl", "TABKEY": "tab2", "txtDate": day},
                            headers={"Referer": "https://www.szse.cn/", "User-Agent": "Mozilla/5.0"}).content, day)
    etfs = {}
    for item in universe:
        hit = (sh if item["exchange"] == "SH" else sz).get(item["code"])
        if hit:
            etfs[item["code"]] = [round(hit[0], 6), round(hit[1], 6)]
    return {"date": day, "etfs": etfs}


def _sum(row: dict | None, codes: list[str], index: int) -> float | None:
    """只有该行里这些代码全部有数才相加，避免成分不同的两天相减。"""
    if not row or not codes or any(code not in row["etfs"] for code in codes):
        return None
    return sum(row["etfs"][code][index] for code in codes)


def _group(rows: list[dict], codes: list[str]) -> dict:
    last, prev, week = rows[-1], rows[-2] if len(rows) > 1 else None, rows[-6] if len(rows) > 5 else None
    held = [c for c in codes if c in last["etfs"]]
    balance = _sum(last, held, 0)
    before, earlier = _sum(prev, held, 0), _sum(week, held, 0)
    return {
        "n": len(codes), "n_margin": len(held), "balance_yi": balance, "buy_yi": _sum(last, held, 1),
        "chg_yi": balance - before if balance is not None and before is not None else None,
        "chg_5d_yi": balance - earlier if balance is not None and earlier is not None else None,
    }


def summary(rows: list[dict], universe: list[dict]) -> dict:
    if not rows:
        return {"categories": [], "total": None, "etfs": {}, "series": []}
    cats = {}
    for item in universe:
        cats.setdefault(item["category"], []).append(item["code"])
    codes = [item["code"] for item in universe]
    held = [c for c in codes if c in rows[-1]["etfs"]]
    etfs = {}
    for code in held:
        g = _group(rows, [code])
        etfs[code] = {k: g[k] for k in ("balance_yi", "buy_yi", "chg_yi", "chg_5d_yi")}
    return {
        "categories": sorted(({"category": c, **_group(rows, cs)} for c, cs in cats.items()),
                             key=lambda g: -(g["balance_yi"] or 0)),
        "total": _group(rows, codes),
        "etfs": etfs,
        "series": [[r["date"], _sum(r, held, 0)] for r in rows],
    }


def update(asof: str, previous: dict | None, session, request, trading_days, universe: list[dict]) -> dict:
    """补齐最近 BACKFILL 个交易日里还没有的日子；交易所尚未公布的日子停在那里，下次再补。"""
    rows = (previous or {}).get("rows")
    if not rows and SEED_PATH.exists():
        rows = json.loads(SEED_PATH.read_text(encoding="utf-8"))["rows"]
    by_day = {r["date"]: r for r in rows or []}
    error = None
    try:
        for day in [d for d in sorted(trading_days(asof))[-BACKFILL:] if d <= asof and d not in by_day]:
            by_day[day] = fetch_day(request, session, day, universe)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    rows = [by_day[d] for d in sorted(by_day)][-KEEP:]
    return {"schema": "nt_margin_v1", "asof": rows[-1]["date"] if rows else None, "error": error, "rows": rows,
            **summary(rows, universe)}
