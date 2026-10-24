"""R6 资金面数据准备（登记前只下载整理，不生成特征结果；来源：上交所/深交所融资融券日报，经 AkShare）。

- 上交所 `stock_margin_sse`：2010-03-31 起，字段 融资余额/融资买入额/融券余量/融券余量金额/融券卖出量/融资融券余额（元）。
- 深交所 `stock_margin_szse`：按日查询；接口不稳定，失败日期记录于 manifest，后续补齐。
PIT 说明：交易所融资融券日报在 T+1 交易日早间发布，使用时需滞后 1 个交易日。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone  # noqa: UP017
from pathlib import Path

import pandas as pd

CACHE = Path("data/cache/margin")


def fetch_sse(start: str = "20100331", end: str = "20250831") -> pd.DataFrame:
    import akshare as ak

    parts = []
    for y in range(int(start[:4]), int(end[:4]) + 1):
        a = max(start, f"{y}0101")
        b = min(end, f"{y}1231")
        for attempt in range(4):
            try:
                parts.append(ak.stock_margin_sse(start_date=a, end_date=b))
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 3:
                    raise
                print("retry", y, type(e).__name__, flush=True)
                time.sleep(3 * (attempt + 1))
        time.sleep(1)
    df = pd.concat(parts, ignore_index=True)
    df["date"] = pd.to_datetime(df["信用交易日期"].astype(str))
    df = df.rename(columns={"融资余额": "fin_balance", "融资买入额": "fin_buy", "融券余量": "sec_qty",
                            "融券余量金额": "sec_balance", "融券卖出量": "sec_sell_qty", "融资融券余额": "total_balance"})
    cols = ["date", "fin_balance", "fin_buy", "sec_qty", "sec_balance", "sec_sell_qty", "total_balance"]
    return df[cols].sort_values("date").drop_duplicates("date").reset_index(drop=True)


def run() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    sse = fetch_sse()
    sse.to_parquet(CACHE / "sse_margin.parquet")
    manifest = dict(downloaded_at=datetime.now(timezone.utc).isoformat(), source="akshare.stock_margin_sse",
                    rows=len(sse), first=str(sse.date.min().date()), last=str(sse.date.max().date()),
                    pit_lag_days=1, szse="pending")
    json.dump(manifest, open(CACHE / "manifest.json", "w"), indent=1, ensure_ascii=False)
    print(manifest, flush=True)


if __name__ == "__main__":
    run()
