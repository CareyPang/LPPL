# TradingView 股票策略回测：官方操作指南与 LPPL 借鉴规格

核查日：2026-11-16。本文仅使用 TradingView 官方帮助、Pine Script 官方文档；**VERIFIED/DOC** 表示本轮核对文档，并非已控制用户账户完成操作。实际 Chrome 验收由主报告单独记录。本文没有控制 Chrome、购买套餐、调用交易账户、添加告警、发布脚本或写入 GitHub。

## 1. 先分清四种不同任务

| 任务 | 用户要解决的问题 | 官方能力与边界 |
|---|---|---|
| 图表和指标 | 看价格、成交量、某一指标的变化 | 指标有信号不等于有可回测订单；strategy 脚本才会产生交易模拟报告 |
| Strategy Report（旧教程常称 Strategy Tester） | 按固定规则模拟历史订单并查看结果 | 添加策略后出现报告；不是任何买卖箭头都能生成回测 |
| Deep Backtesting | 用指定历史范围重新计算同一策略 | 数据范围和初始化起点可能变化；结果不一定与普通模式相同 |
| Bar Replay / Replay Trading | 逐步揭示历史行情，练习观察或模拟操作 | 不是策略报告的同义词，也不是LPPL首次发布证据账本 |

**VERIFIED/DOC**：`indicator()` 与 `strategy()` 不同；后者能交给 broker emulator 模拟订单，并生成报告。策略报告模拟行为不等于向真实券商发出订单。[脚本声明说明](https://www.tradingview.com/pine-script-docs/language/declaration-statements/)

**设计含义 / PROPOSED**：LPPL的网站也应把“当前分析”“历史重放”“预测效果评估”“交易策略模拟”分成清楚入口。现在的顶部区间研究不必先虚构仓位、买卖规则和收益曲线。

## 2. 一次完整的官方推荐操作路线

以下是一份供实测使用的步骤，不是完成记录。示例选择 **NASDAQ:AAPL、标准日K线、内建 RSI Strategy**。若实际账户更适合其他资产，必须重新记录标的、交易所、周期与数据范围。

### 步骤A：先冻结看图对象

**PROPOSED / 实测步骤**：搜索并选择精确的 `NASDAQ:AAPL`，核对资产标题、交易所、日线、标准K线、调整方式、时区及加载数据范围。不要只写“苹果股票回测”。先记录图表设定，再加策略。

**VERIFIED/DOC**：非标准图形可使用合成价格，回测可能不代表真实成交条件；官方建议使用标准图表测试。Heikin Ashi另有标准OHLC成交设置。[策略概念文档](https://www.tradingview.com/pine-script-docs/concepts/strategies/)

**LPPL落点 / PROPOSED**：把资产与数据身份固定在回测页上方，显示复权、日历、数据截止、模型版本。图表视觉变换不得悄悄改LPPL日线输入。

### 步骤B：添加真正的策略

**VERIFIED/DOC**：Supercharts 顶部 `Indicators` → `Technicals` → `Strategies`，或在搜索框找策略；选中后底部自动打开 `Strategy Report`。一张图同时只运行一个strategy。个人、内建、社区策略有不同来源。[Strategy Report入门](https://www.tradingview.com/support/solutions/43000764138-tradingview-strategy-report-how-to-start/)

**实测要求 / PROPOSED**：选择内建 `RSI Strategy`，不要选同名普通RSI指标或未经核查的社区脚本。记录实际显示的名称、来源和默认输入；观察主图标记与底部报告是否同时出现。没有报告时先检查对象类型，不要直接说网站故障。

**VERIFIED/DOC**：该内建策略以RSI跨阈值产生方向变化；Length默认14。超卖线向上穿越触发做多，超买线向下穿越触发做空/反转。它是说明交互流程的示例，不是本报告推荐的投资策略。[RSI Strategy定义](https://www.tradingview.com/support/solutions/43000645066-rsi-strategy/)

若在贵州茅台等A股上体验，这种包含做空/反手的通用模拟不能直接称为可执行A股策略；市场制度、真实可成交条件和费用需另设规则。本轮不据模拟结果推荐交易。

### 步骤C：先看默认报告，再看设置

**PROPOSED / 记录顺序**：先截取或抄录默认版本的测试范围、总交易数、净结果、最大回撤、胜率、Profit Factor及Buy&Hold基准。报告未加载、无交易、存在未平仓交易时分别记录，不写“收益为0”替代未知。

**VERIFIED/DOC**：报告的Metrics提供权益与核心结果，交易列表提供逐笔资料；可用买入持有作为对照。报告还包含收益分解、阶段比较、保证金占用、交易分布与时间特征等不同视角，不能只取最漂亮的一项。[Strategy Report入门](https://www.tradingview.com/support/solutions/43000764138-tradingview-strategy-report-how-to-start/)

**设计含义 / PROPOSED**：顶部摘要要少而有层次，下方分项可继续钻取；主要结果和诊断细节不要在同一层平铺。LPPL应优先给阶段顶覆盖、漏报、时间误差、区间宽度、提前量，再给分组诊断。

### 步骤D：区分 Inputs、Properties 与 Style

**VERIFIED/DOC**：双击图上策略名称，或从名称旁设置按钮打开设置。`Inputs`是作者允许用户编辑的策略参数；`Style`控制显示；`Visibility`控制在哪些周期显示。[Pine入门：修改脚本设置](https://www.tradingview.com/pine-script-docs/primer/first-steps/)

**VERIFIED/DOC**：`Properties`包含初始资金、币种、下单规模、加仓、费用、滑点、保证金与成交/重算假设。佣金可按成交额百分比、每合约或每订单收取，并作用于进出场；滑点以ticks设置。默认重算与成交时点也会影响结果。[Strategy properties](https://www.tradingview.com/support/solutions/43000628599-strategy-properties/)

**实测小对照 / PROPOSED**：保留默认记录A，复制记录B只改变一项可解释的模拟成本，例如佣金或滑点；明确这是演示参数，不冒充真实券商费率。再记录变化和是否需要点更新。最后恢复原参数或移除本次临时策略，不保存或发布未经用户要求的布局。

对LPPL，建议把设置同样分开：

- **研究参数**：采样、时间窗集合、完整周期门槛、聚类规则与版本。
- **评分规则**：阶段/局部标签、匹配方式、重复提醒合并、提前量分层。
- **显示设置**：颜色、图层、显示范围、日/周聚合。
- **交易模拟假设**：仅当用户另行启用策略模拟时出现，不能改变顶部预测评分。

### 步骤E：逐笔明细返回主图

**VERIFIED/DOC**：List of Trades按照入场顺序组织，默认最新交易在上，可反转顺序；点击入场或出场可以将主图滚到对应K线。[List of Trades](https://www.tradingview.com/support/solutions/43000681737-list-of-trades-tab/)

**实测要求 / PROPOSED**：至少查看一笔盈利、一笔亏损或可用的不同交易，点入/出场分别定位；检查日期、价格、方向、仓位与结果是否对应。若深度回测模式下不支持主图定位，记录该边界，不把它称为联动bug。

**LPPL最重要的借鉴**：把“交易列表”转成“提醒事件列表”。每行显示提醒id、首次可见、预测起止、对应尺度/簇、后来修订、匹配的阶段顶和判定原因；点击可回到当时页面。它比一张总准确率卡更能解释模型到底哪里有效。

### 步骤F：最后才尝试更长历史

**VERIFIED/DOC**：Deep Backtesting使用可用历史，允许指定计算区间，而普通模式依赖图表加载的bars。它不是简单把视野拖远。[Deep Backtesting是什么](https://www.tradingview.com/support/solutions/43000666199-what-is-deep-backtesting/)

**VERIFIED/DOC**：官方当前说明需Premium及以上；选择测试范围后会自动进入该模式，并有粉色指示；修改策略后需更新报告，可回到chart session。遇到升级墙应记录而不购买。[How Deep Backtesting works](https://www.tradingview.com/support/solutions/43000666265-how-deep-backtesting-works/)

**VERIFIED/DOC**：每次计算上限为2百万bars，历史深度依资产与周期变化；日线与日线以上使用可用日级历史，分时历史通常更有限。指定范围超限时实际使用范围需要关注。[可用历史数据](https://www.tradingview.com/support/solutions/43000668210-how-much-data-is-available-for-deep-backtesting/)

**VERIFIED/DOC**：深度回测交易只在报告中展示，主图仍可能显示普通模式的交易。起始点不同会使EMA等递推计算不同，进而影响交易；即使日期有重叠也不能假定报告一模一样。[为何不叠到主图](https://www.tradingview.com/support/solutions/43000670566-why-are-the-results-of-deep-backtesting-not-shown-on-the-chart/)、[为何两种结果不同](https://www.tradingview.com/support/solutions/43000666266-why-do-the-data-of-the-regular-mode-and-deep-backtesting-not-match/)

**LPPL落点 / PROPOSED**：当前结果快路径与完整历史重算分离。点开历史图不能无提示启动104周拟合；计算任务卡显示范围、缓存状态、任务id、预期工作量和取消能力。复用已有结果前核对模型、数据与评分版本。

## 3. 回测指标应怎么读

下列是对报告指标的阅读方法与LPPL设计建议，不含本轮实测数值：

| 指标/视图 | 回答的问题 | 不能推出的结论 |
|---|---|---|
| 净损益/权益曲线 | 在这一资金与订单规则下，模拟账户如何变化 | 高收益不等于顶部时间预测准确 |
| 最大回撤 | 模拟权益从峰值到低点的损失 | 不等于这只股票下一次必然回撤幅度 |
| 胜率 | 已闭合交易里盈利交易比例 | 不等于警报命中率或未来上涨概率 |
| Profit Factor | 总盈利与总亏损的比例 | 少量交易或一笔极端收益不能证明稳定性 |
| Buy&Hold | 相同资产的被动持有参照 | 不同资金/风险敞口仍需说明，不可只看绝对收益 |
| 交易明细 | 哪次入场、出场贡献了结果 | 图上的标签不能替代真实可成交条件 |
| 分期/分组 | 哪些时期、方向、交易群体贡献结果 | 看完结果再挑最优分组会造成选择偏差 |

**VERIFIED/DOC**：官方单独说明Sharpe计算采用月度收益并有可配置无风险利率，因此不能拿另一个系统不同频率/利率的同名Sharpe直接比较。[Sharpe Ratio](https://www.tradingview.com/support/solutions/43000681694-sharpe-ratio/)

**PROPOSED**：LPPL的“研究效果”与“交易策略表现”分开：前者先回答阶段顶是否覆盖、漏报多少、首窗偏早/偏晚、窗口宽度、提前量和修订；后者只有在冻结入/出场、仓位、费用、交易约束后才计算收益指标。保持完整周期1.5研究基线，先做小样本，不因UI改造重跑全市场。

## 4. Bar Replay、Replay Trading与策略报告的操作联系

**VERIFIED/DOC**：Bar Replay的官方路径是选历史起点，再播放、暂停、单步、调整速度及返回实时；多个图表可同步回放。官方也明确部分行情列表/交易面板显示实时报价，实时服务器告警继续工作。[回放启用与限制](https://www.tradingview.com/support/solutions/43000474024-how-do-i-turn-bar-replay-on/)

**VERIFIED/DOC**：Replay Trading是单独的历史模拟模式，与Paper Trading不同；可以在会话中设置初始资金、币种及佣金，官方说明交易与汇总数据只在该会话内可用。[历史模拟交易](https://www.tradingview.com/support/solutions/43000691889-learn-to-trade-on-historical-data/)

**PROPOSED**：本轮体验策略报告已足够，不需要连接券商或创建模拟订单来证明导航完整。LPPL的历史研究更应有持久且可追溯的提醒账本，不能借用了播放控件就宣称“当时已知”的完整回放。

## 5. 没有结果时，怎样设计有用的空态

**VERIFIED/DOC**：官方把无交易的原因分成脚本非strategy/无下单命令、资金不足、运行时错误、条件未触发等；脚本内显式下单数量也可能覆盖Properties默认数量。[策略不产生订单](https://www.tradingview.com/support/solutions/43000478450-i-ve-successfully-added-a-strategy-to-my-chart-but-it-doesn-t-generate-orders/)

**PROPOSED** LPPL不能只有一句“无合格拟合”。空态至少区分：

1. 没有足够数据：列缺失范围/字段，保留行情与重试入口。
2. 拟合完成但结构不合格：显示各尺度的通过/未通过数量与原因。
3. 有结构候选但未满足正式提醒条件：保留时间窗，说明缺什么。
4. 候选临近：不因少于5交易日隐藏；显示0–4日等提前量分层。
5. 当前任务排队/失败：旧结果日期与任务状态并存，不改成“没有风险”。
6. 历史尚未计算或没有当时存档：明确“历史补算”与“真实发布证据缺失”。

## 6. 对LPPL回测/复盘页的可落地信息架构

以下全部为**PROPOSED / NOT_RUN**，不是当前仓库已实现功能的断言。

### 顶部上下文行

资产名称/交易所 → 数据截止日 → 研究模式 → 模型与评分版本 → 读取缓存/计算任务状态。右侧放“重算参数”和“保存研究版本”；不默认启动全历史。

### 页面内二级导航

| 页签 | 默认内容 | 与主图联动 |
|---|---|---|
| 概览 | 阶段顶覆盖、漏报、首窗时间误差、窗口宽度、提前量分布 | 点某类指标筛选相关提醒，保留筛选条件 |
| 提醒明细 | 原始首窗、修订、重复/新提醒、证据与当前判定 | 点某行恢复对应as-of并高亮候选 |
| 阶段顶案例 | 每个标签的匹配与失败分类，未成熟单列 | 点漏报/偏早/偏晚案例定位真实价格与当时结果 |
| 规则与参数 | 拟合设置、聚类设置、评分版本、标签定义与数据hash | 改参数进入草稿，不覆盖原运行 |
| 对照实验 | 旧规则/新规则，在相同提醒预算下成对比较 | 同一案例左右或叠层比较，日期一致 |
| 交易模拟 | 可选，独立的入出场/仓位/费用方案 | 订单记录与模型提醒分别图层，不合并成绩 |

“概览→明细→案例→参数”形成追问路径；用户不需要先读论文才找到一条提醒。“对照实验”需要基础结果可追溯后再加，不建议第一版六个空页签一起上线。

### 报告表与图表如何保持关联

每行提醒绑定 `prediction_id / result_id / cluster_id / asof / first_visible_at / revision_id`。主图选中状态和明细选中状态共用同一对象；日期筛选不能仅过滤表格而不改变图上范围提示；退出历史模式显式返回最新，不静默混用。

固定运行配置保存输入hash、模型版本、评分版本、日历版本及首次可见证据。重新计算产生新run，不覆盖旧结果；默认对照一次只改一个研究因素。模型日期与图表显示日期分别保存，避免日/周切换变成模型参数变化。

### 390px取舍

顶部保留资产与截止日，二级导航使用可横向滚动的短标签；概览指标控制数量，明细以卡片/可展开行展示。点明细后进入大图或底部抽屉，返回保留筛选与滚动位置。不要把桌面权益曲线、交易表、属性面板和AI同时塞进手机一屏。

## 7. 初次使用教程应该怎么做

**PROPOSED**：用可跳过的5步任务教程，完成后留下可复用研究对象：

1. 选择资产，识别最新行情与分析截止日。
2. 选择一个已有候选区间，定位到图上。
3. 打开支持尺度与证据，理解“有结构”和“正式提醒”的差别。
4. 查看一次修订或一个失败案例，不只展示命中案例。
5. 回到当时状态，区分真实首次发布与历史补算。

帮助入口应就近解释当前控件，避免每次都跳到长文：例如“这个百分比是合格拟合占比”“提前天数如何计算”“为何没有正式提醒”。新手引导不覆盖K线焦点；关闭后可从帮助中心重新打开。

## 8. 官方教程入口及版本提醒

以下都是官方入口，可供用户与Devin逐项核对，不是第三方搬运教程：

- [策略报告入门及界面](https://www.tradingview.com/support/solutions/43000764138-tradingview-strategy-report-how-to-start/)
- [内建策略目录](https://www.tradingview.com/support/folders/43000587406/)
- [RSI Strategy示例](https://www.tradingview.com/support/solutions/43000645066-rsi-strategy/)
- [Inputs、Style与Visibility入门](https://www.tradingview.com/pine-script-docs/primer/first-steps/)
- [Properties与成本假设](https://www.tradingview.com/support/solutions/43000628599-strategy-properties/)
- [逐笔交易定位](https://www.tradingview.com/support/solutions/43000681737-list-of-trades-tab/)
- [Deep Backtesting操作及套餐要求](https://www.tradingview.com/support/solutions/43000666265-how-deep-backtesting-works/)
- [回放操作及限制](https://www.tradingview.com/support/solutions/43000474024-how-do-i-turn-bar-replay-on/)
- [完整Pine策略执行模型](https://www.tradingview.com/pine-script-docs/concepts/strategies/)

**版本差异 / VERIFIED/DOC**：官方较新的Report帮助使用`Strategy Report / Metrics`等名称；部分旧帮助仍保留`Overview`、`Verify Price For Limit Orders`等旧式用语。最新Report帮助列出的`Limit order execution`、`Script execution mode`等可能对应新的控件组织。实际体验报告必须写用户账户看到的名称和行为；不能因为旧教程按钮没出现，就说账户没有策略回测，也不能把文档新能力当作本账户已体验成功。

## 9. 本轮体验应交付的最小证据表

| 记录项 | 验收标准 | 本文状态 |
|---|---|---|
| 标的/交易所/周期/标准K线/复权/时区 | 可复现同一数据场景 | DOC指导，UI待主报告 |
| 策略名称/来源/输入/Properties | 没有把普通指标当策略 | DOC指导，UI待主报告 |
| 默认报告及一次单变量变化 | 说明变了什么，保留两组值或明确未完成 | 本指南不记录UI完成状态，见BROWSER_LOG S01–S06；默认报告已生成，单变量对照未完成 |
| 至少一笔交易定位 | 日期、价格、订单类型与图对应 | 本指南不记录UI完成状态，见BROWSER_LOG S04–S05 |
| 数据范围与普通/深度模式 | 不混普通主图与深度报告 | 文档已核验，账户待测 |
| 回放与策略报告边界 | 不把播放界面当回测成功 | 文档已核验，账户待测 |
| 退出与恢复 | 临时策略/参数不污染用户原研究 | 由主任务记录 |

不得在未获得实际数值和对应设置前写“该策略赚了多少”“比LPPL更准”或“回测已经通过”。本报告的价值是拆解可复现交互与评价结构，不是验证任何策略或LPPL的投资效果。
