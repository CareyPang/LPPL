from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

from .sources import UA, rate_limit
from .tencent_sina import tencent_raw

ROOT = Path(__file__).resolve().parents[2]
UNIVERSE_PATH = ROOT / "data/nt_etf/universe.json"
SSE_URL = "https://query.sse.com.cn/commonQuery.do"
SZSE_URL = "https://fund.szse.cn/api/report/ShowReport/data"
HOLDER_PAGE = "https://stock.finance.sina.com.cn/fundInfo/view/FundInfo_JJCYR.php"
HOLDER_API = "https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/CaihuiFundInfoService.getFundHolder"
CFFEX_URL = "http://www.cffex.com.cn/sj/ccpm/{ym}/{dd}/{product}_1.csv"
NT_MATCH = ("中央汇金", "汇金资管", "汇金资产管理", "汇金投资", "社保基金", "全国社保", "社会保障基金", "证金", "中国证券金融", "国新", "诚通")
GROUPS = (("中央汇金", ("中央汇金",)), ("汇金资管", ("汇金资管", "汇金资产管理", "汇金投资")), ("社保基金", ("社保基金", "全国社保", "社会保障基金")), ("证金公司", ("证金", "中国证券金融")), ("国新诚通", ("国新", "诚通")))
INDEX_BY_CATEGORY = {
    "沪深300": "sh000300", "科创50": "sh000688", "创业板": "sz399006",
    "中证1000": "sh000852", "中证500": "sh000905", "上证50": "sh000016",
    "中证A500": "sh000510", "创业板50": "sz399673", "中证800": "sh000906",
    "深证100": "sz399330", "上证180": "sh000010", "上证180金融": "sh000018",
    "MSCI A50": "sh000985",
}
ALL_SHARE_INDEX = "sh000985"
NOTE = "汇金重仓 ETF 份额变化（申赎估算）。全市场申赎合计，不能全部归因于国家队；不进入模型，不构成买卖建议。"
HEADERS = {**UA, "Referer": "https://www.sse.com.cn/"}


def _number(value):
    if value is None or str(value).strip() in ("", "-", "--", "—"):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"not numeric: {value!r}") from exc


def _request(session, url, **kwargs):
    rate_limit()
    response = session.get(url, timeout=25, **kwargs)
    response.raise_for_status()
    return response


def _parse_sse(payload: dict, day: str) -> dict[str, dict]:
    rows, page = payload.get("result"), payload.get("pageHelp")
    if not isinstance(rows, list) or not isinstance(page, dict):
        raise RuntimeError("SSE ETF response lacks result/pageHelp")
    total = int(page["total"])
    if len(rows) != total:
        raise RuntimeError(f"SSE total mismatch: {len(rows)} != {total}")
    if not rows:
        raise RuntimeError(f"SSE has no ETF shares for trading date {day}")
    out = {}
    for row in rows:
        if not {"SEC_CODE", "SEC_NAME", "STAT_DATE", "TOT_VOL"} <= set(row):
            raise RuntimeError("SSE row lacks required fields")
        if row["STAT_DATE"] != day:
            raise RuntimeError("SSE returned a different date")
        out[str(row["SEC_CODE"])] = {"name": row["SEC_NAME"], "shares_10k": _number(row["TOT_VOL"])}
    return out


def _parse_szse(payload: object) -> tuple[dict[str, float], tuple[str, int, int]]:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise RuntimeError("SZSE response is not a table array")
    table = payload[0]
    meta, rows = table.get("metadata"), table.get("data")
    if not isinstance(meta, dict) or not isinstance(rows, list):
        raise RuntimeError("SZSE response lacks metadata/data")
    snap = (str(meta.get("txtStart", meta.get("subname", ""))), int(meta["pagecount"]), int(meta["recordcount"]))
    output = {}
    for row in rows:
        code = re.search(r"(\d{6})", str(row.get("sys_key", "")))
        size = re.search(r">([\d,.]+)</a>", str(row.get("dqgm", "")))
        if not code or not size:
            raise RuntimeError("SZSE row format changed")
        output[code.group(1)] = _number(size.group(1))
    return output, snap


def _parse_szse_history(payload: object) -> tuple[dict[str, float], int]:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise RuntimeError("SZSE history response is not a table array")
    table = payload[0]
    meta, rows = table.get("metadata"), table.get("data")
    if not isinstance(meta, dict) or not isinstance(rows, list):
        raise RuntimeError("SZSE history lacks metadata/data")
    output = {}
    for row in rows:
        if not {"size_date", "current_size"} <= set(row):
            raise RuntimeError("SZSE history row lacks size_date/current_size")
        output[str(row["size_date"])[:10]] = _number(row["current_size"])
    return output, int(meta["pagecount"])


def _parse_holders(payload: dict) -> dict:
    data = payload.get("result", {}).get("data")
    if not isinstance(data, list):
        raise RuntimeError("holder response lacks result.data")
    nt = []
    for row in data:
        if not {"cyrmc", "cyfe", "zfeb"} <= set(row):
            raise RuntimeError("holder row lacks cyrmc/cyfe/zfeb")
        name = str(row["cyrmc"])
        if "联接" in name or not any(token in name for token in NT_MATCH):
            continue
        group = next(group for group, tokens in GROUPS if any(token in name for token in tokens))
        nt.append({"group": group, "name": name, "shares_yi": _number(row["cyfe"]) / 1e8, "ratio": _number(row["zfeb"])})
    nt_shares = sum(row["shares_yi"] for row in nt)
    nt_ratio = sum(row["ratio"] for row in nt)
    return {"nt": nt, "nt_shares_yi": nt_shares, "nt_ratio": nt_ratio}


def _parse_cffex(text: str, ymd: str, product: str) -> dict:
    rows = list(csv.reader(text.splitlines()))
    if len(rows) < 3 or rows[0][:4] != ["交易日", "合约", "排名", "成交量排名"]:
        raise RuntimeError("CFFEX rank CSV header changed")
    sub = [v.strip() for v in rows[1][3:12]]
    expected = ["会员简称", "成交量", "比上一交易日增减", "会员简称", "持买单量", "比上一交易日增减", "会员简称", "持卖单量", "比上一交易日增减"]
    if sub != expected:
        raise RuntimeError("CFFEX rank subheader changed")
    long = long_chg = short = short_chg = 0.0
    for row in rows[2:]:
        if len(row) < 12 or not row[2].strip().isdigit():
            continue
        if row[0].strip() != ymd:
            raise RuntimeError(f"CFFEX date mismatch: {row[0]!r}")
        if row[6].strip() == "中信期货(代客)":
            long += _number(row[7]) or 0
            long_chg += _number(row[8]) or 0
        if row[9].strip() == "中信期货(代客)":
            short += _number(row[10]) or 0
            short_chg += _number(row[11]) or 0
    return {"product": product, "long": long, "long_chg": long_chg, "short": short, "short_chg": short_chg,
            "net_short": short - long, "net_short_chg": short_chg - long_chg}


def flow_yuan(shares: float | None, previous: float | None, close: float | None) -> float | None:
    if shares is None or previous is None or close is None:
        return None
    return (shares - previous) * close


def _window(series: list, days: int) -> tuple[float | None, int]:
    values = [row[3] for row in series[-days:] if row[3] is not None]
    return (sum(values) if values else None, len(values))


def _latest_share_observations(series: list) -> tuple[list | None, list | None]:
    known = [row for row in series if row[1] is not None]
    return (known[-1] if known else None, known[-2] if len(known) > 1 else None)


def _sum_latest(group: list[dict], key: str) -> float | None:
    values = [item["latest"][key] for item in group if item["latest"][key] is not None]
    return sum(values) if values else None


def _shanghai_etf(session, day):
    params = {"sqlId":"COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L","STAT_DATE":day,"isPagination":"true",
              "pageHelp.pageSize":10000,"pageHelp.pageNo":1,"pageHelp.beginPage":1,"pageHelp.cacheSize":1,"pageHelp.endPage":1}
    return _parse_sse(_request(session, SSE_URL, params=params, headers={"Referer":"https://www.sse.com.cn/"}).json(), day)


def _szse_history(session, code, start, end):
    result = {}
    cursor = pd.Timestamp(start)
    while cursor <= pd.Timestamp(end):
        stop = min(cursor + pd.Timedelta(days=109), pd.Timestamp(end))
        page = 1
        expected = None
        while expected is None or page <= expected:
            params = {"SHOWTYPE":"JSON","CATALOGID":"fund_jjgm","TABKEY":"tab1","txtDm":code,
                      "txtStart":cursor.strftime("%Y-%m-%d"),"txtEnd":stop.strftime("%Y-%m-%d"),"PAGENO":page}
            payload = _request(session, SZSE_URL, params=params, headers={"Referer":"https://fund.szse.cn/"}).json()
            values, pagecount = _parse_szse_history(payload)
            if expected is None:
                expected = pagecount
            elif pagecount != expected:
                raise RuntimeError("SZSE history pagecount changed during pagination")
            result.update(values)
            page += 1
        cursor = stop + pd.Timedelta(days=1)
    return result


def _holders(session, code):
    page = _request(session, HOLDER_PAGE, params={"symbol":code}, headers={"Referer":"https://stock.finance.sina.com.cn/"}).content.decode("gbk", errors="replace")
    dates = re.findall(r'<option\s+value="(\d{4}-\d{2}-\d{2})"', page)
    if not dates:
        raise RuntimeError("holder page has no report dates")
    report_date = max(dates)
    payload = _request(session, HOLDER_API, params={"symbol":code,"date":report_date},
                       headers={"Referer":f"{HOLDER_PAGE}?symbol={code}"}).json()
    result = _parse_holders(payload)
    result["report_date"] = report_date
    result["checked_at"] = datetime.now().astimezone().isoformat()
    return result


def _prices(universe, start, end):
    out, errors = {}, []
    for item in universe:
        symbol = item["exchange"].lower() + item["code"]
        try:
            frame = tencent_raw(symbol, start=start, end=end)
            out[item["code"]] = {str(pd.Timestamp(row.date).date()): float(row.close) for row in frame.itertuples()}
        except Exception as exc:
            errors.append(f"{item['code']}: {type(exc).__name__}: {exc}")
    return out, errors


def _fetch_shares(universe, dates, start, end, session):
    sh, sz, sse_errors, szse_errors = {}, {}, [], []
    # Warm SSE cookies before querying the daily disclosure endpoint.
    try:
        _request(session, "https://www.sse.com.cn/", headers=HEADERS)
    except Exception as exc:
        sse_errors.append(f"warmup: {type(exc).__name__}: {exc}")
    for day in dates:
        try:
            sh[day] = _shanghai_etf(session, day)
        except Exception as exc:
            sse_errors.append(f"{day}: {type(exc).__name__}: {exc}")
    for item in universe:
        if item["exchange"] != "SZ":
            continue
        try:
            sz[item["code"]] = _szse_history(session, item["code"], start, end)
        except Exception as exc:
            szse_errors.append(f"{item['code']}: {type(exc).__name__}: {exc}")
    return sh, sz, sse_errors, szse_errors


def _load_previous(path):
    if not path or not Path(path).is_file():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fetch(asof: str, previous=None, backfill_start=None, session=None) -> dict:
    universe = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    prev = _load_previous(previous) if isinstance(previous, (str, Path)) else previous
    start = backfill_start or (prev.get("asof") if prev and not backfill_start else asof)
    start = start or asof
    session = session or requests.Session()
    prices, price_errors = _prices(universe, start, asof)
    calendar = sorted({day for values in prices.values() for day in values})
    if not calendar:
        calendar = [asof]
    sh, sz, sse_errors, szse_errors = _fetch_shares(universe, calendar, start, asof, session)
    previous_by_code = {e["code"]: e for e in (prev or {}).get("etfs", [])}
    etfs = []
    holders_errors = []
    for item in universe:
        old = previous_by_code.get(item["code"], {})
        old_series = old.get("series", []) if not backfill_start else []
        close_map = {**{row[0]: row[2] for row in old_series}, **prices.get(item["code"], {})}
        share_map = {row[0]: row[1] for row in old_series}
        if item["exchange"] == "SH":
            for day, values in sh.items():
                if item["code"] in values:
                    share_map[day] = values[item["code"]]["shares_10k"] / 10000
        else:
            for day, value in sz.get(item["code"], {}).items():
                share_map[day] = value / 10000
        dates = sorted(set(share_map) | set(close_map))
        series = []
        prior = None
        for day in dates:
            shares, close = share_map.get(day), close_map.get(day)
            flow = flow_yuan(shares, prior, close)
            series.append([day, shares, close, flow])
            prior = shares
        holder = old.get("holders")
        checked = pd.to_datetime((holder or {}).get("checked_at"), errors="coerce")
        if holder is None or pd.isna(checked) or (pd.Timestamp.now(tz="UTC") - (checked.tz_localize("UTC") if checked.tzinfo is None else checked.tz_convert("UTC"))).days >= 7:
            try:
                holder = _holders(session, item["code"])
            except Exception as exc:
                holders_errors.append(f"{item['code']}: {type(exc).__name__}: {exc}")
                holder = holder or {"report_date": None, "nt": [], "nt_shares_yi": None, "nt_ratio": None, "checked_at": None}
        latest = series[-1] if series else [asof, None, None, None]
        latest_shares, prior_shares = _latest_share_observations(series)
        latest_shares_yi = latest_shares[1] if latest_shares else None
        prev_shares = holder.get("nt_shares_yi") if holder else None
        nt_ratio = holder.get("nt_ratio") if holder else None
        report_total = prev_shares / nt_ratio * 100 if prev_shares is not None and nt_ratio else None
        windows = {f"flow_{n}d": _window(series, n) for n in (5, 21, 120)}
        ytd = [r[3] for r in series if r[0][:4] == asof[:4] and r[3] is not None]
        holder = {**(holder or {}), "nt_value_yi": prev_shares * latest[2] if prev_shares is not None and latest[2] is not None else None}
        etfs.append({**item, "series": series, "latest": {"shares_yi": latest_shares_yi,
            "shares_date": latest_shares[0] if latest_shares else None,
            "chg_yi": latest_shares_yi - prior_shares[1] if latest_shares and prior_shares else None,
            "flow_yi": latest[3], **{k: v[0] for k,v in windows.items()}, "flow_ytd": sum(ytd) if ytd else None,
            "flow_ytd_n_days": len(ytd),
            **{f"{k}_n_days": v[1] for k,v in windows.items()}},
            "holders": holder,
            "shares_vs_report": latest_shares_yi/report_total if report_total and latest_shares_yi is not None else None})
    sources = {
        "prices": {"ok": not price_errors, "error": "; ".join(price_errors) if price_errors else None},
        "sse_shares": {"ok": bool(sh) and not sse_errors, "error": "; ".join(sse_errors) if sse_errors else None},
        "szse_shares": {"ok": len(sz) == sum(x["exchange"] == "SZ" for x in universe) and not szse_errors, "error": "; ".join(szse_errors) if szse_errors else None},
        "holders": {"ok": not holders_errors, "error": "; ".join(holders_errors) if holders_errors else None},
    }
    cffex = {"date": asof, "products": []}
    try:
        for product in ("IF", "IH", "IC", "IM"):
            url = CFFEX_URL.format(ym=asof[:7].replace("-", ""), dd=asof[-2:], product=product)
            text = _request(session, url, headers={"Referer":"http://www.cffex.com.cn/"}).content.decode("gbk")
            cffex["products"].append(_parse_cffex(text, asof.replace("-", ""), product))
        sources["cffex"] = {"ok": True, "error": None}
    except Exception as exc:
        sources["cffex"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    indices, index_errors = {}, []
    for symbol in sorted(set(INDEX_BY_CATEGORY.values()) | {ALL_SHARE_INDEX}):
        try:
            frame = tencent_raw(symbol, start=start, end=asof)
            indices[symbol] = [
                {"date": str(pd.Timestamp(row.date).date()), "open": float(row.open), "high": float(row.high),
                 "low": float(row.low), "close": float(row.close)}
                for row in frame.itertuples()
            ]
        except Exception as exc:
            index_errors.append(f"{symbol}: {type(exc).__name__}: {exc}")
    sources["indices"] = {"ok": not index_errors, "error": "; ".join(index_errors) if index_errors else None}
    dates = sorted({row[0] for e in etfs for row in e["series"]})
    totals_daily = []
    for day in dates:
        values = [r[3] for e in etfs for r in e["series"] if r[0] == day and r[3] is not None]
        totals_daily.append([day, sum(values) if values else None])
    def total_window(days=None, year=False):
        rows = [r for r in totals_daily if (not year or r[0][:4] == asof[:4])]
        if days:
            rows = rows[-days:]
        values = [r[1] for r in rows if r[1] is not None]
        return {"flow_yi": sum(values) if values else None, "n_days": len(values)}
    totals = {"today":total_window(1)["flow_yi"],"d5":total_window(5),"d21":total_window(21),
              "d120":total_window(120),"ytd":total_window(year=True),"daily":totals_daily}
    categories = []
    for category in sorted({e["category"] for e in etfs}):
        group = [e for e in etfs if e["category"] == category]
        categories.append({"category":category,"n":len(group),"today":_sum_latest(group, "flow_yi"),"d5":_sum_latest(group, "flow_5d"),
            "d21":_sum_latest(group, "flow_21d"),"report_shares_yi":sum(e["holders"].get("nt_shares_yi") or 0 for e in group),
            "latest_shares_yi":sum(e["latest"]["shares_yi"] or 0 for e in group),
            "nt_value_yi":sum(e["holders"].get("nt_value_yi") or 0 for e in group)})
    return {"asof":asof,"generated_at":datetime.now().astimezone().isoformat(),"sources":sources,"universe":universe,
        "etfs":etfs,"categories":categories,"totals":totals,"daily":totals_daily,"cffex":cffex,
        "indices":indices,"index_by_category":INDEX_BY_CATEGORY,"all_share_index":ALL_SHARE_INDEX,
        "notes":[NOTE,"中信期货代客为全部客户合计，常被视作机构套保参考，不等于国家队。"]}


def write_snapshot(data: dict, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    latest = out / "nt_etf_latest.json"
    dated = out / f"nt_etf_{data['asof']}.json"
    text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    latest.write_text(text, encoding="utf-8")
    dated.write_text(text, encoding="utf-8")
    return latest, dated


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--out", type=Path, default=Path("out/nt_etf"))
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--backfill-start")
    args = parser.parse_args(argv)
    data = fetch(args.date, args.previous, args.backfill_start)
    write_snapshot(data, args.out)
    print(json.dumps({"asof":data["asof"],"sources":data["sources"],"totals":data["totals"]},ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
