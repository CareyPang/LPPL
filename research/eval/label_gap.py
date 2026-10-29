"""开发段诊断（只读，不改 Round 1 标签）：Round 1 顶部标签漏掉了哪些标准口径的顶。

对 6 指数 2000–2018，把 Pagan–Sossounov（±168 日）与 Lunde–Timmermann（20%/15%）转折点，
与 Round 1 主标签（ε-共识顶 + 自适应门槛 d_t=max(10%, Q90₅ₐ) + 60 日回撤）逐个对照：
峰值日前 35 日内有 y=1 记为"已标"。输出 reports/label_gap_dev.md。
python -m research.eval.label_gap
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .alt_labels import lt_turns, ps_turns

ROOT = Path(__file__).resolve().parents[2]
SYMS = ["sh000001", "sz399001", "sh000300", "sz399006", "sh000016", "sh000905"]
DEV = ("2000-01-01", "2018-12-31")


def _px(sym: str) -> pd.Series:
    df = pd.read_parquet(ROOT / f"data/frozen/v20261024/{sym}_qfq.parquet")
    dc = [c for c in df.columns if "date" in c.lower()][0]
    pc = [c for c in df.columns if c.lower() in ("close", "adj_close", "close_adj")][0]
    return pd.Series(df[pc].values, index=pd.to_datetime(df[dc])).sort_index()


def main() -> None:
    rows = []
    for s in SYMS:
        px = _px(s)
        lab = pd.read_parquet(ROOT / f"data/labels/top_v1/{s}.parquet")
        lab.index = pd.to_datetime(lab.index)
        y = lab["main__y"].fillna(0)
        x = np.log(px.values)
        for name, pk in (("PS", ps_turns(x)[0]), ("LT", lt_turns(x)[0])):
            for i in pk:
                d = px.index[i]
                if not (DEV[0] <= str(d.date()) <= DEV[1]):
                    continue
                dd60 = px.iloc[i : i + 61].min() / px.iloc[i] - 1
                rows.append(
                    dict(
                        symbol=s,
                        method=name,
                        peak=d.date(),
                        dd60=round(dd60, 3),
                        d_t=round(float(lab["main__d_t"].asof(d)), 3),
                        labelled=bool(y.loc[d - pd.Timedelta(days=35) : d].max() == 1),
                    )
                )
    df = pd.DataFrame(rows)
    out = ROOT / "reports"
    df.to_csv(out / "label_gap_dev.csv", index=False)
    summ = df.groupby("method").agg(n=("peak", "size"), labelled=("labelled", "sum"))
    summ["share"] = (summ.labelled / summ.n).round(2)
    miss = df[(~df.labelled) & (df.method == "PS")].sort_values(["symbol", "peak"])
    md = [
        "# Round 1 顶部标签 vs 标准牛熊划分（开发段 6 指数 2000–2018，诊断，不改标签）\n",
        "PS = Pagan–Sossounov ±168 日局部极值；LT = Lunde–Timmermann 20%/15% 停时。"
        "`labelled` = 峰值日前 35 日内主标签 y=1。\n",
        summ.to_markdown(),
        "\n\n## PS 顶中被主标签漏掉的（dd60 = 峰后 60 日最大回撤；d_t = 当日自适应门槛）\n",
        miss.to_markdown(index=False),
        "\n\n漏掉原因：(a) 自适应门槛 d_t 在大崩盘后被推高到 0.3+，之后数年 −20～−28% 的顶都不合格；"
        "(b) 60 日回撤窗口把慢顶（2001-06、2018-01）排除。两者都不是模型问题。\n",
    ]
    (out / "label_gap_dev.md").write_text("\n".join(md), encoding="utf-8")
    print(summ)
    print(miss.to_string(index=False))


if __name__ == "__main__":
    main()
