# 510210 行情来源与回放复现

上证综指产生阶段顶提醒，富国上证综指 ETF（上交所二级市场代码 510210，人民币计价）承接模拟订单。基金管理人列明其跟踪标的是上证综合指数。回放使用场内开盘成交价和收盘价，基金份额净值仅用于基金披露。**VERIFIED**。[上交所产品资料概要](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-11-10/510210_20261110_1JB0.pdf) · [富国基金产品页](https://www.fullgoal.com.cn/fundDetail/510210/index.html)

## 数据怎样取得

| 对象 | 取得时间（UTC） | 核对结果 |
| --- | --- | --- |
| [搜狐历史行情](https://q.stock.sohu.com/hisHq?code=cn_510210&start=20251127&end=20261118&stat=1&order=D&period=d) | 2026-11-19 09:08:35 | 2025-11-27 至 2026-11-18 共 236 个交易日。各日四价均为正值，最高最低包含开盘和收盘，各日成交量大于零。 |
| [Yahoo 历史行情](https://query1.finance.yahoo.com/v8/finance/chart/510210.SS?period1=1764115200&period2=1795046400&interval=1d&events=div%2Csplits) | 2026-11-19 09:07:38 | 将 Unix 时点转换为上海交易日，在指定区间取 `indicators.quote[0]` 的四价。前 235 个交易日与搜狐按 0.001 元精度逐格一致。11 月 18 日返回空收盘价及冲突的开高低，排除此行。 |
| [英为财情历史行情](https://cn.investing.com/etfs/fullgoal-sse-composite-historical-data) | 2026-11-19 查阅 | 11 月 18 日开 0.934、高 0.935、低 0.926、收 0.933，成交量 678.35 百万份，四价与搜狐末日逐格一致。 |
| [富国基金分配表](https://www.fullgoal.com.cn/fundDetail/510210/index.html)及[天天基金分红拆分表](https://fundf10.eastmoney.com/fhsp_510210.html) | 2026-11-19 查阅，天天基金原件 09:07:40 | 管理人列有三次分红，皆在 2023 年。天天基金的最近一次权益登记日为 2023-12-19，除息为 12-20，发放为 12-25。拆分折算表仅列 2011、2021 年的操作，本段对应零笔现金分配和零笔份额拆合。 |

**VERIFIED** 指上述公开来源对该次快照的交叉一致性。分销网站可能共用上游数据。ETF 行情与此次使用的上证综指档案 `price_history.dates` 逐日对齐，档案的 756 根日线中有 236 根落入研究期，双方日期集合完全相同。每个提醒的次日由这个共同交易日序列确定。订单成交价、持仓日终估值均取 ETF，自指数读取的价格仅用于原标签与信号。交易所逐笔开盘竞价撮合记录及账户真实成交为 **NOT_INSPECTED**。

## 字段和指纹

搜狐返回数组第一项，要求 `code=cn_510210`、`status=0`。下列下标从零开始。

| 源字段 | 输出列 | 口径 |
| --- | --- | --- |
| `hq[i][0]` | `date` | 上海市场交易日期，按升序输出 |
| `hq[i][1]` | `open` | 场内开盘，元/份，三位小数 |
| `hq[i][6]` | `high` | 场内最高，元/份 |
| `hq[i][5]` | `low` | 场内最低，元/份 |
| `hq[i][2]` | `close` | 场内收盘，元/份 |
| `hq[i][7]` | `volume_lots` | 手数，1 手为 100 份，用来核验该日有交易 |

| 文件 | SHA-256 |
| --- | --- |
| 搜狐原始响应，23,597 字节 | `285af7c559d97ff36264a9002a866ae552107bee0e6cc37a0157b295ef62fee5` |
| 规范化 510210 OHLC CSV，UTF-8 无 BOM，CRLF 行尾 | `804467fc8d19b417e460944bbabdecfc6e2fbe80ec22dd3b09634299d83c07b3` |
| Yahoo 原始响应 | `c174ba344bb84478f4d940e0be84407c19041c4d305b5ccff170cf9bb7e88825` |
| 天天基金分红拆分页面 | `e64100ed3a501cb83e014216a6620431570be4912752ae057545ac33ee4ae727` |
| 上证综指 `sh000001_latest.json` 2026-11-18 版 | `55f3547596f790c1a9fa1e36e0270e7b27c6bde1344673e178cf3ac6b5448430` |

用 Python 标准库从仓库根目录运行下面的命令。脚本对行数、时间范围、标的代码、四价、正成交量、规范化字节摘要作检查。已有响应可传入 `--from-raw` 离线重建。供应商订正历史引起内容摘要变化时，脚本报出新旧摘要，使用者可复查差异。

```powershell
. D:\CodexData\config\analysis-env.ps1
python research/data/stage_etf_quote_sample.py --output "$env:CODEX_ANALYSIS_WORK/510210_ohlc.csv"
```

**NOT_ESTABLISHED** 表示本次未取得报价供应商整段行情的公开再分发及商业数据订阅授权。原始行情保存在本机研究目录，仓库提供处理方法、校验值及交易研究结果。网站接入需另行确认相应授权。
