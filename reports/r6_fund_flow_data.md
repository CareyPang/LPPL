# R6 资金面数据准备（仅下载整理，未计算特征、未看任何与标签的关系）

| file                        | desc               |   rows | start      | end        | cols                                                                         |
|:----------------------------|:-------------------|-------:|:-----------|:-----------|:-----------------------------------------------------------------------------|
| sse_margin.parquet          | 上交所融资融券日报 |   3747 | 2010-03-31 | 2025-08-29 | fin_balance, fin_buy, sec_qty, sec_balance, sec_sell_qty, total_balance      |
| szse_margin.parquet         | 深交所融资融券日报 |   3747 | 2010-03-31 | 2025-08-29 | 融资买入额, 融资余额, 融券卖出量, 融券余量, 融券余额, 融资融券余额           |
| margin_account_info.parquet | 市场级融资账户统计 |   3413 | 2012-09-27 | 2026-10-23 | fin_balance_all, sec_balance_all, fin_buy_all, sec_sell_all, avg_maint_ratio |

- 来源：AkShare `stock_margin_sse` / `stock_margin_szse`（按日增量，失败 0）/ `stock_margin_account_info`；manifest：`{"downloaded_at": "2026-10-24T12:50:20.820454+00:00", "source": "akshare.stock_margin_sse", "rows": 3747, "first": "2010-03-31", "last": "2025-08-29", "pit_lag_days": 1, "szse": "pending"}`。
- PIT：融资日报 T 日数据按 T+1 交易日可得（滞后 1 日）；开发段 2000–2009 无覆盖，融资类特征只能做 2010-03-31 起子样本（prereg §14.2）。
- 市场级账户统计 2012-09 起，只作描述性展示，不进阶梯。
- 两所合并：沪深融资余额相加后再算 20/60 日对数变化；深交所缺失日以上交所单独报告。
