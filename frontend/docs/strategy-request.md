# 策略回放报告 · 前端字段需求（设计端 → Devin）

前端组件：`frontend/app/strategy-panel.js`（回测页「策略回测」页签与标的页「回测」页签共用）。
数据只经 `LPPL.strategy(sym)` 读取 `lab/mock/data/strategy/<sym>.json`；文件不存在时组件整块显示「策略回测结果未发布」。

## 口径（硬规则）
- 这是**事前登记规则的历史回放**，不叫“策略收益”。
- 每个区间的汇总带 `evidence`；`LPPL.ev(level).show === false`（`none` / `fail*` / `dev_only` / `dev_failed` / `pending_cal` / `pending_test`）时只显示状态文字，不显示任何数值。
- 所有汇总显示 `n`（交易次数）与「历史回放」。
- 只开放事前登记的规则（`rule_id` 对应 `docs/preregistration*.md`），不提供自由调参。

## 文件：`strategy/<sym>.json`
```json
{
  "rule_id": "R1-top-exit-v1",
  "prereg_doc": "docs/preregistration.md#r1",
  "asof": "2026-11-13",
  "segments": { "dev": ["2005-01-04", "2014-12-31"], "cal": ["2015-01-01", "2019-12-31"], "test": ["2020-01-01", "2026-11-13"] },
  "metrics": {
    "dev":  { "evidence": "dev_only", "n_trades": 12, "win_rate": 0.5, "total_return": 0.3, "bh_return": 0.4, "cagr": 0.03, "max_drawdown": -0.2, "bh_max_drawdown": -0.7, "profit_factor": 1.2, "avg_trade_return": 0.02, "avg_bars": 30, "exposure": 0.4, "turnover": 1.2 },
    "cal":  { "evidence": "pending_cal" },
    "test": { "evidence": "descriptive", "n_trades": 4, "...": "同上" },
    "all":  { "evidence": "descriptive", "n_trades": 20, "...": "同上" }
  },
  "equity": [ { "date": "2005-01-04", "nav": 1.0, "bh_nav": 1.0 }, { "date": "2005-01-05", "nav": 1.0, "bh_nav": 1.01 } ],
  "trades": [ { "entry": "2020-03-02", "exit": "2020-04-01", "side": "long", "bars": 21, "ret": 0.04, "segment": "test", "reason_in": "...", "reason_out": "..." } ],
  "properties": { "t_plus_1": true, "limit_lock": true, "fee_bps": 2.5, "stamp_bps": 5, "slippage_bps": 5, "position": "全仓/空仓", "benchmark": "买入持有" },
  "note": "可选说明"
}
```
- 比例一律用小数（0.12 = 12%），前端负责格式化与 `+/-` 号。
- `metrics` 至少给 `test` 或 `all`；缺的区间不显示按钮。`segments` 缺某段时该区间按钮禁用。
- `equity` 为日频或周频均可，`bh_nav` 可缺；三段底色按 `segments` 画。
- `trades.exit` 为 `null` 表示仍持有。

## 建议的 evidence 等级
| 区间 | 建议 |
|---|---|
| dev | `dev_only`（只在开发段看过，不显示数值） |
| cal | 通过 → `descriptive`；未跑 → `pending_cal`；未通过 → `dev_failed` |
| test | 通过 → `descriptive`；未跑 → `pending_test`；未通过 → `fail` |
| all | 与 test 同级，但只有 test 为 `descriptive` 时才给 `descriptive` |

## 标的页挂载
标的页「回测」页签读取同一文件（个股为 `strategy/<code>.json`）；个股查询结果里也可直接挂 `strategy` 字段（结构同上），有则优先。
