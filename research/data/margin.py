"""R6 资金面数据准备（登记前只下载整理，不生成特征结果；来源：上交所/深交所融资融券日报，经 AkShare）。

- 上交所 `stock_margin_sse`：2010-03-31 起，字段 融资余额/融资买入额/融券余量/融券余量金额/融券卖出量/融资融券余额（元）。
- 深交所 `stock_margin_szse`：按日查询；接口不稳定，失败日期记录于 manifest，后续补齐。
PIT 说明：交易所融资融券日报在 T+1 交易日早间发布，使用时需滞后 1 个交易日。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
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
    now = datetime.now(timezone.utc).isoformat()  # noqa: UP017
    manifest = dict(downloaded_at=now, source="akshare.stock_margin_sse",
                    rows=len(sse), first=str(sse.date.min().date()), last=str(sse.date.max().date()),
                    pit_lag_days=1, szse="pending")
    json.dump(manifest, open(CACHE / "manifest.json", "w"), indent=1, ensure_ascii=False)
    print(manifest, flush=True)




def fetch_account_info() -> pd.DataFrame:
    """中证金融/东方财富两融账户统计（2012-09 起，日度；含平均维持担保比例）。"""
    import akshare as ak

    d = ak.stock_margin_account_info()
    d["date"] = pd.to_datetime(d["日期"])
    d = d.rename(columns={"融资余额": "fin_balance_all", "融券余额": "sec_balance_all", "融资买入额": "fin_buy_all",
                          "融券卖出额": "sec_sell_all", "平均维持担保比例": "avg_maint_ratio"})
    cols = ["date", "fin_balance_all", "sec_balance_all", "fin_buy_all", "sec_sell_all", "avg_maint_ratio"]
    return d[cols].sort_values("date").drop_duplicates("date").reset_index(drop=True)


def fetch_szse(dates: pd.DatetimeIndex, out: Path, pause: float = 0.8) -> None:
    """深交所按日查询，增量写入 out（parquet）；失败日期跳过并记录。"""
    import akshare as ak

    done = pd.read_parquet(out) if out.exists() else pd.DataFrame()
    have = set(done.date) if len(done) else set()
    rows, failed = [], []
    for i, d in enumerate(dates):
        if d in have:
            continue
        try:
            x = ak.stock_margin_szse(date=d.strftime("%Y%m%d"))
            x["date"] = d
            rows.append(x)
        except Exception as e:  # noqa: BLE001
            failed.append((str(d.date()), type(e).__name__))
            time.sleep(3)
        time.sleep(pause)
        if rows and (i % 50 == 0):
            pd.concat([done, *rows], ignore_index=True).to_parquet(out)
    if rows:
        pd.concat([done, *rows], ignore_index=True).to_parquet(out)
    json.dump(failed, open(out.with_suffix(".failed.json"), "w"))
    print("szse done", len(rows), "failed", len(failed), flush=True)


def run_extra() -> None:
    acc = fetch_account_info()
    acc.to_parquet(CACHE / "margin_account_info.parquet")
    print("account_info", len(acc), acc.date.min().date(), acc.date.max().date(), flush=True)
    sse = pd.read_parquet(CACHE / "sse_margin.parquet")
    fetch_szse(pd.DatetimeIndex(sse.date), CACHE / "szse_margin.parquet")


if __name__ == "__main__":
    import sys

    run_extra() if len(sys.argv) > 1 and sys.argv[1] == "extra" else run()


SZSE_RENAME = {"融资余额": "fin_balance", "融资买入额": "fin_buy", "融券余量": "sec_qty",
               "融券余额": "sec_balance", "融券卖出量": "sec_sell_qty", "融资融券余额": "total_balance"}


def load_margin(cache: Path = CACHE) -> pd.DataFrame:
    """沪深融资日报合并（宽表，列后缀 _sse/_szse/_all），`avail_date` = 数据日的下一行日期（PIT 滞后 1 个交易日）。

    深交所缺失日按 NaN 保留；_all 列在任一所缺失时为 NaN，调用方自行决定回退到上交所。
    """
    sse = pd.read_parquet(cache / "sse_margin.parquet").set_index("date").add_suffix("_sse")
    szse = pd.read_parquet(cache / "szse_margin.parquet").rename(columns=SZSE_RENAME).set_index("date").add_suffix("_szse")
    df = sse.join(szse, how="outer").sort_index()
    for c in ("fin_balance", "fin_buy", "total_balance"):
        df[f"{c}_all"] = df[f"{c}_sse"] + df[f"{c}_szse"]
    df.index.name = "date"
    df["avail_date"] = df.index.to_series().shift(-1)
    return df.reset_index()
