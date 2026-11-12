from __future__ import annotations

import argparse
import json
import math
import re
import time
from datetime import datetime
from pathlib import Path

import requests

TENCENT_QFQ_URL = "https://ifzq.gtimg.cn/appstock/app/fqkline/get"
TENCENT_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"
MAX_CANDIDATES = 400
MAX_OUTPUT = 50
RULES = {
    "main": {"label": "主板", "3d": {"up": 20.0, "down": -20.0}},
    "main_st": {"label": "主板 ST", "3d": {"up": 12.0, "down": -12.0}},
    "growth": {"label": "创业板", "3d": {"up": 30.0, "down": -30.0}},
    "star": {"label": "科创板", "3d": {"up": 30.0, "down": -30.0}},
    "bj": {"label": "北交所", "3d": {"up": 40.0, "down": -40.0}},
    "10d": {"up": 100.0, "down": -50.0},
    "30d": {"up": 200.0, "down": -70.0},
}
BOARD_TO_BENCHMARK = {
    "沪主板": "sh000001",
    "深主板": "sz399001",
    "创业板": "sz399006",
    "科创板": "sh000688",
    "北交所": "bj899050",
}
RULE_NOTE = "以交易所现行规则为准，规则摘要可能滞后。"


def board_for_code(code: str) -> str | None:
    code = str(code).strip()
    if re.fullmatch(r"\d{6}", code):
        if code.startswith(("920", "8", "4")):
            return "北交所"
        if code.startswith(("688", "689")):
            return "科创板"
        if code.startswith(("300", "301")):
            return "创业板"
        if code.startswith("6"):
            return "沪主板"
        if code.startswith(("0", "2")):
            return "深主板"
    return None


def _symbol(code: str) -> str:
    if re.fullmatch(r"(sh|sz|bj)\d{6}", code):
        return code
    board = board_for_code(code)
    prefix = {
        "沪主板": "sh",
        "深主板": "sz",
        "创业板": "sz",
        "科创板": "sh",
        "北交所": "bj",
    }.get(board)
    if not prefix:
        raise ValueError(f"无法确定证券市场代码前缀: {code}")
    return prefix + code


class TencentQfqClient:
    def __init__(self, session=None, sleep=time.sleep, min_interval=0.15):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": TENCENT_UA})
        self.sleep = sleep
        self.min_interval = min_interval
        self.last_call = None

    def _pace(self):
        now = time.monotonic()
        if self.last_call is not None:
            self.sleep(max(0.0, self.min_interval - (now - self.last_call)))
        self.last_call = time.monotonic()

    def fetch(self, symbol: str) -> list[dict]:
        self._pace()
        response = self.session.get(
            TENCENT_QFQ_URL,
            params={"param": f"{symbol},day,,,40,qfq"},
            timeout=20,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Tencent qfq 返回非 JSON: {exc}") from exc
        node = (payload.get("data") or {}).get(symbol)
        if not isinstance(node, dict):
            raise RuntimeError(f"Tencent qfq 缺少 {symbol} 数据")
        key = "qfqday" if "qfqday" in node else "day"
        raw_rows = node.get(key)
        if key == "qfqday" and not raw_rows and node.get("day"):
            raise RuntimeError(f"Tencent qfq {symbol} qfqday 为空")
        if not isinstance(raw_rows, list):
            raise RuntimeError(f"Tencent qfq {symbol} 缺少 {key} 行")
        rows, seen = [], set()
        for row in raw_rows:
            if not isinstance(row, list) or len(row) < 6:
                raise RuntimeError(f"Tencent qfq {symbol} 行格式无效")
            day = str(row[0])
            if re.fullmatch(r"\d{8}", day):
                day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
            else:
                day = day[:10]
            try:
                close = float(row[2])
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"Tencent qfq {symbol} 收盘价无效: {row[2]!r}") from exc
            if not math.isfinite(close) or close <= 0:
                raise RuntimeError(f"Tencent qfq {symbol} 收盘价无效: {row[2]!r}")
            if day in seen:
                raise RuntimeError(f"Tencent qfq {symbol} 日期重复: {day}")
            seen.add(day)
            rows.append({"date": day, "close": close})
        rows.sort(key=lambda item: item["date"])
        return rows


def deviation_pct(stock_rows: list[dict], benchmark_rows: list[dict], days: int) -> float | None:
    if len(stock_rows) < days + 1 or len(benchmark_rows) < days + 1:
        return None
    stock_start, stock_end = stock_rows[-days - 1]["close"], stock_rows[-1]["close"]
    bench_start, bench_end = benchmark_rows[-days - 1]["close"], benchmark_rows[-1]["close"]
    if min(stock_start, stock_end, bench_start, bench_end) <= 0:
        return None
    stock_return = (stock_end / stock_start - 1) * 100
    benchmark_return = (bench_end / bench_start - 1) * 100
    return stock_return - benchmark_return


def remaining_to_trigger(devs: dict, thresholds: dict) -> dict:
    options = []
    triggered = False
    for window in ("3d", "10d", "30d"):
        value, limits = devs.get(window), thresholds.get(window)
        if value is None or not limits:
            continue
        for direction, level in (("up", limits["up"]), ("down", limits["down"])):
            raw = level - value if direction == "up" else value - level
            if raw <= 0:
                triggered = True
            options.append(
                {
                    "window": window,
                    "direction": direction,
                    "threshold_pct": level,
                    "remaining_pp": max(0.0, raw),
                }
            )
    nearest = min(options, key=lambda item: item["remaining_pp"]) if options else None
    return {
        "threshold": nearest,
        "remaining_pp": nearest["remaining_pp"] if nearest else None,
        "near": nearest is not None and nearest["remaining_pp"] <= 5.0,
        "triggered": triggered,
    }


def _candidate_union(market: dict, cap: int = MAX_CANDIDATES) -> list[dict]:
    candidates = {}

    def add_rows(rows, source):
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or "").strip()
            if not re.fullmatch(r"\d{6}", code):
                continue
            item = candidates.setdefault(code, {"code": code, "name": row.get("name"), "sources": []})
            if not item.get("name") and row.get("name"):
                item["name"] = row["name"]
            if source not in item["sources"]:
                item["sources"].append(source)

    pools = market.get("limit_pools") or {}
    for kind in ("zt", "zb", "dt"):
        add_rows(pools.get(f"{kind}_rows"), f"limit_pools_{kind}")
        add_rows((pools.get("top20") or {}).get(kind), f"limit_pools_{kind}")
    hot = market.get("hot") or {}
    add_rows(hot.get("ths"), "hot_ths")
    add_rows(hot.get("eastmoney"), "hot_eastmoney")
    dragon = market.get("dragon_tiger") or {}
    add_rows(dragon.get("top_buy"), "dragon_tiger")
    add_rows(dragon.get("top_sell"), "dragon_tiger")
    return list(candidates.values())[:cap]


def _thresholds(board: str, name: str) -> dict:
    if board in ("沪主板", "深主板"):
        rule = RULES["main_st"] if "ST" in (name or "").upper() else RULES["main"]
    else:
        rule = {
            "创业板": RULES["growth"],
            "科创板": RULES["star"],
            "北交所": RULES["bj"],
        }[board]
    return {"3d": dict(rule["3d"]), "10d": dict(RULES["10d"]), "30d": dict(RULES["30d"])}


def calculate(market: dict, client=None, max_candidates: int = MAX_CANDIDATES) -> dict:
    candidate_cap = max(0, min(int(max_candidates), MAX_CANDIDATES))
    candidates = _candidate_union(market, cap=candidate_cap)
    qfq = client or TencentQfqClient()
    boards = {item["code"]: board_for_code(item["code"]) for item in candidates}
    benchmarks = sorted({BOARD_TO_BENCHMARK[b] for b in boards.values() if b})
    benchmark_rows, benchmark_errors = {}, {}
    for benchmark in benchmarks:
        try:
            benchmark_rows[benchmark] = qfq.fetch(benchmark)
        except Exception as exc:
            benchmark_errors[benchmark] = f"{type(exc).__name__}: {exc}"

    items, missing = [], []
    for candidate in candidates:
        code, name = candidate["code"], str(candidate.get("name") or "")
        board = boards[code]
        if board is None:
            missing.append({"code": code, "name": name, "error": "无法映射所属板块"})
            continue
        benchmark = BOARD_TO_BENCHMARK[board]
        if benchmark in benchmark_errors:
            missing.append({"code": code, "name": name, "error": f"基准 {benchmark} 不可用: {benchmark_errors[benchmark]}"})
            continue
        try:
            stock_rows = qfq.fetch(_symbol(code))
        except Exception as exc:
            missing.append({"code": code, "name": name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        devs = {
            f"{days}d": deviation_pct(stock_rows, benchmark_rows[benchmark], days)
            for days in (3, 10, 30)
        }
        thresholds = _thresholds(board, name)
        distance = remaining_to_trigger(devs, thresholds)
        if any(value is None for value in devs.values()):
            missing.append({"code": code, "name": name, "error": "40 根日线不足以计算全部区间"})
        items.append(
            {
                "code": code,
                "name": name,
                "board": board,
                "benchmark": benchmark,
                "candidate_sources": candidate["sources"],
                "dev_3d": devs["3d"],
                "dev_10d": devs["10d"],
                "dev_30d": devs["30d"],
                "thresholds": thresholds,
                **distance,
            }
        )
    items.sort(
        key=lambda item: (
            item["remaining_pp"] is None,
            item["remaining_pp"] if item["remaining_pp"] is not None else math.inf,
            item["code"],
        )
    )
    near_n = sum(item["near"] for item in items)
    triggered_n = sum(item["triggered"] for item in items)
    return {
        "asof": market.get("asof"),
        "generated": datetime.now().astimezone().isoformat(),
        "source": {
            "ok": bool(items) or not candidates,
            "provider": "Tencent qfq daily",
            "candidate_count": len(candidates),
            "available_count": len(items),
            "missing": len(missing),
            "missing_codes": missing,
            "rule_source": "交易所异常波动规则摘要",
        },
        "counts": {
            "candidate_count": len(candidates),
            "available_count": len(items),
            "near": near_n,
            "triggered": triggered_n,
        },
        "rules": {
            "thresholds": RULES,
            "note": RULE_NOTE,
            "definition": "区间偏离值=个股区间收盘收益率-对应基准指数区间收盘收益率；距离为距任一方向下一触发阈值的百分点。",
        },
        "items": items[:MAX_OUTPUT],
        "evidence": "descriptive",
        "note": "异动提醒是对交易所异常波动规则的距离描述，不是预测或交易信号。",
    }


def write_snapshot(data: dict, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    latest = out / "abnormal_latest.json"
    text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    latest.write_text(text, encoding="utf-8")
    return latest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("out/abnormal"))
    args = parser.parse_args(argv)
    market = json.loads(args.market.read_text(encoding="utf-8"))
    result = calculate(market)
    latest = write_snapshot(result, args.out)
    print(json.dumps({"latest": str(latest), "counts": result["counts"], "source": result["source"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
