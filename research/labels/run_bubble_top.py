"""导出指数泡沫顶主标签和 look500 附表。"""
from __future__ import annotations

import sys
from dataclasses import replace

import pandas as pd

from .bubble_top import TOP_COLUMNS, BubbleTopParams, bubble_tops
from .run_top import FROZEN, INDEXES, ROOT

OUTPUT = ROOT / "reports" / "bubble_top_labels"
EXPECTED_COLUMNS = ("date", "open", "high", "low", "close", "volume", "amount")
VARIANTS = {
    "main": BubbleTopParams(),
    "look500": replace(BubbleTopParams(), look=500),
}
TABLE_COLUMNS = ("symbol", "variant", "top_date", "dd_hit_date", "confirm_date", "rise", "dd")
RULE_TEXT = """\
指数主口径：look=250、涨幅门槛 rise=50%、回撤门槛 dd=20%、回撤观察 horizon=60 个交易日、
去重窗口 dedup=120 个交易日。个股预设仅将 rise 改为 100%、dd 改为 30%；look500 附表只将 look 改为 500。

候选日 i 必须满足：i≥look；c[i] 是 c[i-look:i+1] 的最高收盘；c[i]/该窗口最低收盘−1≥rise。
在 (i, i+horizon] 首次有收盘价≤c[i]×(1−dd)，否则不是顶部；在 (i, i+dedup] 不得有高于 c[i] 的收盘。
对满足前三项的候选，若相距不超过 dedup 个交易日，只保留收盘价较高者；收盘价相同保留较早日。
确认日为 max(dd 首次触及日, i+dedup)，只有从该日开始标签才可知。
若 dedup 窗口尚未完整，或 horizon 尚未完整且尚未触及 dd，则导出 status=pending、confirm_date=NaT；
pending 不计为已知标签。已确认的 PIT 视图仅保留 confirm_date≤asof 的记录。

百分比字段以小数存储；Markdown 表格将 rise_pct 和 dd_pct_60 格式化为百分数。
"""


def _display_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "（无）"
    table = df.loc[:, list(TABLE_COLUMNS)].copy()
    table["top_date"] = pd.to_datetime(table["top_date"]).dt.strftime("%Y-%m-%d")
    table["dd_hit_date"] = pd.to_datetime(table["dd_hit_date"]).dt.strftime("%Y-%m-%d").fillna("—")
    table["confirm_date"] = pd.to_datetime(table["confirm_date"]).dt.strftime("%Y-%m-%d").fillna("—")
    table["rise"] = table.pop("rise").map(lambda value: f"{value:.1%}")
    table["dd"] = table.pop("dd").map(lambda value: f"{value:.1%}" if pd.notna(value) else "—")
    return table.to_markdown(index=False)


def _table_rows(df: pd.DataFrame) -> pd.DataFrame:
    table = df.rename(columns={"rise_pct": "rise", "dd_pct_60": "dd"})
    return table.loc[:, list(TABLE_COLUMNS)]


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records = []
    missing = []
    for symbol in INDEXES:
        path = FROZEN / f"{symbol}_qfq.parquet"
        if not path.is_file():
            missing.append(symbol)
            print(f"缺少冻结数据，未替代：{symbol} ({path})", file=sys.stderr)
            continue
        data = pd.read_parquet(path)
        if tuple(data.columns) != EXPECTED_COLUMNS:
            raise ValueError(f"unexpected frozen schema for {symbol}: {tuple(data.columns)}")
        dates = pd.DatetimeIndex(data.date)
        close = data.close.to_numpy(dtype=float)
        for variant, params in VARIANTS.items():
            tops = bubble_tops(dates, close, params)
            tops.insert(0, "variant", variant)
            tops.insert(0, "symbol", symbol)
            records.append(tops)

    columns = ["symbol", "variant", *TOP_COLUMNS]
    tops = pd.concat(records, ignore_index=True) if records else pd.DataFrame(columns=columns)
    tops = tops.loc[:, columns]
    tops.to_csv(OUTPUT / "tops.csv", index=False)

    confirmed = tops[tops.status == "confirmed"]
    pending = tops[tops.status == "pending"]
    main_count = int((confirmed.variant == "main").sum())
    sections = [
        "# 泡沫顶标签（主标签）与确认日",
        "",
        RULE_TEXT.strip(),
        "",
        "## 确认顶部",
        "",
    ]
    for symbol in INDEXES:
        rows = _table_rows(confirmed[confirmed.symbol == symbol])
        sections.extend([f"### {symbol}", "", _display_table(rows), ""])
    sections.extend(["## Pending tops", ""])
    for symbol in INDEXES:
        rows = _table_rows(pending[pending.symbol == symbol])
        if not rows.empty:
            sections.extend([f"### {symbol}", "", _display_table(rows), ""])
    if pending.empty:
        sections.extend(["（无）", ""])
    sections.extend([
        "## 与此前非正式计数的比较",
        "",
        f"主口径按指数累加确认 {main_count} 条标签；此前非正式统计称 2001、2007、2015 三次“加速翻倍后崩”的泡沫，"
        "前者是分指数日级标签，不能与市场级轮次数一一等同。",
        "",
    ])
    if missing:
        sections.extend(["缺失且未替代的冻结数据：" + "、".join(missing), ""])
    (OUTPUT / "bubble_top_labels.md").write_text("\n".join(sections), encoding="utf-8")

    print("Confirmed tops:")
    print(_display_table(_table_rows(confirmed)))
    print("\nPending tops:")
    print(_display_table(_table_rows(pending)))
    if missing:
        print("\nMissing frozen data (not substituted): " + ", ".join(missing))


if __name__ == "__main__":
    main()
