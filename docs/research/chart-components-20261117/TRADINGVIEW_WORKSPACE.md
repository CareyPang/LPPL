# TradingView专业工作区：承接上一轮的增量结论

日期：2026-11-17。此文承接此前未提交GitHub的市场页、Take a snapshot、Get widget和Full chart分析；与本目录开源组件审查一起交付。

## 1. 实测范围与边界

**VERIFIED / UI（上轮同日操作记录）：** 已在用户登录的Chrome中打开上证完整图表，展开Take a snapshot及Trend tools菜单。观察到顶部资产/周期/指标/回放/布局/截图，左侧绘图，右侧自选/详情/对象入口，底部时间范围和既有RSI策略报告。

截图菜单可见下载、复制图片、复制链接、新标签页打开和发布图片入口；趋势工具菜单可见趋势线、射线、水平/垂直线、通道等。只检查菜单，不修改用户已保存绘图，不发布图片，不重新验证已有策略结果。

随后电脑控制因无法可靠识别浏览器URL自动停止。**NOT_INSPECTED：** 本次未完成市场页全部交互、Widget按钮点击、每一绘图工具实际放置/保存或移动端运行。没有把公开文档当成这些操作已完成的证明。

## 2. 为什么专业：组织方式比图标数量重要

**VERIFIED / public page：** [中国市场页](https://www.tradingview.com/markets/china/)组织主要指数、市场宽度、股票排行、ETF、汇率及宏观日历等内容。它帮助用户从市场整体进入具体资产。

**设计判断：** LPPL应采用三级职责：
- 市场页：发现值得研究的资产与背景；
- 资产页：价格、相关事件和当前模型结论；
- 完整图表：连续观察、划线、区间证据和历史回放。

Full chart是独立研究工作区；它内部还有独立的Fullscreen按钮，不能把两个概念混为一谈。LPPL当前已有index.html终端，需要补通普通股票入口和上下文，不是从零再造终端。

## 3. 三种保存/交付必须分开

| 功能 | 实质 | LPPL对应实现 |
|---|---|---|
| Take a snapshot | 冻结当前画面 | 本地PNG优先，带行情/区间/证据页脚 |
| 保存/分享布局 | 恢复资产、视窗、用户绘图及面板 | 独立ViewState和Drawing对象，明确本地/云端 |
| 分享研究记录 | 访问某一版本的模型证据 | prediction_id、数据版本、当时可得信息与修订链 |
| Get widget | 生成嵌入组件配置代码 | 第三方外围行情，或后续自建只读研究卡；两者分开 |

[官方截图说明](https://www.tradingview.com/support/solutions/43000482537-how-to-share-a-snapshot/)支持截图用途；分享图片链接涉及存储，不等于保存可编辑布局。LPPL不直接沿用第三方截图永久有效承诺。

## 4. Get widget不是导出完整官网

**VERIFIED / docs。** [Widget配置器](https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/)提供嵌入配置；当前Widgets有iframe与Web Component等形式，不能把所有格式一概称iframe。

[数据FAQ](https://www.tradingview.com/widget-docs/faq/data/)明确，Widget不能注入自有行情。因此不能把LPPL自己的数据与区间直接塞进它。要接自有行情和模型叠层，采用图表库/自有渲染器。

[Advanced Charts FAQ](https://www.tradingview.com/charting-library-docs/latest/resources/Frequently-Asked-Questions/)明确其与Trading Platform不提供Pine、Alerts、Strategy Tester、Bar Replay等依赖服务端的官网功能。图表库也不自动提供行情数据。上述限制不能错误扩大成“官网自身没有这些功能”。

**NOT_ESTABLISHED：** TradingView私有后端、数据库和完整网站源码。本报告解释可独立实现的公开方案，不声称已获取私有实现。

## 5. LPPL的专业化增量

优先完成“上证/茅台→完整图表→区间→证据→返回”。用户点击区间后，证据面板展示已有且允许的尺度、区间、数据截止日、模型版本、观察/提醒/修订性质，以及为何仍处观察状态；不能用未经校准的聚类密度直接显示为命中概率。

桌面按顶部控制、左侧小工具集、中央图表、右侧证据、底部回放组织。390px保留图表与核心结论，工具和证据使用可展开面板。拟合尺度与K线周期独立分组；状态色与涨跌色独立，不能依赖颜色本身传递全部含义。

当前main已有K线交互、历史回放和受限策略报告；详见本目录README的固定代码证据。需要新增或补全的是普通股票完整入口、用户绘图生命周期、证据截图、布局保存和正确失败反馈。本轮不重做已有功能，不把TradingView全部按钮数量作为验收目标。
