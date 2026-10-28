"""D1 日更：单标的最新 as-of 日的 LPPLS 拟合与契约 JSON（docs/product_contract.md）。

- 行情：默认联网刷新（research.data.cache.refresh，AkShare 限速）并写入当日 vintage；``--frozen`` 用冻结版本离线自检。
- 拟合：与 v2 扫描同一函数 ``lppls_scan.fit_one``（需 ``LPPLS_BOX=v2``），窗口 = 短尺度 30–120 + 125–750 日；
  只算 as-of 一日，约 145 次拟合。
- 输出：``web/mock/data/<sym>_latest.json``（``--asof`` 指定则为 ``<sym>_<asof>.json``）。p20 需校准后的前推模型，日更暂为 None。
用法：LPPLS_BOX=v2 python -m research.pipeline.daily sh000001 [--frozen] [--asof 2018-12-28] [--windows 125,250,500]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..data import cache
from ..eval.export_contract import build_record
from ..features.lppls_rules import _derived, rules
from ..features.lppls_scan import (
    BOX,
    BOXES,
    COLS,
    IDX_WINDOWS,
    SHORT_WINDOWS,
    STK_WINDOWS,
    XL_WINDOWS,
    XS_WINDOWS,
    fit_one,
)
from ..lppls import core as _core

FROZEN = "v20261024"
OUT = Path("web/mock/data")


def load_ohlc(sym: str, frozen: bool) -> tuple[pd.DataFrame, str]:
    if frozen:
        df = cache.load(sym, frozen=FROZEN, auto_refresh=False)
        return df, f"frozen_{FROZEN}"
    v = cache.refresh(sym)
    df = cache.load(sym, auto_refresh=False)
    return df, f"vintage_{v.vintage}_{v.source}"


def fit_asof(logp: pd.Series, asof: pd.Timestamp, windows: tuple[int, ...]) -> pd.DataFrame:
    i = int(logp.index.get_indexer([asof])[0])
    if i < 0:
        raise ValueError(f"as-of {asof.date()} 不是交易日")
    rows = []
    for n in windows:
        if i + 1 < n:
            continue
        rows.append((asof, *fit_one(logp.iloc[i + 1 - n : i + 1].to_numpy())))
    d = pd.DataFrame(rows, columns=COLS)
    lp = logp.to_numpy()
    d["y_std"] = [lp[i + 1 - n : i + 1].std() for n in d.n]
    return d


def run(sym: str, frozen: bool = False, asof: str | None = None, windows: tuple[int, ...] | None = None,
        out: Path = OUT, trust_boot: int = 100) -> Path:
    _core.ALLOW_INSIDE = bool(BOXES[BOX]["inside"])  # 与 lppls_scan.run 一致：v2 允许 t_c 落在窗内
    ohlc, version = load_ohlc(sym, frozen)
    ohlc = ohlc.sort_values("date").reset_index(drop=True)
    logp = pd.Series(np.log(ohlc.close.to_numpy(float)), index=pd.DatetimeIndex(ohlc.date))
    date = pd.Timestamp(asof) if asof else logp.index[-1]
    ohlc_pit = ohlc[ohlc.date <= date]
    logp = logp[logp.index <= date]
    ws = windows or (XS_WINDOWS + SHORT_WINDOWS + IDX_WINDOWS + XL_WINDOWS)
    d = _derived(fit_asof(logp, date, ws))
    rec = build_record(sym, str(date.date()), d, rules(d), logp.index, ohlc_pit, None, data_version=version)
    if trust_boot:
        from ..lppls.trust import trust
        rec["top"]["trust"] = trust(logp, date, d[d.n.isin(STK_WINDOWS)], b=trust_boot)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{sym}_{'latest' if asof is None else asof}.json"
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str))
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sym")
    ap.add_argument("--frozen", action="store_true")
    ap.add_argument("--asof")
    ap.add_argument("--windows", help="逗号分隔窗口长度（自检用）")
    a = ap.parse_args()
    ws = tuple(int(x) for x in a.windows.split(",")) if a.windows else None
    p = run(a.sym, a.frozen, a.asof, ws)
    rec = json.loads(p.read_text())
    print(p, json.dumps(rec["top"]["lppls_confidence"], ensure_ascii=False))


if __name__ == "__main__":
    main()
