"""原站 F03 资产目录：316 标的主数据表（代码、名称、交易所、类型、所属指数、是否有单资产契约）。

只整合已有静态来源（universe.py 的 BROAD/INDUSTRY、stock_names.json、universe_current.json 的中证最近公布成分，非 PIT），
不抓取、不计算任何模型量。输出 web/mock/data/catalog.json，供 workbench.html 资产目录页搜索/筛选。
"""

from __future__ import annotations

import json
from pathlib import Path

from .universe import BROAD, INDUSTRY

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "web/mock/data"
OUT = DATA / "catalog.json"
EXCH = {"sh": "SSE 上交所", "sz": "SZSE 深交所"}
BOARD = {"60": "沪市主板", "68": "科创板", "00": "深市主板", "30": "创业板"}


def _sym(code6: str) -> str:
    return ("sh" if code6.startswith(("6", "9")) else "sz") + code6


def build() -> dict:
    cur = json.loads((DATA / "universe_current.json").read_text())
    names = json.loads((DATA / "stock_names.json").read_text())
    members = {k: set(v) for k, v in cur["indices"].items()}
    contracts = {
        p.name.split("_")[0] for p in DATA.glob("*_latest.json") if p.name != "universe_latest.json"
    }
    rows = []
    for sym, name in BROAD.items():
        rows.append(
            dict(
                symbol=sym,
                code=sym[2:],
                name=name,
                exchange=EXCH[sym[:2]],
                type="index",
                board=None,
                member_of=[],
                dashboard=sym in contracts,
            )
        )
    for sym, name in INDUSTRY.items():
        rows.append(
            dict(
                symbol=sym,
                code=sym[2:],
                name=name,
                exchange="CSI 中证指数",
                type="industry",
                board=None,
                member_of=[],
                dashboard=sym in contracts,
            )
        )
    for code in sorted(cur["indices"]["sh000300"]):
        sym = _sym(code)
        rows.append(
            dict(
                symbol=sym,
                code=code,
                name=names.get(code, code),
                exchange=EXCH[sym[:2]],
                type="stock",
                board=BOARD.get(code[:2]),
                member_of=[k for k in ("sh000016", "sh000300", "sh000905") if code in members[k]],
                dashboard=False,
            )
        )
    return dict(
        generated=cur.get("fetched"),
        membership_source=cur.get("note"),
        source_date=cur.get("source_date"),
        n=len(rows),
        index_names={**BROAD, **INDUSTRY},
        rows=rows,
    )


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), ensure_ascii=False, indent=1))
    print(OUT, json.loads(OUT.read_text())["n"])
