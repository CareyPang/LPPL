# TradingView 完整流程实操记录

日期2026-11-16，Windows Chrome，用户已有登录会话。只读浏览与临时策略模拟；不真实下单、不连接券商、不发布、不购买。此文件只记录实际看到/完成的动作，官方说明与规划另列。

## 全站导航

| ID | 操作 | 观察 / VERIFIED_UI | 边界 |
|---|---|---|---|
| N01 | 从Features点击Markets | 点击进入markets概览；加载后展示指数选项和主走势图 | 单次加载出现等待，不是性能基准 |
| N02 | 悬停Markets | 一列分类：Entire world、Countries、News、Indices、Stocks、Crypto、Futures、Forex、Government bonds、Corporate bonds、ETFs、Economy | 只展开，不声称访问所有资产列表 |
| N03 | 悬停Indices | 扩成三列：类别、Overview/All/Major/US/S&P sectors/Currency indices、代表指数报价卡 | 本次右列是报价卡，未见逐行sparkline |
| N04 | 悬停S&P500卡的D标记、名称 | D提示延迟10分钟；卡可导向指数详情；名称悬停未见额外小图弹层 | 不能把D解释为日线或已断流 |
| N05 | 悬停Products | Supercharts突出；Screeners/Calendars/News Flow/Portfolios/Yield Curves/Options/Macro Maps；下方Pricing/Features/What's new/Market data | 按工具任务组织，未购买 |
| N06 | 悬停Screeners | 次栏分筛选器与Heatmaps，股票/ETF/债券/加密/Pine等 | 与Markets按资产发现是不同入口 |
| N07 | 悬停Calendars | Economic/Earnings/Dividends/IPOs | 入口分组已验证，日历内部筛选未在此步测试 |
| N08 | 悬停Community | The Leap、Indicator marketplace、Trading ideas、Indicators and strategies、Community contests、Power of community | 没有参赛/发布/购买脚本 |
| N09 | 悬停Brokers | Top/Compare/Open an account/Award brokers，推荐经纪商卡及Trading space | 仅目录，不操作开户/连接账户 |
| N10 | 悬停More | Help Center、Downloads、For business、公司介绍/博客/无障碍等 | 不安装软件 |
| N11 | More→Help Center，搜索strategy并回车 | 搜索结果有类别数量和问题摘要；出现未来数据偏差、策略无交易、参数等文章入口 | 文档内容由官方资料文件补充 |
| N12 | 全站搜索AAPL | Symbols/Ideas/Scripts/People；资产类型chips；结果带NASDAQ及其他来源 | 同名存在跨市场/衍生资产，不应仅用裸代码 |
| N13 | 选择NASDAQ:AAPL行 | 行内可见Launch chart/See overview两种动作；本次进入Supercharts日线 | 搜索可直接进入工具，不一定先过详情页 |

## 单股策略实际操作

| ID | 操作 | 观察 / VERIFIED_UI | 边界 |
|---|---|---|---|
| S01 | AAPL日线→Indicators，搜索RSI，选BUILT-IN Technicals的RSI strategy | 添加后图上显示RSI str 14 30 70；底部自动出现Strategy Report | 没有选择社区同名脚本，没有下单 |
| S02 | 查看默认Metrics | 范围1980-12-12至2026-11-13；净损益−99,969.95USD（−99.97%）；最大回撤203,024.63USD（99.99%）；盈利交易22/214（10.28%）；Profit Factor0.62；Margin calls174 | 这是网页模拟输出，不是独立复算，不是对策略有效性的结论 |
| S03 | 打开Inputs / Properties / Style / Visibility，再Cancel | Inputs14/30/70；初始100,000USD；仓位100% equity；pyramiding1；commission0%；slippage0ticks；long/short leverage1x；4 ticks/bar；on bar close；order delay one tick；limit requested price | 未修改参数；复权细项和数据导出未独立核验；不称严格可复现研究 |
| S04 | 切List of trades | 最近一笔#214 Short：2017-01-13入场29.78，2017-01-18出场30.13，1股，−0.35USD/−1.18% | 该笔不是2026年最近市场行情；回测后期无交易的原因未独立诊断 |
| S05 | 点#214入场日期，然后点出现的定位图标 | 主图移至2016–2017附近，显示RsiSE/RsiLE、Margin call标记；右侧报价仍为当前行情 | 日期文字点击本身未观察到跳转；定位图标点击后验证成功 |
| S06 | 打开Testing period菜单 | Available chart range默认；Last7/30/90/365 days、Entire history、Custom date range | 点击Last365后观察期内范围未变，没有形成有效第二次结果；不宣称已完成Deep回测或确定套餐限制 |
| S07 | 点图表右侧Apple Inc外链 | 新标签打开NASDAQ:AAPL股票概览，原图表标签保留 | 没有保存布局、发布脚本或创建提醒；原临时策略仍在原标签 |

费用敏感性比较、Pine源码审计、Bar Replay逐步交易、Deep付费回测、多图同步、真实手机：NOT_RUN/NOT_INSPECTED。本轮已真正添加并查看一个策略的结果，不把未完成的日期切换算成第二次回测。

## 单资产研究页签

以下均保留NASDAQ:AAPL资产头和右侧自选；只记录页面结构，未验证财务、预测或新闻本身的真实准确性。

| ID | 页签 / 操作 | VERIFIED_UI观察 | 边界 |
|---|---|---|---|
| A01 | Overview入口 | 品牌、面包屑、股票名称/交易所、常规与盘前报价分列；完整图表入口、不同期间表现卡 | 首次加载主图有空白，后续核对另记 |
| A02 | Financials→Statements，向下滚动，Annual→Quarterly | Overview/Statements/Statistics/Estimates/Dividends/Earnings/Segments；利润/资产负债/现金流；图和表一起切季度；URL含statements-period=FQ；旧年Locked | 未下载报表、未遍历全部财务指标 |
| A03 | Financials滚动 | 大资产头收拢为小行情条，See on Supercharts保留；主导航仍在 | 所见桌面1920px，不是390px验收 |
| A04 | Filings→Earnings过滤 | 按年排列事件卡；财报/公司事件筛选；8-K、10-K等原文入口；筛Earnings后产品发布卡不再出现 | 没有打开/保存全部原文 |
| A05 | News→Key facts→Latest news | 摘要带来源；新闻按时间/标题/来源，分类Earnings/Dividends/Share buybacks/Mergers/Insider trading/Analysts | 没有复制新闻全文；摘要不视为独立核实 |
| A06 | Community | Trade ideas/Minds，图表观点卡，视频与时间/热度控件 | 未发帖、关注、评论；观点不是官方证据 |
| A07 | Technicals，1day→1week | Oscillators/Summary/Moving Averages及计数；周期切换后指针与汇总变化 | 技术汇总不是未来顶部时间或校准概率 |
| A08 | Forecasts | 过去2年与未来1年目标价分区；Max/Avg/Min；分析师数量和评级分布 | 这是分析师目标，不是LPPL；未独立核实预测业绩 |
| A09 | Seasonals，曲线→表格 | 年份区间滑杆，Average、Percent；月度红绿热表；URL含seasonals-tab=table | 没有对季节性做统计检验 |
| A10 | Options，打开expiration | Chain/Volatility/Build your own strategy；Calls/Puts两侧、Strike中间；可选具体到期日/范围与搜索；显示DTE，部分Bid/Ask为空 | 未选交易组合或下单；缺失报价不是零价 |
| A11 | ETFs，打开Fund flows并等待 | Funds holding the stock按持有该股关联ETF；概览有Mkt value/Weight/Issuer/AUM；切换后列实际变成1M/3M/1Y/3Y/YTD资金流 | 未独立复算流量，不将ETF持股与当日买入该股混淆 |
| A12 | Bonds，点击Maturity date表头 | 同发行人公司债表，YTW、Price、Coupon、Maturity、金额、评级；点击后未观察到重排 | 不宣称表头排序已验证；没有交易 |
| A13 | 回Overview，点击6months并等待 | 主图从短期走势图切为约5月至11月的六个月面积图；URL含timeframe=6M，选中期间卡显示对应收益；Full chart入口仍在 | 概览图不是策略报告；本轮没有重新打开一个新的布局 |

结束时概览标签停在AAPL六个月视图；原Supercharts标签保留本次临时RSI模拟，没有点击保存布局。未宣称已清理或恢复原标签全部状态。

## 浏览器证据处理

不上传完整截图，因为其中可见账户及其他浏览器标签。报告中的行为是本轮人工检查的工具截图记录，不等同第三方可重放的自动化测试。光标蓝色光晕属于跨站存在的操作显示，不归因为TradingView特效。
