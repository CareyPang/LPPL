# stocks_v20261024

- 股票池：`data/universe/csi300_{20100104,20181228,20211231}.csv`，即三期历史成分股快照（来自妙想 mx-data，原始返回结果一起保存）的并集，共 577 只。
- 每只股票：先下载不复权日线（新浪 549 只；退市或停牌的 28 只新浪取不到，改用腾讯），再乘以新浪后复权因子（`stock_zh_a_daily(adjust="hfq-factor")`），得到后复权收盘价 `close_hfq`。
- parquet 文件放在 `data/cache/stocks/`（不提交到 git）；本目录的 `manifest.json` 记录每个文件的 sha256、行数、起止日期、非正价格数、单日涨跌幅超过 25% 的天数。
- 下载结果：577/577 成功，没有非正价格。
- 重新生成：`python -m research.data.stocks`。
